import numpy as np

# Tracks the signal as it moves through the processing pipeline.
class SignalContext:

    def __init__(self):
        # Raw input for the first tab.
        self.raw_iq_handle = None
        self.raw_iq_path = ""
        self.raw_sr = 1.0
        self.file_duration = 0.0
        
        # Selected region from the spectrogram tab.
        self.selection_hint = (0.0, 1.0)

        # We pass these so downstream tabs look consistent with spectrogram.
        self.viz_fft_size = 1024
        self.viz_overlap = 0
        self.viz_levels = (-120, 0) # min_db, max_db
        self.viz_lut = None # The color gradient lookup table
        self.viz_trace_color = '#FFA500'

        # Filtered and tuned data.
        self.filtered_signal = None
        self.filtered_sr = 1.0
        self.filter_center_freq = 0.0

        # Demodulated data.
        self.demod_signal = None 
        self.demod_sr = 1.0
        self.demod_mode = "Unknown"

        # Sliced symbols.
        self.symbols = None
        self.symbol_rate = 1.0
        self.thresholds = []

        # Extracted packet data.
        self.extracted_packets = []

    # Resets the context to empty state.
    def clear(self):
        self.__init__()
