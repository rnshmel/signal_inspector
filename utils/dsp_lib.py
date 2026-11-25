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

    # Convert to log scale (dB) in float32 to avoid float64 upcast.
    # Add a tiny epsilon to prevent log(0).
    Sxx_db = np.asarray(Sxx, dtype=np.float32)
    np.add(Sxx_db, np.float32(1e-9), out=Sxx_db)
    np.log10(Sxx_db, out=Sxx_db)
    Sxx_db *= np.float32(20.0)
    
    # Calculate image extent for plotting [min_t, max_t, min_f, max_f].
    duration = len(data) / sr
    extent = [0, duration, -sr/2, sr/2]
    
    return Sxx_db, extent

def compute_mosaic_spectrogram(data_handle, sr, start_idx, stop_idx, fft_size=1024, target_width=2000, progress_cb=None):
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

    # Allocate the matrix [Freq Rows x Time Cols]
    mosaic_sxx = np.empty((fft_size, actual_width), dtype=np.float32)

    # Process in bounded-RAM batches so large FFT sizes stay within a few MB
    batch_cols = max(1, min(64, (1024 * 1024) // max(1, fft_size)))
    use_sparse = hasattr(data_handle, "read_sparse_chunks")

    for b0 in range(0, actual_width, batch_cols):
        b1 = min(b0 + batch_cols, actual_width)
        batch_starts = window_starts[b0:b1]

        if use_sparse:
            sub_cb = (lambda done, _tot, base=b0: progress_cb(base + done, actual_width)) if progress_cb is not None else None
            batch_chunks = data_handle.read_sparse_chunks(batch_starts, fft_size, progress_cb=sub_cb)
        else:
            batch_chunks = np.stack([data_handle[idx : idx + fft_size] for idx in batch_starts], axis=0)

        _, _, batch_sxx = scipy.signal.spectrogram(
            batch_chunks,
            fs=sr,
            nperseg=fft_size,
            detrend=False,
            mode='magnitude',
            return_onesided=False,
            axis=-1,
        )
        mosaic_sxx[:, b0:b1] = batch_sxx[:, :, 0].T
        if not use_sparse and progress_cb is not None:
            progress_cb(b1, actual_width)

    # Shift and convert to dB in float32 in-place (fftshift returns a fresh float32 array).
    Sxx_db = np.fft.fftshift(mosaic_sxx, axes=0)
    np.add(Sxx_db, np.float32(1e-9), out=Sxx_db)
    np.log10(Sxx_db, out=Sxx_db)
    Sxx_db *= np.float32(20.0)
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
    
    return filtered_data, num_taps

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

def demodulate_dpsk(data, k_offset):
    # DPSK Demodulation using a delayed complex conjugate
    k_offset = max(1, int(k_offset))
    
    # Shift the array by k_offset. 
    # Fill the initial gap with zeros to avoid wrap-around issues
    delayed = np.roll(data, k_offset)
    delayed[:k_offset] = 0
    
    # Multiply by the complex conjugate of the delayed signal
    mult = data * np.conj(delayed)
    
    # Extract the absolute phase angle
    return np.abs(np.angle(mult))

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


def apply_sliding_normalization(data, window_len):
    """Normalize a 1D signal to [-1.0, +1.0] using strided overlapping min/max windows."""
    if data is None or len(data) == 0:
        return data

    window_len = int(window_len)
    if window_len < 2:
        return data

    arr = np.asarray(data, dtype=np.float64)
    n = len(arr)

    if window_len >= n:
        lo = float(np.min(arr))
        hi = float(np.max(arr))
        span = hi - lo
        if span <= 1e-12:
            return np.zeros(n, dtype=np.float64)
        out = 2.0 * (arr - lo) / span - 1.0
        np.clip(out, -1.0, 1.0, out=out)
        return out

    step = max(1, window_len // 4)
    windows = np.lib.stride_tricks.sliding_window_view(arr, window_len)[::step]
    lo_vals = windows.min(axis=1)
    hi_vals = windows.max(axis=1)

    starts = np.arange(0, n - window_len + 1, step, dtype=np.float64)
    half_span = (window_len - 1) / 2.0
    centers = starts + half_span

    # Ensure tail samples are anchored to a full-width window at the end
    last_start = n - window_len
    if int(starts[-1]) < last_start:
        lo_vals = np.append(lo_vals, float(np.min(arr[last_start:])))
        hi_vals = np.append(hi_vals, float(np.max(arr[last_start:])))
        centers = np.append(centers, float(last_start) + half_span)

    idx = np.arange(n, dtype=np.float64)
    lo_env = np.interp(idx, centers, lo_vals)
    hi_env = np.interp(idx, centers, hi_vals)

    span = hi_env - lo_env
    valid = span > 1e-12
    out = np.zeros(n, dtype=np.float64)
    out[valid] = 2.0 * (arr[valid] - lo_env[valid]) / span[valid] - 1.0
    np.clip(out, -1.0, 1.0, out=out)
    return out


