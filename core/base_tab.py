from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QMessageBox)
from PyQt5.QtCore import Qt

class BaseSignalTab(QWidget):
    # Parent class for all signal inspector tabs.
    # Enforces the [load input --> process --> stage output] workflow.
    def __init__(self, context, title):
        super().__init__()
        self.context = context
        self.tab_title = title
        
        # Main layout for the widget.
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(5, 5, 5, 5)
        self._main_layout.setSpacing(5)

        # The command bar standard header.
        self.header_frame = QFrame()
        self.header_frame.setFrameShape(QFrame.StyledPanel)
        self.header_frame.setStyleSheet("background-color: #f0f0f0; border-radius: 4px;")
        self.header_layout = QHBoxLayout(self.header_frame)
        self.header_layout.setContentsMargins(10, 5, 10, 5)

        # Input zone controls.
        self.btn_load = QPushButton("⬇ LOAD INPUT")
        self.btn_load.setStyleSheet("""
            QPushButton {
                background-color: #c8e6c9; 
                border: 1px solid #81c784; 
                border-radius: 4px; 
                padding: 6px 15px; 
                font-weight: bold; 
                color: #1b5e20;
            }
            QPushButton:hover {
                background-color: #a5d6a7;
            }
            QPushButton:pressed {
                background-color: #81c784;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                border: 1px solid #bdbdbd;
                color: #9e9e9e;
            }
        """)
        self.btn_load.clicked.connect(self._handle_load)
        self.lbl_input_status = QLabel("Waiting...")
        self.lbl_input_status.setStyleSheet("color: #666; font-style: italic;")

        # Output zone controls.
        self.btn_stage = QPushButton("STAGE OUTPUT ➡")
        self.btn_stage.setStyleSheet("""
            QPushButton {
                background-color: #bbdefb; 
                border: 1px solid #64b5f6; 
                border-radius: 4px; 
                padding: 6px 15px; 
                font-weight: bold; 
                color: #0d47a1;
            }
            QPushButton:hover {
                background-color: #90caf9;
            }
            QPushButton:pressed {
                background-color: #64b5f6;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                border: 1px solid #bdbdbd;
                color: #9e9e9e;
            }
        """)
        self.btn_stage.clicked.connect(self._handle_stage)
        self.lbl_output_status = QLabel("Not Staged")
        self.lbl_output_status.setStyleSheet("color: #666; font-style: italic;")

        # Add widgets to the header.
        self.header_layout.addWidget(self.btn_load)
        self.header_layout.addWidget(self.lbl_input_status)
        self.header_layout.addStretch()
        self.header_layout.addWidget(QLabel(f"<b>{title}</b>"))
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.lbl_output_status)
        self.header_layout.addWidget(self.btn_stage)

        self._main_layout.addWidget(self.header_frame)

        # The content area where child classes fill UI.
        self.content_widget = QWidget()
        self.layout = QVBoxLayout(self.content_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.addWidget(self.content_widget)

    def _handle_load(self):
        # Wrapper to handle errors during loading.
        try:
            success, msg = self.load_input()
            if success:
                # Enable staging only if load succeeded.
                self.lbl_input_status.setText(f"Loaded: {msg}")
                self.lbl_input_status.setStyleSheet("color: #2E7D32; font-weight: bold;")
                self.btn_stage.setEnabled(True)
            else:
                self.lbl_input_status.setText(f"Error: {msg}")
                self.lbl_input_status.setStyleSheet("color: #d32f2f;")
        except Exception as e:
            print(f"Error loading tab {self.tab_title}: {e}")
            QMessageBox.critical(self, "Load Error", str(e))

    def _handle_stage(self):
        # Wrapper to handle errors during staging.
        try:
            success, msg = self.stage_output()
            if success:
                self.lbl_output_status.setText(f"Staged: {msg}")
                self.lbl_output_status.setStyleSheet("color: #1565C0; font-weight: bold;")
            else:
                self.lbl_output_status.setText(f"Error: {msg}")
                self.lbl_output_status.setStyleSheet("color: #d32f2f;")
        except Exception as e:
            print(f"Error staging tab {self.tab_title}: {e}")
            QMessageBox.critical(self, "Stage Error", str(e))

    # Virtual methods that tabs must override.
    def load_input(self):
        # Pull data from self.context. 
        # Returns success boolean and status message string.
        return False, "Not Implemented"

    def stage_output(self):
        # Push local data to self.context.
        # Returns success boolean and status message string.
        return False, "Not Implemented"
