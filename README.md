# Signal Inspector

**Version:** 2.0.0
 
A Digital Signals Processing (DSP) tool designed for inspecting and reverse-engineering basic signals via IQ recordings. Built with Python 3, PyQt6, PyQtGraph, NumPy, and SciPy.

Note: currently supports
- 2/4/8 Level FSK
- 2/4/8 Level ASK
- 2 Level PSK

**TODO**
- Add support for 4/8 PSK.
- Add FEC and checksum analysis.
- Add additional encodings.

---

## Quick Start

This repository separates environment provisioning (`setup.sh`) from application execution (`run.sh`).

### Prerequisites
- Python 3.10+
- Linux / macOS / Windows (Ubuntu / Xubuntu 22.04+ recommended)
- On Debian/Ubuntu/Xubuntu Linux systems, `python3-venv` and Qt6 XCB/OpenGL runtime libraries (such as `libxcb-cursor0`) are required. `./setup.sh` checks for missing system packages and prints the exact `apt install` command if needed.

### Setup and Running the Tool
1. **Clone the repository:**
   ```bash
   git clone https://www.github.com/rnshmel/signal_inspector.git
   cd signal_inspector
   ```

2. **Set up the environment:**
   ```bash
   ./setup.sh -e
   ```
   *`setup.sh` verifies Python 3.10+ and Qt6 system dependencies, creates `.venv`, and installs packages from `requirements.txt`.*

   Common `setup.sh` options:
   - `-e`, `--examples`: Create `example_signals/` and generate sample `.cf32` IQ recordings (2-FSK, OOK, BPSK, 4-FSK).
   - `-c`, `--clean`: Remove any existing `.venv` and `example_signals/` before doing a clean install.
   - `-h`, `--help`: Show usage and all available options.

3. **Launch:**
   ```bash
   ./run.sh basic_signal_inspector
   ```
   *`run.sh` activates `.venv`, sets `PYTHONPATH`, and launches the requested script from `apps/` (the `.py` extension is optional). Run `./run.sh --help` to list available apps.*

---

## User Guide

### The Workflow: "Load, Process, Stage"
The Inspector operates as a linear pipeline. Data does not automatically flow between tabs. You must explicitly **Stage** output from one tab and **Load** it into the next.

### 1. Spectrogram View (Source)
The entry point for raw IQ data. Supports `cf32` (Complex Float 32), `cs16` (Complex Int 16), `cs8` (Complex Int 8), and `cu8` (Complex Unsigned 8) recordings.
- **Controls:** Open IQ recordings and pan/zoom across a debounced waterfall with a full-duration minimap.
- **Mosaic View:** If zoomed out on massive files beyond the configured RAM limit, you can enable a "Mosaic" stride to visualize the entire file duration without taxing RAM.

### 2. Tuner and Filter (Extraction)
Isolates a specific signal of interest from the wideband recording.
- **Input:** Raw IQ File Handle (from Tab 1).
- **Time Selection:** Vertical sliders select the time slice to process.
- **Frequency Selection:** Horizontal sliders select the offset frequency and bandwidth.
- **DSP:** Mixes the selection to Baseband (0 Hz) and applies a low-pass filter.
- **Export:** (Optional) Save specific raw or filtered fragments to disk as `.cf32` for external tools.

### 3. Demodulator (Analog)
Converts complex IQ samples into real-valued analog signals.
- **Input:** Filtered Baseband IQ (from Tab 2).
- **Modes:**
  - **Amplitude (ASK):** Magnitude detection.
  - **Frequency (FSK):** Phase differencing.
  - **Phase (PSK):** Delayed-conjugate differential phase detection.
- **Matched Filtering (Optional):** Apply Moving Average, Gaussian, or Root-Raised Cosine (RRC) filtering sized interactively with the on-plot box.
- **Slicer Preview:** Overlay threshold lines on the analog waveform to visualize how discrete symbol levels will be decided.

### 4. Symbol Timing Recovery (Digital)
Converts analog signals into discrete symbols (0, 1, 2, 3, etc) via user-aided symbol recovery.
- **Input:** Demodulated Analog Signal + Thresholds (from Tab 3).
- **Manual Clocking:** Drag the "Clock Region" box to align with the edges of your symbols.
- **Auto-Sync (Beta):** After manually aligning 4+ symbols, the tool can algorithmically estimate the clock for the rest of the burst.

### 5. Data Inspector (Analysis)
Basic reverse engineering.
- **Input:** Symbol Stream (from Tab 4).
- **Decoding Pipeline:**
  1. **Symbol Polarity:** Optionally invert discrete symbol levels (`(M-1) - s`).
  2. **Symbol Mapping:** Configure $M$-level **Absolute** or **Differential** mappings (with Binary/Gray presets) to turn symbols into bit patterns (e.g., `3 -> 10`, `0 -> 00`).
  3. **Bit String Actions:** Invert bits (`0 <-> 1`) or decode Manchester line coding (IEEE or Thomas).
- **Analysis:** View bits in an editable workbench with alternating byte highlighting, live bit/byte/cursor metrics, and a synchronized Hex/ASCII viewer supporting `MSB First` / `LSB First` byte bit order. Search for hex or binary preambles/sync words with live match counting and wrap indicators, and align streams to a match.
- **Export:** Save packed raw bytes (`.BIN`), ASCII bit strings (`.TXT`), or raw `uint8` discrete symbols (`.BIN`).

---

## Developer Guide

### Architecture
The project follows a modular pattern where:
- **Core (`core/`):** The `SignalContext` and `BaseSignalTab` templates.
- **Tabs (`tabs/`):** The individual processing modules.
- **Utils (`utils/`):** All pure DSP math functions (SciPy/NumPy).

### The Data Backbone: `SignalContext`
Data is passed between tabs via a shared object called `SignalContext`. Data is categorized by "Generations":

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
Environment setup and execution are split across two scripts:

- **`./setup.sh`**: Handles initial provisioning. It locates the project root, checks for Python 3.10+ and required Linux Qt6 system libraries, creates `.venv`, installs dependencies from `requirements.txt`, and optionally generates `example_signals/` (`-e`).
- **`./run.sh`**: Handles execution. It verifies `.venv` exists, activates it, sets `PYTHONPATH` so `apps/` can import `core/` and `utils/`, and launches the specified app in `apps/`.

To create a new application configuration, place it in `apps/` and run `./run.sh my_new_app.py`.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

**Author:** **Richard N Shmel** | Electrical Engineer
* [RNS Tech Solutions LLC](https://www.rnstechsolutions.com/)
* [LinkedIn](https://www.linkedin.com/in/richard-shmel)
* [GitHub](https://github.com/rnshmel)
