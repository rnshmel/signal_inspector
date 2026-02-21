import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QPushButton, QWidget, QSplitter, QCheckBox,
                             QGroupBox, QRadioButton, QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt

# Import the base class.
from core.base_tab import BaseSignalTab
# Import dsp utilities.
import utils.dsp_lib as dsp

class TunerTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Tune and Filter")
        
        # Local state to store the result before staging.
        self.local_filtered_data = None
        self.local_filtered_sr = 1.0
        self.local_center_freq = 0.0
        self.last_freq_bounds = None
        
        # Viz settings (will be overwritten by load_input).
        self.viz_fft_size = 1024
        self.viz_overlap = 0
        
        self.init_ui()

    def init_ui(self):
        # Main layout: Horizontal (Plots | Sidebar)
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # Visualization (Splitter)
        self.viz_layout = QVBoxLayout()
        self.splitter = QSplitter(Qt.Vertical)
        self.viz_layout.addWidget(self.splitter)
        main_h_layout.addLayout(self.viz_layout, stretch=1)

        # Top Plot (Input)
        self.top_widget = QWidget()
        self.top_layout = QVBoxLayout(self.top_widget)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_info = QLabel("1. Tune Selection")
        self.lbl_info.setStyleSheet("font-weight: bold; color: #444;")
        self.top_layout.addWidget(self.lbl_info)

        self.plot_input = pg.PlotWidget()
        self.plot_input.setLabel('left', 'Frequency', units='Hz')
        self.plot_input.setLabel('bottom', 'Time', units='s')
        self.img_input = pg.ImageItem()
        self.plot_input.addItem(self.img_input)
        self.top_layout.addWidget(self.plot_input)

        # Interactive items
        self.region_time = pg.LinearRegionItem(orientation='vertical')
        self.region_time.setZValue(10)
        self.plot_input.addItem(self.region_time)
        
        self.freq_center_line = pg.InfiniteLine(angle=0, movable=True)
        self.freq_center_line.setZValue(11) 
        self.plot_input.addItem(self.freq_center_line)
        
        self.region_freq = pg.LinearRegionItem(orientation='horizontal')
        self.region_freq.setZValue(10)
        self.plot_input.addItem(self.region_freq)
        
        self.freq_center_line.sigPositionChanged.connect(self.on_center_line_drag)
        self.region_freq.sigRegionChanged.connect(self.on_region_drag)
        
        self.splitter.addWidget(self.top_widget)

        # Bottom Plot (Result)
        self.bottom_widget = QWidget()
        self.bottom_layout = QVBoxLayout(self.bottom_widget)
        self.bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_result = QLabel("2. Filtered Result (Shifted to DC)")
        self.lbl_result.setStyleSheet("font-weight: bold; color: #444;")
        self.bottom_layout.addWidget(self.lbl_result)
        
        self.plot_result = pg.PlotWidget()
        self.plot_result.setLabel('left', 'Frequency', units='Hz')
        self.plot_result.setLabel('bottom', 'Time', units='s')
        self.img_result = pg.ImageItem()
        self.plot_result.addItem(self.img_result)
        self.bottom_layout.addWidget(self.plot_result)
        
        self.splitter.addWidget(self.bottom_widget)
        self.splitter.setSizes([600, 400])

        # RIGHT: Sidebar Controls
        self.sidebar = QGroupBox("Tuner Controls")
        self.sidebar.setFixedWidth(280)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # Processing Controls
        self.btn_apply = QPushButton("Apply Filter & Mix (⬇)")
        self.btn_apply.setMinimumHeight(40)
        self.btn_apply.setStyleSheet("font-weight: bold; background-color: #e1f5fe;")
        self.btn_apply.clicked.connect(self.run_filter)
        self.sidebar_layout.addWidget(self.btn_apply)
        self.sidebar_layout.addSpacing(15)
        
        self.sidebar_layout.addWidget(QLabel("Selection Color:"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(['Green', 'Red', 'Cyan', 'Yellow', 'White'])
        self.cb_color.currentTextChanged.connect(self.update_colors)
        self.sidebar_layout.addWidget(self.cb_color)
        
        self.chk_show_time = QCheckBox("Show Time Region")
        self.chk_show_time.setChecked(True)
        self.chk_show_time.stateChanged.connect(self.toggle_visibility)
        self.sidebar_layout.addWidget(self.chk_show_time)
        
        self.chk_show_freq = QCheckBox("Show Freq Region")
        self.chk_show_freq.setChecked(True)
        self.chk_show_freq.stateChanged.connect(self.toggle_visibility)
        self.sidebar_layout.addWidget(self.chk_show_freq)
        
        self.sidebar_layout.addSpacing(20)

        # Export Controls
        self.grp_export = QGroupBox("File Export")
        self.layout_export = QVBoxLayout()
        self.grp_export.setLayout(self.layout_export)
        
        self.rb_raw = QRadioButton("Raw Slice (X-Axis only)")
        self.rb_raw.setToolTip("Saves the raw IQ data from the selected time region without filtering.")
        self.rb_processed = QRadioButton("Filtered (X + Y Axis)")
        self.rb_processed.setToolTip("Saves the result of the mixing and filtering operation.")
        self.rb_processed.setChecked(True)
        
        self.btn_save = QPushButton("Save Fragment (.cf32)")
        self.btn_save.clicked.connect(self.export_fragment)
        
        self.layout_export.addWidget(self.rb_raw)
        self.layout_export.addWidget(self.rb_processed)
        self.layout_export.addWidget(self.btn_save)
        
        self.sidebar_layout.addWidget(self.grp_export)
        self.sidebar_layout.addStretch()

        main_h_layout.addWidget(self.sidebar, stretch=0)

        self.update_colors('Green')

    def load_input(self):
        # Check if raw data exists in context.
        if self.context.raw_iq_handle is None:
            return False, "No Raw IQ Data found in Context (Tab 1)."

        # Import Visualization Settings from Context.
        self.viz_fft_size = self.context.viz_fft_size
        self.viz_overlap = self.context.viz_overlap
        
        # Apply visual settings to both image items.
        if self.context.viz_lut is not None:
            self.img_input.setLookupTable(self.context.viz_lut)
            self.img_result.setLookupTable(self.context.viz_lut)
            
        self.img_input.setLevels(self.context.viz_levels)
        self.img_result.setLevels(self.context.viz_levels)

        # Get hint from tab 1 selection.
        min_t, max_t = self.context.selection_hint
        duration = max_t - min_t
        
        # Update labels.
        self.lbl_info.setText(f"1. Tune Selection ({min_t:.4f}s - {max_t:.4f}s)")
        
        # Slice the data from the memmap.
        sr = self.context.raw_sr
        i_start = max(0, int(min_t * sr))
        i_stop = min(len(self.context.raw_iq_handle), int(max_t * sr))
        
        if i_stop <= i_start:
            return False, "Invalid time selection."

        data_slice = self.context.raw_iq_handle[i_start:i_stop]
        
        # Compute input spectrogram using dsp lib and Context FFT settings.
        sxx, extent = dsp.compute_spectrogram(data_slice, sr, self.viz_fft_size, self.viz_overlap)
        
        # Update input image.
        self.img_input.setImage(sxx.T, autoLevels=False) # Use explicit levels set above
        self.img_input.setRect(pg.QtCore.QRectF(min_t, extent[2], duration, extent[3]-extent[2]))
        
        # Set default selection regions based on the loaded slice.
        center_t = min_t + (duration / 2)
        width_t = duration * 0.5
        
        self.region_time.blockSignals(True)
        self.region_time.setRegion([center_t - width_t/2, center_t + width_t/2])
        self.region_time.blockSignals(False)
        
        # Set default frequency selection (center).
        f_span = sr
        width_f = f_span * 0.1
        
        self.freq_center_line.blockSignals(True)
        self.region_freq.blockSignals(True)
        self.freq_center_line.setValue(0)
        self.region_freq.setRegion([-width_f/2, width_f/2])
        self.last_freq_bounds = (-width_f/2, width_f/2)
        self.freq_center_line.blockSignals(False)
        self.region_freq.blockSignals(False)
        
        return True, "Raw IQ Slice Loaded"

    def stage_output(self):
        # Check if local processing has happened.
        if self.local_filtered_data is None:
            return False, "No filtered data generated. Click 'Apply' first."
            
        # Commit to context.
        self.context.filtered_signal = self.local_filtered_data
        self.context.filtered_sr = self.local_filtered_sr
        self.context.filter_center_freq = self.local_center_freq
        
        return True, f"Staged {len(self.local_filtered_data)} samples @ {self.local_filtered_sr/1e3:.1f} kHz"

    def run_filter(self):
        # Verify inputs exist.
        if self.context.raw_iq_handle is None: return
        
        # Get UI parameters.
        min_t, max_t = self.region_time.getRegion()
        target_freq = self.freq_center_line.value()
        f_min, f_max = self.region_freq.getRegion()
        bandwidth = f_max - f_min    
        sr = self.context.raw_sr
        i_start = max(0, int(min_t * sr))
        i_stop = min(len(self.context.raw_iq_handle), int(max_t * sr))
        
        # Extract the slice for processing.
        raw_data = self.context.raw_iq_handle[i_start:i_stop]
        if len(raw_data) == 0: return

        # Perform DSP mixing and filtering.
        filtered_data = dsp.mix_and_filter(raw_data, sr, target_freq, bandwidth)
        
        # Store results locally.
        self.local_filtered_data = filtered_data
        self.local_filtered_sr = sr
        self.local_center_freq = target_freq

        # Preview output spectrogram using Cached FFT settings.
        sxx, extent = dsp.compute_spectrogram(filtered_data, sr, self.viz_fft_size, self.viz_overlap)
        self.img_result.setImage(sxx.T, autoLevels=False)
        self.img_result.setRect(pg.QtCore.QRectF(0, extent[2], extent[1], extent[3]-extent[2]))   
        self.lbl_result.setText(f"2. Filtered Result (Shifted {target_freq/1e3:.1f} kHz to DC | BW: {bandwidth/1e3:.1f} kHz)")

    def export_fragment(self):
        if self.context.raw_iq_handle is None: 
            QMessageBox.warning(self, "Export Error", "No source file loaded.")
            return

        # Determine if we are saving Raw or Processed
        is_processed = self.rb_processed.isChecked()
        
        # Determine Data and Sample Rate
        if not is_processed:
            # RAW (X-Axis Only)
            min_t, max_t = self.region_time.getRegion()
            sr = self.context.raw_sr
            i_start = max(0, int(min_t * sr))
            i_stop = min(len(self.context.raw_iq_handle), int(max_t * sr))
            
            if i_stop <= i_start:
                QMessageBox.warning(self, "Export Error", "Invalid time selection.")
                return
                
            # Grab raw slice
            data_to_save = self.context.raw_iq_handle[i_start:i_stop]
            save_sr = sr
            prefix = "fragment"
        else:
            # PROCESSED (Filtered)
            # Ensure filter is up to date
            self.run_filter() 
            if self.local_filtered_data is None:
                QMessageBox.warning(self, "Export Error", "Processing failed or no data selected.")
                return
                
            data_to_save = self.local_filtered_data
            save_sr = self.local_filtered_sr
            prefix = "fragment"

        # Ask for filename
        default_name = f"{prefix}_{int(save_sr)}.cf32"
        fname, _ = QFileDialog.getSaveFileName(self, "Save IQ Fragment", default_name, "Complex Float 32 (*.cf32)")
        
        if fname:
            try:
                # Ensure complex64 (standard .cf32 format)
                data_to_save.astype(np.complex64).tofile(fname)
                QMessageBox.information(self, "Export Successful", f"Saved {len(data_to_save):,} samples to:\n{fname}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def on_center_line_drag(self):
        self.region_freq.blockSignals(True) 
        center = self.freq_center_line.value()
        min_f, max_f = self.region_freq.getRegion()
        width = max_f - min_f
        new_min = center - width/2
        new_max = center + width/2
        self.region_freq.setRegion([new_min, new_max])
        self.last_freq_bounds = (new_min, new_max) 
        self.region_freq.blockSignals(False)

    def on_region_drag(self):
        # Symmetrical resizing logic:
        self.freq_center_line.blockSignals(True)
        self.region_freq.blockSignals(True)

        center = self.freq_center_line.value()
        min_f, max_f = self.region_freq.getRegion()
        
        if self.last_freq_bounds is None: 
            self.last_freq_bounds = (min_f, max_f)
            
        last_min, last_max = self.last_freq_bounds
        
        # Determine which edge moved (top or bottom).
        if abs(max_f - last_max) > abs(min_f - last_min): 
            # Top edge moved.
            new_radius = abs(max_f - center)
        else: 
            # Bottom edge moved (or both moved equal/neither, default to min).
            new_radius = abs(min_f - center)
            
        new_min = center - new_radius
        new_max = center + new_radius
        
        # Apply symmetrical bounds.
        self.region_freq.setRegion([new_min, new_max])
        self.last_freq_bounds = (new_min, new_max)
        
        self.freq_center_line.blockSignals(False)
        self.region_freq.blockSignals(False)

    def update_colors(self, color_name):
        c_map = {'Green':'#00FF00', 'Red':'#FF0000', 'Cyan':'#00FFFF', 'Yellow':'#FFFF00', 'White':'#FFFFFF'}
        c = c_map.get(color_name, '#00FF00')
        brush_color = pg.mkColor(c); brush_color.setAlpha(50) 
        
        for line in self.region_time.lines:
            line.setPen(pg.mkPen(color=c, width=2, style=Qt.DashLine))
            line.setHoverPen(pg.mkPen(color=c, width=4))
        self.region_time.setBrush(brush_color)
        
        for line in self.region_freq.lines:
            line.setPen(pg.mkPen(color=c, width=2, style=Qt.DashLine))
            line.setHoverPen(pg.mkPen(color=c, width=4))
        self.region_freq.setBrush(brush_color)
        
        self.freq_center_line.setPen(pg.mkPen(color=c, width=2))
        self.freq_center_line.setHoverPen(pg.mkPen(color=c, width=4))

    def toggle_visibility(self):
        self.region_time.setVisible(self.chk_show_time.isChecked())
        self.region_freq.setVisible(self.chk_show_freq.isChecked())
        self.freq_center_line.setVisible(self.chk_show_freq.isChecked())
