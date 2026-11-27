import numpy as np
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QPushButton, QGroupBox, QCheckBox, QSlider, 
                             QSpinBox, QScrollArea, QSizePolicy, QWidget,
                             QSplitter)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg

# Import the base class.
from core.base_tab import BaseSignalTab
# Import dsp utilities.
import utils.dsp_lib as dsp

# Horizontal split between Left (Visualization) and Right (Sidebar Controls)
# Setting SIDEBAR_PANEL_STRETCH = 0 lets the sidebar sit at natural sizeHint width
VIZ_PANEL_STRETCH = 1
SIDEBAR_PANEL_STRETCH = 0

# Vertical split inside Visualization panel: Main Demod Plot vs. Minimap
MAIN_PLOT_STRETCH = 8
MINI_PLOT_STRETCH = 1

# Debounce delay (ms) before slicing/updating plot after pan/zoom
DEBOUNCE_MS = 100

# Extra time buffer ratio rendered on either side of the visible plot window
VIEW_BUFFER_RATIO = 0.25

# Trace line widths
ANALOG_PEN_WIDTH = 3
DIGITAL_PEN_WIDTH = 5

class DemodTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Demodulator")
        
        # Local state.
        self.local_filtered_data = None
        self.local_filtered_sr = 1.0
        
        self.raw_demod_result = None
        self.filtered_demod_result = None
        self.demod_result = None
        self.norm_applied = False
        self.norm_window_len = 0
        
        self.thresh_lines = []
        self.digital_color_name = 'Orange'
        
        # Timer for debouncing heavy array slicing
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.refresh_plot_data)
        
        self.init_ui()

    def init_ui(self):
        # Main layout is horizontal (Plot | Controls).
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # Visualization
        viz_container = QWidget()
        self.viz_layout = QVBoxLayout(viz_container)
        self.viz_layout.setContentsMargins(0, 0, 0, 0)
        
        # Main plot setup.
        self.plot_main = pg.PlotWidget()
        self.plot_main.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_main.setLabel('bottom', 'Time', units='s')
        self.plot_main.showGrid(x=True, y=True, alpha=0.3)
        self.plot_main.setBackground('#1e1e1e')
        self.apply_opaque_grid('#383838')
        self.plot_main.setMouseEnabled(x=True, y=False)
        
        # Analog trace (debounced downsampling in update_main_plot instead of per-frame clip/downsample).
        self.curve_main = self.plot_main.plot(
            pen=pg.mkPen('g', width=ANALOG_PEN_WIDTH),
            dynamicRangeLimit=None
        )
        
        # Digital overlay trace.
        self.pen_digital = pg.mkPen('#FFA500', width=DIGITAL_PEN_WIDTH)
        self.curve_digital = self.plot_main.plot(
            pen=self.pen_digital,
            dynamicRangeLimit=None
        )
        self.curve_digital.setVisible(False)

        overlay_layout = QVBoxLayout(self.plot_main)
        overlay_layout.setContentsMargins(0, 10, 10, 0)
        
        btn_row = QHBoxLayout()
        btn_row.addStretch(1) # Pushes buttons to the right
        
        self.btn_y_in = QPushButton("+")
        self.btn_y_out = QPushButton("-")
        self.btn_y_in.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btn_y_out.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        
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
        
        self.btn_y_in.clicked.connect(self.manual_y_zoom_in)
        self.btn_y_out.clicked.connect(self.manual_y_zoom_out)
        
        btn_row.addWidget(self.btn_y_in)
        btn_row.addWidget(self.btn_y_out)
        
        overlay_layout.addLayout(btn_row)
        overlay_layout.addStretch(1) # Pushes the row to the top

        # Filter box.
        self.filter_region = pg.LinearRegionItem(brush=pg.mkBrush(255, 255, 255, 50))
        self.filter_region.setZValue(10)
        self.filter_region.hide()
        self.filter_region.sigRegionChanged.connect(self.update_filter_label)
        self.plot_main.addItem(self.filter_region)

        # Normalization window box.
        self.norm_region = pg.LinearRegionItem(
            brush=pg.mkBrush(0, 200, 255, 45),
            pen=pg.mkPen('#00E5FF', width=2),
            hoverPen=pg.mkPen('#80F0FF', width=4),
        )
        self.norm_region.setZValue(11)
        self.norm_region.hide()
        self.norm_region.sigRegionChanged.connect(self.update_norm_label)
        self.plot_main.addItem(self.norm_region)
        
        self.viz_layout.addWidget(self.plot_main, stretch=MAIN_PLOT_STRETCH)
        
        # Mini map.
        self.plot_mini = pg.PlotWidget()
        self.plot_mini.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.plot_mini.hideAxis('bottom')
        self.plot_mini.hideAxis('left')
        self.plot_mini.setBackground('#1e1e1e')
        self.curve_mini = self.plot_mini.plot(pen=pg.mkPen('w', width=1))
        self.region = pg.LinearRegionItem(pen=pg.mkPen('w', width=4), hoverPen=pg.mkPen('y', width=8))
        self.region.setZValue(10)
        self.plot_mini.addItem(self.region)
        
        # Connecting the visual navigation mapping
        self.region.sigRegionChanged.connect(self.update_zoom_from_region)
        self.plot_main.sigRangeChanged.connect(self.on_range_changed)
        
        self.viz_layout.addWidget(self.plot_mini, stretch=MINI_PLOT_STRETCH)

        # Sidebar Controls
        self.sidebar = QGroupBox("Demodulation")
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        self.btn_run = QPushButton("RUN DEMOD")
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #e1f5fe; padding: 8px 15px;")
        self.btn_run.clicked.connect(self.run_demod)
        self.sidebar_layout.addWidget(self.btn_run)
        
        self.sidebar_layout.addWidget(QLabel("Mode:"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["Amplitude (ASK)", "Frequency (FSK)", "Phase (PSK)"])
        self.sidebar_layout.addWidget(self.cb_mode)
        
        autoscale_layout = QHBoxLayout()
        self.btn_autoscale = QPushButton("Auto Scale Y-Axis")
        self.btn_autoscale.clicked.connect(self.autoscale_view)
        autoscale_layout.addWidget(self.btn_autoscale)
        
        self.chk_auto_autoscale = QCheckBox("Auto auto-scale")
        self.chk_auto_autoscale.setChecked(True)
        autoscale_layout.addWidget(self.chk_auto_autoscale)
        
        self.sidebar_layout.addLayout(autoscale_layout)

        self.grp_filter = QGroupBox("Matched Filtering (Optional)")
        self.filter_layout = QVBoxLayout()
        self.grp_filter.setLayout(self.filter_layout)
        
        self.cb_filter = QComboBox()
        self.cb_filter.addItems(["Moving Average", "Gaussian", "RRC"])
        self.filter_layout.addWidget(self.cb_filter)
        
        self.chk_filter_box = QCheckBox("Show Filter Size Box")
        self.chk_filter_box.stateChanged.connect(self.toggle_filter_box)
        self.filter_layout.addWidget(self.chk_filter_box)
        
        self.lbl_filter_len = QLabel("Length: -- samples")
        self.filter_layout.addWidget(self.lbl_filter_len)
        
        self.btn_apply_filter = QPushButton("Apply Filter")
        self.btn_apply_filter.clicked.connect(self.apply_filter)
        self.filter_layout.addWidget(self.btn_apply_filter)
        
        self.sidebar_layout.addWidget(self.grp_filter)

        self.btn_advanced = QPushButton("Advanced \u25B8")
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setChecked(False)
        self.btn_advanced.setStyleSheet("QPushButton { text-align: left; padding: 3px 6px; }")
        self.btn_advanced.toggled.connect(self.toggle_advanced_section)
        self.sidebar_layout.addWidget(self.btn_advanced)

        self.advanced_container = QWidget()
        self.advanced_container.setVisible(False)
        adv_layout = QVBoxLayout(self.advanced_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(4)

        self.grp_norm = QGroupBox("Sliding Normalization")
        norm_layout = QVBoxLayout(self.grp_norm)

        self.chk_norm_box = QCheckBox("Show Norm Window Box")
        self.chk_norm_box.stateChanged.connect(self.toggle_norm_box)
        norm_layout.addWidget(self.chk_norm_box)

        self.lbl_norm_len = QLabel("Length: -- samples")
        norm_layout.addWidget(self.lbl_norm_len)

        row_norm_btns = QHBoxLayout()
        self.btn_apply_norm = QPushButton("Normalize")
        self.btn_apply_norm.clicked.connect(self.apply_normalization)
        row_norm_btns.addWidget(self.btn_apply_norm)

        self.btn_reset_norm = QPushButton("Reset")
        self.btn_reset_norm.setEnabled(False)
        self.btn_reset_norm.clicked.connect(self.reset_normalization)
        row_norm_btns.addWidget(self.btn_reset_norm)
        norm_layout.addLayout(row_norm_btns)

        self.lbl_norm_status = QLabel("")
        self.lbl_norm_status.setStyleSheet("color: #00838F; font-size: 9pt; font-weight: bold;")
        self.lbl_norm_status.setVisible(False)
        norm_layout.addWidget(self.lbl_norm_status)

        adv_layout.addWidget(self.grp_norm)
        self.sidebar_layout.addWidget(self.advanced_container)

        # View Settings.
        self.grp_view = QGroupBox("View Settings")
        self.view_layout = QVBoxLayout()
        self.grp_view.setLayout(self.view_layout)

        self.lbl_active_points = QLabel("Visible Points: --")
        self.lbl_active_points.setStyleSheet("font-size: 9pt; color: #888; font-weight: bold;")
        self.view_layout.addWidget(self.lbl_active_points)
        
        self.chk_light_mode = QCheckBox("Light Mode")
        self.chk_light_mode.stateChanged.connect(self.toggle_light_mode)
        self.view_layout.addWidget(self.chk_light_mode)
        
        # Interactive Threshold Setting
        row_thresh = QHBoxLayout()
        row_thresh.addWidget(QLabel("Plot Threshold:"))
        self.spin_plot_thresh = QSpinBox()
        self.spin_plot_thresh.setRange(1000, 5000000)
        self.spin_plot_thresh.setSingleStep(10000)
        self.spin_plot_thresh.setValue(10000)
        self.spin_plot_thresh.setToolTip("Maximum points drawn 1:1 before peak-downsampling activates.")
        self.spin_plot_thresh.valueChanged.connect(self.refresh_plot_data)
        row_thresh.addWidget(self.spin_plot_thresh)
        self.view_layout.addLayout(row_thresh)
        
        self.sidebar_layout.addWidget(self.grp_view)
        
        # Slicer Controls (Thresholds).
        self.grp_slicer = QGroupBox("Slicer (Thresholds)")
        self.slicer_layout = QVBoxLayout()
        self.grp_slicer.setLayout(self.slicer_layout)
        
        self.chk_slicer = QCheckBox("Enable Overlay")
        self.chk_slicer.stateChanged.connect(self.toggle_slicer)
        self.slicer_layout.addWidget(self.chk_slicer)
        
        self.slicer_layout.addWidget(QLabel("Symbol Levels:"))
        self.cb_levels = QComboBox()
        self.cb_levels.addItems(["2 Levels (Binary)", "4 Levels (2-bit)", "8 Levels (3-bit)"])
        self.cb_levels.currentTextChanged.connect(self.setup_thresholds)
        self.slicer_layout.addWidget(self.cb_levels)
        
        self.slicer_layout.addWidget(QLabel("Trace Color:"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(['Orange', 'Lime', 'Cyan', 'Magenta', 'Yellow', 'White/Black', 'Blue'])
        self.cb_color.currentTextChanged.connect(self.update_digital_color)
        self.slicer_layout.addWidget(self.cb_color)
        
        self.lbl_opacity = QLabel("Overlay Opacity: 100%")
        self.slicer_layout.addWidget(self.lbl_opacity)
        
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_opacity.setTickInterval(25)
        self.slider_opacity.valueChanged.connect(self.update_opacity)
        self.slicer_layout.addWidget(self.slider_opacity)

        self.lbl_thresh_info = QLabel("Values: None")
        self.lbl_thresh_info.setStyleSheet("font-size: 9pt; color: #666;")
        self.lbl_thresh_info.setWordWrap(True)
        self.slicer_layout.addWidget(self.lbl_thresh_info)
        
        self.sidebar_layout.addWidget(self.grp_slicer)
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

        # Initial state setup.
        self.update_digital_color('Orange')
        self.update_opacity(100)

    def load_input(self):
        # Pull filtered data from context.
        if self.context.filtered_signal is None:
            return False, "No filtered signal in Context (Tab 2)."
            
        # Create a local copy to ensure safety.
        self.local_filtered_data = np.copy(self.context.filtered_signal)
        self.local_filtered_sr = self.context.filtered_sr
        
        # Reset Demod and Filter state on new load.
        self.raw_demod_result = None
        self.filtered_demod_result = None
        self.demod_result = None
        self.chk_filter_box.setChecked(False)
        self.chk_norm_box.setChecked(False)
        self._set_norm_state(False, 0)
        
        self.plot_main.setTitle("Data Loaded. Select Mode and click RUN.")
        self.btn_run.setEnabled(True)
        
        return True, f"Loaded {len(self.local_filtered_data)} samples."

    def stage_output(self):
        # Push demodulated data to context.
        if self.demod_result is None:
            return False, "No demodulated data. Click 'RUN DEMOD' first."
            
        self.context.demod_mode = self.cb_mode.currentText()
        self.context.demod_sr = self.local_filtered_sr
        
        # If we are doing DPSK and slicer is active, threshold the entire array for the next tab.
        if "Phase" in self.context.demod_mode and self.chk_slicer.isChecked() and self.thresh_lines:
            thresh = self.thresh_lines[0].value()
            edges = np.diff((self.demod_result > thresh).astype(int)) > 0
            edges = np.insert(edges, 0, False)

            full_state = (np.cumsum(edges) % 2) * 2 - 1 
            self.context.demod_signal = full_state
            
        else:
            self.context.demod_signal = self.demod_result
        
        # Save threshold settings if slicer was active.
        if self.chk_slicer.isChecked() and self.thresh_lines:
            if "Phase" in self.context.demod_mode:
                # overide to 0
                self.context.thresholds = [0.0]
            else:
                vals = sorted([line.value() for line in self.thresh_lines])
                self.context.thresholds = vals
        
        # Save color preference.
        self.context.viz_trace_color = self.get_adaptive_color(self.digital_color_name)
        
        return True, f"Staged {len(self.context.demod_signal)} samples."

    def run_demod(self):
        if self.local_filtered_data is None: return
        
        mode = self.cb_mode.currentText()
        sr = self.local_filtered_sr
        
        # Use DSP library.
        if "Amplitude" in mode:
            self.raw_demod_result = dsp.demodulate_am(self.local_filtered_data)
            self.plot_main.setLabel('left', 'Magnitude')
        elif "Frequency" in mode:
            self.raw_demod_result = dsp.demodulate_fm(self.local_filtered_data, sr)
            self.plot_main.setLabel('left', 'Frequency', units='Hz')
        elif "Phase" in mode:
            # Look up filter length from context
            k_base = getattr(self.context, 'filter_length', 1) 
            k = int(k_base * 1.05)
            self.raw_demod_result = dsp.demodulate_dpsk(self.local_filtered_data, k)
            self.plot_main.setLabel('left', 'Phase Mag', units='rad')
            
        # Default active array is the raw array.
        self.filtered_demod_result = self.raw_demod_result.copy()
        self.demod_result = self.filtered_demod_result.copy()
        self._set_norm_state(False, 0)

        # Update minimap. Peak decimate for pure speed on the mini overview.
        self._update_minimap()

        # Reset navigation region.
        duration = len(self.demod_result) / sr
        self.plot_mini.setXRange(0, duration) 
        start_t, end_t = 0, duration * 0.15
        
        self.region.blockSignals(True)
        self.region.setRegion([start_t, end_t])
        self.region.blockSignals(False)
        
        # Calling setXRange triggers on_range_changed, which starts the timer
        self.plot_main.setXRange(start_t, end_t, padding=0)
        
        self.autoscale_view()
        
        # Reset filter and norm region sizes to a sensible default.
        box_width = max(0.0001, (end_t - start_t) * 0.05)
        self.filter_region.setRegion([start_t + box_width, start_t + (box_width * 2)])
        self.update_filter_label()
        self.norm_region.setRegion([start_t + box_width, start_t + (box_width * 2)])
        self.update_norm_label()
        
        # Re-apply slicer if enabled.
        if self.chk_slicer.isChecked():
            self.setup_thresholds()
            
        self.refresh_plot_data()

    def on_range_changed(self, _, viewRange):
        # Visually sync the minimap box immediately
        self.region.blockSignals(True)
        self.region.setRegion(viewRange[0])
        self.region.blockSignals(False)
        
        # Restart the timer. If user is actively scrolling, this keeps resetting
        self.update_timer.start(DEBOUNCE_MS)

    def refresh_plot_data(self):
        # Automatically adjust Y-Axis if enabled before drawing points
        if getattr(self, 'chk_auto_autoscale', None) and self.chk_auto_autoscale.isChecked():
            self.autoscale_view()
            
        self.update_main_plot()
        
        if self.chk_slicer.isChecked():
            self.update_digital_overlay()

    def update_main_plot(self):
        if self.demod_result is None: return
        
        sr = self.local_filtered_sr
        total_points = len(self.demod_result)
        
        # Get the strict visible time window
        view_range = self.plot_main.viewRange()[0]
        min_t, max_t = view_range[0], view_range[1]
        
        # Add a buffer on either side so panning isn't instantly jarring
        pad_t = (max_t - min_t) * VIEW_BUFFER_RATIO
        min_t = max(0, min_t - pad_t)
        max_t = min(total_points / sr, max_t + pad_t)
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(total_points, int(max_t * sr))
        
        if i_stop <= i_start: return
        
        # Only extract the exact segment we need
        view_y = self.demod_result[i_start:i_stop]
        
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
            
        self.curve_main.setData(view_x, view_y)

    def update_digital_overlay(self):
        if self.demod_result is None or not self.chk_slicer.isChecked(): return
        if not self.thresh_lines: return
        
        thresh_vals = sorted([line.value() for line in self.thresh_lines])
        
        txt = " | ".join([f"{v:.4f}" for v in thresh_vals])
        self.lbl_thresh_info.setText(f"Thresholds: {txt}")
        
        sr = self.local_filtered_sr
        total_points = len(self.demod_result)
        
        view_range = self.plot_main.viewRange()[0]
        min_t, max_t = view_range[0], view_range[1]
        
        pad_t = (max_t - min_t) * VIEW_BUFFER_RATIO
        min_t = max(0, min_t - pad_t)
        max_t = min(total_points / sr, max_t + pad_t)
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(total_points, int(max_t * sr))
        
        if i_stop <= i_start: return
        
        view_y = self.demod_result[i_start:i_stop]
        
        if "Phase" in self.cb_mode.currentText():
            thresh = thresh_vals[0] if thresh_vals else 0.5
            
            # Find rising edges ONLY
            edges = np.diff((view_y > thresh).astype(int)) > 0
            edges = np.insert(edges, 0, False)
            
            # Track state, mod 2, map 0 == -1 and 1 == 1
            state = (np.cumsum(edges) % 2) * 2 - 1
            
            # Scale it to look nice overlaid on the analog spikes
            y_max = np.max(view_y) if len(view_y) > 0 else 1.0
            mapped_y = state * (y_max * 0.4) + (y_max * 0.5)
        else:
            # Digitize only the visible data for normal AM/FM
            view_symbols = np.digitize(view_y, thresh_vals)
            
            mapped_y = np.zeros_like(view_y)
            unique_syms = np.unique(view_symbols)
            
            # Map symbols back to analog levels for the overlay trace.
            for s in unique_syms:
                mask = (view_symbols == s)
                if np.any(mask):
                    val = np.median(view_y[mask])
                    mapped_y[mask] = val

        thresh_pts = self.spin_plot_thresh.value()
        step = max(1, len(view_y) // thresh_pts) if len(view_y) > thresh_pts else 1
        if step > 1:
            mapped_y = mapped_y[::step]
        view_x = np.arange(i_start, i_stop, step, dtype=np.float64) / sr

        self.curve_digital.setData(view_x, mapped_y)

    def _update_minimap(self):
        if self.demod_result is None or len(self.demod_result) == 0:
            self.curve_mini.setData([], [])
            return
        sr = self.local_filtered_sr
        mini_step = max(1, len(self.demod_result) // 5000)
        mini_y = self.demod_result[::mini_step]
        mini_x = np.arange(len(mini_y)) * (mini_step / sr)
        self.curve_mini.setData(mini_x, mini_y)

    def _toggle_window_box(self, region, checked, update_label_fn):
        if checked:
            view_range = self.plot_main.viewRange()[0]
            min_x, max_x = view_range[0], view_range[1]
            view_width = max_x - min_x

            box_width = view_width * 0.20
            center_x = min_x + (view_width / 2.0)
            region.setRegion([center_x - (box_width / 2.0), center_x + (box_width / 2.0)])

            region.show()
            update_label_fn()
        else:
            region.hide()

    def _update_window_label(self, region, label):
        if not region.isVisible():
            return
        min_x, max_x = region.getRegion()
        length_samples = int(abs(max_x - min_x) * self.local_filtered_sr)
        label.setText(f"Length: {length_samples} samples")

    def toggle_filter_box(self, checked):
        self._toggle_window_box(self.filter_region, checked, self.update_filter_label)

    def update_filter_label(self):
        self._update_window_label(self.filter_region, self.lbl_filter_len)

    def apply_filter(self):
        if self.raw_demod_result is None:
            return

        min_x, max_x = self.filter_region.getRegion()
        length_samples = int(abs(max_x - min_x) * self.local_filtered_sr)

        # If the box is too small (or user wants to quickly revert).
        if length_samples < 2:
            self.filtered_demod_result = self.raw_demod_result.copy()
        else:
            f_type = self.cb_filter.currentText()
            # Apply filter strictly to the RAW data to avoid compound filtering.
            self.filtered_demod_result = dsp.apply_matched_filter(self.raw_demod_result, f_type, length_samples)

        if self.norm_applied and self.norm_window_len >= 2:
            self.demod_result = dsp.apply_sliding_normalization(
                self.filtered_demod_result, self.norm_window_len
            )
        else:
            self.demod_result = self.filtered_demod_result.copy()

        self._update_minimap()
        self.refresh_plot_data()

    def toggle_advanced_section(self, checked):
        self.advanced_container.setVisible(checked)
        self._update_advanced_button_text()

    def _update_advanced_button_text(self):
        if self.btn_advanced.isChecked():
            self.btn_advanced.setText("Advanced \u25BE")
        elif self.norm_applied:
            self.btn_advanced.setText("Advanced \u25B8 (Normalized)")
        else:
            self.btn_advanced.setText("Advanced \u25B8")

    def _set_norm_state(self, applied, window_len=0):
        self.norm_applied = bool(applied)
        self.norm_window_len = int(window_len) if applied else 0
        self.btn_reset_norm.setEnabled(self.norm_applied)
        if self.norm_applied:
            self.lbl_norm_status.setText(f"Active (W: {self.norm_window_len:,})")
            self.lbl_norm_status.setVisible(True)
        else:
            self.lbl_norm_status.setText("")
            self.lbl_norm_status.setVisible(False)
        self._update_advanced_button_text()

    def _refresh_after_norm_change(self):
        self._update_minimap()
        self.autoscale_view()
        if self.chk_slicer.isChecked():
            self.setup_thresholds()
        self.refresh_plot_data()

    def toggle_norm_box(self, checked):
        self._toggle_window_box(self.norm_region, checked, self.update_norm_label)

    def update_norm_label(self):
        self._update_window_label(self.norm_region, self.lbl_norm_len)

    def apply_normalization(self):
        if self.filtered_demod_result is None:
            return

        min_x, max_x = self.norm_region.getRegion()
        length_samples = int(abs(max_x - min_x) * self.local_filtered_sr)
        if length_samples < 2:
            self.reset_normalization()
            return

        self.demod_result = dsp.apply_sliding_normalization(
            self.filtered_demod_result, length_samples
        )
        self._set_norm_state(True, length_samples)
        self._refresh_after_norm_change()

    def reset_normalization(self):
        if self.filtered_demod_result is None:
            return

        self.demod_result = self.filtered_demod_result.copy()
        self._set_norm_state(False, 0)
        self._refresh_after_norm_change()

    def get_adaptive_color(self, name):
        # Returns hex color tuple (dark_mode_hex, light_mode_hex).
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
        self.update_opacity(self.slider_opacity.value())

    def update_opacity(self, value):
        self.lbl_opacity.setText(f"Overlay Opacity: {value}%")
        hex_color = self.get_adaptive_color(self.digital_color_name)
        c = pg.mkColor(hex_color)
        alpha = int((value / 100.0) * 255)
        c.setAlpha(alpha)
        self.pen_digital = pg.mkPen(c, width=DIGITAL_PEN_WIDTH)
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
            self.curve_main.setPen(pg.mkPen('#006400', width=ANALOG_PEN_WIDTH))
            self.filter_region.setBrush(pg.mkBrush(0, 0, 0, 50))
            self.norm_region.setBrush(pg.mkBrush(0, 131, 143, 45))
            for line in self.norm_region.lines:
                line.setPen(pg.mkPen('#00838F', width=2))
        else:
            self.plot_main.setBackground('#1e1e1e')
            self.plot_main.getAxis('left').setPen('w')
            self.plot_main.getAxis('bottom').setPen('w')
            self.plot_main.getAxis('left').setTextPen('w')
            self.plot_main.getAxis('bottom').setTextPen('w')
            self.apply_opaque_grid('#383838')
            self.curve_main.setPen(pg.mkPen('g', width=ANALOG_PEN_WIDTH))
            self.filter_region.setBrush(pg.mkBrush(255, 255, 255, 50))
            self.norm_region.setBrush(pg.mkBrush(0, 200, 255, 45))
            for line in self.norm_region.lines:
                line.setPen(pg.mkPen('#00E5FF', width=2))
        
        self.update_digital_color(self.digital_color_name)

    def toggle_slicer(self):
        enabled = self.chk_slicer.isChecked()
        if enabled:
            self.setup_thresholds()
            self.curve_digital.setVisible(True)
            self.update_digital_overlay()
            self.slider_opacity.setEnabled(True)
            self.cb_color.setEnabled(True)
        else:
            for line in self.thresh_lines:
                self.plot_main.removeItem(line)
            self.thresh_lines.clear()
            self.curve_digital.setVisible(False)
            self.curve_digital.setData([], [])
            self.slider_opacity.setEnabled(False)
            self.cb_color.setEnabled(False)

    def setup_thresholds(self):
        if not self.chk_slicer.isChecked(): return
        
        for line in self.thresh_lines:
            self.plot_main.removeItem(line)
        self.thresh_lines.clear()
        
        lvl_text = self.cb_levels.currentText()
        if lvl_text.startswith("2"): num_lines = 1
        elif lvl_text.startswith("4"): num_lines = 3
        elif lvl_text.startswith("8"): num_lines = 7
        else: num_lines = 1

        # Determine Y-axis range for placing lines.
        view_range = self.plot_main.viewRange()[1] 
        y_min, y_max = view_range[0], view_range[1]
        
        if abs(y_max - y_min) < 1e-6:
             if self.demod_result is not None:
                 y_min = float(np.percentile(self.demod_result, 1))
                 y_max = float(np.percentile(self.demod_result, 99))
             else: y_min, y_max = -1, 1
        span = y_max - y_min
        
        l_color = '#000000' if self.chk_light_mode.isChecked() else '#FFD700'
        line_pen = pg.mkPen(l_color, width=3, style=Qt.PenStyle.DashLine) 

        for i in range(num_lines):
            step = span / (num_lines + 1)
            pos = y_min + (step * (i + 1))
            line = pg.InfiniteLine(pos=pos, angle=0, movable=True, pen=line_pen)
            line.sigPositionChanged.connect(self.limit_line_movement)
            line.sigPositionChanged.connect(self.update_digital_overlay)
            self.plot_main.addItem(line)
            self.thresh_lines.append(line)
        
        self.update_digital_overlay()

    def limit_line_movement(self, moved_line):
        # Prevents lines from crossing each other.
        if moved_line not in self.thresh_lines: return
        idx = self.thresh_lines.index(moved_line)
        val = moved_line.value()
        margin = 0.0001 
        
        if idx > 0:
            lower_neighbor = self.thresh_lines[idx - 1]
            if val <= lower_neighbor.value() + margin:
                moved_line.setValue(lower_neighbor.value() + margin)
        if idx < len(self.thresh_lines) - 1:
            upper_neighbor = self.thresh_lines[idx + 1]
            if val >= upper_neighbor.value() - margin:
                moved_line.setValue(upper_neighbor.value() - margin)

    def autoscale_view(self):
        if self.demod_result is None: return
        
        min_t, max_t = self.region.getRegion()
        sr = self.local_filtered_sr
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(len(self.demod_result), int(max_t * sr))
        
        if i_stop <= i_start: return
        
        view_y = self.demod_result[i_start:i_stop]
        if len(view_y) == 0: return
        
        y_min = float(np.min(view_y))
        y_max = float(np.max(view_y))
        
        if abs(y_max - y_min) < 1e-9: margin = 1.0 
        else: margin = (y_max - y_min) * 0.20
        
        self.plot_main.setYRange(y_min - margin, y_max + margin)

    def update_zoom_from_region(self):
        min_x, max_x = self.region.getRegion()
        self.plot_main.setXRange(min_x, max_x, padding=0)

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
