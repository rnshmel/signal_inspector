import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QPushButton, QGroupBox, QCheckBox, QSlider,
                             QSpinBox, QDoubleSpinBox, QProgressDialog, QMessageBox)
from PyQt5.QtCore import Qt

# Import the base class.
from core.base_tab import BaseSignalTab
# Import dsp utilities.
import utils.dsp_lib as dsp

class SlicerTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Bit Recovery")
        
        # Local state.
        self.cached_symbol_data = None
        self.local_sr = 1.0
        
        self.symbol_buffer = None
        self.last_symbol_count = 1
        
        # Visual items.
        self.tick_lines = []
        self.digital_color_name = 'Orange'
        
        self.init_ui()

    def init_ui(self):
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # LEFT: Visualization
        self.viz_layout = QVBoxLayout()
        
        self.plot_main = pg.PlotWidget()
        self.plot_main.setLabel('bottom', 'Time', units='s')
        self.plot_main.setLabel('left', 'Symbol Index') 
        self.plot_main.showGrid(x=True, y=True, alpha=0.3)
        self.plot_main.setDownsampling(auto=False)
        self.plot_main.setClipToView(False)
        self.plot_main.setMouseEnabled(x=True, y=False)
        self.plot_main.setBackground('#1e1e1e')
        
        self.pen_digital = pg.mkPen('#FFA500', width=4)
        self.curve_digital = self.plot_main.plot(pen=self.pen_digital) 
        
        # Clock Region (The interactive box).
        self.clock_region = pg.LinearRegionItem(brush=pg.mkBrush(255, 255, 255, 30))
        self.clock_region.setZValue(100)
        for line in self.clock_region.lines:
            line.setPen(pg.mkPen('#AAAAAA', width=4))
            line.setHoverPen(pg.mkPen('#FFFFFF', width=6))
            
        self.clock_region.sigRegionChanged.connect(self.update_clock_ticks)
        self.clock_region.sigRegionChanged.connect(self.extract_symbols)
        self.plot_main.addItem(self.clock_region)
        
        # Stop line (limit for auto sync).
        self.stop_line = pg.InfiniteLine(
            pos=0, 
            angle=90, 
            movable=True, 
            pen=pg.mkPen('r', width=3, style=Qt.DashLine),
            label='STOP', 
            labelOpts={'position': 0.95, 'color': 'r'}
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
        self.plot_main.sigRangeChanged.connect(self.update_nav_from_zoom)
        
        self.viz_layout.addWidget(self.plot_mini)
        main_h_layout.addLayout(self.viz_layout, stretch=1)

        # RIGHT: Controls
        self.sidebar = QGroupBox("Clock Recovery")
        self.sidebar.setFixedWidth(280)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # Section 1: Manual
        self.sidebar_layout.addWidget(QLabel("1. Manual Timing:"))
        self.chk_lock_pos = QCheckBox("Lock Position (Resize Only)")
        self.chk_lock_pos.stateChanged.connect(self.toggle_lock_position)
        self.sidebar_layout.addWidget(self.chk_lock_pos)
        
        row_sym = QHBoxLayout()
        row_sym.addWidget(QLabel("Symbol Count:"))
        self.spin_symbols = QSpinBox()
        self.spin_symbols.setRange(1, 100000) 
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

        # Section 2: Visuals.
        self.grp_vis = QGroupBox("2. Visual Settings")
        self.vis_layout = QVBoxLayout()
        self.grp_vis.setLayout(self.vis_layout)
        
        self.chk_light_mode = QCheckBox("Light Mode")
        self.chk_light_mode.stateChanged.connect(self.toggle_light_mode)
        self.vis_layout.addWidget(self.chk_light_mode)
        
        self.vis_layout.addSpacing(10)
        self.vis_layout.addWidget(QLabel("Trace Color:"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(['Orange', 'Lime', 'Cyan', 'Magenta', 'Yellow', 'White/Black', 'Blue'])
        self.cb_color.currentTextChanged.connect(self.update_digital_color)
        self.vis_layout.addWidget(self.cb_color)
        
        self.vis_layout.addSpacing(10)
        self.lbl_opacity = QLabel("Trace Opacity: 100%")
        self.vis_layout.addWidget(self.lbl_opacity)
        
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.setTickPosition(QSlider.TicksBelow)
        self.slider_opacity.setTickInterval(25)
        self.slider_opacity.valueChanged.connect(self.update_opacity)
        self.vis_layout.addWidget(self.slider_opacity)

        self.sidebar_layout.addWidget(self.grp_vis)
        self.sidebar_layout.addSpacing(20)
        
        # Section 3: Auto Sync.
        self.grp_auto = QGroupBox("3. Auto-Sync (Beta)")
        self.auto_layout = QVBoxLayout()
        self.grp_auto.setLayout(self.auto_layout)
        
        row_tol = QHBoxLayout()
        row_tol.addWidget(QLabel("Sync Tolerance:"))
        self.spin_tolerance = QDoubleSpinBox()
        self.spin_tolerance.setRange(1.0, 50.0)
        self.spin_tolerance.setValue(10.0) 
        self.spin_tolerance.setSuffix("%")
        self.spin_tolerance.setSingleStep(1.0)
        row_tol.addWidget(self.spin_tolerance)
        self.auto_layout.addLayout(row_tol)
        
        self.chk_stop_limit = QCheckBox("Set Stop Marker")
        self.chk_stop_limit.stateChanged.connect(self.toggle_stop_line)
        self.auto_layout.addWidget(self.chk_stop_limit)
        
        self.auto_layout.addSpacing(5)
        
        self.btn_auto_sync = QPushButton("Auto-Sync")
        self.btn_auto_sync.setEnabled(False) 
        self.btn_auto_sync.setToolTip("Align at least 4 symbols manually to enable.")
        self.btn_auto_sync.clicked.connect(self.run_auto_sync)
        self.auto_layout.addWidget(self.btn_auto_sync)
        
        self.sidebar_layout.addWidget(self.grp_auto)
        
        self.sidebar_layout.addSpacing(10)
        self.lbl_debug = QLabel("Drag the white box edges to align with symbols.")
        self.lbl_debug.setWordWrap(True)
        self.lbl_debug.setStyleSheet("color: #666; font-style: italic;")
        self.sidebar_layout.addWidget(self.lbl_debug)
        
        self.sidebar_layout.addStretch()
        main_h_layout.addWidget(self.sidebar, stretch=0)

        # Init state.
        self.update_digital_color('Orange')
        self.update_opacity(100)

    def load_input(self):
        # Pull analog data from context.
        if self.context.demod_signal is None:
            return False, "No demodulated signal in Context (Tab 3)."
            
        self.local_sr = self.context.demod_sr
        
        # Apply Thresholds immediately to get the signal (ints).
        # This is a "soft decision array".
        self.cached_symbol_data = dsp.slice_signal(self.context.demod_signal, self.context.thresholds)
        
        # Restore color preference.
        user_color = self.context.viz_trace_color
        # Find matching combo text if possible, otherwise default.
        # This is a bit rough, matching hex to name, but it works.
        idx = self.cb_color.findText(next((k for k,v in {
            'Orange': '#FFA500', 'Lime': '#32CD32', 'Cyan': '#00FFFF', 
            'Magenta': '#FF00FF', 'Yellow': '#FFFF00', 'White': '#FFFFFF',
            'Black': '#000000', 'Blue': '#0000FF'
        }.items() if v == user_color), 'Orange'))
        if idx >= 0: self.cb_color.setCurrentIndex(idx)
        
        # Update Plot Data
        MAX_POINTS = 10000
        total_points = len(self.cached_symbol_data)
        if total_points > MAX_POINTS:
            step = total_points // MAX_POINTS
            y_data = self.cached_symbol_data[::step]
            x_axis = np.arange(len(y_data)) * (step / self.local_sr)
        else:
            y_data = self.cached_symbol_data
            x_axis = np.arange(total_points) / self.local_sr
            
        self.curve_digital.setData(x_axis, y_data)
        
        # Update Mini Map
        mini_step = max(1, len(y_data) // 5000)
        self.curve_mini.setData(x_axis[::mini_step], y_data[::mini_step]) 
        
        current_range = self.plot_mini.viewRange()[0]
        actual_duration = len(self.cached_symbol_data) / self.local_sr
        
        # Only reset zoom if significant change.
        if abs(current_range[1] - actual_duration) > 0.01:
             self.plot_mini.setXRange(0, actual_duration)
             zoom_t = actual_duration * 0.005
             self.nav_region.setRegion([0, zoom_t])
             
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
             
             self.check_auto_enable()
             self.update_clock_ticks()
             self.stop_line.setValue(actual_duration)
        
        self.autoscale_view()
        self.extract_symbols()
        
        return True, f"Loaded {len(self.cached_symbol_data)} symbol samples."

    def stage_output(self):
        # We perform an explicit length check on numpy array to avoid ambiguity.
        if self.symbol_buffer is None or len(self.symbol_buffer) == 0:
            return False, "No symbols extracted."
            
        # Commit to context.
        self.context.symbols = np.copy(self.symbol_buffer)
        
        # Calculate symbol rate (baud).
        min_t, max_t = self.clock_region.getRegion()
        count = self.spin_symbols.value()
        duration = max_t - min_t
        if duration > 0:
            self.context.symbol_rate = count / duration
        else:
            self.context.symbol_rate = 0
            
        return True, f"Staged {len(self.context.symbols)} symbols."

    def extract_symbols(self):
        # Samples the data at the calculated clock ticks.
        if self.cached_symbol_data is None: return
        
        min_t, max_t = self.clock_region.getRegion()
        num_symbols = self.spin_symbols.value()
        sym_width = (max_t - min_t) / num_symbols
        sr = self.local_sr
        
        # Sample at the center (0.5 offset) of each clock period.
        sample_times = [min_t + (sym_width * (i + 0.5)) for i in range(num_symbols)]
        
        # Convert times to indices.
        indices = np.clip(np.array(sample_times) * sr, 0, len(self.cached_symbol_data)-1).astype(int)
        
        # Extract.
        symbols = self.cached_symbol_data[indices]
        self.symbol_buffer = symbols

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
        # Draws the vertical red lines.
        min_x, max_x = self.clock_region.getRegion()
        width = max_x - min_x
        num_symbols = self.spin_symbols.value()
        tick_pen = pg.mkPen('#FF5555', style=Qt.DashLine, width=2)
        
        # Clear old lines.
        while len(self.tick_lines) > 0:
            self.plot_main.removeItem(self.tick_lines.pop())
            
        if num_symbols <= 1: return
        
        sym_width = width / num_symbols
        needed_lines = num_symbols - 1
        
        view_min, view_max = self.plot_main.viewRange()[0]
        
        # Timing lags, don't draw if there are too many lines on the screen.
        if needed_lines > 200: 
            # Only draw lines currently visible in the viewport.
            start_idx = max(0, int((view_min - min_x) / sym_width))
            end_idx = min(needed_lines, int((view_max - min_x) / sym_width) + 1)
            
            if (end_idx - start_idx) > 200: return
            
            for i in range(start_idx, end_idx):
                l = pg.InfiniteLine(angle=90, movable=False, pen=tick_pen)
                x_pos = min_x + ((i + 1) * sym_width)
                l.setValue(x_pos)
                self.plot_main.addItem(l)
                self.tick_lines.append(l)
        else:
            # Draw all of the lines.
            for i in range(needed_lines):
                l = pg.InfiniteLine(angle=90, movable=False, pen=tick_pen)
                x_pos = min_x + ((i + 1) * sym_width)
                l.setValue(x_pos)
                self.plot_main.addItem(l)
                self.tick_lines.append(l)

    def run_auto_sync(self):
        if self.cached_symbol_data is None: return

        min_t, max_t = self.clock_region.getRegion()
        current_count = self.spin_symbols.value()
        current_width = max_t - min_t
        start_time = min_t
        
        sr = self.local_sr
        limit = self.stop_line.value() if self.chk_stop_limit.isChecked() else None
        
        # Use DSP lib to calculate new duration.
        success, final_time, added_syms = dsp.find_clock_sync(
            self.cached_symbol_data, 
            sr, 
            start_time, 
            current_width, 
            current_count, 
            self.spin_tolerance.value(),
            limit
        )
        
        new_total_symbols = current_count + added_syms
        
        self.spin_symbols.blockSignals(True)
        self.clock_region.blockSignals(True)
        
        self.last_symbol_count = new_total_symbols
        self.spin_symbols.setValue(new_total_symbols)
        self.clock_region.setRegion([start_time, final_time]) 
        
        self.clock_region.blockSignals(False)
        self.spin_symbols.blockSignals(False)
        
        self.update_clock_ticks()
        self.extract_symbols()
        self.check_auto_enable()

    def autoscale_view(self):
        if self.cached_symbol_data is None: return
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
        count = self.spin_symbols.value()
        if count >= 4:
            self.btn_auto_sync.setEnabled(True)
            self.btn_auto_sync.setText(f"Auto-Sync (Next: {count+1})")
        else:
            self.btn_auto_sync.setEnabled(False)
            self.btn_auto_sync.setText("Auto-Sync (Align 4+)")

    def toggle_lock_position(self):
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
        if show and self.cached_symbol_data is not None:
            end_t = len(self.cached_symbol_data) / self.local_sr
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
        self.update_opacity(self.slider_opacity.value())

    def update_opacity(self, value):
        self.lbl_opacity.setText(f"Trace Opacity: {value}%")
        hex_color = self.get_adaptive_color(self.digital_color_name)
        c = pg.mkColor(hex_color)
        alpha = int((value / 100.0) * 255)
        c.setAlpha(alpha)
        self.pen_digital = pg.mkPen(c, width=4)
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
        self.plot_main.setXRange(min_x, max_x, padding=0)
        self.update_clock_ticks()

    def update_nav_from_zoom(self, _, viewRange):
        self.nav_region.blockSignals(True)
        self.nav_region.setRegion(viewRange[0])
        self.nav_region.blockSignals(False)
        self.update_clock_ticks()
