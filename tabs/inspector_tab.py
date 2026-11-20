import numpy as np
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QGroupBox, QPlainTextEdit, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QAbstractItemView, 
                             QRadioButton, QSplitter, QLineEdit, QFileDialog,
                             QMessageBox, QCheckBox, QComboBox, QSpinBox, QScrollArea,
                             QDialog, QDialogButtonBox, QSizePolicy)
from PyQt6.QtGui import QFont, QFontMetrics, QTextCursor, QColor, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtCore import Qt, QTimer

from core.base_tab import BaseSignalTab
import utils.encoding_lib as enc

# Horizontal split between Left (Visualization) and Right (Sidebar Controls)
# Setting SIDEBAR_PANEL_STRETCH = 0 lets the sidebar sit at natural sizeHint width
VIZ_PANEL_STRETCH = 1
SIDEBAR_PANEL_STRETCH = 0

# Vertical split inside Left panel: Top (Bit Stream Editor) vs. Bottom (Hex Viewer)
BITS_EDITOR_STRETCH = 1
HEX_TABLE_STRETCH = 1

# Debounce delay (ms) before rebuilding hex table after editing bit stream
HEX_DEBOUNCE_MS = 250

class AbsoluteMapDialog(QDialog):
    # Popup window for defining Absolute Symbol Mapping.
    def __init__(self, modulus, current_mapping=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Absolute Mapping")
        self.modulus = modulus
        self.layout = QVBoxLayout(self)
        
        row_presets = QHBoxLayout()
        btn_bin = QPushButton("Binary Preset")
        btn_bin.clicked.connect(lambda: self.apply_preset('binary'))
        btn_gray = QPushButton("Gray Code Preset")
        btn_gray.clicked.connect(lambda: self.apply_preset('gray'))
        row_presets.addWidget(btn_bin)
        row_presets.addWidget(btn_gray)
        self.layout.addLayout(row_presets)
        
        self.table = QTableWidget(self.modulus, 2)
        self.table.setHorizontalHeaderLabels(["Symbol (Int)", "Bit String"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.layout.addWidget(self.table)
        
        self.apply_preset('binary')
        if current_mapping and len(current_mapping) == self.modulus:
            for sym, bits in current_mapping.items():
                if 0 <= sym < self.modulus:
                    self.table.setItem(sym, 1, QTableWidgetItem(bits))
        
        self.bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.bbox.accepted.connect(self.accept)
        self.bbox.rejected.connect(self.reject)
        self.layout.addWidget(self.bbox)

    def apply_preset(self, mode):
        mapping = enc.generate_mapping_dict(self.modulus, mode)
        for sym, bits in mapping.items():
            item_sym = QTableWidgetItem(str(sym))
            item_sym.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(sym, 0, item_sym)
            self.table.setItem(sym, 1, QTableWidgetItem(bits))

    def get_mapping(self):
        mapping = {}
        for row in range(self.modulus):
            sym = int(self.table.item(row, 0).text())
            bits = self.table.item(row, 1).text().strip()
            mapping[sym] = bits
        return mapping

class DifferentialMapDialog(QDialog):
    # Popup window for defining M-Level Differential Mapping.
    def __init__(self, modulus=2, current_mapping=None, parent=None):
        super().__init__(parent)
        self.modulus = max(2, int(modulus))
        self.setWindowTitle(f"Configure {self.modulus}-Level Diff Mapping")
        self.layout = QVBoxLayout(self)
        
        row_presets = QHBoxLayout()
        btn_bin = QPushButton("Binary Preset")
        btn_bin.clicked.connect(lambda: self.apply_preset('binary'))
        btn_gray = QPushButton("Gray Code Preset")
        btn_gray.clicked.connect(lambda: self.apply_preset('gray'))
        row_presets.addWidget(btn_bin)
        row_presets.addWidget(btn_gray)
        self.layout.addLayout(row_presets)

        self.table = QTableWidget(self.modulus, 2)
        self.table.setHorizontalHeaderLabels(["Transition", "Bit String"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.layout.addWidget(self.table)

        self.apply_preset('binary')
        if current_mapping and len(current_mapping) == self.modulus:
            for sym, bits in current_mapping.items():
                if 0 <= sym < self.modulus:
                    self.table.setItem(sym, 1, QTableWidgetItem(bits))
        
        self.bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.bbox.accepted.connect(self.accept)
        self.bbox.rejected.connect(self.reject)
        self.layout.addWidget(self.bbox)

    def apply_preset(self, mode):
        mapping = enc.generate_mapping_dict(self.modulus, mode)
        for row, bits in mapping.items():
            if row == 0:
                label = "0 (Same)"
            elif self.modulus == 2 and row == 1:
                label = "1 (Shift)"
            else:
                label = f"+{row} (mod {self.modulus})"
            item_trans = QTableWidgetItem(label)
            item_trans.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, item_trans)
            self.table.setItem(row, 1, QTableWidgetItem(bits))

    def get_mapping(self):
        return {row: self.table.item(row, 1).text().strip() for row in range(self.modulus)}

class ByteHighlighter(QSyntaxHighlighter):
    # Highlights every alternating byte (8 non-whitespace bits) and flags invalid chars.
    def __init__(self, document):
        super().__init__(document)
        self.highlight_format = QTextCharFormat()
        self.error_format = QTextCharFormat()
        self.combined_error_format = QTextCharFormat()
        self.set_mode(False)

    def set_mode(self, is_light):
        bg = QColor("#E0E0E0") if is_light else QColor("#424242")
        err_fg = QColor("#d32f2f") if is_light else QColor("#ff5252")
        self.highlight_format.setBackground(bg)
        self.error_format.setForeground(err_fg)
        self.error_format.setFontWeight(QFont.Weight.Bold)
        self.combined_error_format = QTextCharFormat(self.highlight_format)
        self.combined_error_format.setForeground(err_fg)
        self.combined_error_format.setFontWeight(QFont.Weight.Bold)
        self.rehighlight()

    def highlightBlock(self, text):
        bit_idx = max(0, self.previousBlockState())
        for i, ch in enumerate(text):
            if ch.isspace():
                continue
            is_alt = (bit_idx // 8) % 2 == 1
            is_err = ch not in ('0', '1')
            if is_alt and is_err:
                self.setFormat(i, 1, self.combined_error_format)
            elif is_alt:
                self.setFormat(i, 1, self.highlight_format)
            elif is_err:
                self.setFormat(i, 1, self.error_format)
            bit_idx += 1
        self.setCurrentBlockState(bit_idx)

class InspectorTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Inspector")
        
        self.btn_stage.setVisible(False)
        self.lbl_output_status.setVisible(False)
        
        self.local_symbols = None
        self.modulus = 2
        self.active_mapping_mode = 'absolute'
        self.active_mapping_dict = {}
        
        self.is_syncing = False
        self.stashed_bits = "" 
        
        self.hex_timer = QTimer()
        self.hex_timer.setSingleShot(True)
        self.hex_timer.setInterval(HEX_DEBOUNCE_MS)
        self.hex_timer.timeout.connect(self.update_hex_view)
        
        self.init_ui()

    def init_ui(self):
        # Header stash/restore buttons
        self.btn_stash = QPushButton("💾 Save State")
        self.btn_stash.setToolTip("Saves the current bit string for a quick reset.")
        self.btn_stash.setStyleSheet("font-weight: bold; background-color: #fff3e0;")
        self.btn_stash.clicked.connect(self.stash_state)
        
        self.btn_restore = QPushButton("📂 Load State")
        self.btn_restore.setToolTip("Restores the previously saved bit string.")
        self.btn_restore.setStyleSheet("font-weight: bold; background-color: #e3f2fd;")
        self.btn_restore.clicked.connect(self.restore_state)
        self.btn_restore.setEnabled(False)

        self.header_layout.insertWidget(1, self.btn_stash)
        self.header_layout.insertWidget(2, self.btn_restore)

        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)
        
        # LEFT: Split View (Vertical Splitter for editor/hex)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.splitter.setChildrenCollapsible(False)
        
        self.grp_bits = QGroupBox("Bit Stream (Editable Workbench)")
        self.grp_bits_layout = QVBoxLayout()
        self.grp_bits.setLayout(self.grp_bits_layout)
        
        self.txt_bits = QPlainTextEdit()
        self.txt_bits.setFont(QFont("Monospace", 14))
        self.txt_bits.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
        
        self.txt_bits.textChanged.connect(self.hex_timer.start)
        self.txt_bits.cursorPositionChanged.connect(self.sync_highlight_to_hex)
        self.txt_bits.selectionChanged.connect(self.update_bit_metrics)
        self.grp_bits_layout.addWidget(self.txt_bits)

        self.lbl_bit_metrics = QLabel("Total: 0 bits (0 bytes)  |  Cursor: Bit 0 (Byte 0x0000)  |  Selected: 0 bits")
        self.lbl_bit_metrics.setStyleSheet("font-size: 9pt; color: #757575; font-weight: bold;")
        self.lbl_bit_metrics.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.grp_bits_layout.addWidget(self.lbl_bit_metrics)
        
        self.highlighter = ByteHighlighter(self.txt_bits.document())
        self.splitter.addWidget(self.grp_bits)
        
        # Hex View
        self.grp_hex = QGroupBox("Hex Viewer (Read-Only)")
        self.grp_hex_layout = QVBoxLayout()
        self.grp_hex.setLayout(self.grp_hex_layout)
        
        self.table_hex = QTableWidget()
        self.table_hex.setColumnCount(18) 
        headers = ["Offset"] + [f"{i:02X}" for i in range(16)] + ["ASCII"]
        self.table_hex.setHorizontalHeaderLabels(headers)
        self.table_hex.verticalHeader().setVisible(False)
        self.table_hex.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_hex.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_hex.cellClicked.connect(self.sync_highlight_to_bits)
        
        header = self.table_hex.horizontalHeader()
        for col in range(17):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(17, QHeaderView.ResizeMode.Stretch)
        
        self.grp_hex_layout.addWidget(self.table_hex)
        self.splitter.addWidget(self.grp_hex)
        self.splitter.setStretchFactor(0, BITS_EDITOR_STRETCH)
        self.splitter.setStretchFactor(1, HEX_TABLE_STRETCH)
        
        # RIGHT: Controls
        self.sidebar = QGroupBox("Analysis Controls")
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # Symbol Mapping
        self.grp_map = QGroupBox("1. Symbol to Bit Mapping")
        self.map_layout = QVBoxLayout()
        self.grp_map.setLayout(self.map_layout)
        
        self.lbl_sym_info = QLabel("Symbols: 0 | Levels: Unknown")
        self.lbl_sym_info.setStyleSheet("color: #757575; font-style: italic;")
        self.map_layout.addWidget(self.lbl_sym_info)
        
        self.btn_cfg_abs = QPushButton("Configure Absolute Map")
        self.btn_cfg_abs.clicked.connect(self.configure_absolute_map)
        self.map_layout.addWidget(self.btn_cfg_abs)
        
        self.btn_cfg_diff = QPushButton("Configure Differential Map")
        self.btn_cfg_diff.clicked.connect(self.configure_differential_map)
        self.map_layout.addWidget(self.btn_cfg_diff)
        
        self.lbl_map_status = QLabel("Mode: Absolute (Binary Default)")
        self.lbl_map_status.setStyleSheet("font-weight: bold;")
        self.map_layout.addWidget(self.lbl_map_status)

        self.chk_invert_symbols = QCheckBox("Invert Symbol Polarity ((M-1) - s)")
        self.chk_invert_symbols.setToolTip("Inverts discrete symbol values (0..M-1) before bit mapping or symbol export.")
        self.chk_invert_symbols.stateChanged.connect(self.on_invert_symbols_toggled)
        self.map_layout.addWidget(self.chk_invert_symbols)
        
        self.btn_send_workbench = QPushButton("Send to Bit Workbench")
        self.btn_send_workbench.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")
        self.btn_send_workbench.clicked.connect(self.send_to_workbench)
        self.map_layout.addWidget(self.btn_send_workbench)
        
        self.sidebar_layout.addWidget(self.grp_map)

        # View Settings
        self.grp_view = QGroupBox("View Settings")
        self.view_layout = QVBoxLayout()
        self.grp_view.setLayout(self.view_layout)
        
        self.chk_light_mode = QCheckBox("Light Mode")
        self.chk_light_mode.stateChanged.connect(self.update_view_settings)
        self.view_layout.addWidget(self.chk_light_mode)
        
        row_font = QHBoxLayout()
        row_font.addWidget(QLabel("Font Size:"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 72)
        self.spin_font.setValue(14)
        self.spin_font.valueChanged.connect(self.update_view_settings)
        row_font.addWidget(self.spin_font)
        self.view_layout.addLayout(row_font)

        row_endian = QHBoxLayout()
        row_endian.addWidget(QLabel("Byte Bit Order:"))
        self.cb_bit_order = QComboBox()
        self.cb_bit_order.addItems(["MSB First", "LSB First"])
        self.cb_bit_order.setToolTip(
            "Controls per-byte bit ordering in the Hex Viewer and .BIN export only (does not alter raw wire-order pattern search)."
        )
        self.cb_bit_order.currentTextChanged.connect(self.update_hex_view)
        row_endian.addWidget(self.cb_bit_order)
        self.view_layout.addLayout(row_endian)
        
        self.sidebar_layout.addWidget(self.grp_view)

        # Bit String Actions
        self.grp_logic = QGroupBox("2. Bit String Actions")
        self.logic_layout = QVBoxLayout()
        self.grp_logic.setLayout(self.logic_layout)
        
        self.btn_invert = QPushButton("Invert Bits (0 <--> 1)")
        self.btn_invert.clicked.connect(self.action_invert)
        self.logic_layout.addWidget(self.btn_invert)
        
        self.logic_layout.addWidget(QLabel("Line Encoding:"))
        self.cb_encoding = QComboBox()
        self.cb_encoding.addItems(["Manchester (IEEE)", "Manchester (Thomas)"])
        self.logic_layout.addWidget(self.cb_encoding)
        
        self.btn_decode_line = QPushButton("Apply Line Decoding")
        self.btn_decode_line.clicked.connect(self.action_line_decode)
        self.logic_layout.addWidget(self.btn_decode_line)
        
        self.sidebar_layout.addWidget(self.grp_logic)
        
        # Pattern Search
        self.grp_pattern = QGroupBox("Pattern Search & Align")
        self.pat_layout = QVBoxLayout()
        self.grp_pattern.setLayout(self.pat_layout)
        
        self.row_search_mode = QHBoxLayout()
        self.rb_bin = QRadioButton("Binary")
        self.rb_hex = QRadioButton("Hex")
        self.rb_hex.setChecked(True)
        self.rb_hex.setToolTip(
            "Searches the bit stream in raw wire (MSB-first) bit order, independent of the Hex Viewer's Byte Bit Order setting."
        )
        self.rb_bin.toggled.connect(self.reset_search_status)
        self.row_search_mode.addWidget(self.rb_bin)
        self.row_search_mode.addWidget(self.rb_hex)
        self.pat_layout.addLayout(self.row_search_mode)
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Enter Pattern...")
        self.txt_search.textChanged.connect(self.reset_search_status)
        self.pat_layout.addWidget(self.txt_search)
        
        row_pat = QHBoxLayout()
        self.btn_find = QPushButton("Find Next")
        self.btn_find.clicked.connect(self.find_pattern)
        self.btn_align = QPushButton("Align (Cut Prev)")
        self.btn_align.clicked.connect(self.align_pattern)
        row_pat.addWidget(self.btn_find)
        row_pat.addWidget(self.btn_align)
        self.pat_layout.addLayout(row_pat)

        self.lbl_search_status = QLabel("Matches: --")
        self.lbl_search_status.setStyleSheet("font-size: 9pt; color: #757575;")
        self.lbl_search_status.setWordWrap(True)
        self.pat_layout.addWidget(self.lbl_search_status)
        
        self.sidebar_layout.addWidget(self.grp_pattern)
        
        # Export
        self.sidebar_layout.addWidget(QLabel("<b>Export:</b>"))
        self.btn_save_bin = QPushButton("Save .BIN (Raw Bytes)")
        self.btn_save_bin.clicked.connect(lambda: self.export_data('bin'))
        self.sidebar_layout.addWidget(self.btn_save_bin)
        
        self.btn_save_txt = QPushButton("Save .TXT (Bit String)")
        self.btn_save_txt.clicked.connect(lambda: self.export_data('txt'))
        self.sidebar_layout.addWidget(self.btn_save_txt)

        self.btn_save_syms = QPushButton("Save .BIN (Raw Symbols)")
        self.btn_save_syms.setToolTip("Saves the raw symbols (0, 1, 2, 3, etc.) from Bit Recovery as 1 byte per symbol (uint8).")
        self.btn_save_syms.clicked.connect(lambda: self.export_data('syms'))
        self.sidebar_layout.addWidget(self.btn_save_syms)
        
        self.sidebar_layout.addStretch()

        # Sidebar inside scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        scroll_area.setWidget(self.sidebar)

        # Combine workbench/hex and sidebar in a user-resizable horizontal splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.splitter)
        self.main_splitter.addWidget(scroll_area)
        self.main_splitter.setStretchFactor(0, VIZ_PANEL_STRETCH)
        self.main_splitter.setStretchFactor(1, SIDEBAR_PANEL_STRETCH)
        main_h_layout.addWidget(self.main_splitter)

        self.update_view_settings()
    
    def load_input(self):
        if self.context.symbols is None:
            return False, "No symbols in context."
            
        self.local_symbols = self.context.symbols
        
        unique = np.unique(self.local_symbols)
        self.modulus = int(np.max(unique)) + 1 if len(unique) > 0 else 2
        
        self.active_mapping_mode = 'absolute'
        self.active_mapping_dict = enc.generate_mapping_dict(self.modulus, 'binary')
        
        self.chk_invert_symbols.blockSignals(True)
        self.chk_invert_symbols.setChecked(False)
        self.chk_invert_symbols.blockSignals(False)

        self.lbl_sym_info.setText(f"Symbols: {len(self.local_symbols)} | Levels: {self.modulus}")
        self.lbl_map_status.setText("Mode: Absolute (Binary Preset)")
        self.send_to_workbench()
        
        return True, f"Loaded {len(self.local_symbols)} symbols."

    def stage_output(self):
        return True, "No next stage."

    def configure_absolute_map(self):
        curr = self.active_mapping_dict if (
            self.active_mapping_mode == 'absolute' and len(self.active_mapping_dict) == self.modulus
        ) else None
        dialog = AbsoluteMapDialog(self.modulus, current_mapping=curr, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.active_mapping_dict = dialog.get_mapping()
            self.active_mapping_mode = 'absolute'
            self.lbl_map_status.setText("Mode: Absolute (Custom)")
            if self.local_symbols is not None:
                self.send_to_workbench()

    def configure_differential_map(self):
        curr = self.active_mapping_dict if (
            self.active_mapping_mode == 'differential' and len(self.active_mapping_dict) == self.modulus
        ) else None
        dialog = DifferentialMapDialog(self.modulus, current_mapping=curr, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.active_mapping_dict = dialog.get_mapping()
            self.active_mapping_mode = 'differential'
            self.lbl_map_status.setText("Mode: Differential (Custom)")
            if self.local_symbols is not None:
                self.send_to_workbench()

    def on_invert_symbols_toggled(self):
        if self.local_symbols is not None:
            self.send_to_workbench()

    def send_to_workbench(self):
        if self.local_symbols is None:
            return

        syms = self.local_symbols
        if self.chk_invert_symbols.isChecked():
            syms = enc.invert_symbols(syms, self.modulus)
            
        if self.active_mapping_mode == 'absolute':
            bit_str = enc.map_symbols_to_bits(syms, self.active_mapping_dict)
            
        elif self.active_mapping_mode == 'differential':
            diff_syms = enc.decode_differential(syms, self.modulus)
            bit_str = enc.map_symbols_to_bits(diff_syms, self.active_mapping_dict)
            
        self.txt_bits.blockSignals(True)
        self.txt_bits.setPlainText(bit_str)
        self.txt_bits.blockSignals(False)
        self.update_hex_view()
        
        self.lbl_input_status.setVisible(True)
        self.lbl_input_status.setText("Workbench populated with mapped bits.")
        self.lbl_input_status.setStyleSheet("color: #1565C0;")

    def _update_hex_column_widths(self, font):
        fm = QFontMetrics(font)
        self.table_hex.setColumnWidth(0, fm.horizontalAdvance("00000000") + 20)
        byte_width = fm.horizontalAdvance("00") + 16
        for col in range(1, 17):
            self.table_hex.setColumnWidth(col, byte_width)
        self.table_hex.verticalHeader().setDefaultSectionSize(fm.height() + 6)

    def update_view_settings(self):
        size = self.spin_font.value()
        is_light = self.chk_light_mode.isChecked()
        
        font = QFont("Monospace", size)
        self.txt_bits.setFont(font)
        self.table_hex.setFont(font)
        self.table_hex.horizontalHeader().setFont(font)
        self._update_hex_column_widths(font)
        
        if is_light:
            self.txt_bits.setStyleSheet("background-color: #FFFFFF; color: #000000;")
            self.table_hex.setStyleSheet("""
                QTableWidget {
                    background-color: #FFFFFF;
                    color: #000000;
                    gridline-color: #D0D0D0;
                }
                QHeaderView::section {
                    background-color: #F0F0F0;
                    color: #000000;
                    border: 1px solid #D0D0D0;
                    padding: 2px;
                }
            """)
        else:
            self.txt_bits.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
            self.table_hex.setStyleSheet("""
                QTableWidget {
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                    gridline-color: #333333;
                }
                QHeaderView::section {
                    background-color: #2b2b2b;
                    color: #e0e0e0;
                    border: 1px solid #3c3c3c;
                    padding: 2px;
                }
            """)
            
        self.highlighter.set_mode(is_light)
        self.update_hex_view()

    def stash_state(self):
        self.stashed_bits = self.txt_bits.toPlainText()
        self.btn_restore.setEnabled(True)
        self.lbl_input_status.setVisible(True)
        self.lbl_input_status.setText("Workbench state saved.")
        self.lbl_input_status.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def restore_state(self):
        if self.stashed_bits or self.stashed_bits == "":
            self.txt_bits.setPlainText(self.stashed_bits)
            self.lbl_input_status.setVisible(True)
            self.lbl_input_status.setText("Workbench state restored.")
            self.lbl_input_status.setStyleSheet("color: #1565C0; font-weight: bold;")

    def action_invert(self):
        text = self.txt_bits.toPlainText()
        if not text: return
        self.txt_bits.setPlainText(enc.invert_bit_string(text))

    def action_line_decode(self):
        text = "".join(c for c in self.txt_bits.toPlainText() if not c.isspace())
        if not text: return
        
        enc_mode = self.cb_encoding.currentText()
        scheme = 'IEEE' if 'IEEE' in enc_mode else 'Thomas'
        
        decoded_text = enc.decode_manchester_string(text, scheme)
        self.txt_bits.setPlainText(decoded_text)

    def update_bit_metrics(self):
        raw_text = self.txt_bits.toPlainText()
        total_bits = sum(1 for c in raw_text if not c.isspace())
        total_bytes = (total_bits + 7) // 8
        cursor = self.txt_bits.textCursor()
        pos = cursor.position()
        bit_pos = sum(1 for c in raw_text[:pos] if not c.isspace())
        byte_idx = bit_pos // 8
        sel_bits = sum(1 for c in cursor.selectedText() if not c.isspace()) if cursor.hasSelection() else 0
        self.lbl_bit_metrics.setText(
            f"Total: {total_bits:,} bits ({total_bytes:,} bytes)  |  "
            f"Cursor: Bit {bit_pos:,} (Byte 0x{byte_idx:04X})  |  "
            f"Selected: {sel_bits:,} bits"
        )

    def update_hex_view(self):
        if not hasattr(self, 'table_hex'): return

        bits = "".join(c for c in self.txt_bits.toPlainText() if not c.isspace())
        if len(bits) == 0:
            self.table_hex.clearContents()
            self.table_hex.setRowCount(0)
            self.hex_timer.stop()
            self.update_bit_metrics()
            return

        padding = (8 - len(bits) % 8) % 8
        bits_padded = bits + "0" * padding
        lsb_first = (self.cb_bit_order.currentText() == "LSB First")
        
        byte_data = []
        for i in range(0, len(bits_padded), 8):
            byte_str = bits_padded[i:i+8]
            if lsb_first:
                byte_str = byte_str[::-1]
            try:
                byte_data.append(int(byte_str, 2))
            except ValueError:
                byte_data.append(None)
        
        is_light = self.chk_light_mode.isChecked()
        offset_bg = QColor("#eaeaea") if is_light else QColor("#2a2a2a")
        offset_fg = QColor("#333333") if is_light else QColor("#90caf9")
        err_fg = QColor("#d32f2f") if is_light else QColor("#ff5252")

        self.table_hex.setUpdatesEnabled(False)
        self.table_hex.blockSignals(True)
        self.table_hex.clearContents()
        self.table_hex.setRowCount((len(byte_data) + 15) // 16)
        
        for row in range(self.table_hex.rowCount()):
            offset_item = QTableWidgetItem(f"{row*16:08X}")
            offset_item.setBackground(offset_bg)
            offset_item.setForeground(offset_fg)
            self.table_hex.setItem(row, 0, offset_item)
            
            ascii_str = ""
            for col in range(16):
                idx = row * 16 + col
                if idx < len(byte_data):
                    val = byte_data[idx]
                    if val is None:
                        item = QTableWidgetItem("??")
                        item.setForeground(err_fg)
                        self.table_hex.setItem(row, col + 1, item)
                        ascii_str += "?"
                    else:
                        self.table_hex.setItem(row, col + 1, QTableWidgetItem(f"{val:02X}"))
                        if 32 <= val <= 126: ascii_str += chr(val)
                        else: ascii_str += "."
                else:
                    self.table_hex.setItem(row, col + 1, QTableWidgetItem(""))
            
            self.table_hex.setItem(row, 17, QTableWidgetItem(ascii_str))
            
        self.table_hex.blockSignals(False)
        self.table_hex.setUpdatesEnabled(True)
        self.hex_timer.stop()
        self.update_bit_metrics()

    def _bit_range_to_doc_positions(self, text, bit_start, bit_end):
        if bit_end <= bit_start:
            return None, None
        bit_idx = 0
        doc_start = None
        doc_end = None
        for i, ch in enumerate(text):
            if ch.isspace():
                continue
            if bit_idx == bit_start:
                doc_start = i
            if bit_idx < bit_end:
                doc_end = i + 1
            if bit_idx == bit_end - 1:
                break
            bit_idx += 1
        if doc_start is None:
            return None, None
        return doc_start, doc_end

    def sync_highlight_to_hex(self):
        if self.is_syncing: return
        self.is_syncing = True
        
        raw_text = self.txt_bits.toPlainText()
        pos = self.txt_bits.textCursor().position()
        bit_pos = sum(1 for c in raw_text[:pos] if not c.isspace())
        
        byte_idx = bit_pos // 8
        row = byte_idx // 16
        col = (byte_idx % 16) + 1 
        
        if row < self.table_hex.rowCount():
            self.table_hex.blockSignals(True)
            self.table_hex.setCurrentCell(row, col)
            self.table_hex.blockSignals(False)
            
        self.is_syncing = False
        self.update_bit_metrics()

    def sync_highlight_to_bits(self, row, col):
        if self.is_syncing: return
        if col < 1 or col > 16: return
        
        byte_idx = (row * 16) + (col - 1)
        bit_start = byte_idx * 8
        bit_end = bit_start + 8
        
        raw_text = self.txt_bits.toPlainText()
        doc_start, doc_end = self._bit_range_to_doc_positions(raw_text, bit_start, bit_end)
        if doc_start is None:
            return

        self.is_syncing = True
        cursor = self.txt_bits.textCursor()
        cursor.setPosition(doc_end)
        cursor.setPosition(doc_start, QTextCursor.MoveMode.KeepAnchor)
        
        self.txt_bits.blockSignals(True) 
        self.txt_bits.setTextCursor(cursor)
        self.txt_bits.setFocus()
        self.txt_bits.blockSignals(False)
        
        self.is_syncing = False
        self.update_bit_metrics()

    def reset_search_status(self):
        self.lbl_search_status.setText("Matches: --")
        self.lbl_search_status.setStyleSheet("font-size: 9pt; color: #757575;")

    def find_pattern(self):
        pattern = "".join(self.txt_search.text().split())
        if not pattern: return
        
        is_hex = self.rb_hex.isChecked()
        raw_text = self.txt_bits.toPlainText()
        bits = "".join(c for c in raw_text if not c.isspace())
        
        if is_hex:
            try:
                pattern = "".join(f"{int(char, 16):04b}" for char in pattern)
            except ValueError:
                QMessageBox.warning(self, "Error", "Invalid Hex Pattern")
                return

        matches = []
        search_pos = 0
        while True:
            m = bits.find(pattern, search_pos)
            if m == -1:
                break
            matches.append(m)
            search_pos = m + 1

        if not matches:
            self.lbl_search_status.setText("No matches found (0)")
            self.lbl_search_status.setStyleSheet("font-size: 9pt; color: #d32f2f; font-weight: bold;")
            return

        cursor = self.txt_bits.textCursor()
        doc_pos = max(cursor.position(), cursor.anchor()) if cursor.hasSelection() else cursor.position()
        curr_bit_pos = sum(1 for c in raw_text[:doc_pos] if not c.isspace())

        wrapped = False
        match_idx = next((i for i, m in enumerate(matches) if m >= curr_bit_pos), None)
        if match_idx is None:
            match_idx = 0
            wrapped = True

        idx = matches[match_idx]
        doc_start, doc_end = self._bit_range_to_doc_positions(raw_text, idx, idx + len(pattern))
        if doc_start is not None:
            cursor.setPosition(doc_end)
            cursor.setPosition(doc_start, QTextCursor.MoveMode.KeepAnchor)
            self.txt_bits.setTextCursor(cursor)
            self.txt_bits.setFocus()

        wrap_tag = " [Wrapped]" if wrapped else ""
        color = "#EF6C00" if wrapped else "#2E7D32"
        self.lbl_search_status.setText(
            f"Match {match_idx + 1} of {len(matches)} (Bit {idx}, Byte 0x{idx // 8:04X}){wrap_tag}"
        )
        self.lbl_search_status.setStyleSheet(f"font-size: 9pt; color: {color}; font-weight: bold;")

    def align_pattern(self):
        cursor = self.txt_bits.textCursor()
        if not cursor.hasSelection():
            self.find_pattern()
            cursor = self.txt_bits.textCursor()
            
        if cursor.hasSelection():
            start = cursor.selectionStart()
            if start > 0:
                full_text = self.txt_bits.toPlainText()
                new_text = full_text[start:]
                self.txt_bits.setPlainText(new_text)

    def export_data(self, fmt):
        if fmt == 'syms':
            if self.local_symbols is None or len(self.local_symbols) == 0:
                QMessageBox.warning(self, "Export Error", "No raw symbols loaded.")
                return
            fname, _ = QFileDialog.getSaveFileName(
                self, "Save Raw Symbols (.BIN)", "captured_symbols.bin", "Binary Files (*.bin);;All Files (*)"
            )
            if not fname: return
            try:
                syms = self.local_symbols
                if self.chk_invert_symbols.isChecked():
                    syms = enc.invert_symbols(syms, self.modulus)
                np.asarray(syms, dtype=np.uint8).tofile(fname)
                QMessageBox.information(self, "Saved", f"File saved to {fname}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
            return

        raw_text = self.txt_bits.toPlainText()
        data_text = "".join(c for c in raw_text if not c.isspace())
        fname, _ = QFileDialog.getSaveFileName(self, f"Save {fmt.upper()}", f"captured_packet.{fmt}")
        if not fname: return
        
        try:
            if fmt == 'txt':
                with open(fname, 'w') as f:
                    f.write(data_text)
            elif fmt == 'bin':
                sanitized = "".join(c if c in ('0', '1') else '0' for c in data_text)
                padding = (8 - len(sanitized) % 8) % 8
                bits_padded = sanitized + "0" * padding
                lsb_first = (self.cb_bit_order.currentText() == "LSB First")
                byte_array = bytearray()
                for i in range(0, len(bits_padded), 8):
                    chunk = bits_padded[i:i+8]
                    if lsb_first:
                        chunk = chunk[::-1]
                    byte_array.append(int(chunk, 2))
                with open(fname, 'wb') as f:
                    f.write(byte_array)
            QMessageBox.information(self, "Saved", f"File saved to {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
