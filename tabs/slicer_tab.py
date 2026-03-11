import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QPushButton, QGroupBox, QCheckBox, QSlider,
                             QSpinBox, QDoubleSpinBox, QMessageBox, QScrollArea)
from PyQt5.QtCore import Qt, QTimer

# Import the base class.
from core.base_tab import BaseSignalTab
# Import dsp utilities.
import utils.dsp_lib as dsp

class SlicerTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Bit Recovery")
        
        # Local state.
        self.centered_analog_data = None
        self.adjusted_thresholds = []
        self.local_sr = 1.0
        
        self.symbol_buffer = None
        self.last_symbol_count = 1
        
        # Auto-Sync State
        self.auto_clock_centers = None
        self.auto_clock_edges = None
        
        # Visual items.
        self.tick_lines = []
        self.digital_color_name = 'Orange'

        # Timer for debouncing heavy array slicing and tick updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.refresh_plot_data)
        
        self.init_ui()

    def init_ui(self):
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # Visualization
        self.viz_layout = QVBoxLayout()
        
        self.plot_main = pg.PlotWidget()
        self.plot_main.setLabel('bottom', 'Time', units='s')
        self.plot_main.setLabel('left', 'Amplitude') 
        self.plot_main.showGrid(x=True, y=True, alpha=0.3)
        # Optimization
        self.plot_main.setClipToView(True)
        self.plot_main.setDownsampling(auto=True, mode='peak')
        self.plot_main.setMouseEnabled(x=True, y=False)
        self.plot_main.setBackground('#1e1e1e')
        
        self.pen_digital = pg.mkPen('#FFA500', width=2)
        self.curve_digital = self.plot_main.plot(pen=self.pen_digital) 
        
        # Zero-Line Reference
        self.zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#555555', width=1, style=Qt.DashLine))
        self.plot_main.addItem(self.zero_line)
        
        # Clock Region (The interactive manual box).
        self.clock_region = pg.LinearRegionItem(brush=pg.mkBrush(255, 255, 255, 30))
        self.clock_region.setZValue(100)
        for line in self.clock_region.lines:
            line.setPen(pg.mkPen('#AAAAAA', width=4))
            line.setHoverPen(pg.mkPen('#FFFFFF', width=6))
            
        # Hook up clock region changes
        self.clock_region.sigRegionChanged.connect(self.update_clock_ticks)
        self.clock_region.sigRegionChanged.connect(self.extract_symbols)
        self.plot_main.addItem(self.clock_region)
        
        # Auto-Sync Boundary Line (Red Solid)
        self.auto_start_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('r', width=3))
        self.auto_start_line.setVisible(False)
        self.plot_main.addItem(self.auto_start_line)
        
        # Stop line (limit for auto sync).
        self.stop_line = pg.InfiniteLine(
            pos=0, angle=90, movable=True, 
            pen=pg.mkPen('#FF00FF', width=3, style=Qt.DashLine),
            label='STOP LIMIT', labelOpts={'position': 0.95, 'color': '#FF00FF'}
        )
        self.stop_line.setVisible(False) 
        self.plot_main.addItem(self.stop_line)
        
        self.viz_layout.addWidget(self.plot_main)
        
        # Mini map
        self.plot_mini = pg.PlotWidget()
        self.plot_mini.setFixedHeight(80)
        self.plot_mini.hideAxis('bottom')
        self.plot_mini.hideAxis('left')
        self.plot_mini.setBackground('#1e1e1e')
        self.curve_mini = self.plot_mini.plot(pen=pg.mkPen('w', width=1))
        
        self.nav_region = pg.LinearRegionItem()
        self.nav_region.setZValue(10)
        self.plot_mini.addItem(self.nav_region)
        self.nav_region.sigRegionChanged.connect(self.update_zoom_from_nav)
        
        # Connect main plot range changes to our debounced handler
        self.plot_main.sigRangeChanged.connect(self.on_range_changed)
        
        self.viz_layout.addWidget(self.plot_mini)

        # Sidebar Controls
        self.sidebar = QGroupBox("Clock Recovery")
        self.sidebar.setMinimumWidth(250)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # Section 1: Manual
        self.sidebar_layout.addWidget(QLabel("1. Manual Timing (Seed):"))
        self.chk_lock_pos = QCheckBox("Lock Position (Resize Only)")
        self.chk_lock_pos.stateChanged.connect(self.toggle_lock_position)
        self.sidebar_layout.addWidget(self.chk_lock_pos)
        
        row_sym = QHBoxLayout()
        row_sym.addWidget(QLabel("Symbol Count:"))
        self.spin_symbols = QSpinBox()
        self.spin_symbols.setRange(1, 10000) 
        self.spin_symbols.setValue(1)
        self.spin_symbols.valueChanged.connect(self.update_clock_box_size) 
        self.spin_symbols.valueChanged.connect(self.update_clock_ticks)    
        self.spin_symbols.valueChanged.connect(self.extract_symbols)
        self.spin_symbols.valueChanged.connect(self.check_auto_enable) 
        row_sym.addWidget(self.spin_symbols)
        self.sidebar_layout.addLayout(row_sym)
        self.sidebar_layout.addSpacing(10)
        
        self.btn_autoscale = QPushButton("Auto Scale Y-Axis")
        self.btn_autoscale.clicked.connect(self.autoscale_view)
        self.sidebar_layout.addWidget(self.btn_autoscale)
        self.sidebar_layout.addSpacing(20)

        # Visuals.
        self.grp_vis = QGroupBox("2. Visual Settings")
        self.vis_layout = QVBoxLayout()
        self.grp_vis.setLayout(self.vis_layout)

        # View Settings
        self.lbl_active_points = QLabel("Visible Points: --")
        self.lbl_active_points.setStyleSheet("font-size: 11px; color: #888; font-weight: bold;")
        self.vis_layout.addWidget(self.lbl_active_points)
        
        row_thresh = QHBoxLayout()
        row_thresh.addWidget(QLabel("Plot Threshold:"))
        self.spin_plot_thresh = QSpinBox()
        self.spin_plot_thresh.setRange(1000, 5000000)
        self.spin_plot_thresh.setSingleStep(10000)
        self.spin_plot_thresh.setValue(10000)
        self.spin_plot_thresh.setToolTip("Maximum points drawn 1:1 before peak-downsampling activates.")
        self.spin_plot_thresh.valueChanged.connect(self.refresh_plot_data)
        row_thresh.addWidget(self.spin_plot_thresh)
        self.vis_layout.addLayout(row_thresh)
        
        self.chk_light_mode = QCheckBox("Light Mode")
        self.chk_light_mode.stateChanged.connect(self.toggle_light_mode)
        self.vis_layout.addWidget(self.chk_light_mode)
        
        self.vis_layout.addSpacing(10)
        self.vis_layout.addWidget(QLabel("Trace Color:"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(['Orange', 'Lime', 'Cyan', 'Magenta', 'Yellow', 'White/Black', 'Blue'])
        self.cb_color.currentTextChanged.connect(self.update_digital_color)
        self.vis_layout.addWidget(self.cb_color)
        
        self.sidebar_layout.addWidget(self.grp_vis)
        self.sidebar_layout.addSpacing(20)
        
        # Section 3: Auto Sync.
        self.grp_auto = QGroupBox("3. Auto-Sync (PLL)")
        self.auto_layout = QVBoxLayout()
        self.grp_auto.setLayout(self.auto_layout)
        
        row_tol = QHBoxLayout()
        row_tol.addWidget(QLabel("Loop Gain (\u03B1):"))
        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.01, 0.99)
        self.spin_alpha.setValue(0.15) 
        self.spin_alpha.setSingleStep(0.05)
        row_tol.addWidget(self.spin_alpha)
        self.auto_layout.addLayout(row_tol)
        
        self.chk_stop_limit = QCheckBox("Set Stop Marker")
        self.chk_stop_limit.stateChanged.connect(self.toggle_stop_line)
        self.auto_layout.addWidget(self.chk_stop_limit)
        
        self.auto_layout.addSpacing(5)
        
        row_auto_btns = QHBoxLayout()
        self.btn_auto_sync = QPushButton("Auto-Sync")
        self.btn_auto_sync.setEnabled(False) 
        self.btn_auto_sync.setToolTip("Align at least 4 symbols manually to enable.")
        self.btn_auto_sync.setStyleSheet("background-color: #e8f5e9; font-weight: bold;")
        self.btn_auto_sync.clicked.connect(self.run_auto_sync)
        row_auto_btns.addWidget(self.btn_auto_sync)
        
        self.btn_clear_auto = QPushButton("Clear")
        self.btn_clear_auto.setEnabled(False)
        self.btn_clear_auto.clicked.connect(self.clear_auto_sync)
        row_auto_btns.addWidget(self.btn_clear_auto)
        
        self.auto_layout.addLayout(row_auto_btns)
        
        self.lbl_auto_status = QLabel("Status: Manual Mode")
        self.lbl_auto_status.setStyleSheet("color: #666; font-size: 11px;")
        self.auto_layout.addWidget(self.lbl_auto_status)
        
        self.sidebar_layout.addWidget(self.grp_auto)
        
        self.sidebar_layout.addSpacing(10)
        self.lbl_debug = QLabel("Drag the white box edges to manually align ticks with symbol zero-crossings.")
        self.lbl_debug.setWordWrap(True)
        self.lbl_debug.setStyleSheet("color: #666; font-style: italic;")
        self.sidebar_layout.addWidget(self.lbl_debug)
        
        self.sidebar_layout.addStretch()

        # Add Layout Components
        main_h_layout.addLayout(self.viz_layout, stretch=5)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.sidebar)
        main_h_layout.addWidget(scroll_area, stretch=1)

        # Init state.
        self.update_digital_color('Orange')

    def load_input(self):
        # Pull analog data from context.
        if self.context.demod_signal is None:
            return False, "No demodulated signal in Context (Tab 3)."
            
        self.local_sr = self.context.demod_sr
        
        # CFO
        self.centered_analog_data, self.adjusted_thresholds, _ = dsp.remove_dc_bias(
            self.context.demod_signal, 
            self.context.thresholds
        )
        
        # Reset Auto-Sync state
        self.clear_auto_sync()
        
        # Restore color preference.
        user_color = self.context.viz_trace_color
        idx = self.cb_color.findText(next((k for k,v in {
            'Orange': '#FFA500', 'Lime': '#32CD32', 'Cyan': '#00FFFF', 
            'Magenta': '#FF00FF', 'Yellow': '#FFFF00', 'White/Black': '#FFFFFF',
            'Blue': '#5555FF'
        }.items() if v == user_color), 'Orange'))
        if idx >= 0: self.cb_color.setCurrentIndex(idx)
        
        # Update Mini Map (Statically decimated for speed)
        total_points = len(self.centered_analog_data)
        mini_step = max(1, total_points // 5000)
        y_data_mini = self.centered_analog_data[::mini_step]
        x_axis_mini = np.arange(len(y_data_mini)) * (mini_step / self.local_sr)
        self.curve_mini.setData(x_axis_mini, y_data_mini) 
        
        current_range = self.plot_mini.viewRange()[0]
        actual_duration = total_points / self.local_sr
        
        # Only reset zoom if significant change.
        if abs(current_range[1] - actual_duration) > 0.01:
             self.plot_mini.setXRange(0, actual_duration)
             zoom_t = actual_duration * 0.005
             
             self.nav_region.blockSignals(True)
             self.nav_region.setRegion([0, zoom_t])
             self.nav_region.blockSignals(False)
             
             # Reset clock box.
             box_width = zoom_t * 0.2
             box_center = zoom_t / 2
             self.clock_region.blockSignals(True)
             self.clock_region.setRegion([box_center - box_width/2, box_center + box_width/2])
             self.clock_region.blockSignals(False)
             
             self.spin_symbols.blockSignals(True)
             self.spin_symbols.setValue(1) 
             self.spin_symbols.blockSignals(False)
             self.last_symbol_count = 1 
             
             self.plot_main.setXRange(0, zoom_t, padding=0)
             
             self.check_auto_enable()
             self.stop_line.setValue(actual_duration)
        
        self.autoscale_view()
        self.extract_symbols()
        
        # Trigger an immediate plot refresh
        self.refresh_plot_data()
        
        return True, f"Loaded {total_points} samples."

    def on_range_changed(self, _, viewRange):
        # Visually sync the minimap box immediately
        self.nav_region.blockSignals(True)
        self.nav_region.setRegion(viewRange[0])
        self.nav_region.blockSignals(False)
        
        # Restart the timer to debounce the plot update
        self.update_timer.start(50)

    def refresh_plot_data(self):
        self.update_main_plot()
        self.update_clock_ticks()

    def update_main_plot(self):
        if self.centered_analog_data is None: return
        
        sr = self.local_sr
        total_points = len(self.centered_analog_data)
        
        # Get the strict visible time window
        view_range = self.plot_main.viewRange()[0]
        min_t, max_t = view_range[0], view_range[1]
        
        # Add a buffer on either side for panning
        pad_t = (max_t - min_t) * 0.25
        min_t = max(0, min_t - pad_t)
        max_t = min(total_points / sr, max_t + pad_t)
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(total_points, int(max_t * sr))
        
        if i_stop <= i_start: return
        
        # Only extract the exact segment we need
        view_y = self.centered_analog_data[i_start:i_stop]
        view_x = np.arange(i_start, i_stop) / sr
        
        # Decide if we pass raw points or let PyQtGraph apply peak-downsampling
        num_points = len(view_y)
        if num_points > self.spin_plot_thresh.value():
            self.plot_main.setDownsampling(auto=True, mode='peak')
            self.lbl_active_points.setText(f"Visible Points: {num_points:,}  [Downsampled]")
        else:
            self.plot_main.setDownsampling(auto=False)
            self.lbl_active_points.setText(f"Visible Points: {num_points:,}  [1:1]")
            
        self.curve_digital.setData(view_x, view_y)

    def stage_output(self):
        if self.symbol_buffer is None or len(self.symbol_buffer) == 0:
            return False, "No symbols extracted."
            
        # Commit to context
        self.context.symbols = np.copy(self.symbol_buffer)
        
        # Calculate overall symbol rate (baud).
        if self.auto_clock_centers is not None and len(self.auto_clock_centers) > 1:
            duration = self.auto_clock_centers[-1] - self.auto_clock_centers[0]
            count = len(self.auto_clock_centers)
            self.context.symbol_rate = count / duration if duration > 0 else 0
        else:
            min_t, max_t = self.clock_region.getRegion()
            count = self.spin_symbols.value()
            duration = max_t - min_t
            self.context.symbol_rate = count / duration if duration > 0 else 0
            
        return True, f"Staged {len(self.context.symbols)} symbols."

    def extract_symbols(self):
        # Extracts specific points in time from the analog wave and runs them through the slicer
        if self.centered_analog_data is None: return
        
        sr = self.local_sr
        
        # If Auto-Sync is locked, use its combined timestamps exactly
        if self.auto_clock_centers is not None:
            timestamps = self.auto_clock_centers.tolist()
        else:
            # Otherwise, calculate timestamps manually from the box
            min_t, max_t = self.clock_region.getRegion()
            num_symbols = self.spin_symbols.value()
            sym_width = (max_t - min_t) / num_symbols
            timestamps = [min_t + (sym_width * (i + 0.5)) for i in range(num_symbols)]
            
        # Sample and digitize via DSP lib
        self.symbol_buffer = dsp.sample_and_slice(
            self.centered_analog_data, 
            timestamps, 
            sr, 
            self.adjusted_thresholds
        )

    def update_clock_box_size(self):
        # Adjusts the region width when symbol count changes manually.
        min_x, max_x = self.clock_region.getRegion()
        current_width = max_x - min_x
        new_count = self.spin_symbols.value()
        
        if not hasattr(self, 'last_symbol_count'):
            self.last_symbol_count = new_count
            return
            
        old_count = self.last_symbol_count
        if old_count < 1: old_count = 1 
        if new_count == old_count: return
        
        avg_sym_width = current_width / old_count
        new_width = avg_sym_width * new_count
        
        self.clock_region.setRegion([min_x, min_x + new_width])
        self.last_symbol_count = new_count
        self.check_auto_enable()

    def update_clock_ticks(self):
        # Draws the vertical clock lines based on Manual + Auto states.
        if self.centered_analog_data is None: return
        
        # Combine edges to draw.
        if self.auto_clock_edges is not None:
            edges_to_draw = self.auto_clock_edges
        else:
            min_x, max_x = self.clock_region.getRegion()
            num_symbols = self.spin_symbols.value()
            sym_width = (max_x - min_x) / num_symbols
            if num_symbols > 1:
                edges_to_draw = [min_x + ((i + 1) * sym_width) for i in range(num_symbols - 1)]
            else:
                edges_to_draw = []
            
        # Clear old lines.
        while len(self.tick_lines) > 0:
            self.plot_main.removeItem(self.tick_lines.pop())
            
        if not edges_to_draw: return
        
        tick_pen = pg.mkPen('#FF5555', style=Qt.DashLine, width=2)
        view_min, view_max = self.plot_main.viewRange()[0]
        
        # Convert to numpy array for fast filtering
        edges_arr = np.array(edges_to_draw)
        
        # Fallback sym_width approximation to pad view range
        pad_width = edges_arr[1] - edges_arr[0] if len(edges_arr) > 1 else 0.001
        
        # Filter edges to only what is currently in the viewport to prevent lag
        visible_edges = edges_arr[(edges_arr >= view_min - pad_width) & (edges_arr <= view_max + pad_width)]
        
        # Max lines on screen check to protect UI thread
        if len(visible_edges) > 300:
            visible_edges = visible_edges[::len(visible_edges)//300]
            
        for x_pos in visible_edges:
            l = pg.InfiniteLine(angle=90, movable=False, pen=tick_pen)
            l.setValue(x_pos)
            self.plot_main.addItem(l)
            self.tick_lines.append(l)

    def run_auto_sync(self):
        if self.centered_analog_data is None: return

        min_t, max_t = self.clock_region.getRegion()
        current_count = self.spin_symbols.value()
        current_width = max_t - min_t
        start_time = min_t
        
        sr = self.local_sr
        limit = self.stop_line.value() if self.chk_stop_limit.isChecked() else None
        
        # Use DSP lib with PLL algorithm
        success, centers, manual_boundary = dsp.find_clock_sync(
            self.centered_analog_data, 
            sr, 
            start_time, 
            current_width, 
            current_count, 
            self.spin_alpha.value(),
            limit
        )
        
        if success and len(centers) > 0:
            self.auto_clock_centers = centers
            # Reconstruct the edges from the centers for visualization
            self.auto_clock_edges = [centers[0] - (centers[1]-centers[0])/2] # First edge
            for i in range(len(centers) - 1):
                self.auto_clock_edges.append((centers[i] + centers[i+1]) / 2.0)
            self.auto_clock_edges.append(centers[-1] + (centers[-1]-centers[-2])/2) # Last edge
            
            # Lock the UI
            self.clock_region.setMovable(False)
            for line in self.clock_region.lines:
                line.setMovable(False)
            
            self.spin_symbols.setEnabled(False)
            self.btn_auto_sync.setEnabled(False)
            self.btn_clear_auto.setEnabled(True)
            self.chk_lock_pos.setEnabled(False)
            
            # Show Red Boundary Line
            self.auto_start_line.setValue(manual_boundary)
            self.auto_start_line.setVisible(True)
            
            total = len(centers)
            self.lbl_auto_status.setText(f"Status: PLL Mode (Total Sym: {total})")
            self.lbl_auto_status.setStyleSheet("color: #2E7D32; font-weight: bold;")
            
            self.refresh_plot_data()
            self.extract_symbols()

    def clear_auto_sync(self):
        # Resets back to manual mode.
        self.auto_clock_centers = None
        self.auto_clock_edges = None
        
        self.auto_start_line.setVisible(False)
        
        # Unlock UI
        self.spin_symbols.setEnabled(True)
        self.btn_clear_auto.setEnabled(False)
        self.chk_lock_pos.setEnabled(True)
        
        self.toggle_lock_position() # Apply correct lock state for lines
        
        self.lbl_auto_status.setText("Status: Manual Mode")
        self.lbl_auto_status.setStyleSheet("color: #666; font-size: 11px;")
        
        self.check_auto_enable()
        self.refresh_plot_data()
        self.extract_symbols()

    def autoscale_view(self):
        if self.centered_analog_data is None: return
        x_data, y_data = self.curve_digital.getData()
        if x_data is None: return
        
        min_t, max_t = self.nav_region.getRegion()
        i_start = np.searchsorted(x_data, min_t)
        i_stop = np.searchsorted(x_data, max_t)
        if i_stop <= i_start: return
        
        view_y = y_data[i_start:i_stop]
        if len(view_y) == 0: return
        
        y_min = np.min(view_y)
        y_max = np.max(view_y)
        if abs(y_max - y_min) < 1e-9: margin = 1.0 
        else: margin = (y_max - y_min) * 0.20 
        
        self.plot_main.setYRange(y_min - margin, y_max + margin)

    def check_auto_enable(self):
        # Only check if we aren't currently auto-synced
        if self.auto_clock_centers is not None:
            return
            
        count = self.spin_symbols.value()
        if count >= 4:
            self.btn_auto_sync.setEnabled(True)
            self.btn_auto_sync.setText(f"Auto-Sync (Next: {count+1})")
        else:
            self.btn_auto_sync.setEnabled(False)
            self.btn_auto_sync.setText("Auto-Sync (Align 4+)")

    def toggle_lock_position(self):
        if self.auto_clock_centers is not None:
            return # Blocked by Auto-Sync
            
        should_lock = self.chk_lock_pos.isChecked()
        if should_lock:
            self.clock_region.setMovable(False)
            for line in self.clock_region.lines:
                line.setMovable(True)
                line.setAcceptedMouseButtons(Qt.LeftButton)
        else:
            self.clock_region.setMovable(True)
            for line in self.clock_region.lines:
                line.setMovable(True)

    def toggle_stop_line(self):
        show = self.chk_stop_limit.isChecked()
        self.stop_line.setVisible(show)
        if show and self.centered_analog_data is not None:
            end_t = len(self.centered_analog_data) / self.local_sr
            if self.stop_line.value() == 0:
                self.stop_line.setValue(end_t)

    def get_adaptive_color(self, name):
        colors = {
            'Orange':       ('#FFA500', '#D35400'),
            'Lime':         ('#32CD32', '#006400'),
            'Cyan':         ('#00FFFF', '#008B8B'),
            'Magenta':      ('#FF00FF', '#8B008B'),
            'Yellow':       ('#FFFF00', '#B58900'),
            'White/Black': ('#FFFFFF', '#000000'), 
            'Blue':         ('#5555FF', '#00008B')
        }
        dark, light = colors.get(name, ('#FFA500', '#D35400'))
        return light if self.chk_light_mode.isChecked() else dark

    def update_digital_color(self, color_name):
        self.digital_color_name = color_name
        hex_color = self.get_adaptive_color(color_name)
        self.pen_digital = pg.mkPen(pg.mkColor(hex_color), width=2)
        self.curve_digital.setPen(self.pen_digital)

    def toggle_light_mode(self):
        if self.chk_light_mode.isChecked():
            self.plot_main.setBackground('w')
            self.plot_main.getAxis('left').setPen('k')
            self.plot_main.getAxis('bottom').setPen('k')
            self.plot_main.getAxis('left').setTextPen('k')
            self.plot_main.getAxis('bottom').setTextPen('k')
            self.clock_region.setBrush(pg.mkBrush(0, 0, 0, 50)) 
        else:
            self.plot_main.setBackground('#1e1e1e')
            self.plot_main.getAxis('left').setPen('w')
            self.plot_main.getAxis('bottom').setPen('w')
            self.plot_main.getAxis('left').setTextPen('w')
            self.plot_main.getAxis('bottom').setTextPen('w')
            self.clock_region.setBrush(pg.mkBrush(255, 255, 255, 30))
        
        self.update_digital_color(self.digital_color_name)

    def update_zoom_from_nav(self):
        min_x, max_x = self.nav_region.getRegion()
        # Modifying XRange here triggers on_range_changed internally
        self.plot_main.setXRange(min_x, max_x, padding=0)

    def update_nav_from_zoom(self, _, viewRange):
        # We don't need to do anything here anymore, on_range_changed handles it
        pass
