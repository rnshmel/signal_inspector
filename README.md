# Signal Inspector

**Version:** 1.1.0
 
A Digital Signals Processing (DSP) tool designed for inspecting and reverse-engineering basic signals via IQ recordings. Built with Python 3, PyQt5, NumPy, and SciPy.

Note: currently supports
- 2/4/8 FSK
- 2/4/8 ASK

**TODO**
- Add support for PSK.
- Add FEC and checksum analysis.
- Add additional encodings.
- Add additional symbol timing recovery options.

---

## Quick Start

This tool includes a launcher to handle Python virtual environments and dependencies automatically.

### Prerequisites
- Python 3.8+
- Linux / macOS / Windows (Ubuntu recommended)

### Running the Tool
1. **Clone the repository:**
   ```bash
   git clone https://www.github.com/rnshmel/signal_inspector.git
   cd signal-inspector
   ```

2. **Launch:**
   ```bash
   ./run.sh basic_signal_inspector
   ```
   *The script will automatically create a `.venv`, install dependencies from `requirements.txt`, and launch the application.*

---

## User Guide

### The Workflow: "Load, Process, Stage"
The Inspector operates as a linear pipeline. Data does not automatically flow between tabs. You must explicitly **Stage** output from one tab and **Load** it into the next.

### 1. Spectrogram View (Source)
The entry point for raw data. Only complex floating-point 32-bit data is supported.
- **Controls:** Open IQ recordings.
- **Memory Safety:** Uses `np.memmap` to handle multi-gigabyte files without crashing RAM.
- **Mosaic View:** If zoomed out on massive files, enables a "Mosaic" stride to visualize the entire file duration safely.
- **Action:** Click **"STAGE FILE"** to make the file handle available to the Tuner.

### 2. Tuner and Filter (Extraction)
Isolates a specific signal of interest from the wideband recording.
- **Input:** Raw IQ File Handle (from Tab 1).
- **Time Selection:** Vertical sliders select the time slice to process.
- **Frequency Selection:** Horizontal sliders select the carrier frequency and bandwidth.
- **DSP:** Mixes the selection to Baseband (0 Hz) and applies a low-pass filter.
- **Export:** (Optional) Save specific raw or filtered fragments to disk as `.cf32` for external tools.
- **Action:** Click **"Apply"** to preview, then **"STAGE OUTPUT"** to save the filtered samples to memory.

### 3. Demodulator (Analog)
Converts complex IQ samples into real-valued analog signals.
- **Input:** Filtered Baseband IQ (from Tab 2).
- **Modes:**
  - **Amplitude:** Magnitude detection (ASK).
  - **Frequency:** Phase differencing (FSK).
- **Slicer Preview:** Overlay threshold lines on the analog waveform to visualize how bits will be decided.
- **Action:** Click **"STAGE OUTPUT"** to commit the analog demodulation and threshold settings.

### 4. Symbol Timing Recovery (Digital)
Converts analog signals into discrete symbols (0, 1, 2, 3, etc) via user-aided symbol recovery.
- **Input:** Demodulated Analog Signal + Thresholds (from Tab 3).
- **Manual Clocking:** Drag the "Clock Region" box to align red tick marks with the edges of your symbols.
- **Auto-Sync (Beta):** After manually aligning 4+ symbols, the tool can algorithmically estimate the clock for the rest of the burst.
- **Action:** Click **"STAGE OUTPUT"** to extract the discrete symbols.

### 5. Data Inspector (Analysis)
Basic reverse engineering.
- **Input:** Symbol Stream (from Tab 4).
- **Decoding Pipeline:**
  1. **Line Logic:** Invert symbols (Active Low) or apply Differential Decoding (NRZ-I / Modulo subtraction).
  2. **Symbol Mapping:** Map discrete integers (0, 1, 2, 3) to bit patterns (e.g., `3 -> 10`, `0 -> 00`).
  3. **Line Coding:** Decode Manchester (IEEE or Thomas).
- **Analysis:** View bits as binary stream or Hex dump. Highlight hex bytes to see corresponding bits. Search for preambles/sync words.

---

## Developer Guide

### Architecture
The project follows a modular pattern where:
- **Core (`core/`):** The `SignalContext` and `BaseSignalTab` templates.
- **Tabs (`tabs/`):** The individual processing modules.
- **Utils (`utils/`):** All pure DSP math functions (SciPy/NumPy).

### The Data Backbone: `SignalContext`
Data is passed between tabs via a shared singleton-like object called `SignalContext`. Data is categorized by "Generations":

| Generation | Data Type | Source | Description |
| :--- | :--- | :--- | :--- |
| **Gen 0** | `raw_iq_handle` | Tab 1 | `np.memmap` reference to the disk file. Read-only. |
| **Gen 1** | `filtered_signal` | Tab 2 | `complex64` array. Baseband, filtered slice. |
| **Gen 2** | `demod_signal` | Tab 3 | `float32` array. Magnitude or Freq Deviation. |
| **Gen 3** | `symbols` | Tab 4 | `int8` array. Discrete symbol indices. |
| **Gen 4** | *N/A* | Tab 5 | Final bits/packets (Analysis only). |

### Adding a New Tab
To add a new module (e.g., "OFDM Demodulator"):

1. **Create the File:** Create `tabs/ofdm_tab.py`.
2. **Inherit:** Subclass `core.base_tab.BaseSignalTab`.
3. **Implement Input:** Override `load_input(self)`.
   ```python
   def load_input(self):
       # Example: Grab Gen 1 (Filtered IQ)
       if self.context.filtered_signal is None: return False, "No Data"
       self.local_data = self.context.filtered_signal.copy() # Always copy!
       return True, f"Loaded {len(self.local_data)} samples"
   ```
4. **Implement Output:** Override `stage_output(self)`.
   ```python
   def stage_output(self):
       # Perform DSP...
       # Write to Context
       self.context.demod_signal = my_ofdm_result
       return True, "Staged OFDM symbols"
   ```
5. **Register:** Add the tab to `apps/basic_signal_inspector.py`.

### DSP Utilities
All heavy mathematical lifting resides in `utils/dsp_lib.py`. This ensures consistency across tabs and allows for easier unit testing.

### Deployment
Use `run.sh` for all execution. It handles:
1.  Locating the project root (independent of CWD).
2.  Creating/Activating the `.venv`.
3.  Installing pinned dependencies from `requirements.txt`.
4.  Setting `PYTHONPATH` so the `apps/` directory can import `core/`.

To create a new application configuration, place it in `apps/` and run `./run.sh my_new_app.py`.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

**Author:** **Richard N Shmel** | Electrical Engineer
* [RNS Tech Solutions LLC](https://www.rnstechsolutions.com/)
* [LinkedIn](https://www.linkedin.com/in/richard-shmel)
* [GitHub](https://github.com/rnshmel)