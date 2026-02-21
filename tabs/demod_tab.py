import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QPushButton, QGroupBox, QCheckBox, QSlider)
from PyQt5.QtCore import Qt

# Import the base class.
from core.base_tab import BaseSignalTab
# Import dsp utilities.
import utils.dsp_lib as dsp

class DemodTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Demodulator")
        
        # Local state.
        self.local_filtered_data = None
        self.local_filtered_sr = 1.0
        
        self.raw_demod_result = None
        self.demod_result = None
        
        self.thresh_lines = []
        self.digital_color_name = 'Orange'
        
        self.init_ui()

    def init_ui(self):
        # Main layout is horizontal (Plot | Controls).
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # LEFT: Visualization
        self.viz_layout = QVBoxLayout()
        
        # Main plot setup.
        self.plot_main = pg.PlotWidget()
        self.plot_main.setLabel('bottom', 'Time', units='s')
        self.plot_main.showGrid(x=True, y=True, alpha=0.3)
        self.plot_main.setDownsampling(auto=False)
        self.plot_main.setClipToView(False)
        self.plot_main.setMouseEnabled(x=True, y=False)
        self.plot_main.setBackground('#1e1e1e')
        
        # Analog trace.
        self.curve_main = self.plot_main.plot(pen=pg.mkPen('g', width=3))
        
        # Digital overlay trace.
        self.pen_digital = pg.mkPen('#FFA500', width=4)
        self.curve_digital = self.plot_main.plot(pen=self.pen_digital)
        self.curve_digital.setVisible(False)

        # Filter box.
        self.filter_region = pg.LinearRegionItem(brush=pg.mkBrush(255, 255, 255, 50))
        self.filter_region.setZValue(10)
        self.filter_region.hide()
        self.filter_region.sigRegionChanged.connect(self.update_filter_label)
        self.plot_main.addItem(self.filter_region)
        
        self.viz_layout.addWidget(self.plot_main)
        
        # Mini map.
        self.plot_mini = pg.PlotWidget()
        self.plot_mini.setFixedHeight(80)
        self.plot_mini.hideAxis('bottom')
        self.plot_mini.hideAxis('left')
        self.plot_mini.setBackground('#1e1e1e')
        self.curve_mini = self.plot_mini.plot(pen=pg.mkPen('w', width=1))
        
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        self.plot_mini.addItem(self.region)
        self.region.sigRegionChanged.connect(self.update_zoom_from_region)
        self.plot_main.sigRangeChanged.connect(self.update_region_from_zoom)
        
        self.viz_layout.addWidget(self.plot_mini)
        main_h_layout.addLayout(self.viz_layout, stretch=1)

        # RIGHT: Sidebar Controls
        self.sidebar = QGroupBox("Demodulation")
        self.sidebar.setFixedWidth(280)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        self.btn_run = QPushButton("RUN DEMOD")
        self.btn_run.setMinimumHeight(40)
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #e1f5fe;")
        self.btn_run.clicked.connect(self.run_demod)
        self.sidebar_layout.addWidget(self.btn_run)
        self.sidebar_layout.addSpacing(20)
        
        self.sidebar_layout.addWidget(QLabel("Mode:"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["Amplitude (ASK/OOK)", "Frequency (FSK)"])
        self.sidebar_layout.addWidget(self.cb_mode)
        self.sidebar_layout.addSpacing(10)
        
        self.btn_autoscale = QPushButton("Auto Scale Y-Axis")
        self.btn_autoscale.clicked.connect(self.autoscale_view)
        self.sidebar_layout.addWidget(self.btn_autoscale)
        self.sidebar_layout.addSpacing(20)

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
        self.sidebar_layout.addSpacing(10)

        # View Settings.
        self.grp_view = QGroupBox("View Settings")
        self.view_layout = QVBoxLayout()
        self.grp_view.setLayout(self.view_layout)
        
        self.chk_light_mode = QCheckBox("Light Mode")
        self.chk_light_mode.stateChanged.connect(self.toggle_light_mode)
        self.view_layout.addWidget(self.chk_light_mode)
        self.sidebar_layout.addWidget(self.grp_view)
        self.sidebar_layout.addSpacing(10)
        
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
        
        self.slicer_layout.addSpacing(10)
        self.slicer_layout.addWidget(QLabel("Trace Color:"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(['Orange', 'Lime', 'Cyan', 'Magenta', 'Yellow', 'White/Black', 'Blue'])
        self.cb_color.currentTextChanged.connect(self.update_digital_color)
        self.slicer_layout.addWidget(self.cb_color)
        
        self.slicer_layout.addSpacing(10)
        self.lbl_opacity = QLabel("Overlay Opacity: 100%")
        self.slicer_layout.addWidget(self.lbl_opacity)
        
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.setTickPosition(QSlider.TicksBelow)
        self.slider_opacity.setTickInterval(25)
        self.slider_opacity.valueChanged.connect(self.update_opacity)
        self.slicer_layout.addWidget(self.slider_opacity)

        self.slicer_layout.addSpacing(10)
        self.lbl_thresh_info = QLabel("Values: None")
        self.lbl_thresh_info.setStyleSheet("font-size: 10px; color: #666;")
        self.lbl_thresh_info.setWordWrap(True)
        self.slicer_layout.addWidget(self.lbl_thresh_info)
        
        self.sidebar_layout.addWidget(self.grp_slicer)
        self.sidebar_layout.addStretch()
        
        main_h_layout.addWidget(self.sidebar, stretch=0)

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
        self.demod_result = None
        self.chk_filter_box.setChecked(False)
        
        self.plot_main.setTitle("Data Loaded. Select Mode and click RUN.")
        self.btn_run.setEnabled(True)
        
        return True, f"Loaded {len(self.local_filtered_data)} samples."

    def stage_output(self):
        # Push demodulated data to context.
        if self.demod_result is None:
            return False, "No demodulated data. Click 'RUN DEMOD' first."
            
        self.context.demod_signal = self.demod_result
        self.context.demod_sr = self.local_filtered_sr
        self.context.demod_mode = self.cb_mode.currentText()
        
        # Save threshold settings if slicer was active.
        if self.chk_slicer.isChecked() and self.thresh_lines:
            vals = sorted([line.value() for line in self.thresh_lines])
            self.context.thresholds = vals
        
        # Save color preference.
        self.context.viz_trace_color = self.get_adaptive_color(self.digital_color_name)
        
        return True, f"Staged {len(self.demod_result)} samples."

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
            
        # Default active array is the raw array.
        self.demod_result = self.raw_demod_result.copy()
            
        self.update_main_plot()
        
        # Update minimap.
        # Decimate for speed.
        mini_step = max(1, len(self.demod_result) // 5000)
        mini_y = self.demod_result[::mini_step]
        mini_x = np.arange(len(mini_y)) * (mini_step / sr)
        self.curve_mini.setData(mini_x, mini_y)
        
        # Reset navigation region.
        duration = len(self.demod_result) / sr
        self.plot_mini.setXRange(0, duration) 
        start_t, end_t = 0, duration * 0.25 
        
        self.region.blockSignals(True)
        self.region.setRegion([start_t, end_t])
        self.region.blockSignals(False)
        self.plot_main.setXRange(start_t, end_t, padding=0)
        
        self.autoscale_view()
        
        # Reset filter region size to a sensible default.
        box_width = max(0.0001, (end_t - start_t) * 0.05)
        self.filter_region.setRegion([start_t + box_width, start_t + (box_width * 2)])
        self.update_filter_label()
        
        # Re-apply slicer if enabled.
        if self.chk_slicer.isChecked():
            self.setup_thresholds()
            self.update_digital_overlay()

    def update_main_plot(self):
        if self.demod_result is None: return
        
        sr = self.local_filtered_sr
        total_points = len(self.demod_result)
        
        # Downsample for display.
        # Note: magic number, need to remove at some point.
        MAX_POINTS = 10000
        if total_points > MAX_POINTS:
            step = total_points // MAX_POINTS
            y = self.demod_result[::step]
            x = np.arange(len(y)) * (step / sr)
        else:
            y = self.demod_result
            x = np.arange(total_points) / sr
            
        self.curve_main.setData(x, y)

    def toggle_filter_box(self, checked):
        if checked:
            self.filter_region.show()
            self.update_filter_label()
        else:
            self.filter_region.hide()

    def update_filter_label(self):
        if not self.filter_region.isVisible():
            return
        min_x, max_x = self.filter_region.getRegion()
        # Time width in seconds * sample rate = length in samples
        length_samples = int(abs(max_x - min_x) * self.local_filtered_sr)
        self.lbl_filter_len.setText(f"Length: {length_samples} samples")

    def apply_filter(self):
        if self.raw_demod_result is None:
            return
            
        min_x, max_x = self.filter_region.getRegion()
        length_samples = int(abs(max_x - min_x) * self.local_filtered_sr)
        
        # If the box is too small (or user wants to quickly revert).
        if length_samples < 2:
            self.demod_result = self.raw_demod_result.copy()
        else:
            f_type = self.cb_filter.currentText()
            # Apply filter strictly to the RAW data to avoid compound filtering.
            self.demod_result = dsp.apply_matched_filter(self.raw_demod_result, f_type, length_samples)
            
        self.update_main_plot()
        
        # Auto-update slicer overlay to reflect the smoothed data
        if self.chk_slicer.isChecked():
            self.update_digital_overlay()

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
        self.pen_digital = pg.mkPen(c, width=4)
        self.curve_digital.setPen(self.pen_digital)

    def toggle_light_mode(self):
        if self.chk_light_mode.isChecked():
            self.plot_main.setBackground('w')
            self.plot_main.getAxis('left').setPen('k')
            self.plot_main.getAxis('bottom').setPen('k')
            self.plot_main.getAxis('left').setTextPen('k')
            self.plot_main.getAxis('bottom').setTextPen('k')
            self.curve_main.setPen(pg.mkPen('#006400', width=2))
            self.filter_region.setBrush(pg.mkBrush(0, 0, 0, 50))
        else:
            self.plot_main.setBackground('#1e1e1e')
            self.plot_main.getAxis('left').setPen('w')
            self.plot_main.getAxis('bottom').setPen('w')
            self.plot_main.getAxis('left').setTextPen('w')
            self.plot_main.getAxis('bottom').setTextPen('w')
            self.curve_main.setPen(pg.mkPen('g', width=3))
            self.filter_region.setBrush(pg.mkBrush(255, 255, 255, 50))
        
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
                 y_min = np.percentile(self.demod_result, 1)
                 y_max = np.percentile(self.demod_result, 99)
             else: y_min, y_max = -1, 1
        span = y_max - y_min
        
        l_color = '#000000' if self.chk_light_mode.isChecked() else '#FFD700'
        line_pen = pg.mkPen(l_color, width=3, style=Qt.DashLine) 

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

    def update_digital_overlay(self):
        if self.demod_result is None or not self.chk_slicer.isChecked(): return
        if not self.thresh_lines: return
        
        thresh_vals = sorted([line.value() for line in self.thresh_lines])
        
        # Digitize (slice) the data locally for preview.
        full_symbols = np.digitize(self.demod_result, thresh_vals)
        
        txt = " | ".join([f"{v:.4f}" for v in thresh_vals])
        self.lbl_thresh_info.setText(f"Thresholds: {txt}")
        
        # Prepare visualization data.
        sr = self.local_filtered_sr
        MAX_POINTS = 10000
        total_points = len(self.demod_result)
        
        if total_points > MAX_POINTS:
            step = total_points // MAX_POINTS
            view_data = self.demod_result[::step]
            view_symbols = full_symbols[::step]
            x_axis = np.arange(len(view_data)) * (step / sr)
        else:
            view_data = self.demod_result
            view_symbols = full_symbols
            x_axis = np.arange(total_points) / sr
            
        mapped_y = np.zeros_like(view_data)
        unique_syms = np.unique(view_symbols)
        
        # Map symbols back to analog levels for the overlay trace.
        for s in unique_syms:
            mask = (view_symbols == s)
            if np.any(mask):
                val = np.median(view_data[mask])
                mapped_y[mask] = val
                
        self.curve_digital.setData(x_axis, mapped_y)

    def autoscale_view(self):
        if self.demod_result is None: return
        x_data, y_data = self.curve_main.getData()
        if x_data is None: return
        
        min_t, max_t = self.region.getRegion()
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

    def update_zoom_from_region(self):
        min_x, max_x = self.region.getRegion()
        self.plot_main.setXRange(min_x, max_x, padding=0)

    def update_region_from_zoom(self, _, viewRange):
        self.region.blockSignals(True)
        self.region.setRegion(viewRange[0])
        self.region.blockSignals(False)
