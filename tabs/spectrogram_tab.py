import os
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QLineEdit, QPushButton, QFileDialog, QGroupBox, 
                             QGridLayout, QCheckBox, QSpinBox)
from PyQt5.QtCore import Qt

# Import the base class from core.
from core.base_tab import BaseSignalTab
# Import dsp utilities.
import utils.dsp_lib as dsp

class SpectrogramTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "File IO and Spectrogram")
        
        self.btn_load.setVisible(False)
        self.lbl_input_status.setVisible(False)

        self.btn_stage.setText("STAGE FILE ➡")
        self.btn_stage.setEnabled(False) 
        
        self.local_iq_handle = None
        self.local_duration = 0
        self.current_file_path = "" 
        
        self.init_ui()

    def init_ui(self):
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # Sidebar controls.
        self.sidebar = QGroupBox("Controls")
        self.sidebar.setFixedWidth(280)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # File Config
        grp_file = QGroupBox("File Configuration")
        layout_file = QGridLayout()
        grp_file.setLayout(layout_file)
        
        self.txt_path = QLineEdit()
        self.txt_path.setReadOnly(True)
        self.txt_path.setPlaceholderText("Select File...")
        
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self.browse_file)
        
        layout_file.addWidget(QLabel("File:"), 0, 0)
        layout_file.addWidget(self.txt_path, 0, 1)
        layout_file.addWidget(btn_browse, 0, 2)
        
        self.txt_sr = QLineEdit("2000000")
        layout_file.addWidget(QLabel("Sample Rate:"), 1, 0)
        layout_file.addWidget(self.txt_sr, 1, 1, 1, 2)

        self.btn_load_local = QPushButton("LOAD DATA")
        self.btn_load_local.clicked.connect(self.load_local_data)
        layout_file.addWidget(self.btn_load_local, 2, 0, 1, 3)

        self.sidebar_layout.addWidget(grp_file)
        self.sidebar_layout.addSpacing(10)

        # Memory Settings
        grp_mem = QGroupBox("Memory / View Control")
        layout_mem = QVBoxLayout()
        grp_mem.setLayout(layout_mem)

        row_ram = QHBoxLayout()
        row_ram.addWidget(QLabel("Max RAM (MB):"))
        self.spin_ram_limit = QSpinBox()
        # 100MB to 2GB (VM safe)
        self.spin_ram_limit.setRange(100, 2000)
        # Default 500MB
        self.spin_ram_limit.setValue(500)
        self.spin_ram_limit.setSingleStep(100)
        self.spin_ram_limit.setToolTip("Limits the amount of data loaded into RAM for the spectrogram.")
        self.spin_ram_limit.valueChanged.connect(self.refresh_spectrogram)
        row_ram.addWidget(self.spin_ram_limit)
        layout_mem.addLayout(row_ram)

        self.chk_sparse = QCheckBox("Enable Mosaic View")
        self.chk_sparse.setToolTip("If view exceeds RAM limit, load sparse chunks (Mosaic) instead of clamping.")
        self.chk_sparse.setChecked(False)
        self.chk_sparse.stateChanged.connect(self.refresh_spectrogram)
        layout_mem.addWidget(self.chk_sparse)

        self.sidebar_layout.addWidget(grp_mem)
        
        self.lbl_file_info = QLabel("No File Loaded")
        self.sidebar_layout.addWidget(self.lbl_file_info)
        self.sidebar_layout.addSpacing(10)

        # Spectrogram Config
        self.sidebar_layout.addWidget(QLabel("FFT Size:"))
        self.cb_fft = QComboBox()
        self.cb_fft.addItems([str(2**i) for i in range(8, 16)])
        self.cb_fft.setCurrentText("1024")
        self.cb_fft.currentTextChanged.connect(self.refresh_spectrogram)
        self.sidebar_layout.addWidget(self.cb_fft)
        
        self.chk_overlap = QCheckBox("High Res (Overlap)")
        self.chk_overlap.stateChanged.connect(self.refresh_spectrogram)
        self.sidebar_layout.addWidget(self.chk_overlap)

        self.sidebar_layout.addWidget(QLabel("Color Map:"))
        self.cb_cmap = QComboBox()
        self.cb_cmap.addItems(['viridis', 'plasma', 'inferno', 'Rainbow', 'White Hot', 'Black Hot'])
        self.cb_cmap.setCurrentText('inferno') 
        self.cb_cmap.currentTextChanged.connect(self.update_colormap)
        self.sidebar_layout.addWidget(self.cb_cmap)

        self.sidebar_layout.addWidget(QLabel("Levels:"))
        self.hist_widget = pg.HistogramLUTWidget()
        self.hist_widget.setMinimumHeight(150)
        self.hist_widget.setLevels(-120, 0)
        self.sidebar_layout.addWidget(self.hist_widget)
        self.sidebar_layout.addStretch()

        # Visualization area.
        self.viz_layout = QVBoxLayout()
        self.plot_spec = pg.PlotWidget()
        self.plot_spec.setLabel('left', 'Frequency', units='Hz')
        self.plot_spec.setLabel('bottom', 'Time', units='s')
        self.img_spec = pg.ImageItem()
        self.plot_spec.addItem(self.img_spec)
        self.hist_widget.setImageItem(self.img_spec)
        
        self.update_colormap('inferno')

        self.plot_mini = pg.PlotWidget()
        self.plot_mini.setFixedHeight(80)
        self.plot_mini.hideAxis('bottom')
        self.curve_mini = self.plot_mini.plot(pen='w')
        
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        for line in self.region.lines:
            line.setPen(pg.mkPen(color='w', width=3))
            line.setHoverPen(pg.mkPen(color='r', width=5))
        self.plot_mini.addItem(self.region)
        self.region.sigRegionChanged.connect(self.update_zoom_from_region)
        self.plot_spec.sigRangeChanged.connect(self.update_region_from_zoom)

        self.viz_layout.addWidget(self.plot_spec)
        self.viz_layout.addWidget(self.plot_mini)

        main_h_layout.addLayout(self.viz_layout, stretch=1)
        main_h_layout.addWidget(self.sidebar, stretch=0)

    def browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open IQ", "", "Complex (*.c32 *.cf32 *.fc32 *.f32 *.raw *.bin *.iq)")
        if fname:
            self.current_file_path = fname
            self.txt_path.setText(os.path.basename(fname))

    def load_local_data(self):
        if not self.current_file_path:
            self.lbl_file_info.setText("Error: No file selected")
            return

        try:
            sr_val = float(self.txt_sr.text())
            self.local_iq_handle = np.memmap(self.current_file_path, dtype=np.complex64, mode='r')
            self.local_duration = len(self.local_iq_handle) / sr_val
            
            self.lbl_file_info.setText(f"{len(self.local_iq_handle):,} Samples\n{self.local_duration:.4f} Sec")
            self.update_minimap()
            self.region.setRegion([0, min(0.25, self.local_duration)])
            self.refresh_spectrogram()
            self.btn_stage.setEnabled(True)
            
        except Exception as e:
            self.lbl_file_info.setText(f"Error: {str(e)}")
            print(e)

    def load_input(self):
        return False, "Not Applicable"

    def stage_output(self):
        if self.local_iq_handle is None:
            return False, "No file loaded"
            
        self.context.raw_iq_handle = self.local_iq_handle
        self.context.raw_sr = float(self.txt_sr.text())
        self.context.file_duration = self.local_duration
        self.context.selection_hint = self.region.getRegion()
        self.context.raw_iq_path = self.current_file_path
        
        fft_size = int(self.cb_fft.currentText())
        self.context.viz_fft_size = fft_size
        self.context.viz_overlap = (fft_size // 2) if self.chk_overlap.isChecked() else 0
        self.context.viz_levels = self.hist_widget.getLevels()
        self.context.viz_lut = self.hist_widget.gradient.getLookupTable(256)
        
        return True, f"Ready for Tuner ({self.context.raw_sr/1e6:.1f} MHz)"

    def update_minimap(self):
        if self.local_iq_handle is None: return
        step = max(1, len(self.local_iq_handle) // 5000)
        data = np.abs(self.local_iq_handle[::step])
        t = np.linspace(0, self.local_duration, len(data))
        self.curve_mini.setData(t, data)
        self.plot_mini.setXRange(0, self.local_duration)
        self.region.setBounds([0, self.local_duration])

    def refresh_spectrogram(self):
        if self.local_iq_handle is None: return
        min_t, max_t = self.region.getRegion()
        sr = float(self.txt_sr.text())
        fft_size = int(self.cb_fft.currentText())
        overlap = fft_size // 2 if self.chk_overlap.isChecked() else 0
        
        i_start = max(0, int(min_t * sr))
        i_stop = min(len(self.local_iq_handle), int(max_t * sr))
        
        if i_stop <= i_start: return
        
        # Calculate Max Samples allowed by RAM Limit
        # Complex64 = 8 bytes.
        max_ram_mb = self.spin_ram_limit.value()
        max_samples = int((max_ram_mb * 1024 * 1024) / 8)
        
        req_samples = i_stop - i_start
        use_mosaic = self.chk_sparse.isChecked()
        
        if req_samples <= max_samples:
            # We are within limit.
            # Load contiguous chunk normally.
            data = self.local_iq_handle[i_start:i_stop]
            sxx, extent = dsp.compute_spectrogram(data, sr, fft_size, overlap)
            
            self.img_spec.setImage(sxx.T, autoLevels=False)
            self.img_spec.setRect(pg.QtCore.QRectF(min_t, extent[2], (max_t-min_t), extent[3]-extent[2]))
            
        elif not use_mosaic:
            # Over limit
            # Clamp the read to the max allowed samples.
            limit_stop = i_start + max_samples
            data = self.local_iq_handle[i_start:limit_stop]
            sxx, extent = dsp.compute_spectrogram(data, sr, fft_size, overlap)
            
            # Calculate actual duration of loaded data.
            actual_dur = (limit_stop - i_start) / sr
            
            # Set image rect. It will appear cut off on the screen (shorter than the view range).
            self.img_spec.setImage(sxx.T, autoLevels=False)
            self.img_spec.setRect(pg.QtCore.QRectF(min_t, extent[2], actual_dur, extent[3]-extent[2]))
            
        else:
            # Over Limit but mosaic is checked.
            # Use DSP library function.
            sxx, extent = dsp.compute_mosaic_spectrogram(
                self.local_iq_handle, 
                sr, 
                i_start, 
                i_stop, 
                fft_size, 
                target_width=2000
            )
            
            if sxx is not None:
                self.img_spec.setImage(sxx.T, autoLevels=False)
                # Extent from dsp_lib is [0, dur, min_f, max_f]
                # Map to global time (min_t)
                self.img_spec.setRect(pg.QtCore.QRectF(min_t, extent[2], extent[1], extent[3]-extent[2]))

    def update_colormap(self, t):
        if t == 'White Hot':
            grad = pg.GradientEditorItem()
            grad.restoreState({'ticks': [(0.0, (0,0,0,255)), (1.0, (255,255,255,255))], 'mode': 'rgb'})
            self.hist_widget.gradient.setColorMap(grad.colorMap())
        elif t == 'Black Hot':
            grad = pg.GradientEditorItem()
            grad.restoreState({'ticks': [(0.0, (255,255,255,255)), (1.0, (0,0,0,255))], 'mode': 'rgb'})
            self.hist_widget.gradient.setColorMap(grad.colorMap())
        elif t == 'Rainbow':
            grad = pg.GradientEditorItem()
            grad.restoreState({'ticks': [
                (0.0, (0,0,128,255)), (0.2, (0,0,255,255)), (0.4, (0,255,255,255)), 
                (0.6, (255,255,0,255)), (0.8, (255,0,0,255)), (1.0, (128,0,0,255))
            ], 'mode': 'rgb'})
            self.hist_widget.gradient.setColorMap(grad.colorMap())
        else:
            self.hist_widget.gradient.loadPreset(t)

    def update_zoom_from_region(self):
        min_x, max_x = self.region.getRegion()
        self.plot_spec.setXRange(min_x, max_x, padding=0)
        self.refresh_spectrogram()

    def update_region_from_zoom(self, _, viewRange):
        self.region.blockSignals(True)
        self.region.setRegion(viewRange[0])
        self.region.blockSignals(False)
