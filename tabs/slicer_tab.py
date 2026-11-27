import numpy as np
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, 
                             QPushButton, QGroupBox, QCheckBox,
                             QSpinBox, QDoubleSpinBox, QScrollArea,
                             QSizePolicy, QWidget, QSplitter)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg

# Import the base class.
from core.base_tab import BaseSignalTab
# Import clock recovery and slicing utilities.
import utils.clock_recovery_lib as clk

# Horizontal split between Left (Visualization) and Right (Sidebar Controls)
# Setting SIDEBAR_PANEL_STRETCH = 0 lets the sidebar sit at natural sizeHint width
VIZ_PANEL_STRETCH = 1
SIDEBAR_PANEL_STRETCH = 0

# Vertical split inside Visualization panel: Main Slicer Plot vs. Minimap
MAIN_PLOT_STRETCH = 8
MINI_PLOT_STRETCH = 1

# Debounce delay (ms) before slicing/updating plot after pan/zoom
DEBOUNCE_MS = 100

# Extra time buffer ratio rendered on either side of the visible plot window
VIEW_BUFFER_RATIO = 0.25

# Trace line width
TRACE_PEN_WIDTH = 3

# Maximum number of symbols allowed in the viewport once Auto-Sync is active
# (or when manual symbol count reaches this threshold) to prevent zoom-out lag
# plotting all the vertical semi-translucent lines is a performance sink 
MAX_VISIBLE_SYMBOLS = 1024
MAX_OVERLAY_ITEMS = 1500

