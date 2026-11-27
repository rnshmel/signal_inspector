import os
import time
import numpy as np
from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QLineEdit, QPushButton, QFileDialog, QGroupBox, 
                             QGridLayout, QCheckBox, QSpinBox, QScrollArea,
                             QSizePolicy, QWidget, QSplitter)
from PyQt6.QtCore import Qt, QTimer, QEventLoop
import pyqtgraph as pg

# Import the base class from core.
from core.base_tab import BaseSignalTab
# Import dsp and IQ I/O utilities.
import utils.dsp_lib as dsp
import utils.iq_io_lib as iq_io

# Horizontal split between Left (Visualization) and Right (Sidebar Controls)
# Setting SIDEBAR_PANEL_STRETCH = 0 lets the sidebar sit at natural sizeHint width
VIZ_PANEL_STRETCH = 1
SIDEBAR_PANEL_STRETCH = 0

# Vertical split inside Visualization panel: Main Spectrogram vs. Minimap
SPEC_PLOT_STRETCH = 8
MINI_PLOT_STRETCH = 1

# File Configuration Grid: Column stretch ratios [Label, Path Input, Browse Button]
FILE_GRID_LABEL_STRETCH = 0
FILE_GRID_PATH_STRETCH = 1
FILE_GRID_BTN_STRETCH = 0

# Sidebar internal vertical stretch (Histogram LUT widget vs bottom spacer)
HIST_WIDGET_STRETCH = 2
SIDEBAR_BOTTOM_STRETCH = 1

# Debounce delay (ms) before recomputing spectrogram after pan/zoom
DEBOUNCE_MS = 250

# Extra time buffer ratio rendered on either side of the visible spectrogram window
VIEW_BUFFER_RATIO = 0.00

# Minimap anchor & burst sampling parameters
MINIMAP_MIN_ANCHORS = 1000
MINIMAP_MAX_ANCHORS = 2500
MINIMAP_BURST_SAMPLES = 512

