import numpy as np
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QGroupBox, QPlainTextEdit, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QAbstractItemView, 
                             QRadioButton, QSplitter, QLineEdit, QFileDialog,
                             QMessageBox, QCheckBox, QComboBox, QSpinBox)
from PyQt5.QtGui import QFont, QTextCursor, QColor, QSyntaxHighlighter, QTextCharFormat
from PyQt5.QtCore import Qt

from core.base_tab import BaseSignalTab
import utils.dsp_lib as dsp

class ByteHighlighter(QSyntaxHighlighter):
    # Highlights every alternating byte (8 characters) in the text document.
    def __init__(self, document):
        super().__init__(document)
        self.highlight_format = QTextCharFormat()
        self.set_mode(False)

    def set_mode(self, is_light):
        if is_light:
            # Light Mode
            self.highlight_format.setBackground(QColor("#E0E0E0"))
        else:
            # Dark Mode
            self.highlight_format.setBackground(QColor("#424242"))
        
        self.rehighlight()

    def highlightBlock(self, text):
        # Pattern: [Normal 8] [Highlight 8] [Normal 8] [Highlight 8]
        for i in range(8, len(text), 16):
            length = min(8, len(text) - i)
            self.setFormat(i, length, self.highlight_format)

class InspectorTab(BaseSignalTab):
    def __init__(self, context):
        super().__init__(context, "Inspector")
        
        self.btn_stage.setVisible(False)
        self.lbl_output_status.setVisible(False)
        
        self.local_symbols = None
        self.is_syncing = False
        
        self.init_ui()

    def init_ui(self):
        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)
        
        # LEFT: Split View
        self.splitter = QSplitter(Qt.Vertical)
        main_h_layout.addWidget(self.splitter, stretch=1)
        
        # Bit Editor.
        self.grp_bits = QGroupBox("Bit Stream (Editable)")
        self.grp_bits_layout = QVBoxLayout()
        self.grp_bits.setLayout(self.grp_bits_layout)
        
        self.txt_bits = QPlainTextEdit()
        self.txt_bits.setFont(QFont("Monospace", 10))
        self.txt_bits.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
        self.txt_bits.textChanged.connect(self.update_hex_view)
        self.txt_bits.cursorPositionChanged.connect(self.sync_highlight_to_hex)
        self.grp_bits_layout.addWidget(self.txt_bits)
        
        # Attach the Byte Highlighter
        self.highlighter = ByteHighlighter(self.txt_bits.document())
        self.splitter.addWidget(self.grp_bits)
        
        # Hex View.
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
        self.sidebar.setFixedWidth(300)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        main_h_layout.addWidget(self.sidebar, stretch=0)
        
        # View Settings
        self.grp_view = QGroupBox("View Settings")
        self.view_layout = QVBoxLayout()
        self.grp_view.setLayout(self.view_layout)
        
        # Light Mode
        self.chk_light_mode = QCheckBox("Light Mode")
        self.chk_light_mode.stateChanged.connect(self.update_view_settings)
        self.view_layout.addWidget(self.chk_light_mode)
        
        # Font Size
        row_font = QHBoxLayout()
        row_font.addWidget(QLabel("Font Size:"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 72)
        self.spin_font.setValue(10)
        self.spin_font.valueChanged.connect(self.update_view_settings)
        row_font.addWidget(self.spin_font)
        self.view_layout.addLayout(row_font)
        
        self.sidebar_layout.addWidget(self.grp_view)
        self.sidebar_layout.addSpacing(15)

        # Line Coding & Logic
        self.grp_logic = QGroupBox("1. Line Coding & Logic")
        self.logic_layout = QVBoxLayout()
        self.grp_logic.setLayout(self.logic_layout)
        
        # Symbol Operations
        self.chk_invert = QCheckBox("Invert Symbols (Active Low)")
        self.chk_invert.stateChanged.connect(self.apply_mapping)
        self.logic_layout.addWidget(self.chk_invert)
        
        self.chk_diff = QCheckBox("Differential (NRZ-I)")
        self.chk_diff.setToolTip("Interprets change as 1, no-change as 0 (for Binary).")
        self.chk_diff.stateChanged.connect(self.apply_mapping)
        self.logic_layout.addWidget(self.chk_diff)
        
        # Bit Operations
        self.logic_layout.addWidget(QLabel("Line Encoding:"))
        self.cb_encoding = QComboBox()
        self.cb_encoding.addItems(["None (NRZ-L)", "Manchester (IEEE 802.3)", "Manchester (G.E. Thomas)"])
        self.cb_encoding.currentTextChanged.connect(self.apply_mapping)
        self.logic_layout.addWidget(self.cb_encoding)
        
        self.sidebar_layout.addWidget(self.grp_logic)
        self.sidebar_layout.addSpacing(15)

        # Symbol Mapping.
        self.sidebar_layout.addWidget(QLabel("<b>2. Symbol Mapping:</b>"))
        self.table_map = QTableWidget()
        self.table_map.setColumnCount(2)
        self.table_map.setHorizontalHeaderLabels(["Sym", "Bits"])
        self.table_map.verticalHeader().setVisible(False)
        self.table_map.setFixedHeight(150)
        self.sidebar_layout.addWidget(self.table_map)
        
        row_map_btns = QHBoxLayout()
        self.btn_map_bin = QPushButton("Binary")
        self.btn_map_bin.clicked.connect(lambda: self.set_mapping_preset('binary'))
        self.btn_map_gray = QPushButton("Gray Code")
        self.btn_map_gray.clicked.connect(lambda: self.set_mapping_preset('gray'))
        self.btn_apply_map = QPushButton("Apply Map")
        self.btn_apply_map.setStyleSheet("font-weight: bold;")
        self.btn_apply_map.clicked.connect(self.apply_mapping)
        
        row_map_btns.addWidget(self.btn_map_bin)
        row_map_btns.addWidget(self.btn_map_gray)
        row_map_btns.addWidget(self.btn_apply_map)
        self.sidebar_layout.addLayout(row_map_btns)
        self.sidebar_layout.addSpacing(15)
        
        # Pattern search and clip
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
        self.sidebar_layout.addSpacing(15)
        
        # Export out as file
        self.sidebar_layout.addWidget(QLabel("<b>Export:</b>"))
        self.btn_save_bin = QPushButton("Save .BIN (Raw Bytes)")
        self.btn_save_bin.clicked.connect(lambda: self.export_data('bin'))
        self.sidebar_layout.addWidget(self.btn_save_bin)
        
        self.btn_save_txt = QPushButton("Save .TXT (Bit String)")
        self.btn_save_txt.clicked.connect(lambda: self.export_data('txt'))
        self.sidebar_layout.addWidget(self.btn_save_txt)
        
        self.sidebar_layout.addStretch()
    
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

    def load_input(self):
        if self.context.symbols is None:
            return False, "No symbols in context."
            
        self.local_symbols = self.context.symbols
        
        # Setup mapping table based on symbol range.
        unique = np.unique(self.local_symbols)
        max_sym = int(np.max(unique)) if len(unique) > 0 else 1
        
        self.table_map.setRowCount(max_sym + 1)
        for i in range(max_sym + 1):
            item_sym = QTableWidgetItem(str(i))
            item_sym.setFlags(Qt.ItemIsEnabled) 
            self.table_map.setItem(i, 0, item_sym)
            
            # Default mapping logic if empty.
            if self.table_map.item(i, 1) is None:
                bits_per_sym = int(np.ceil(np.log2(max_sym + 1)))
                fmt = f"{{0:0{bits_per_sym}b}}"
                default_bits = fmt.format(i)
                self.table_map.setItem(i, 1, QTableWidgetItem(default_bits))
        
        self.apply_mapping()
        return True, f"Loaded {len(self.local_symbols)} symbols."

    def stage_output(self):
        return True, "No next stage."

    def set_mapping_preset(self, mode):
        rows = self.table_map.rowCount()
        bits_per_sym = int(np.ceil(np.log2(rows)))
        
        for i in range(rows):
            if mode == 'binary':
                val = i
            elif mode == 'gray':
                val = i ^ (i >> 1)
            
            fmt = f"{{0:0{bits_per_sym}b}}"
            self.table_map.setItem(i, 1, QTableWidgetItem(fmt.format(val)))
        
        self.apply_mapping()

    def apply_mapping(self):
        # Convert symbol stream to bit string using mapping.
        if self.local_symbols is None: return
        
        processed_symbols = np.copy(self.local_symbols)
        modulus = self.table_map.rowCount() # Number of symbol levels
        
        # Differential
        if self.chk_diff.isChecked():
            processed_symbols = dsp.decode_differential(processed_symbols, modulus)
            
        # Invert
        if self.chk_invert.isChecked():
            processed_symbols = dsp.invert_symbols(processed_symbols, modulus)
        
        mapping = {}
        rows = self.table_map.rowCount()
        
        # Build mapping dictionary.
        for i in range(rows):
            item = self.table_map.item(i, 1)
            bit_str = item.text() if item else ""
            mapping[i] = bit_str
            
        # Initialize output array of object type (strings).
        full_text_arr = np.empty(len(processed_symbols), dtype=object)
        
        for sym, bit_str in mapping.items():
            mask = (processed_symbols == sym)
            full_text_arr[mask] = bit_str
            
        # Join into one massive string.
        full_text = "".join(full_text_arr)
        
        # Line codes.
        enc_mode = self.cb_encoding.currentText()
        if "Manchester" in enc_mode:
            scheme = 'IEEE' if 'IEEE' in enc_mode else 'Thomas'
            full_text = dsp.decode_manchester_string(full_text, scheme)
        
        self.txt_bits.blockSignals(True)
        self.txt_bits.setPlainText(full_text)
        self.txt_bits.blockSignals(False)
        
        self.update_hex_view()

    def update_hex_view(self):
        if not hasattr(self, 'table_hex'):
            return

        bits = self.txt_bits.toPlainText().replace("\n", "").replace(" ", "")
        padding = (8 - len(bits) % 8) % 8
        bits_padded = bits + "0" * padding
        
        # Convert bit string to byte array.
        byte_data = []
        for i in range(0, len(bits_padded), 8):
            byte_str = bits_padded[i:i+8]
            try:
                byte_data.append(int(byte_str, 2))
            except:
                pass 
        
        self.table_hex.blockSignals(True)
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
        
        if cursor.hasSelection():
            curr_pos = max(cursor.position(), cursor.anchor())
        else:
            curr_pos = cursor.position()
            
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
