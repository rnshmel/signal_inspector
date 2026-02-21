import sys
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget

# Import core context.
from core.context import SignalContext
# Import tabs.
from tabs.spectrogram_tab import SpectrogramTab
from tabs.tuner_tab import TunerTab
from tabs.demod_tab import DemodTab
from tabs.slicer_tab import SlicerTab
from tabs.inspector_tab import InspectorTab

# Configure pyqtgraph global options.
pg.setConfigOptions(imageAxisOrder='col-major')

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Basic Signal Inspector")
        self.resize(1200, 900)
        
        # Initialize the data backbone.
        self.context = SignalContext()
        
        # Setup UI.
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Load tabs.
        # We pass the shared context to every tab.
        self.spectrogram_tab = SpectrogramTab(self.context)
        self.tuner_tab = TunerTab(self.context)
        self.demod_tab = DemodTab(self.context)
        self.slicer_tab = SlicerTab(self.context)
        self.inspector_tab = InspectorTab(self.context)

        self.tabs.addTab(self.spectrogram_tab, self.spectrogram_tab.tab_title)
        self.tabs.addTab(self.tuner_tab, self.tuner_tab.tab_title)
        self.tabs.addTab(self.demod_tab, self.demod_tab.tab_title)
        self.tabs.addTab(self.slicer_tab, self.slicer_tab.tab_title)
        self.tabs.addTab(self.inspector_tab, self.inspector_tab.tab_title)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