# Minimum interval (seconds) between busy-status UI repaints
PROGRESS_UPDATE_INTERVAL_S = 0.05

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
        self.minimap_t = None
        self.minimap_rms = None
        self.minimap_peak = None
        self._is_busy = False
        self._last_progress_time = 0.0

        self.lbl_busy_status = QLabel("")
        self.lbl_busy_status.setStyleSheet("color: #1565C0; font-weight: bold;")
        self.lbl_busy_status.setMinimumWidth(230)
        self.header_layout.insertWidget(0, self.lbl_busy_status)

        # Timer for debouncing heavy spectrogram FFT updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.refresh_spectrogram)
        
        self.init_ui()

    def init_ui(self):
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)

        # Sidebar controls.
        self.sidebar = QGroupBox("Controls")
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # File Config
        grp_file = QGroupBox("File Configuration")
        layout_file = QGridLayout()
        grp_file.setLayout(layout_file)
        
        self.txt_path = QLineEdit()
        self.txt_path.setReadOnly(True)
        self.txt_path.setPlaceholderText("Select File...")
        self.txt_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        btn_browse = QPushButton("...")
        btn_browse.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        btn_browse.clicked.connect(self.browse_file)
        
        layout_file.addWidget(QLabel("File:"), 0, 0)
        layout_file.addWidget(self.txt_path, 0, 1)
        layout_file.addWidget(btn_browse, 0, 2)
        layout_file.setColumnStretch(0, FILE_GRID_LABEL_STRETCH)
        layout_file.setColumnStretch(1, FILE_GRID_PATH_STRETCH)
        layout_file.setColumnStretch(2, FILE_GRID_BTN_STRETCH)
        
        self.cb_dtype = QComboBox()
        self.cb_dtype.addItems(["cf32 (Complex Float 32)", 
                                "cs16 (Complex Int 16)", 
                                "cs8 (Complex Int 8)", 
                                "cu8 (Complex Unsigned 8)"])
        layout_file.addWidget(QLabel("Data Type:"), 1, 0)
        layout_file.addWidget(self.cb_dtype, 1, 1, 1, 2)

        self.txt_sr = QLineEdit("2000000")
        layout_file.addWidget(QLabel("Sample Rate:"), 2, 0)
        layout_file.addWidget(self.txt_sr, 2, 1, 1, 2)

        self.btn_load_local = QPushButton("LOAD DATA")
        self.btn_load_local.clicked.connect(self.load_local_data)
        layout_file.addWidget(self.btn_load_local, 3, 0, 1, 3)

        self.sidebar_layout.addWidget(grp_file)

        # Memory Settings
        grp_mem = QGroupBox("Memory / View Control")
        layout_mem = QVBoxLayout()
        grp_mem.setLayout(layout_mem)

        row_ram = QHBoxLayout()
        row_ram.addWidget(QLabel("Max RAM (MB):"))
        self.spin_ram_limit = QSpinBox()
        self.spin_ram_limit.setRange(50, 2000)
        self.spin_ram_limit.setValue(350)
        self.spin_ram_limit.setSingleStep(50)
        self.spin_ram_limit.setToolTip("Limits the amount of data loaded into RAM for the spectrogram.")
        self.spin_ram_limit.valueChanged.connect(self.schedule_refresh)
        row_ram.addWidget(self.spin_ram_limit)
        layout_mem.addLayout(row_ram)

        self.chk_sparse = QCheckBox("Enable Strided View")
        self.chk_sparse.setToolTip("If view exceeds RAM limit, load sparse chunks instead of clamping.")
        self.chk_sparse.setChecked(False)
        self.chk_sparse.stateChanged.connect(self.refresh_spectrogram)
        layout_mem.addWidget(self.chk_sparse)

        row_minimap = QHBoxLayout()
        row_minimap.addWidget(QLabel("Minimap:"))
        self.cb_minimap_mode = QComboBox()
        self.cb_minimap_mode.addItems(["RMS", "Peak"])
        self.cb_minimap_mode.setCurrentText("RMS")
        self.cb_minimap_mode.setToolTip("Switch instantly between cached RMS average and Peak amplitude envelopes.")
        self.cb_minimap_mode.currentTextChanged.connect(self._render_minimap_curve)
        row_minimap.addWidget(self.cb_minimap_mode, stretch=1)
        layout_mem.addLayout(row_minimap)

        self.sidebar_layout.addWidget(grp_mem)
        
        self.lbl_file_info = QLabel("No File Loaded")
        self.sidebar_layout.addWidget(self.lbl_file_info)

        # Spectrogram Config
        self.sidebar_layout.addWidget(QLabel("FFT Size:"))
        self.cb_fft = QComboBox()
        self.cb_fft.addItems([str(2**i) for i in range(8, 16)])
        self.cb_fft.setCurrentText("1024")
        self.cb_fft.currentTextChanged.connect(self.refresh_spectrogram)
        self.sidebar_layout.addWidget(self.cb_fft)
        
        self.sidebar_layout.addWidget(QLabel("Overlap Factor:"))
        self.cb_overlap = QComboBox()
        self.cb_overlap.addItems(["0", "2", "4", "8", "16", "32"])
        self.cb_overlap.setCurrentText("0")
        self.cb_overlap.currentTextChanged.connect(self.refresh_spectrogram)
        self.sidebar_layout.addWidget(self.cb_overlap)

        self.sidebar_layout.addWidget(QLabel("Color Map:"))
        self.cb_cmap = QComboBox()
        self.cb_cmap.addItems(['viridis', 'plasma', 'inferno', 'Rainbow', 'White Hot', 'Black Hot'])
        self.cb_cmap.setCurrentText('inferno') 
        self.cb_cmap.currentTextChanged.connect(self.update_colormap)
        self.sidebar_layout.addWidget(self.cb_cmap)

        self.sidebar_layout.addWidget(QLabel("Levels:"))
        self.hist_widget = pg.HistogramLUTWidget()
        self.hist_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        self.hist_widget.setLevels(-130, -30)
        self.hist_widget.setHistogramRange(-130, -30)
        self.sidebar_layout.addWidget(self.hist_widget, stretch=HIST_WIDGET_STRETCH)
        self.sidebar_layout.addStretch(SIDEBAR_BOTTOM_STRETCH)

        # Visualization area.
        viz_container = QWidget()
        self.viz_layout = QVBoxLayout(viz_container)
        self.viz_layout.setContentsMargins(0, 0, 0, 0)
        
        self.plot_spec = pg.PlotWidget()
        self.plot_spec.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_spec.setLabel('left', 'Frequency', units='Hz')
        self.plot_spec.setLabel('bottom', 'Time', units='s')
        self.img_spec = pg.ImageItem()
        self.plot_spec.addItem(self.img_spec)
        self.hist_widget.setImageItem(self.img_spec)
        
        self.update_colormap('inferno')

        self.plot_mini = pg.PlotWidget()
        self.plot_mini.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.plot_mini.hideAxis('bottom')
        self.curve_mini = self.plot_mini.plot(pen='w')
        
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        for line in self.region.lines:
            line.setPen(pg.mkPen(color='w', width=4))
            line.setHoverPen(pg.mkPen(color='r', width=8))
        self.plot_mini.addItem(self.region)
        self.region.sigRegionChanged.connect(self.update_zoom_from_region)
        self.plot_spec.sigRangeChanged.connect(self.update_region_from_zoom)

        self.viz_layout.addWidget(self.plot_spec, stretch=SPEC_PLOT_STRETCH)
        self.viz_layout.addWidget(self.plot_mini, stretch=MINI_PLOT_STRETCH)
        
        # Apply sidebar inside scroll area to right side
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

    def browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open IQ", "", "All Files (*)")
        if fname:
            self.current_file_path = fname
            self.txt_path.setText(os.path.basename(fname))

    def load_local_data(self):
        if not self.current_file_path:
            self.lbl_file_info.setText("Error: No file selected")
            return
        if self._is_busy:
            return

        self._is_busy = True
        self.update_timer.stop()
        has_app = QApplication.instance() is not None
        if has_app:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            self._set_busy_status("Opening file...", force=True)
            sr_val = float(self.txt_sr.text())
            if sr_val <= 0.0:
                raise ValueError("Sample rate must be > 0.")

            # Instantiate the wrapper instead of raw memmap
            fmt_str = self.cb_dtype.currentText()
            new_handle = iq_io.MappedIQWrapper(self.current_file_path, fmt_str)

            old_handle = self.local_iq_handle
            if old_handle is not None and old_handle is not self.context.raw_iq_handle:
                old_handle.close()
            self.local_iq_handle = new_handle

            self.local_duration = len(self.local_iq_handle) / sr_val

            self.lbl_file_info.setText(f"{len(self.local_iq_handle):,} Samples\n{self.local_duration:.4f} Sec")
            self.update_minimap()

            init_end = min(0.15, self.local_duration)
            vb = self.plot_spec.getViewBox()
            self.region.blockSignals(True)
            self.plot_spec.blockSignals(True)
            vb.blockSignals(True)
            try:
                self.region.setRegion([0, init_end])
                self.plot_spec.setXRange(0, init_end, padding=0)
            finally:
                vb.blockSignals(False)
                self.plot_spec.blockSignals(False)
                self.region.blockSignals(False)

            self.update_timer.stop()
            self._refresh_spectrogram_impl()
            self.btn_stage.setEnabled(True)
            
        except Exception as e:
            self.lbl_file_info.setText(f"Error: {str(e)}")
            print(e)
        finally:
            self.lbl_busy_status.setText("")
            if has_app:
                QApplication.restoreOverrideCursor()
            self._is_busy = False

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
        
        overlap_factor = int(self.cb_overlap.currentText())
        overlap = 0 if overlap_factor == 0 else fft_size - (fft_size // overlap_factor)
        
        self.context.viz_fft_size = fft_size
        self.context.viz_overlap = overlap
        self.context.viz_levels = self.hist_widget.getLevels()
        self.context.viz_lut = self.hist_widget.gradient.getLookupTable(256)
        
        return True, f"Ready for Tuner ({self.context.raw_sr/1e6:.1f} MHz)"

    def _render_minimap_curve(self):
        if self.minimap_t is None or len(self.minimap_t) == 0:
            self.curve_mini.setData([], [])
            return
        y_vals = self.minimap_peak if self.cb_minimap_mode.currentText() == "Peak" else self.minimap_rms
        self.curve_mini.setData(self.minimap_t, y_vals)

    def _set_busy_status(self, text, force=False):
        now = time.monotonic()
        if not force and (now - self._last_progress_time) < PROGRESS_UPDATE_INTERVAL_S:
            return
        self._last_progress_time = now
        self.lbl_busy_status.setText(text)
        self.lbl_busy_status.repaint()
        if QApplication.instance() is not None:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _make_progress_cb(self, label):
        last_pct = -1
        def _cb(done, total):
            nonlocal last_pct
            if total <= 0:
                return
            pct = int((done * 100) / total)
            is_done = done >= total
            if pct == last_pct and not is_done:
                return
            now = time.monotonic()
            if not is_done and (now - self._last_progress_time) < PROGRESS_UPDATE_INTERVAL_S:
                return
            last_pct = pct
            self._set_busy_status(f"{label} {pct}%", force=True)
        return _cb

    def update_minimap(self):
        if self.local_iq_handle is None:
            return
        total_samples = len(self.local_iq_handle)
        if total_samples == 0 or self.local_duration <= 0.0:
            self.minimap_t = None
            self.minimap_rms = None
            self.minimap_peak = None
            self._render_minimap_curve()
            return

        sr = total_samples / self.local_duration
        num_anchors = max(MINIMAP_MIN_ANCHORS, min(int(self.plot_mini.width()), MINIMAP_MAX_ANCHORS))

        if total_samples <= num_anchors * MINIMAP_BURST_SAMPLES:
            self._set_busy_status("Scanning minimap...", force=True)
            raw = self.local_iq_handle[:]
            mag_sq = raw.real * raw.real + raw.imag * raw.imag
            if total_samples <= num_anchors:
                mag = np.sqrt(mag_sq)
                self.minimap_rms = mag
                self.minimap_peak = mag
                self.minimap_t = np.linspace(0.0, self.local_duration, total_samples)
            else:
                edges = np.linspace(0, total_samples, num_anchors + 1, dtype=np.int64)
                starts = edges[:-1]
                counts = np.diff(edges)
                self.minimap_rms = np.sqrt(np.add.reduceat(mag_sq, starts) / counts)
                self.minimap_peak = np.sqrt(np.maximum.reduceat(mag_sq, starts))
                self.minimap_t = ((edges[:-1] + edges[1:]) * 0.5) / sr
        else:
            starts = np.linspace(0, total_samples - MINIMAP_BURST_SAMPLES, num_anchors, dtype=np.int64)
            starts = (starts // MINIMAP_BURST_SAMPLES) * MINIMAP_BURST_SAMPLES
            self._set_busy_status("Scanning minimap... 0%", force=True)
            chunks = self.local_iq_handle.read_sparse_chunks(
                starts,
                MINIMAP_BURST_SAMPLES,
                progress_cb=self._make_progress_cb("Scanning minimap..."),
            )
            mag_sq = chunks.real * chunks.real + chunks.imag * chunks.imag
            self.minimap_rms = np.sqrt(mag_sq.mean(axis=1))
            self.minimap_peak = np.sqrt(mag_sq.max(axis=1))
            self.minimap_t = (starts + MINIMAP_BURST_SAMPLES / 2.0) / sr

        self._render_minimap_curve()
        self.plot_mini.setXRange(0, self.local_duration)
        self.region.setBounds([0, self.local_duration])

    def refresh_spectrogram(self):
        if self.local_iq_handle is None or self._is_busy:
            return
        self._is_busy = True
        self.update_timer.stop()
        has_app = QApplication.instance() is not None
        if has_app:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._refresh_spectrogram_impl()
        finally:
            self.lbl_busy_status.setText("")
            if has_app:
                QApplication.restoreOverrideCursor()
            self._is_busy = False

    def _refresh_spectrogram_impl(self):
        if self.local_iq_handle is None: return
        min_t, max_t = self.region.getRegion()
        sr = float(self.txt_sr.text())

        # Add a buffer on either side if wanted
        pad_t = (max_t - min_t) * VIEW_BUFFER_RATIO
        min_t = max(0.0, min_t - pad_t)
        max_t = min(self.local_duration, max_t + pad_t)
        
        fft_size = int(self.cb_fft.currentText())
        overlap_factor = int(self.cb_overlap.currentText())
        overlap = 0 if overlap_factor == 0 else fft_size - (fft_size // overlap_factor)
        
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
            self._set_busy_status("Reading IQ data...", force=True)
            data = self.local_iq_handle[i_start:i_stop]
            self._set_busy_status("Computing spectrogram...", force=True)
            sxx, extent = dsp.compute_spectrogram(data, sr, fft_size, overlap)
            
            self._set_busy_status("Rendering spectrogram...", force=True)
            self.img_spec.setImage(sxx.T, autoLevels=False)
            self.img_spec.setRect(pg.QtCore.QRectF(min_t, extent[2], (max_t-min_t), extent[3]-extent[2]))
            
        elif not use_mosaic:
            # Over limit
            # Clamp the read to the max allowed samples.
            limit_stop = i_start + max_samples
            self._set_busy_status("Reading IQ data...", force=True)
            data = self.local_iq_handle[i_start:limit_stop]
            self._set_busy_status("Computing spectrogram...", force=True)
            sxx, extent = dsp.compute_spectrogram(data, sr, fft_size, overlap)
            
            # Calculate actual duration of loaded data.
            actual_dur = (limit_stop - i_start) / sr
            
            # Set image rect. It will appear cut off on the screen (shorter than the view range).
            self._set_busy_status("Rendering spectrogram...", force=True)
            self.img_spec.setImage(sxx.T, autoLevels=False)
            self.img_spec.setRect(pg.QtCore.QRectF(min_t, extent[2], actual_dur, extent[3]-extent[2]))
            
        else:
            # Over Limit but mosaic is checked.
            # Use DSP library function.
            self._set_busy_status("Computing spectrogram... 0%", force=True)
            sxx, extent = dsp.compute_mosaic_spectrogram(
                self.local_iq_handle, 
                sr, 
                i_start, 
                i_stop, 
                fft_size, 
                target_width=2000,
                progress_cb=self._make_progress_cb("Computing spectrogram...")
            )
            
            if sxx is not None:
                self._set_busy_status("Rendering spectrogram...", force=True)
                self.img_spec.setImage(sxx.T, autoLevels=False)
                # Extent from dsp_lib is [0, dur, min_f, max_f]
                # Map to global time (min_t)
                self.img_spec.setRect(pg.QtCore.QRectF(min_t, extent[2], extent[1], extent[3]-extent[2]))

        self.update_timer.stop()

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

    def schedule_refresh(self):
        self.update_timer.start(DEBOUNCE_MS)

    def update_zoom_from_region(self):
        min_x, max_x = self.region.getRegion()
        self.plot_spec.setXRange(min_x, max_x, padding=0)

    def update_region_from_zoom(self, _, viewRange):
        self.region.blockSignals(True)
        self.region.setRegion(viewRange[0])
        self.region.blockSignals(False)
        self.update_timer.start(DEBOUNCE_MS)
