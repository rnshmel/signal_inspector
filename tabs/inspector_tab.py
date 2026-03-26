import numpy as np
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QGroupBox, QPlainTextEdit, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QAbstractItemView, 
                             QRadioButton, QSplitter, QLineEdit, QFileDialog,
                             QMessageBox, QCheckBox, QComboBox, QSpinBox, QScrollArea,
                             QDialog, QDialogButtonBox)
from PyQt5.QtGui import QFont, QTextCursor, QColor, QSyntaxHighlighter, QTextCharFormat
from PyQt5.QtCore import Qt, QTimer

from core.base_tab import BaseSignalTab
import utils.encoding_lib as enc

class AbsoluteMapDialog(QDialog):
    # Popup window for defining Absolute Symbol Mapping.
    def __init__(self, modulus, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Absolute Mapping")
        self.setMinimumWidth(300)
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layout.addWidget(self.table)
        
        self.apply_preset('binary')
        
        self.bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bbox.accepted.connect(self.accept)
        self.bbox.rejected.connect(self.reject)
        self.layout.addWidget(self.bbox)

    def apply_preset(self, mode):
        mapping = enc.generate_mapping_dict(self.modulus, mode)
        for sym, bits in mapping.items():
            item_sym = QTableWidgetItem(str(sym))
            item_sym.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(sym, 0, item_sym)
            self.table.setItem(sym, 1, QTableWidgetItem(bits))

    def get_mapping(self):
        mapping = {}
        for row in range(self.modulus):
            sym = int(self.table.item(row, 0).text())
            bits = self.table.item(row, 1).text()
            mapping[sym] = bits
        return mapping

class DifferentialMapDialog(QDialog):
    # Popup window for defining 2-Level Differential Mapping.
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure 2-Level Diff Mapping")
        self.setMinimumWidth(350)
        self.layout = QVBoxLayout(self)
        
        self.table = QTableWidget(2, 2)
        self.table.setHorizontalHeaderLabels(["Transition", "Bit String"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layout.addWidget(self.table)

        self.table.setItem(0, 0, QTableWidgetItem("Same"))
        self.table.item(0, 0).setFlags(Qt.ItemIsEnabled)
        self.table.setItem(0, 1, QTableWidgetItem("0"))
        
        self.table.setItem(1, 0, QTableWidgetItem("Shift"))
        self.table.item(1, 0).setFlags(Qt.ItemIsEnabled)
        self.table.setItem(1, 1, QTableWidgetItem("1"))
        
        self.bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bbox.accepted.connect(self.accept)
        self.bbox.rejected.connect(self.reject)
        self.layout.addWidget(self.bbox)

    def get_mapping(self):
        return {
            0: self.table.item(0, 1).text(),
            1: self.table.item(1, 1).text()
        }

class ByteHighlighter(QSyntaxHighlighter):
    # Highlights every alternating byte (8 characters) in the text document.
    def __init__(self, document):
        super().__init__(document)
        self.highlight_format = QTextCharFormat()
        self.set_mode(False)

    def set_mode(self, is_light):
        if is_light:
            self.highlight_format.setBackground(QColor("#E0E0E0"))
        else:
            self.highlight_format.setBackground(QColor("#424242"))
        self.rehighlight()

    def highlightBlock(self, text):
        for i in range(8, len(text), 16):
            length = min(8, len(text) - i)
            self.setFormat(i, length, self.highlight_format)

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
        self.hex_timer.setInterval(500)
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
        self.splitter = QSplitter(Qt.Vertical)
        
        self.grp_bits = QGroupBox("Bit Stream (Editable Workbench)")
        self.grp_bits_layout = QVBoxLayout()
        self.grp_bits.setLayout(self.grp_bits_layout)
        
        self.txt_bits = QPlainTextEdit()
        self.txt_bits.setFont(QFont("Monospace", 10))
        self.txt_bits.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
        
        self.txt_bits.textChanged.connect(self.hex_timer.start)
        self.txt_bits.cursorPositionChanged.connect(self.sync_highlight_to_hex)
        self.grp_bits_layout.addWidget(self.txt_bits)
        
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
        self.table_hex.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_hex.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_hex.cellClicked.connect(self.sync_highlight_to_bits)
        
        self.table_hex.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_hex.horizontalHeader().setSectionResizeMode(17, QHeaderView.Stretch)
        
        self.grp_hex_layout.addWidget(self.table_hex)
        self.splitter.addWidget(self.grp_hex)
        
        # RIGHT: Controls
        self.sidebar = QGroupBox("Analysis Controls")
        self.sidebar.setMinimumWidth(250)
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
        
        self.btn_cfg_diff = QPushButton("Configure 2-Level Diff Map")
        self.btn_cfg_diff.clicked.connect(self.configure_differential_map)
        self.map_layout.addWidget(self.btn_cfg_diff)
        
        self.lbl_map_status = QLabel("Mode: Absolute (Binary Default)")
        self.lbl_map_status.setStyleSheet("font-weight: bold;")
        self.map_layout.addWidget(self.lbl_map_status)
        
        self.btn_send_workbench = QPushButton("Send to Bit Workbench")
        self.btn_send_workbench.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")
        self.btn_send_workbench.clicked.connect(self.send_to_workbench)
        self.map_layout.addWidget(self.btn_send_workbench)
        
        self.sidebar_layout.addWidget(self.grp_map)
        self.sidebar_layout.addSpacing(10)

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
        self.spin_font.setValue(10)
        self.spin_font.valueChanged.connect(self.update_view_settings)
        row_font.addWidget(self.spin_font)
        self.view_layout.addLayout(row_font)
        
        self.sidebar_layout.addWidget(self.grp_view)
        self.sidebar_layout.addSpacing(10)

        # Bit String Actions
        self.grp_logic = QGroupBox("2. Bit String Actions")
        self.logic_layout = QVBoxLayout()
        self.grp_logic.setLayout(self.logic_layout)
        
        self.btn_invert = QPushButton("Invert Bits (0 <--> 1)")
        self.btn_invert.clicked.connect(self.action_invert)
        self.logic_layout.addWidget(self.btn_invert)
        
        self.logic_layout.addSpacing(10)
        self.logic_layout.addWidget(QLabel("Line Encoding:"))
        self.cb_encoding = QComboBox()
        self.cb_encoding.addItems(["Manchester (IEEE)", "Manchester (Thomas)"])
        self.logic_layout.addWidget(self.cb_encoding)
        
        self.btn_decode_line = QPushButton("Apply Line Decoding")
        self.btn_decode_line.clicked.connect(self.action_line_decode)
        self.logic_layout.addWidget(self.btn_decode_line)
        
        self.sidebar_layout.addWidget(self.grp_logic)
        self.sidebar_layout.addSpacing(10)
        
        # Pattern Search
        self.grp_pattern = QGroupBox("Pattern Search & Align")
        self.pat_layout = QVBoxLayout()
        self.grp_pattern.setLayout(self.pat_layout)
        
        self.row_search_mode = QHBoxLayout()
        self.rb_bin = QRadioButton("Binary")
        self.rb_hex = QRadioButton("Hex")
        self.rb_hex.setChecked(True) 
        self.row_search_mode.addWidget(self.rb_bin)
        self.row_search_mode.addWidget(self.rb_hex)
        self.pat_layout.addLayout(self.row_search_mode)
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Enter Pattern...")
        self.pat_layout.addWidget(self.txt_search)
        
        row_pat = QHBoxLayout()
        self.btn_find = QPushButton("Find Next")
        self.btn_find.clicked.connect(self.find_pattern)
        self.btn_align = QPushButton("Align (Cut Prev)")
        self.btn_align.clicked.connect(self.align_pattern)
        row_pat.addWidget(self.btn_find)
        row_pat.addWidget(self.btn_align)
        self.pat_layout.addLayout(row_pat)
        
        self.sidebar_layout.addWidget(self.grp_pattern)
        self.sidebar_layout.addSpacing(10)
        
        # Export
        self.sidebar_layout.addWidget(QLabel("<b>Export:</b>"))
        self.btn_save_bin = QPushButton("Save .BIN (Raw Bytes)")
        self.btn_save_bin.clicked.connect(lambda: self.export_data('bin'))
        self.sidebar_layout.addWidget(self.btn_save_bin)
        
        self.btn_save_txt = QPushButton("Save .TXT (Bit String)")
        self.btn_save_txt.clicked.connect(lambda: self.export_data('txt'))
        self.sidebar_layout.addWidget(self.btn_save_txt)
        
        self.sidebar_layout.addStretch()

        main_h_layout.addWidget(self.splitter, stretch=5)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.sidebar)
        main_h_layout.addWidget(scroll_area, stretch=1)
    
    def load_input(self):
        if self.context.symbols is None:
            return False, "No symbols in context."
            
        self.local_symbols = self.context.symbols
        
        unique = np.unique(self.local_symbols)
        self.modulus = int(np.max(unique)) + 1 if len(unique) > 0 else 2
        
        self.active_mapping_mode = 'absolute'
        self.active_mapping_dict = enc.generate_mapping_dict(self.modulus, 'binary')
        
        self.lbl_sym_info.setText(f"Symbols: {len(self.local_symbols)} | Levels: {self.modulus}")
        self.lbl_map_status.setText("Mode: Absolute (Binary Preset)")
        self.send_to_workbench()
        
        return True, f"Loaded {len(self.local_symbols)} symbols."

    def stage_output(self):
        return True, "No next stage."

    def configure_absolute_map(self):
        dialog = AbsoluteMapDialog(self.modulus, self)
        if dialog.exec_() == QDialog.Accepted:
            self.active_mapping_dict = dialog.get_mapping()
            self.active_mapping_mode = 'absolute'
            self.lbl_map_status.setText("Mode: Absolute (Custom)")

    def configure_differential_map(self):
        dialog = DifferentialMapDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.active_mapping_dict = dialog.get_mapping()
            self.active_mapping_mode = 'differential'
            self.lbl_map_status.setText("Mode: Differential (Custom)")

    def send_to_workbench(self):
        if self.local_symbols is None:
            return
            
        if self.active_mapping_mode == 'absolute':
            bit_str = enc.map_symbols_to_bits(self.local_symbols, self.active_mapping_dict)
            
        elif self.active_mapping_mode == 'differential':
            diff_syms = enc.decode_differential(self.local_symbols, self.modulus)
            bit_str = enc.map_symbols_to_bits(diff_syms, self.active_mapping_dict)
            
        self.txt_bits.blockSignals(True)
        self.txt_bits.setPlainText(bit_str)
        self.txt_bits.blockSignals(False)
        self.update_hex_view()
        
        self.lbl_input_status.setVisible(True)
        self.lbl_input_status.setText("Workbench populated with mapped bits.")
        self.lbl_input_status.setStyleSheet("color: #1565C0;")

    def update_view_settings(self):
        size = self.spin_font.value()
        is_light = self.chk_light_mode.isChecked()
        
        font = QFont("Monospace", size)
        self.txt_bits.setFont(font)
        
        if is_light:
            self.txt_bits.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        else:
            self.txt_bits.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
            
        self.highlighter.set_mode(is_light)

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
        text = self.txt_bits.toPlainText()
        if not text: return
        
        enc_mode = self.cb_encoding.currentText()
        scheme = 'IEEE' if 'IEEE' in enc_mode else 'Thomas'
        
        decoded_text = enc.decode_manchester_string(text, scheme)
        self.txt_bits.setPlainText(decoded_text)

    def update_hex_view(self):
        if not hasattr(self, 'table_hex'): return

        bits = self.txt_bits.toPlainText().replace("\n", "").replace(" ", "")
        padding = (8 - len(bits) % 8) % 8
        bits_padded = bits + "0" * padding
        
        byte_data = []
        for i in range(0, len(bits_padded), 8):
            byte_str = bits_padded[i:i+8]
            try:
                byte_data.append(int(byte_str, 2))
            except:
                pass 
        
        self.table_hex.setUpdatesEnabled(False)
        self.table_hex.blockSignals(True)
        self.table_hex.clearContents()
        self.table_hex.setRowCount(0)
        self.table_hex.setRowCount((len(byte_data) + 15) // 16)
        
        for row in range(self.table_hex.rowCount()):
            offset_item = QTableWidgetItem(f"{row*16:08X}")
            offset_item.setBackground(QColor("#333333"))
            self.table_hex.setItem(row, 0, offset_item)
            
            ascii_str = ""
            for col in range(16):
                idx = row * 16 + col
                if idx < len(byte_data):
                    val = byte_data[idx]
                    self.table_hex.setItem(row, col + 1, QTableWidgetItem(f"{val:02X}"))
                    if 32 <= val <= 126: ascii_str += chr(val)
                    else: ascii_str += "."
                else:
                    self.table_hex.setItem(row, col + 1, QTableWidgetItem(""))
            
            self.table_hex.setItem(row, 17, QTableWidgetItem(ascii_str))
            
        self.table_hex.blockSignals(False)
        self.table_hex.setUpdatesEnabled(True)

    def sync_highlight_to_hex(self):
        if self.is_syncing: return
        self.is_syncing = True
        
        cursor = self.txt_bits.textCursor()
        pos = cursor.position()
        
        byte_idx = pos // 8
        row = byte_idx // 16
        col = (byte_idx % 16) + 1 
        
        if row < self.table_hex.rowCount():
            self.table_hex.blockSignals(True)
            self.table_hex.setCurrentCell(row, col)
            self.table_hex.blockSignals(False)
            
        self.is_syncing = False

    def sync_highlight_to_bits(self, row, col):
        if self.is_syncing: return
        if col < 1 or col > 16: return
        
        self.is_syncing = True
        
        byte_idx = (row * 16) + (col - 1)
        bit_start = byte_idx * 8
        bit_end = bit_start + 8
        
        cursor = self.txt_bits.textCursor()
        cursor.setPosition(bit_end)
        cursor.setPosition(bit_start, QTextCursor.KeepAnchor)
        
        self.txt_bits.blockSignals(True) 
        self.txt_bits.setTextCursor(cursor)
        self.txt_bits.setFocus()
        self.txt_bits.blockSignals(False)
        
        self.is_syncing = False

    def find_pattern(self):
        pattern = self.txt_search.text().replace(" ", "")
        if not pattern: return
        
        is_hex = self.rb_hex.isChecked()
        text = self.txt_bits.toPlainText()
        
        if is_hex:
            try:
                bin_pattern = ""
                for char in pattern:
                    val = int(char, 16)
                    bin_pattern += f"{val:04b}"
                pattern = bin_pattern
            except:
                QMessageBox.warning(self, "Error", "Invalid Hex Pattern")
                return

        cursor = self.txt_bits.textCursor()
        curr_pos = max(cursor.position(), cursor.anchor()) if cursor.hasSelection() else cursor.position()
        idx = text.find(pattern, curr_pos)
        
        if idx == -1: idx = text.find(pattern, 0)
            
        if idx != -1:
            cursor.setPosition(idx + len(pattern))
            cursor.setPosition(idx, QTextCursor.KeepAnchor)
            self.txt_bits.setTextCursor(cursor)
            self.txt_bits.setFocus()
        else:
            QMessageBox.information(self, "Search", "Pattern not found.")

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
        data_text = self.txt_bits.toPlainText().replace("\n", "")
        fname, _ = QFileDialog.getSaveFileName(self, f"Save {fmt.upper()}", f"captured_packet.{fmt}")
        if not fname: return
        
        try:
            if fmt == 'txt':
                with open(fname, 'w') as f:
                    f.write(data_text)
            elif fmt == 'bin':
                padding = (8 - len(data_text) % 8) % 8
                bits_padded = data_text + "0" * padding
                byte_array = bytearray()
                for i in range(0, len(bits_padded), 8):
                    byte_array.append(int(bits_padded[i:i+8], 2))
                with open(fname, 'wb') as f:
                    f.write(byte_array)
            QMessageBox.information(self, "Saved", f"File saved to {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
