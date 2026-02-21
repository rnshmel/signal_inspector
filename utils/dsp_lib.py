import numpy as np
import scipy.signal

def compute_spectrogram(data, sr, fft_size=1024, overlap=0):
    # Computes a magnitude spectrogram in dB.
    # Returns (Sxx_db, extent).

    # Calculate the spectrogram using scipy.
    # Explicitly set return_onesided=False to suppress complex input warnings.
    f, t, Sxx = scipy.signal.spectrogram(data, fs=sr, 
                                         nperseg=fft_size, noverlap=overlap, 
                                         detrend=False, mode='magnitude',
                                         return_onesided=False)
    
    # Shift zero frequency to the center.
    Sxx = np.fft.fftshift(Sxx, axes=0)
    
    # Convert to log scale (dB).
    # Add a tiny epsilon to prevent log(0).
    Sxx_db = 20 * np.log10(Sxx + 1e-9)
    
    # Calculate image extent for plotting [min_t, max_t, min_f, max_f].
    duration = len(data) / sr
    extent = [0, duration, -sr/2, sr/2]
    
    return Sxx_db, extent

def compute_mosaic_spectrogram(data_handle, sr, start_idx, stop_idx, fft_size=1024, target_width=2000):
    # Computes a mosaic (time-sparse) spectrogram in dB.
    # Returns (Sxx_db, extent).

    # Calculate stride to fit the duration into roughly target_width columns
    count = stop_idx - start_idx
    if count <= 0: return None, [0, 0, 0, 0]

    total_windows = count // fft_size
    stride_windows = max(1, total_windows // target_width)
    stride_samples = stride_windows * fft_size
    
    # Generate indices for the start of each window
    window_starts = np.arange(start_idx, stop_idx - fft_size, stride_samples, dtype=np.int64)
    
    # Limit to target_width to ensure memory safety
    window_starts = window_starts[:target_width]
    actual_width = len(window_starts)
    
    if actual_width == 0: return None, [0, 0, 0, 0]

    # Compute dimensions using a single slice.
    first_chunk = data_handle[start_idx : start_idx + fft_size]
    _, _, Sxx_sample = scipy.signal.spectrogram(first_chunk, fs=sr, nperseg=fft_size, 
                                            detrend=False, mode='magnitude', return_onesided=False)
    rows = Sxx_sample.shape[0]
    
    # Allocate the matrix [Freq Rows x Time Cols]
    mosaic_sxx = np.zeros((rows, actual_width), dtype=np.float32)
    
    # Fill columns
    for i, idx in enumerate(window_starts):
        chunk = data_handle[idx : idx + fft_size]
        _, _, col_sxx = scipy.signal.spectrogram(chunk, fs=sr, nperseg=fft_size, 
                                            detrend=False, mode='magnitude', return_onesided=False)
        mosaic_sxx[:, i] = col_sxx.flatten()

    # Shift and return
    mosaic_sxx = np.fft.fftshift(mosaic_sxx, axes=0)
    Sxx_db = 20 * np.log10(mosaic_sxx + 1e-9)
    duration = count / sr
    extent = [0, duration, -sr/2, sr/2]
    
    return Sxx_db, extent

def mix_and_filter(data, sr, target_freq, bandwidth):
    # Mixes the signal to baseband and applies a low pass filter.
    # Returns filtered_data.

    # Create the mixing vector to shift target_freq to DC.
    offset_freq = -target_freq
    n = np.arange(len(data), dtype=np.float64)
    # Use modulo 1.0 to keep arguments small and preserve precision.
    cycles = np.mod(n * (offset_freq / sr), 1.0)
    phase = 2 * np.pi * cycles
    mixer = np.exp(1j * phase).astype(np.complex64)
    mixed_data = data * mixer
    
    # 2. Filtering.
    # Design a simple FIR filter.
    cutoff_hz = bandwidth / 2.0
    # Transition width is 25% of bandwidth.
    trans_width = bandwidth * 0.25
    # Calculate number of taps.
    ntw = trans_width / sr
    num_taps = int(4.0 / ntw)
    # Ensure odd number of taps for type I filter.
    if num_taps % 2 == 0: num_taps += 1
    
    # Create windowed sync filter.
    taps = scipy.signal.firwin(num_taps, cutoff_hz, fs=sr)
    
    # Apply filter.
    filtered_data = scipy.signal.lfilter(taps, 1.0, mixed_data)
    
    return filtered_data

def demodulate_am(data):
    # Performs Amplitude Demodulation.
    # Returns float32 array of magnitude.
    return np.abs(data)

def demodulate_fm(data, sr):
    # Performs Frequency Demodulation.
    # Returns float32 array of frequency deviation in Hz.
    
    # Calculate phase difference between consecutive samples.
    # data[1:] * conj(data[:-1]) effectively subtracts phases.
    d_phase = np.angle(data[1:] * np.conj(data[:-1]))
    
    # Keep array size consistent with input.
    d_phase = np.append(d_phase, d_phase[-1])
    
    # Convert radians per sample to Hz.
    demod_data = d_phase * (sr / (2 * np.pi))
    
    return demod_data

def slice_signal(analog_data, thresholds):
    # Converts analog float data to integer symbols based on thresholds.
    # Returns int array (0, 1, 2, 3, etc).
    if not thresholds:
        # Default binary if no thresholds provided.
        # Use simple mean.
        thresh = [np.mean(analog_data)]
    else:
        thresh = thresholds
        
    return np.digitize(analog_data, thresh)

def apply_matched_filter(data, filter_type, length, beta=0.35):
    # Generates and applies a matched filter to the input data array.
    # Returns the filtered numpy array.

    length = int(length)
    # Too small to filter
    if length < 2:
        return data
    
    # Force odd
    if length % 2 == 0:
        length += 1
        
    if filter_type == "Moving Average":
        taps = np.ones(length) / length
        
    elif filter_type == "Gaussian":
        std = length / 6.0 
        taps = scipy.signal.windows.gaussian(length, std=std)
        # Normalize
        taps /= np.sum(taps)
        
    elif filter_type == "RRC":
        taps = _generate_rrc(length, beta)
        
    else:
        return data

    # Apply filter
    filtered_data = np.convolve(data, taps, mode='same')
    return filtered_data

def _generate_rrc(length, beta):
    # Generates Root-Raised Cosine (RRC) filter taps.
    # Length: Number of taps (should be odd).
    # Beta: Rolloff factor (0.0 to 1.0).

    taps = np.zeros(length)
    # T represents the symbol duration, which we equate to the filter length
    T = length
    
    # Time vector centered at 0
    t_vec = np.arange(-length // 2 + 1, length // 2 + 1)
    
    for i, t in enumerate(t_vec):
        if t == 0.0:
            taps[i] = 1.0 - beta + (4 * beta / np.pi)
        
        elif beta != 0 and t == T / (4 * beta):
            taps[i] = (beta / np.sqrt(2)) * (((1 + 2 / np.pi) * (np.sin(np.pi / (4 * beta)))) + 
                                             ((1 - 2 / np.pi) * (np.cos(np.pi / (4 * beta)))))
        
        elif beta != 0 and t == -T / (4 * beta):
            taps[i] = (beta / np.sqrt(2)) * (((1 + 2 / np.pi) * (np.sin(np.pi / (4 * beta)))) + 
                                             ((1 - 2 / np.pi) * (np.cos(np.pi / (4 * beta)))))
        
        else:
            num = np.sin(np.pi * t * (1 - beta) / T) + 4 * beta * (t / T) * np.cos(np.pi * t * (1 + beta) / T)
            den = np.pi * (t / T) * (1 - (4 * beta * t / T) ** 2)
            taps[i] = num / den
            
    # Normalize
    return taps / np.sqrt(np.sum(taps**2))

def find_clock_sync(symbol_data, sr, start_time, current_width, current_count, tolerance_pct=10.0, limit_time=None):
    # Attempts to find symbol edges to sync the clock.
    # Returns (success, new_duration, added_symbols).
    # Note: requires oversmapling.
    
    cursor_t = start_time + current_width
    added_symbols = 0
    idx_cursor = int(cursor_t * sr)
    
    avg_sym_width = current_width / current_count
    idx_width_est = int(avg_sym_width * sr)
    
    search_radius = int(idx_width_est * (tolerance_pct / 100.0))
    total_len = len(symbol_data)
    
    limit_idx = total_len
    if limit_time is not None:
        limit_idx = min(total_len, int(limit_time * sr))
        
    MAX_SYMBOLS = 10000
    
    while idx_cursor < limit_idx and added_symbols < MAX_SYMBOLS:
        target_idx = idx_cursor + idx_width_est
        if target_idx >= limit_idx: break
        
        w_start = max(idx_cursor + 1, target_idx - search_radius)
        w_stop = min(limit_idx - 1, target_idx + search_radius)
        
        if w_start >= w_stop: break
        
        # Look for a transition (edge).
        chunk = symbol_data[w_start:w_stop]
        diffs = np.abs(np.diff(chunk))
        changes = np.where(diffs > 0)[0]
        
        if len(changes) > 0:
            # Snap to the closest edge found.
            relative_target = target_idx - w_start
            best_change_idx = (np.abs(changes - relative_target)).argmin()
            found_edge_relative = changes[best_change_idx]
            actual_edge_idx = w_start + found_edge_relative + 1
            idx_cursor = actual_edge_idx
        else:
            # No edge found, coast along estimated width.
            idx_cursor = target_idx
            
        added_symbols += 1
        
    new_duration = idx_cursor / sr
    return True, new_duration, added_symbols

def invert_symbols(symbols, modulus):
    return (modulus - 1) - symbols

def decode_differential(symbols, modulus):
    # Create output array of same shape.
    diff = np.zeros_like(symbols)
    
    # Calculate diff.
    # We slice to vectorize: symbols[1:] - symbols[:-1]
    # We use modulo to handle wrapping (ex. 0 - 1 = -1 --> 3 in mod 4)
    d = np.mod(symbols[1:] - symbols[:-1], modulus)
    
    # Assign to output, leaving first element as 0 (default).
    diff[1:] = d
    
    return diff

def decode_manchester_string(bit_string, scheme):
    # Ensure even length
    if len(bit_string) % 2 != 0:
        bit_string = bit_string[:-1]
    
    # We process the string as chunks of 2.
    # Simple list comprehension approach, easy in Python.
    pairs = [bit_string[i:i+2] for i in range(0, len(bit_string), 2)]
    decoded = []
    
    if scheme == 'IEEE':
        # 10 = 1 and 01 -= 0
        map_table = {'10': '1', '01': '0'}
    elif scheme == 'Thomas':
        # 01 = 1 and 10 = 0
        map_table = {'01': '1', '10': '0'}
    else:
        # Fallback
        return bit_string
        
    for p in pairs:
        # E for violation (00 or 11).
        # Note: indicates shifted symbols (out-of-phase).
        decoded.append(map_table.get(p, 'E'))
        
    return "".join(decoded)
