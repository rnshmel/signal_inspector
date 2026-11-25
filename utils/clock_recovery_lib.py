# Version 2.1.0: broken out of dsp_lib.py
# Probably need to make the clock rec functions names more descriptive

import numpy as np

def _compute_sps_bounds(sps_time, freq_clamp_pct):
    """Compute optional min/max symbol duration bounds from a +/- percentage clamp."""
    if freq_clamp_pct is None:
        return None, None
    clamp_frac = max(0.01, min(float(freq_clamp_pct), 95.0)) / 100.0
    return sps_time / (1.0 + clamp_frac), sps_time / (1.0 - clamp_frac)

def _interp_sample(analog_data, idx_f):
    """Linearly interpolate a single float sample at continuous index idx_f."""
    idx_clamped = max(0.0, min(float(idx_f), float(len(analog_data) - 1)))
    i0 = int(idx_clamped)
    i1 = min(i0 + 1, len(analog_data) - 1)
    frac = idx_clamped - i0
    return float(analog_data[i0]) * (1.0 - frac) + float(analog_data[i1]) * frac

def _run_pll_clock_sync(
    analog_data,
    sr,
    start_time,
    current_width,
    current_count,
    alpha,
    beta,
    gamma,
    initial_zc,
    limit_time,
    outlier_rejection,
    freq_clamp_pct,
    track_zc,
):
    """Shared 2nd/3rd-order zero-crossing PLL loop used by public clock sync functions."""
    if current_count < 1 or current_width <= 0.0 or len(analog_data) < 2 or sr <= 0.0:
        empty = np.array([], dtype=np.float64)
        return False, empty, (empty.copy() if track_zc else None), float(start_time)

    sps_time = float(current_width) / float(current_count)
    manual_boundary = float(start_time) + float(current_width)

    alpha = float(alpha)
    beta = (alpha / 10.0) if beta is None else float(beta)
    gamma = (beta / 10.0) if (track_zc and gamma is None) else (0.0 if not track_zc else float(gamma))
    min_sps_t, max_sps_t = _compute_sps_bounds(sps_time, freq_clamp_pct)

    current_zc = float(initial_zc)
    clock_centers = []
    zc_thresholds = [] if track_zc else None

    for i in range(int(current_count)):
        clock_centers.append(float(start_time) + (i + 0.5) * sps_time)
        if track_zc:
            zc_thresholds.append(current_zc)

    cursor_edge_t = manual_boundary
    current_sps_t = sps_time

    limit_idx = len(analog_data)
    if limit_time is not None:
        limit_idx = min(limit_idx, int(limit_time * sr))

    added_symbols = 0
    max_symbols = len(analog_data)

    while added_symbols < max_symbols:
        if current_sps_t <= 0.0:
            break

        expected_edge_t = cursor_edge_t + current_sps_t
        expected_edge_idx = int(expected_edge_t * sr)

        if expected_edge_idx >= limit_idx:
            break

        # Search window: +/- 0.5 symbol width
        search_radius_t = 0.5 * current_sps_t
        if search_radius_t <= 0.0:
            break
        search_radius_idx = int(search_radius_t * sr)

        w_start = max(0, expected_edge_idx - search_radius_idx)
        w_stop = min(limit_idx - 1, expected_edge_idx + search_radius_idx)

        if w_start >= w_stop:
            break

        chunk = (analog_data[w_start:w_stop] - current_zc) if track_zc else analog_data[w_start:w_stop]
        crossings = np.where(np.diff(np.signbit(chunk)))[0]

        symbol_zc = current_zc
        if len(crossings) > 0:
            relative_target = expected_edge_idx - w_start
            best_idx = int(np.abs(crossings - relative_target).argmin())

            c_idx = int(crossings[best_idx])
            y0 = float(chunk[c_idx])
            y1 = float(chunk[c_idx + 1])
            span = abs(y0) + abs(y1)
            frac_offset = 0.0 if span == 0.0 else abs(y0) / span

            actual_edge_t = (w_start + c_idx + frac_offset) / sr
            error_t = actual_edge_t - expected_edge_t
            penalty = max(0.0, 1.0 - (abs(error_t) / search_radius_t)) if outlier_rejection else 1.0

            # 1st & 2nd order updates: phase (alpha) and symbol period (beta)
            cursor_edge_t = expected_edge_t + (error_t * alpha * penalty)
            current_sps_t += error_t * beta * penalty
            if min_sps_t is not None:
                current_sps_t = max(min_sps_t, min(current_sps_t, max_sps_t))
            center_t = cursor_edge_t - (current_sps_t / 2.0)

            # 3rd order update: nudge zero-crossing threshold (gamma) on confirmed transitions
            if track_zc and gamma != 0.0:
                next_center_t = cursor_edge_t + (current_sps_t / 2.0)
                if 0.0 <= center_t * sr and next_center_t * sr < limit_idx:
                    y_before = _interp_sample(analog_data, center_t * sr)
                    y_after = _interp_sample(analog_data, next_center_t * sr)
                    if (y_before - current_zc) * (y_after - current_zc) < 0.0:
                        midpoint = 0.5 * (y_before + y_after)
                        zc_error = midpoint - current_zc
                        current_zc += zc_error * (gamma * penalty)
        else:
            # No zero crossing found; freewheel one symbol forward
            cursor_edge_t = expected_edge_t
            center_t = cursor_edge_t - (current_sps_t / 2.0)

        clock_centers.append(center_t)
        if track_zc:
            zc_thresholds.append(symbol_zc)
        added_symbols += 1

    zc_arr = np.array(zc_thresholds, dtype=np.float64) if track_zc else None
    return True, np.array(clock_centers, dtype=np.float64), zc_arr, manual_boundary

