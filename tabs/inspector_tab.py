import numpy as np
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QGroupBox, QPlainTextEdit, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QAbstractItemView, 
                             QRadioButton, QSplitter, QLineEdit, QFileDialog,
                             QMessageBox, QCheckBox, QComboBox, QSpinBox, QScrollArea)
from PyQt5.QtGui import QFont, QTextCursor, QColor, QSyntaxHighlighter, QTextCharFormat
from PyQt5.QtCore import Qt, QTimer

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
        self.stashed_bits = "" # Holds our in-memory saved state
        
        # 500 ms delay before rebuilding hex view
        self.hex_timer = QTimer()
        self.hex_timer.setSingleShot(True)
        self.hex_timer.setInterval(500)
        self.hex_timer.timeout.connect(self.update_hex_view)
        
        self.init_ui()

    def init_ui(self):
        # Add custom header buttons for quick save/load (stash/restore)
        self.btn_stash = QPushButton("💾 Save State")
        self.btn_stash.setToolTip("Saves the current bit string for a quick reset.")
        self.btn_stash.setStyleSheet("font-weight: bold; background-color: #fff3e0;")
        self.btn_stash.clicked.connect(self.stash_state)
        
        self.btn_restore = QPushButton("📂 Load State")
        self.btn_restore.setToolTip("Restores the previously saved bit string.")
        self.btn_restore.setStyleSheet("font-weight: bold; background-color: #e3f2fd;")
        self.btn_restore.clicked.connect(self.restore_state)
        self.btn_restore.setEnabled(False)

        # Insert them into the header_layout inherited from BaseSignalTab
        # Index 1 and 2 puts them directly to the right of the "Load Input" button
        self.header_layout.insertWidget(1, self.btn_stash)
        self.header_layout.insertWidget(2, self.btn_restore)

        main_h_layout = QHBoxLayout()
        self.layout.addLayout(main_h_layout)
        
        # LEFT: Split View (Vertical Splitter for editor/hex)
        self.splitter = QSplitter(Qt.Vertical)
        
        # Bit Editor.
        self.grp_bits = QGroupBox("Bit Stream (Editable Workbench)")
        self.grp_bits_layout = QVBoxLayout()
        self.grp_bits.setLayout(self.grp_bits_layout)
        
        self.txt_bits = QPlainTextEdit()
        self.txt_bits.setFont(QFont("Monospace", 10))
        self.txt_bits.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
        
        # Point the textChanged signal to the timer instead of update_hex_view directly
        self.txt_bits.textChanged.connect(self.hex_timer.start)
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
        self.sidebar.setMinimumWidth(250)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar.setLayout(self.sidebar_layout)
        
        # Symbol Mapping
        self.sidebar_layout.addWidget(QLabel("<b>1. Map Symbols to Buffer:</b>"))
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

        # Line Coding and Logic
        self.grp_logic = QGroupBox("2. Bit String Actions")
        self.logic_layout = QVBoxLayout()
        self.grp_logic.setLayout(self.logic_layout)
        
        self.btn_invert = QPushButton("Invert Bits (0 ↔ 1)")
        self.btn_invert.clicked.connect(self.action_invert)
        self.logic_layout.addWidget(self.btn_invert)
        
        self.btn_diff = QPushButton("Differential Decode (NRZ-I)")
        self.btn_diff.setToolTip("Decodes assuming state change = 1, no change = 0")
        self.btn_diff.clicked.connect(self.action_diff_decode)
        self.logic_layout.addWidget(self.btn_diff)
        
        self.logic_layout.addSpacing(10)
        self.logic_layout.addWidget(QLabel("Line Encoding:"))
        self.cb_encoding = QComboBox()
        self.cb_encoding.addItems(["Manchester (IEEE 802.3)", "Manchester (G.E. Thomas)"])
        self.logic_layout.addWidget(self.cb_encoding)
        
        self.btn_decode_line = QPushButton("Apply Decoding")
        self.btn_decode_line.clicked.connect(self.action_line_decode)
        self.logic_layout.addWidget(self.btn_decode_line)
        
        self.sidebar_layout.addWidget(self.grp_logic)
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

        # Add Layout Components
        main_h_layout.addWidget(self.splitter, stretch=5)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.sidebar)
        main_h_layout.addWidget(scroll_area, stretch=1)
    
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
        # Reads the raw integer symbols, translates them using the map table,
        # and dumps them into the text box buffer. This is a destructive load.
        if self.local_symbols is None: return
        
        mapping = {}
        rows = self.table_map.rowCount()
        
        # Build mapping dictionary.
        for i in range(rows):
            item = self.table_map.item(i, 1)
            bit_str = item.text() if item else ""
            mapping[i] = bit_str
            
        # Initialize output array of object type (strings).
        full_text_arr = np.empty(len(self.local_symbols), dtype=object)
        
        for sym, bit_str in mapping.items():
            mask = (self.local_symbols == sym)
            full_text_arr[mask] = bit_str
            
        # Join into one massive string and dump to the sandbox
        full_text = "".join(full_text_arr)
        
        self.txt_bits.blockSignals(True)
        self.txt_bits.setPlainText(full_text)
        self.txt_bits.blockSignals(False)
        
        # Bypassing the timer for the initial load
        self.update_hex_view()

    def stash_state(self):
        self.stashed_bits = self.txt_bits.toPlainText()
        self.btn_restore.setEnabled(True)
        # Give visual feedback using the existing status label from the base tab
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
        
        # Fast string translation to flip 0s and 1s
        trans = str.maketrans('01', '10')
        new_text = text.translate(trans)
        
        self.txt_bits.setPlainText(new_text)

    def action_diff_decode(self):
        text = self.txt_bits.toPlainText()
        if not text: return
        
        # NRZ-I Decoding: Change = 1, No Change = 0
        # Assume an implicit initial reference state of '0' for the first bit
        out = []
        prev = '0'
        for char in text:
            if char not in ('0', '1'):
                out.append(char) # Preserve whitespace or line breaks if manually added
                continue
                
            if char == prev:
                out.append('0')
            else:
                out.append('1')
            prev = char
            
        self.txt_bits.setPlainText("".join(out))

    def action_line_decode(self):
        text = self.txt_bits.toPlainText()
        if not text: return
        
        enc_mode = self.cb_encoding.currentText()
        scheme = 'IEEE' if 'IEEE' in enc_mode else 'Thomas'
        
        # Hand off to DSP lib to parse the pairs
        decoded_text = dsp.decode_manchester_string(text, scheme)
        self.txt_bits.setPlainText(decoded_text)

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