DEFAULT_ALPHA = 0.30
DEFAULT_BETA = 0.05   # None = Auto (alpha / 10); set a float to override Auto
DEFAULT_GAMMA = 0.05  # None = Auto (beta / 10); set a float to override Auto
PLL_MODE_2ND = "2nd-Order PLL (Default)"
PLL_MODE_3RD = "3rd-Order PLL (CFO Tracking)"

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
        self.auto_zc_thresholds = None
        
        # Visual items.
        self.tick_lines = []
        self.digital_color_name = 'Orange'
        self.last_nav_bounds = None

        # Timer for debouncing heavy array slicing and tick updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.refresh_plot_data)
        
        self.init_ui()

    def init_ui(self):
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # Visualization
        viz_container = QWidget()
        self.viz_layout = QVBoxLayout(viz_container)
        self.viz_layout.setContentsMargins(0, 0, 0, 0)
        
        self.plot_main = pg.PlotWidget()
        self.plot_main.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_main.setLabel('bottom', 'Time', units='s')
        self.plot_main.setLabel('left', 'Amplitude') 
        self.plot_main.showGrid(x=True, y=True, alpha=0.3)
        self.plot_main.setMouseEnabled(x=True, y=False)
        self.plot_main.setBackground('#1e1e1e')
        self.apply_opaque_grid('#383838')
        
        self.pen_digital = pg.mkPen('#FFA500', width=TRACE_PEN_WIDTH)
        self.curve_digital = self.plot_main.plot(pen=self.pen_digital, dynamicRangeLimit=None) 
        self.curve_digital.setZValue(10)
        
        # Zero-Line Reference
        self.zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#555555', width=1, style=Qt.PenStyle.DashLine))
        self.zero_line.setZValue(20)
        self.plot_main.addItem(self.zero_line)

        # Tracked ZC & Multi-Level Threshold Overlays
        self.zc_outer_curve = self.plot_main.plot(
            pen=pg.mkPen('#18FFFF', width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.zc_outer_curve.setZValue(34)

        self.zc_curve = self.plot_main.plot(pen=pg.mkPen('#18FFFF', width=2.5))
        self.zc_curve.setZValue(35)
        
        # Clock Region (that interactive manual box)
        self.clock_region = pg.LinearRegionItem(brush=pg.mkBrush(255, 255, 255, 30))
        self.clock_region.setZValue(100)
        for line in self.clock_region.lines:
            line.setPen(pg.mkPen('#AAAAAA', width=4))
            line.setHoverPen(pg.mkPen('#FFFFFF', width=6))
            
        # Hook up clock region changes
        self.clock_region.sigRegionChanged.connect(self.update_clock_ticks)
        self.clock_region.sigRegionChanged.connect(self.extract_symbols)
        self.clock_region.sigRegionChanged.connect(self.on_clock_region_changed)
        self.plot_main.addItem(self.clock_region)
        
        # Auto-Sync Boundary Line (red line)
        self.auto_start_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('r', width=3))
        self.auto_start_line.setZValue(40)
        self.auto_start_line.setVisible(False)
        self.plot_main.addItem(self.auto_start_line)

        # Sampling Point Markers
        self.sample_points = pg.ScatterPlotItem(
            size=9,
            symbol='o',
            pen=pg.mkPen('#111111', width=1.5),
            brush=pg.mkBrush('#00E676')
        )
        self.sample_points.setZValue(50)
        self.plot_main.addItem(self.sample_points)
        
        # Stop line (limit for auto sync).
        self.stop_line = pg.InfiniteLine(
            pos=0, angle=90, movable=True, 
            pen=pg.mkPen('#FF00FF', width=3, style=Qt.PenStyle.DashLine),
            label='STOP LIMIT', labelOpts={'position': 0.95, 'color': '#FF00FF'}
        )
        self.stop_line.setZValue(80)
        self.stop_line.setVisible(False) 
        self.plot_main.addItem(self.stop_line)
        
        self.viz_layout.addWidget(self.plot_main, stretch=MAIN_PLOT_STRETCH)

        # Floating Y-Axis Controls Overlay
        overlay_layout = QVBoxLayout(self.plot_main)
        overlay_layout.setContentsMargins(0, 10, 10, 0)
        
        btn_row = QHBoxLayout()
        btn_row.addStretch(1) # Pushes buttons to the right
        
        self.btn_locate_cursor = QPushButton("Locate Cursor")
        self.btn_y_in = QPushButton("+")
        self.btn_y_out = QPushButton("-")
        self.btn_locate_cursor.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btn_y_in.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btn_y_out.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        
        locate_style = """
            QPushButton {
                background-color: #3c3c3c;
                color: white;
                font-weight: bold;
                font-size: 10pt;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: #5a5a5a; }
        """
        self.btn_locate_cursor.setStyleSheet(locate_style)
        
        btn_style = """
            QPushButton {
                background-color: #3c3c3c;
                color: white;
                font-weight: bold;
                font-size: 12pt;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 2px 10px;
            }
            QPushButton:hover { background-color: #5a5a5a; }
        """
        self.btn_y_in.setStyleSheet(btn_style)
        self.btn_y_out.setStyleSheet(btn_style)
        
        self.btn_locate_cursor.clicked.connect(self.locate_cursor)
        self.btn_y_in.clicked.connect(self.manual_y_zoom_in)
        self.btn_y_out.clicked.connect(self.manual_y_zoom_out)
        
        btn_row.addWidget(self.btn_locate_cursor)
        btn_row.addWidget(self.btn_y_in)
        btn_row.addWidget(self.btn_y_out)
        
        overlay_layout.addLayout(btn_row)
        overlay_layout.addStretch(1) # Pushes the row to the top
        
        # Mini map
        self.plot_mini = pg.PlotWidget()
        self.plot_mini.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.plot_mini.hideAxis('bottom')
        self.plot_mini.hideAxis('left')
        self.plot_mini.setBackground('#1e1e1e')
        self.curve_mini = self.plot_mini.plot(pen=pg.mkPen('w', width=1))
        self.nav_region = pg.LinearRegionItem(pen=pg.mkPen('w', width=4), hoverPen=pg.mkPen('y', width=8))
        self.nav_region.setZValue(10)
        self.plot_mini.addItem(self.nav_region)
        self.nav_region.sigRegionChanged.connect(self.update_zoom_from_nav)
        
        # Connect main plot range changes to our debounced handler
        self.plot_main.sigRangeChanged.connect(self.on_range_changed)
        
        self.viz_layout.addWidget(self.plot_mini, stretch=MINI_PLOT_STRETCH)

        # Sidebar Controls
        self.sidebar = QGroupBox("Clock Recovery")
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
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
        
        autoscale_layout = QHBoxLayout()
        self.btn_autoscale = QPushButton("Auto Scale Y-Axis")
        self.btn_autoscale.clicked.connect(self.autoscale_view)
        autoscale_layout.addWidget(self.btn_autoscale)
        
        self.chk_auto_autoscale = QCheckBox("Auto auto-scale")
        self.chk_auto_autoscale.setChecked(True)
        autoscale_layout.addWidget(self.chk_auto_autoscale)
        
        self.sidebar_layout.addLayout(autoscale_layout)

        # Visuals.
        self.grp_vis = QGroupBox("2. Visual Settings")
        self.vis_layout = QVBoxLayout()
        self.grp_vis.setLayout(self.vis_layout)

        # View Settings
        self.lbl_active_points = QLabel("Visible Points: --")
        self.lbl_active_points.setStyleSheet("font-size: 9pt; color: #888; font-weight: bold;")
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
        
        self.vis_layout.addWidget(QLabel("Trace Color:"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(['Orange', 'Lime', 'Cyan', 'Magenta', 'Yellow', 'White/Black', 'Blue'])
        self.cb_color.currentTextChanged.connect(self.update_digital_color)
        self.vis_layout.addWidget(self.cb_color)
        
        self.sidebar_layout.addWidget(self.grp_vis)
        
        # Section 3: Auto Sync.
        self.grp_auto = QGroupBox("3. Auto-Sync (PLL)")
        self.auto_layout = QVBoxLayout()
        self.grp_auto.setLayout(self.auto_layout)
        
        row_tol = QHBoxLayout()
        row_tol.addWidget(QLabel("Loop Gain (\u03B1):"))
        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.001, 0.99)
        self.spin_alpha.setDecimals(4)
        self.spin_alpha.setSingleStep(0.01)
        self.spin_alpha.setValue(DEFAULT_ALPHA)
        self.spin_alpha.valueChanged.connect(self.on_alpha_changed)
        row_tol.addWidget(self.spin_alpha)
        self.auto_layout.addLayout(row_tol)
        
        self.chk_stop_limit = QCheckBox("Set Stop Marker")
        self.chk_stop_limit.stateChanged.connect(self.toggle_stop_line)
        self.auto_layout.addWidget(self.chk_stop_limit)

        self.btn_advanced = QPushButton("Advanced \u25B8")
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setChecked(False)
        self.btn_advanced.setStyleSheet("QPushButton { text-align: left; padding: 3px 6px; }")
        self.btn_advanced.toggled.connect(self.toggle_advanced_section)
        self.auto_layout.addWidget(self.btn_advanced)

        self.advanced_container = QWidget()
        self.advanced_container.setVisible(False)
        adv_layout = QVBoxLayout(self.advanced_container)
        adv_layout.setContentsMargins(6, 4, 2, 4)
        adv_layout.setSpacing(4)

        row_order = QHBoxLayout()
        row_order.addWidget(QLabel("Order:"))
        self.cb_pll_order = QComboBox()
        self.cb_pll_order.addItems([PLL_MODE_2ND, PLL_MODE_3RD])
        self.cb_pll_order.currentIndexChanged.connect(self.on_pll_order_changed)
        row_order.addWidget(self.cb_pll_order, stretch=1)
        adv_layout.addLayout(row_order)

        gains_grid = QGridLayout()
        gains_grid.setContentsMargins(0, 0, 0, 0)
        gains_grid.setHorizontalSpacing(4)
        gains_grid.setVerticalSpacing(4)

        init_beta = (DEFAULT_ALPHA / 10.0) if DEFAULT_BETA is None else float(DEFAULT_BETA)
        init_gamma = (init_beta / 10.0) if DEFAULT_GAMMA is None else float(DEFAULT_GAMMA)

        gains_grid.addWidget(QLabel("Freq (\u03B2):"), 0, 0)
        self.spin_beta = QDoubleSpinBox()
        self.spin_beta.setRange(0.0, 0.99)
        self.spin_beta.setDecimals(5)
        self.spin_beta.setSingleStep(0.001)
        self.spin_beta.setValue(init_beta)
        self.spin_beta.setEnabled(DEFAULT_BETA is not None)
        self.spin_beta.valueChanged.connect(self.on_beta_changed)
        gains_grid.addWidget(self.spin_beta, 0, 1)

        self.chk_auto_beta = QCheckBox("Auto")
        self.chk_auto_beta.setChecked(DEFAULT_BETA is None)
        self.chk_auto_beta.setToolTip("Auto-calculate \u03B2 = \u03B1 / 10")
        self.chk_auto_beta.stateChanged.connect(self.on_auto_beta_toggled)
        gains_grid.addWidget(self.chk_auto_beta, 0, 2)

        gains_grid.addWidget(QLabel("CFO (\u03B3):"), 1, 0)
        self.spin_gamma = QDoubleSpinBox()
        self.spin_gamma.setRange(0.0, 0.99)
        self.spin_gamma.setDecimals(6)
        self.spin_gamma.setSingleStep(0.0005)
        self.spin_gamma.setValue(init_gamma)
        self.spin_gamma.setEnabled(False)
        gains_grid.addWidget(self.spin_gamma, 1, 1)

        self.chk_auto_gamma = QCheckBox("Auto")
        self.chk_auto_gamma.setChecked(DEFAULT_GAMMA is None)
        self.chk_auto_gamma.setEnabled(False)
        self.chk_auto_gamma.setToolTip("Auto-calculate \u03B3 = \u03B2 / 10")
        self.chk_auto_gamma.stateChanged.connect(self.on_auto_gamma_toggled)
        gains_grid.addWidget(self.chk_auto_gamma, 1, 2)

        adv_layout.addLayout(gains_grid)

        self.chk_outlier_rejection = QCheckBox("Outlier Rejection (Edge Penalty)")
        self.chk_outlier_rejection.setChecked(True)
        self.chk_outlier_rejection.setToolTip(
            "Taper loop gains linearly to 0 toward +/-0.5 symbol edges. "
            "Uncheck for full gain across the whole window."
        )
        adv_layout.addWidget(self.chk_outlier_rejection)

        row_clamp = QHBoxLayout()
        self.chk_freq_clamp = QCheckBox("Clamp Freq (\u00B1%)")
        self.chk_freq_clamp.setChecked(False)
        self.chk_freq_clamp.setToolTip("Clamp recovered symbol rate within +/-% of the seed box rate.")
        self.chk_freq_clamp.stateChanged.connect(self.on_freq_clamp_toggled)
        row_clamp.addWidget(self.chk_freq_clamp)

        self.spin_freq_clamp = QDoubleSpinBox()
        self.spin_freq_clamp.setRange(1.0, 95.0)
        self.spin_freq_clamp.setDecimals(1)
        self.spin_freq_clamp.setSingleStep(5.0)
        self.spin_freq_clamp.setValue(25.0)
        self.spin_freq_clamp.setSuffix("%")
        self.spin_freq_clamp.setEnabled(False)
        row_clamp.addWidget(self.spin_freq_clamp)
        adv_layout.addLayout(row_clamp)

        self.chk_show_zc = QCheckBox("Show ZC Threshold")
        self.chk_show_zc.setChecked(False)
        self.chk_show_zc.stateChanged.connect(self.on_overlay_toggles_changed)
        adv_layout.addWidget(self.chk_show_zc)

        self.chk_show_samples = QCheckBox("Show Sampling Points")
        self.chk_show_samples.setChecked(False)
        self.chk_show_samples.stateChanged.connect(self.on_overlay_toggles_changed)
        adv_layout.addWidget(self.chk_show_samples)

        self.chk_show_bounds = QCheckBox("Show Symbol Bounds")
        self.chk_show_bounds.setChecked(True)
        self.chk_show_bounds.stateChanged.connect(self.update_clock_ticks)
        adv_layout.addWidget(self.chk_show_bounds)

        self.auto_layout.addWidget(self.advanced_container)
        
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
        self.lbl_auto_status.setStyleSheet("color: #666; font-size: 9pt;")
        self.auto_layout.addWidget(self.lbl_auto_status)

        self.lbl_baud_metric = QLabel("")
        self.lbl_baud_metric.setStyleSheet("color: #0277BD; font-size: 14pt; font-weight: bold;")
        self.lbl_baud_metric.setVisible(False)
        self.auto_layout.addWidget(self.lbl_baud_metric)

        self.lbl_sps_metric = QLabel("")
        self.lbl_sps_metric.setStyleSheet("color: #0277BD; font-size: 14pt; font-weight: bold;")
        self.lbl_sps_metric.setVisible(False)
        self.auto_layout.addWidget(self.lbl_sps_metric)

        self.lbl_zc_metric = QLabel("")
        self.lbl_zc_metric.setStyleSheet("color: #00838F; font-size: 9.5pt; font-weight: bold;")
        self.lbl_zc_metric.setVisible(False)
        self.auto_layout.addWidget(self.lbl_zc_metric)
        
        self.sidebar_layout.addWidget(self.grp_auto)
        
        self.lbl_debug = QLabel("Drag the white box edges to manually align ticks with symbol zero-crossings.")
        self.lbl_debug.setWordWrap(True)
        self.lbl_debug.setStyleSheet("color: #666; font-style: italic;")
        self.sidebar_layout.addWidget(self.lbl_debug)
        
        self.sidebar_layout.addStretch()

        # Sidebar inside scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        scroll_area.setWidget(self.sidebar)

        # Combine visualization and sidebar in a user-resizable horizontal splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(viz_container)
        self.main_splitter.addWidget(scroll_area)
        self.main_splitter.setStretchFactor(0, VIZ_PANEL_STRETCH)
        self.main_splitter.setStretchFactor(1, SIDEBAR_PANEL_STRETCH)
        main_h_layout.addWidget(self.main_splitter)

        # Init state.
        self.update_digital_color('Orange')

    def load_input(self):
        # Pull analog data from context.
        if self.context.demod_signal is None:
            return False, "No demodulated signal in Context (Tab 3)."
            
        self.local_sr = self.context.demod_sr
        
        # CFO
        self.centered_analog_data, self.adjusted_thresholds, _ = clk.remove_dc_bias(
            self.context.demod_signal, 
            self.context.thresholds
        )
        
        # Reset Auto-Sync state
        self.clear_auto_sync(refresh=False)
        
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
             zoom_t = actual_duration * 0.10
             
             self.nav_region.blockSignals(True)
             self.nav_region.setRegion([0, zoom_t])
             self.nav_region.blockSignals(False)
             self.last_nav_bounds = (0, zoom_t)
             
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
        self.last_nav_bounds = tuple(viewRange[0])
        self.nav_region.blockSignals(True)
        self.nav_region.setRegion(viewRange[0])
        self.nav_region.blockSignals(False)
        
        # Restart the timer to debounce the plot update
        self.update_timer.start(DEBOUNCE_MS)

    def refresh_plot_data(self):
        # Automatically adjust Y-Axis if enabled before drawing points
        if getattr(self, 'chk_auto_autoscale', None) and self.chk_auto_autoscale.isChecked():
            self.autoscale_view()
        self.update_main_plot()
        self.update_clock_ticks()
        self.update_clock_overlays()

    def update_main_plot(self):
        if self.centered_analog_data is None: return
        
        sr = self.local_sr
        total_points = len(self.centered_analog_data)
        
        # Get the strict visible time window
        view_range = self.plot_main.viewRange()[0]
        min_t, max_t = view_range[0], view_range[1]
        
        # Add a buffer on either side for panning
        pad_t = (max_t - min_t) * VIEW_BUFFER_RATIO
        min_t = max(0, min_t - pad_t)
        max_t = min(total_points / sr, max_t + pad_t)
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(total_points, int(max_t * sr))
        
        if i_stop <= i_start: return
        
        # Only extract the exact segment we need
        view_y = self.centered_analog_data[i_start:i_stop]
        
        # Decide if we pass raw points or apply fast NumPy Peak Downsampling
        num_points = len(view_y)
        thresh = self.spin_plot_thresh.value()
        ds = 1
        if num_points > thresh:
            self.lbl_active_points.setText(f"Visible Points: {num_points:,}  [Downsampled]")
            num_buckets = max(1, thresh // 2)
            ds = max(1, num_points // num_buckets)
        else:
            self.lbl_active_points.setText(f"Visible Points: {num_points:,}  [1:1]")

        if ds > 1:
            n = num_points // ds
            stx = ds // 2
            x_sub = (np.arange(n, dtype=np.float64) * ds + (i_start + stx)) / sr
            view_x = np.repeat(x_sub, 2)
            y_reshaped = view_y[:n * ds].reshape((n, ds))
            view_y_ds = np.empty(n * 2, dtype=view_y.dtype)
            view_y_ds[0::2] = y_reshaped.max(axis=1)
            view_y_ds[1::2] = y_reshaped.min(axis=1)
            view_y = view_y_ds
        else:
            view_x = np.arange(i_start, i_stop, dtype=np.float64) / sr
            
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
            timestamps = self.auto_clock_centers
            zc_offsets = self.auto_zc_thresholds
        else:
            # Otherwise, calculate timestamps manually from the box
            min_t, max_t = self.clock_region.getRegion()
            num_symbols = self.spin_symbols.value()
            sym_width = (max_t - min_t) / num_symbols
            timestamps = [min_t + (sym_width * (i + 0.5)) for i in range(num_symbols)]
            zc_offsets = None
            
        # Sample and digitize via clock recovery lib
        self.symbol_buffer = clk.sample_and_slice(
            self.centered_analog_data, 
            timestamps, 
            sr, 
            self.adjusted_thresholds,
            zc_offsets=zc_offsets,
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
        self.apply_zoom_limits()

    def on_clock_region_changed(self):
        if self.auto_clock_centers is None and self.spin_symbols.value() >= MAX_VISIBLE_SYMBOLS:
            self.apply_zoom_limits()

    def update_clock_ticks(self):
        # Draws the vertical clock lines based on Manual + Auto states.
        if self.centered_analog_data is None: return
        
        # Clear old lines.
        while len(self.tick_lines) > 0:
            self.plot_main.removeItem(self.tick_lines.pop())

        if not self.chk_show_bounds.isChecked():
            return

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
            
        if edges_to_draw is None or len(edges_to_draw) == 0: return
        
        tick_pen = pg.mkPen('#FF5555', style=Qt.PenStyle.DashLine, width=2)
        view_min, view_max = self.plot_main.viewRange()[0]
        
        # Convert to numpy array for fast filtering
        edges_arr = np.array(edges_to_draw)
        
        # Fallback sym_width approximation to pad view range
        pad_width = edges_arr[1] - edges_arr[0] if len(edges_arr) > 1 else 0.001
        
        # Filter edges to only what is currently in the viewport to prevent lag
        visible_edges = edges_arr[(edges_arr >= view_min - pad_width) & (edges_arr <= view_max + pad_width)]
        
        # Max lines on screen check to protect UI thread
        if len(visible_edges) > MAX_VISIBLE_SYMBOLS:
            step = (len(visible_edges) + MAX_VISIBLE_SYMBOLS - 1) // MAX_VISIBLE_SYMBOLS
            visible_edges = visible_edges[::step]
            
        for x_pos in visible_edges:
            l = pg.InfiniteLine(angle=90, movable=False, pen=tick_pen)
            l.setZValue(5)
            l.setValue(x_pos)
            self.plot_main.addItem(l)
            self.tick_lines.append(l)

    def toggle_advanced_section(self, checked):
        self.advanced_container.setVisible(checked)
        self._update_advanced_button_text()

    def _update_advanced_button_text(self):
        if self.btn_advanced.isChecked():
            self.btn_advanced.setText("Advanced \u25BE")
        elif self.cb_pll_order.currentText() == PLL_MODE_3RD:
            self.btn_advanced.setText("Advanced \u25B8 (3rd-Order)")
        else:
            self.btn_advanced.setText("Advanced \u25B8")

    def _set_pll_controls_enabled(self, enabled):
        is_unlocked = bool(enabled)
        is_3rd = self.cb_pll_order.currentText() == PLL_MODE_3RD
        self.spin_alpha.setEnabled(is_unlocked)
        self.chk_stop_limit.setEnabled(is_unlocked)
        self.stop_line.setMovable(is_unlocked)
        self.cb_pll_order.setEnabled(is_unlocked)
        self.chk_auto_beta.setEnabled(is_unlocked)
        self.spin_beta.setEnabled(is_unlocked and not self.chk_auto_beta.isChecked())
        self.chk_auto_gamma.setEnabled(is_unlocked and is_3rd)
        self.spin_gamma.setEnabled(is_unlocked and is_3rd and not self.chk_auto_gamma.isChecked())
        self.chk_outlier_rejection.setEnabled(is_unlocked)
        self.chk_freq_clamp.setEnabled(is_unlocked)
        self.spin_freq_clamp.setEnabled(is_unlocked and self.chk_freq_clamp.isChecked())

    def on_alpha_changed(self, alpha_val):
        if self.chk_auto_beta.isChecked():
            self.spin_beta.blockSignals(True)
            self.spin_beta.setValue(alpha_val / 10.0)
            self.spin_beta.blockSignals(False)
        if self.chk_auto_gamma.isChecked():
            self.spin_gamma.blockSignals(True)
            self.spin_gamma.setValue(self.spin_beta.value() / 10.0)
            self.spin_gamma.blockSignals(False)

    def on_beta_changed(self, beta_val):
        if self.chk_auto_gamma.isChecked():
            self.spin_gamma.blockSignals(True)
            self.spin_gamma.setValue(beta_val / 10.0)
            self.spin_gamma.blockSignals(False)

    def on_auto_beta_toggled(self):
        is_auto = self.chk_auto_beta.isChecked()
        is_unlocked = self.auto_clock_centers is None
        self.spin_beta.setEnabled(is_unlocked and not is_auto)
        if is_auto:
            self.spin_beta.blockSignals(True)
            self.spin_beta.setValue(self.spin_alpha.value() / 10.0)
            self.spin_beta.blockSignals(False)
            if self.chk_auto_gamma.isChecked():
                self.spin_gamma.blockSignals(True)
                self.spin_gamma.setValue(self.spin_beta.value() / 10.0)
                self.spin_gamma.blockSignals(False)

    def on_auto_gamma_toggled(self):
        is_3rd = self.cb_pll_order.currentText() == PLL_MODE_3RD
        is_auto = self.chk_auto_gamma.isChecked()
        is_unlocked = self.auto_clock_centers is None
        self.spin_gamma.setEnabled(is_unlocked and is_3rd and not is_auto)
        if is_auto:
            self.spin_gamma.blockSignals(True)
            self.spin_gamma.setValue(self.spin_beta.value() / 10.0)
            self.spin_gamma.blockSignals(False)

    def on_pll_order_changed(self):
        is_3rd = self.cb_pll_order.currentText() == PLL_MODE_3RD
        is_unlocked = self.auto_clock_centers is None
        self.chk_auto_gamma.setEnabled(is_unlocked and is_3rd)
        self.spin_gamma.setEnabled(is_unlocked and is_3rd and not self.chk_auto_gamma.isChecked())
        self._update_advanced_button_text()

    def on_freq_clamp_toggled(self):
        is_unlocked = self.auto_clock_centers is None
        self.spin_freq_clamp.setEnabled(is_unlocked and self.chk_freq_clamp.isChecked())

    def on_overlay_toggles_changed(self):
        self.update_clock_overlays()
        self._update_zc_metric_label()

    def _update_zc_metric_label(self):
        if (
            self.auto_zc_thresholds is not None
            and len(self.auto_zc_thresholds) > 0
            and self.chk_show_zc.isChecked()
        ):
            z0 = float(self.auto_zc_thresholds[0])
            z1 = float(self.auto_zc_thresholds[-1])
            self.lbl_zc_metric.setText(f"ZC Track: {z0:.4g} \u2192 {z1:.4g} (\u0394 {z1 - z0:+.4g})")
            self.lbl_zc_metric.setVisible(True)
        else:
            self.lbl_zc_metric.setText("")
            self.lbl_zc_metric.setVisible(False)

    def update_clock_overlays(self):
        """Render optional sampling points and tracked ZC/outer threshold overlays in viewport."""
        if self.centered_analog_data is None:
            self.sample_points.setData([], [])
            self.zc_curve.setData([], [])
            self.zc_outer_curve.setData([], [])
            return

        view_min, view_max = self.plot_main.viewRange()[0]

        # 1. Sampling points
        if self.auto_clock_centers is not None and self.chk_show_samples.isChecked():
            centers_arr = self.auto_clock_centers
            if len(centers_arr) > 0:
                pad_x = (
                    float(centers_arr[1] - centers_arr[0])
                    if len(centers_arr) > 1
                    else (view_max - view_min) * 0.05
                )
                vis_centers = centers_arr[
                    (centers_arr >= view_min - pad_x) & (centers_arr <= view_max + pad_x)
                ]
                if len(vis_centers) == 0:
                    self.sample_points.setData([], [])
                else:
                    if len(vis_centers) > MAX_OVERLAY_ITEMS:
                        step = (len(vis_centers) + MAX_OVERLAY_ITEMS - 1) // MAX_OVERLAY_ITEMS
                        vis_centers = vis_centers[::step]
                    vis_y = clk.sample_signal_at_positions(
                        self.centered_analog_data, vis_centers, self.local_sr
                    )
                    self.sample_points.setData(x=vis_centers, y=vis_y)
            else:
                self.sample_points.setData([], [])
        else:
            self.sample_points.setData([], [])

        # 2. Per-symbol ZC threshold and outer 4/8-FSK boundaries
        outer_offsets = [
            float(t) for t in (self.adjusted_thresholds or []) if abs(float(t)) > 1e-12
        ]
        if (
            self.auto_zc_thresholds is not None
            and self.auto_clock_edges is not None
            and self.chk_show_zc.isChecked()
        ):
            n = min(len(self.auto_clock_edges) - 1, len(self.auto_zc_thresholds))
            if n <= 0:
                self.zc_curve.setData([], [])
                self.zc_outer_curve.setData([], [])
            else:
                left_edges = self.auto_clock_edges[:n]
                right_edges = self.auto_clock_edges[1 : n + 1]
                zcs = self.auto_zc_thresholds[:n]
                mask = (right_edges >= view_min) & (left_edges <= view_max)
                count = int(np.count_nonzero(mask))
                if count == 0:
                    self.zc_curve.setData([], [])
                    self.zc_outer_curve.setData([], [])
                elif count <= MAX_OVERLAY_ITEMS:
                    x_pairs = np.empty(2 * count, dtype=np.float64)
                    x_pairs[0::2] = left_edges[mask]
                    x_pairs[1::2] = right_edges[mask]
                    y_pairs = np.repeat(zcs[mask], 2)
                    self.zc_curve.setData(x_pairs, y_pairs, connect='pairs')
                    if outer_offsets:
                        outer_x = np.tile(x_pairs, len(outer_offsets))
                        outer_y = np.concatenate([y_pairs + off for off in outer_offsets])
                        self.zc_outer_curve.setData(outer_x, outer_y, connect='pairs')
                    else:
                        self.zc_outer_curve.setData([], [])
                else:
                    step = (count + MAX_OVERLAY_ITEMS - 1) // MAX_OVERLAY_ITEMS
                    if self.auto_clock_centers is not None and len(self.auto_clock_centers) >= n:
                        xs = self.auto_clock_centers[:n][mask][::step]
                    else:
                        xs = (0.5 * (left_edges[mask] + right_edges[mask]))[::step]
                    ys = zcs[mask][::step]
                    self.zc_curve.setData(xs, ys, connect='all')
                    if outer_offsets:
                        seg_x = []
                        seg_y = []
                        nan_pt = np.array([np.nan], dtype=np.float64)
                        for idx, off in enumerate(outer_offsets):
                            if idx > 0:
                                seg_x.append(nan_pt)
                                seg_y.append(nan_pt)
                            seg_x.append(xs)
                            seg_y.append(ys + off)
                        self.zc_outer_curve.setData(
                            np.concatenate(seg_x), np.concatenate(seg_y), connect='finite'
                        )
                    else:
                        self.zc_outer_curve.setData([], [])
        else:
            self.zc_curve.setData([], [])
            self.zc_outer_curve.setData([], [])

    def run_auto_sync(self):
        if self.centered_analog_data is None: return

        min_t, max_t = self.clock_region.getRegion()
        current_count = self.spin_symbols.value()
        current_width = max_t - min_t
        start_time = min_t
        
        sr = self.local_sr
        limit = self.stop_line.value() if self.chk_stop_limit.isChecked() else None
        alpha = float(self.spin_alpha.value())
        beta = None if self.chk_auto_beta.isChecked() else float(self.spin_beta.value())
        gamma = None if self.chk_auto_gamma.isChecked() else float(self.spin_gamma.value())
        outlier_rejection = self.chk_outlier_rejection.isChecked()
        freq_clamp_pct = float(self.spin_freq_clamp.value()) if self.chk_freq_clamp.isChecked() else None
        is_3rd = self.cb_pll_order.currentText() == PLL_MODE_3RD
        
        if is_3rd:
            success, centers, zc_thresholds, manual_boundary = clk.find_clock_sync_3rd_order(
                self.centered_analog_data,
                sr,
                start_time,
                current_width,
                current_count,
                initial_zc=0.0,
                alpha=alpha,
                beta=beta,
                gamma=gamma,
                limit_time=limit,
                outlier_rejection=outlier_rejection,
                freq_clamp_pct=freq_clamp_pct,
            )
        else:
            success, centers, manual_boundary = clk.find_clock_sync(
                self.centered_analog_data,
                sr,
                start_time,
                current_width,
                current_count,
                alpha=alpha,
                limit_time=limit,
                beta=beta,
                outlier_rejection=outlier_rejection,
                freq_clamp_pct=freq_clamp_pct,
            )
            zc_thresholds = np.zeros(len(centers), dtype=np.float64)
        
        if success and len(centers) > 0:
            self.auto_clock_centers = centers
            fallback_sps = current_width / max(1, current_count)
            self.auto_clock_edges = clk.compute_edges_from_centers(centers, fallback_sps)
            self.auto_zc_thresholds = zc_thresholds
            
            # Lock the UI
            self.clock_region.setMovable(False)
            for line in self.clock_region.lines:
                line.setMovable(False)
            
            self.spin_symbols.setEnabled(False)
            self.btn_auto_sync.setEnabled(False)
            self.btn_clear_auto.setEnabled(True)
            self.chk_lock_pos.setEnabled(False)
            self.btn_locate_cursor.setEnabled(False)
            self._set_pll_controls_enabled(False)
            
            # Show Red Boundary Line
            self.auto_start_line.setValue(manual_boundary)
            self.auto_start_line.setVisible(True)
            
            total = len(centers)
            if is_3rd:
                self.lbl_auto_status.setText(f"Status: 3rd-Order PLL (Total Sym: {total})")
            else:
                self.lbl_auto_status.setText(f"Status: PLL Mode (Total Sym: {total})")
            self.lbl_auto_status.setStyleSheet("color: #2E7D32; font-weight: bold;")

            if total > 1:
                diffs = np.diff(centers)
                median_duration = float(np.median(diffs))
                if median_duration > 0:
                    baud = 1.0 / median_duration
                    sps = median_duration * self.local_sr
                    self.lbl_baud_metric.setText(f"Median Baud: {baud:.2f}")
                    self.lbl_baud_metric.setVisible(True)
                    self.lbl_sps_metric.setText(f"SPS: {sps:.2f}")
                    self.lbl_sps_metric.setVisible(True)

            self._update_zc_metric_label()
            self.apply_zoom_limits()
            self.refresh_plot_data()
            self.extract_symbols()
        else:
            self.lbl_auto_status.setText("Status: Auto-Sync produced 0 symbols.")
            self.lbl_auto_status.setStyleSheet("color: #d32f2f; font-weight: bold;")

    def clear_auto_sync(self, _checked=False, *, refresh=True):
        # Resets back to manual mode.
        self.auto_clock_centers = None
        self.auto_clock_edges = None
        self.auto_zc_thresholds = None
        
        self.auto_start_line.setVisible(False)
        self.sample_points.setData([], [])
        self.zc_curve.setData([], [])
        self.zc_outer_curve.setData([], [])
        
        # Unlock UI
        self.spin_symbols.setEnabled(True)
        self.btn_clear_auto.setEnabled(False)
        self.chk_lock_pos.setEnabled(True)
        self.btn_locate_cursor.setEnabled(True)
        self._set_pll_controls_enabled(True)
        
        self.toggle_lock_position() # Apply correct lock state for lines
        
        self.lbl_auto_status.setText("Status: Manual Mode")
        self.lbl_auto_status.setStyleSheet("color: #666; font-size: 9pt;")
        
        self.lbl_baud_metric.setText("")
        self.lbl_baud_metric.setVisible(False)
        self.lbl_sps_metric.setText("")
        self.lbl_sps_metric.setVisible(False)
        self._update_zc_metric_label()
        
        self.check_auto_enable()
        self.apply_zoom_limits()
        if refresh:
            self.refresh_plot_data()
            self.extract_symbols()

    def autoscale_view(self):
        if self.centered_analog_data is None: return
        
        min_t, max_t = self.nav_region.getRegion()
        sr = self.local_sr
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(len(self.centered_analog_data), int(max_t * sr))
        if i_stop <= i_start: return
        
        view_y = self.centered_analog_data[i_start:i_stop]
        if len(view_y) == 0: return
        
        y_min = float(np.min(view_y))
        y_max = float(np.max(view_y))
        if abs(y_max - y_min) < 1e-9: margin = 1.0 
        else: margin = (y_max - y_min) * 0.20 
        
        self.plot_main.setYRange(y_min - margin, y_max + margin)

    def locate_cursor(self):
        if self.auto_clock_centers is not None:
            return

        # Calculate viewport bounds
        view_range = self.plot_main.viewRange()[0]
        min_x, max_x = view_range[0], view_range[1]
        view_width = max_x - min_x
        
        # Calculate new region bounds
        box_width = view_width * 0.20
        center_x = min_x + (view_width / 2.0)
        
        # Move the box safely
        self.clock_region.blockSignals(True)
        self.clock_region.setRegion([center_x - (box_width / 2.0), center_x + (box_width / 2.0)])
        self.clock_region.blockSignals(False)
        
        # Trigger symbol extraction explicitly since we blocked signals
        self.update_clock_ticks()
        self.extract_symbols()

    def manual_y_zoom_in(self):
        self.chk_auto_autoscale.setChecked(False)
        y_min, y_max = self.plot_main.viewRange()[1]
        
        span = y_max - y_min
        delta = span * 0.15
        self.plot_main.setYRange(y_min + (delta / 2.0), y_max - (delta / 2.0), padding=0)

    def manual_y_zoom_out(self):
        self.chk_auto_autoscale.setChecked(False)
        y_min, y_max = self.plot_main.viewRange()[1]
        
        span = y_max - y_min
        delta = span * 0.15
        self.plot_main.setYRange(y_min - (delta / 2.0), y_max + (delta / 2.0), padding=0)

    def check_auto_enable(self):
        # Only check if we aren't currently auto-synced
        if self.auto_clock_centers is not None:
            return
            
        count = self.spin_symbols.value()
        if count >= 4:
            self.btn_auto_sync.setEnabled(True)
            self.btn_auto_sync.setText(f"Auto-Sync")
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
                line.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
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
        self.pen_digital = pg.mkPen(pg.mkColor(hex_color), width=TRACE_PEN_WIDTH)
        self.curve_digital.setPen(self.pen_digital)

    def apply_opaque_grid(self, hex_color):
        """Render major-only opaque gridlines behind the plot to avoid alpha-blending overhead."""
        grid_pen = pg.mkPen(hex_color, width=1)
        for axis_name in ('left', 'bottom'):
            ax = self.plot_main.getAxis(axis_name)
            ax.setTickPen(grid_pen)
            ax.setStyle(tickAlpha=255, maxTickLevel=1)
            ax.setZValue(-1000)

    def toggle_light_mode(self):
        if self.chk_light_mode.isChecked():
            self.plot_main.setBackground('w')
            self.plot_main.getAxis('left').setPen('k')
            self.plot_main.getAxis('bottom').setPen('k')
            self.plot_main.getAxis('left').setTextPen('k')
            self.plot_main.getAxis('bottom').setTextPen('k')
            self.apply_opaque_grid('#d8d8d8')
            self.clock_region.setBrush(pg.mkBrush(0, 0, 0, 50)) 
            zc_track_color = '#006064'
            zc_outer_color = '#00838F'
            sample_brush = pg.mkBrush('#00C853')
        else:
            self.plot_main.setBackground('#1e1e1e')
            self.plot_main.getAxis('left').setPen('w')
            self.plot_main.getAxis('bottom').setPen('w')
            self.plot_main.getAxis('left').setTextPen('w')
            self.plot_main.getAxis('bottom').setTextPen('w')
            self.apply_opaque_grid('#383838')
            self.clock_region.setBrush(pg.mkBrush(255, 255, 255, 30))
            zc_track_color = '#18FFFF'
            zc_outer_color = '#18FFFF'
            sample_brush = pg.mkBrush('#00E676')

        self.zc_curve.setPen(pg.mkPen(zc_track_color, width=2.5))
        self.zc_outer_curve.setPen(pg.mkPen(zc_outer_color, width=1.5, style=Qt.PenStyle.DashLine))
        self.sample_points.setPen(pg.mkPen('#111111', width=1.5))
        self.sample_points.setBrush(sample_brush)
        
        self.update_digital_color(self.digital_color_name)

    def get_max_view_span(self):
        # Returns the maximum allowed viewport time span (MAX_VISIBLE_SYMBOLS)
        # when Auto-Sync is active or manual symbol count >= MAX_VISIBLE_SYMBOLS.
        if self.auto_clock_centers is not None and len(self.auto_clock_centers) > 1:
            sym_dur = float(np.median(np.diff(self.auto_clock_centers)))
            if sym_dur > 0:
                return sym_dur * MAX_VISIBLE_SYMBOLS
        elif self.spin_symbols.value() >= MAX_VISIBLE_SYMBOLS:
            c_min, c_max = self.clock_region.getRegion()
            sym_dur = (c_max - c_min) / self.spin_symbols.value()
            if sym_dur > 0:
                return sym_dur * MAX_VISIBLE_SYMBOLS
        return None

    def apply_zoom_limits(self):
        max_span = self.get_max_view_span()
        self.plot_main.setLimits(maxXRange=max_span)
        if max_span is not None:
            min_x, max_x = self.nav_region.getRegion()
            if (max_x - min_x) > max_span:
                new_max = min_x + max_span
                self.nav_region.blockSignals(True)
                self.nav_region.setRegion([min_x, new_max])
                self.nav_region.blockSignals(False)
                self.last_nav_bounds = (min_x, new_max)
                self.plot_main.setXRange(min_x, new_max, padding=0)

    def update_zoom_from_nav(self):
        min_x, max_x = self.nav_region.getRegion()
        max_span = self.get_max_view_span()
        if max_span is not None and (max_x - min_x) > max_span:
            if self.last_nav_bounds is not None:
                last_min, last_max = self.last_nav_bounds
                # Keep the stationary edge anchored while clamping the moved edge
                if abs(min_x - last_min) > abs(max_x - last_max):
                    min_x = max_x - max_span
                else:
                    max_x = min_x + max_span
            else:
                max_x = min_x + max_span
            self.nav_region.blockSignals(True)
            self.nav_region.setRegion([min_x, max_x])
            self.nav_region.blockSignals(False)
        self.last_nav_bounds = (min_x, max_x)
        self.plot_main.setXRange(min_x, max_x, padding=0)