def find_clock_sync(
    analog_data,
    sr,
    start_time,
    current_width,
    current_count,
    alpha=0.25,
    limit_time=None,
    beta=None,
    outlier_rejection=True,
    freq_clamp_pct=None,
):
    """Extract clock timings using a 2nd-order proportional-integral PLL on zero-crossings.

    Assumes ``analog_data`` has already been centered around the chosen zero-crossing level.
    """
    success, clock_centers, _, manual_boundary = _run_pll_clock_sync(
        analog_data,
        sr,
        start_time,
        current_width,
        current_count,
        alpha=alpha,
        beta=beta,
        gamma=0.0,
        initial_zc=0.0,
        limit_time=limit_time,
        outlier_rejection=outlier_rejection,
        freq_clamp_pct=freq_clamp_pct,
        track_zc=False,
    )
    return success, clock_centers, manual_boundary

def find_clock_sync_3rd_order(
    analog_data,
    sr,
    start_time,
    current_width,
    current_count,
    initial_zc=0.0,
    alpha=0.25,
    beta=None,
    gamma=None,
    limit_time=None,
    outlier_rejection=True,
    freq_clamp_pct=None,
):
    """Extract clock timings using a 3rd-order PLL with gradual CFO/ZC tracking.

    ``alpha`` shifts boundary phase, ``beta`` nudges symbol period/frequency, and
    ``gamma`` nudges the zero-crossing threshold on confirmed symbol transitions.
    """
    return _run_pll_clock_sync(
        analog_data,
        sr,
        start_time,
        current_width,
        current_count,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        initial_zc=initial_zc,
        limit_time=limit_time,
        outlier_rejection=outlier_rejection,
        freq_clamp_pct=freq_clamp_pct,
        track_zc=True,
    )

def compute_edges_from_centers(centers, fallback_sps):
    """Reconstruct symbol boundary positions from recovered symbol center timestamps."""
    centers = np.asarray(centers, dtype=np.float64)
    n = len(centers)
    if n == 0:
        return np.array([], dtype=np.float64)
    if n == 1:
        half = float(fallback_sps) / 2.0
        return np.array([centers[0] - half, centers[0] + half], dtype=np.float64)

    first_edge = centers[0] - (centers[1] - centers[0]) / 2.0
    internal_edges = (centers[:-1] + centers[1:]) / 2.0
    last_edge = centers[-1] + (centers[-1] - centers[-2]) / 2.0
    return np.concatenate(([first_edge], internal_edges, [last_edge]))

def sample_signal_at_positions(analog_data, positions, sr):
    """Linearly interpolate analog_data at continuous x-positions."""
    pos = np.asarray(positions, dtype=np.float64)
    if len(pos) == 0 or len(analog_data) == 0:
        return np.array([], dtype=np.float64)

    idx_f = np.clip(pos * sr, 0.0, float(len(analog_data) - 1))
    idx0 = np.floor(idx_f).astype(np.int64)
    idx1 = np.minimum(idx0 + 1, len(analog_data) - 1)
    frac = idx_f - idx0
    return analog_data[idx0] * (1.0 - frac) + analog_data[idx1] * frac

def remove_dc_bias(analog_data, thresholds):
    # Centers the analog data around 0.0 using the middle threshold (CFO correction).

    if thresholds:
        # Get the middle threshold as the DC bias
        mid_idx = len(thresholds) // 2
        dc_offset = thresholds[mid_idx]
    else:
        # Fallback to mean if no thresholds are set
        dc_offset = np.mean(analog_data)
        
    centered_data = analog_data - dc_offset
    adjusted_thresholds = [t - dc_offset for t in thresholds]
    
    return centered_data, adjusted_thresholds, dc_offset

def sample_and_slice(analog_data, timestamps, sr, thresholds, zc_offsets=None):
    """Linearly sample analog data at timestamps and digitize into integer symbols."""
    if timestamps is None or len(timestamps) == 0 or analog_data is None or len(analog_data) == 0:
        return np.array([], dtype=np.int64)

    analog_samples = sample_signal_at_positions(analog_data, timestamps, sr)
    if zc_offsets is not None:
        zc_arr = np.asarray(zc_offsets, dtype=np.float64)
        if len(zc_arr) != len(analog_samples):
            raise ValueError(
                f"zc_offsets length ({len(zc_arr)}) must match timestamps length ({len(analog_samples)})."
            )
        analog_samples = analog_samples - zc_arr

    thresh = [0.0] if not thresholds else thresholds
    return np.digitize(analog_samples, thresh)
