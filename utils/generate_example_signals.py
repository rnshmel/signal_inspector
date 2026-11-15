import os
import logging
import numpy as np

# Configure logging to output to the console
logging.basicConfig(level=logging.INFO, format='%(levelname)s - DSP Module - %(message)s')

def expand_to_samps_per_sym(symbol_array, samps_per_sym):
    """
    Takes a numpy array of symbols and expands it by repeating each symbol.
    """
    logging.info(f"expand_to_samps_per_sym called.")
    logging.info(f"Input symbol array length: {len(symbol_array)} symbols")
    logging.info(f"Samples per symbol: {samps_per_sym}")
    
    num_symbols = len(symbol_array)
    samps = int(samps_per_sym)
    
    # Pre-allocate array for speed, but use a for-loop for readability
    expanded = np.zeros(num_symbols * samps, dtype=symbol_array.dtype)
    
    out_idx = 0
    for sym in symbol_array:
        for _ in range(samps):
            expanded[out_idx] = sym
            out_idx += 1
            
    return expanded

def modulate_ook(expanded_symbols, samp_rate):
    """
    Modulates the expanded symbols using On-Off Keying (OOK).
    """
    logging.info(f"modulate_ook called.")
    
    num_samples = len(expanded_symbols)
    iq_data = np.zeros(num_samples, dtype=np.complex64)
    
    for n in range(num_samples):
        # For OOK, 1 is full amplitude (1.0), 0 is zero amplitude (0.0).
        i_comp = 1.0 if expanded_symbols[n] == 1 else 0.0

        # Q component is naturally 0.0 at baseband (cos(0) = 1, sin(0) = 0)
        iq_data[n] = i_comp + 1j * 0.0
        
    return iq_data

def modulate_2fsk(expanded_symbols, freq_dev, samp_rate):
    """
    Modulates the expanded symbols using Continuous Phase 2-Level Frequency Shift Keying (CPFSK).
    Uses a Phase Accumulator (NCO) approach.
    """
    logging.info(f"modulate_2fsk called.")
    
    num_samples = len(expanded_symbols)
    iq_data = np.zeros(num_samples, dtype=np.complex64)
    
    current_phase = 0.0
    
    for n in range(num_samples):
        # 1. Map symbols to instantaneous frequencies
        if expanded_symbols[n] == 1:
            f = freq_dev
        else:
            f = -freq_dev
            
        # 2. Calculate the phase step for this sample
        phase_step = 2 * np.pi * f / samp_rate
        
        # 3. Accumulate phase
        current_phase += phase_step
        
        # Keep phase bounded between 0 and 2*pi to avoid float precision loss
        current_phase %= (2 * np.pi)
        
        # 4. Calculate I and Q
        i_comp = np.cos(current_phase)
        q_comp = np.sin(current_phase)
        
        iq_data[n] = i_comp + 1j * q_comp
        
    return iq_data

def modulate_4fsk(expanded_symbols, freq_dev, samp_rate):
    """
    Modulates the expanded symbols using Continuous Phase 4-Level Frequency Shift Keying (CPFSK).
    Uses a Phase Accumulator (NCO) approach.
    """
    logging.info(f"modulate_4fsk called.")
    
    num_samples = len(expanded_symbols)
    iq_data = np.zeros(num_samples, dtype=np.complex64)
    
    current_phase = 0.0
    
    for n in range(num_samples):
        # 1. Map the 4 symbol states to frequencies
        sym = expanded_symbols[n]
        if sym == 0:
            f = -3 * freq_dev
        elif sym == 1:
            f = -1 * freq_dev
        elif sym == 2:
            f = +1 * freq_dev
        elif sym == 3:
            f = +3 * freq_dev
        else:
            f = 0  # Fallback
            
        # 2. Calculate the phase step for this sample
        phase_step = 2 * np.pi * f / samp_rate
        
        # 3. Accumulate phase
        current_phase += phase_step
        current_phase %= (2 * np.pi)
        
        # 4. Calculate I and Q
        i_comp = np.cos(current_phase)
        q_comp = np.sin(current_phase)
        
        iq_data[n] = i_comp + 1j * q_comp
        
    return iq_data

def mix_to_baseband_offset(iq_data, offset, samp_rate):
    """
    Mixes the baseband IQ data to a specific frequency offset using a complex sinusoid.
    Uses a Phase Accumulator (NCO) approach for the Local Oscillator.
    """
    logging.info(f"mix_to_baseband_offset called. Offset: {offset} Hz")
    
    num_samples = len(iq_data)
    mixed_data = np.zeros(num_samples, dtype=np.complex64)
    
    current_phase = 0.0
    phase_step = 2 * np.pi * offset / samp_rate
    
    for n in range(num_samples):
        # Accumulate phase for the LO
        current_phase += phase_step
        current_phase %= (2 * np.pi)
        
        # Create the Local Oscillator (LO) at this exact phase
        lo_i = np.cos(current_phase)
        lo_q = np.sin(current_phase)
        local_oscillator = lo_i + 1j * lo_q
        
        # Mix (multiply) the signal with the LO
        mixed_data[n] = iq_data[n] * local_oscillator
        
    return mixed_data

def modulate_bpsk(expanded_symbols, samp_rate):
    """
    Modulates the expanded symbols using Binary Phase Shift Keying (BPSK).
    """
    logging.info(f"modulate_bpsk called.")
    
    num_samples = len(expanded_symbols)
    iq_data = np.zeros(num_samples, dtype=np.complex64)
    
    for n in range(num_samples):
        # For BPSK, 1 is 0 degrees (1.0), 0 is 180 degrees (-1.0)
        i_comp = 1.0 if expanded_symbols[n] == 1 else -1.0
        
        # Q component is naturally 0.0 for basic baseband BPSK
        iq_data[n] = i_comp + 1j * 0.0
        
    return iq_data

def manchester_encode(bit_array):
    """
    Manchester encodes a bit array: 1 becomes [1, 0] and 0 becomes [0, 1].
    """
    logging.info("manchester_encode called.")
    bits = np.asarray(bit_array)
    encoded = np.zeros(len(bits) * 2, dtype=bits.dtype)

    out_idx = 0
    for bit in bits:
        if bit == 1:
            encoded[out_idx] = 1
            encoded[out_idx + 1] = 0
        else:
            encoded[out_idx] = 0
            encoded[out_idx + 1] = 1
        out_idx += 2

    return encoded

def differential_encode(bit_array):
    """
    Differentially encodes a bit array (0 = no flip, 1 = flip).
    """
    logging.info("differential_encode called.")
    bits = np.asarray(bit_array)
    encoded = np.zeros(len(bits), dtype=bits.dtype)

    current_state = 0
    for n in range(len(bits)):
        if bits[n] == 1:
            current_state = 1 - current_state
        encoded[n] = current_state

    return encoded

def hex_to_bits(hex_str):
    """
    Converts a hexadecimal string into a numpy array of bits (0s and 1s, MSB first).
    """
    clean_text = hex_str.strip().replace(" ", "")
    bin_str = "".join(f"{int(c, 16):04b}" for c in clean_text)
    return np.array(list(bin_str), dtype=np.uint8)

def add_padding_and_noise(iq_data):
    """
    Pads the IQ signal with its own length of zeros on either end and adds AWGN.
    """
    logging.info("Applying Padding and Noise)")
    sig_len = len(iq_data)
    padding = np.zeros(sig_len, dtype=np.complex64)

    final_iq = np.concatenate((padding, iq_data, padding))

    noise_i = np.random.normal(0, 0.05, len(final_iq))
    noise_q = np.random.normal(0, 0.05, len(final_iq))
    noise = (noise_i + 1j * noise_q).astype(np.complex64)

    final_iq += noise
    return final_iq

def write_readme(output_dir):
    """
    Writes a plain-text readme.txt explaining each generated example signal,
    its parameters, framing, and expected message.
    """
    readme_text = """Signal Inspector Example Signals

General Info:
- File Format: 32-bit Complex Float (.cf32)
- Sample Rate: 2000000 sps (2 Msps)
- Each signal is padded with its own length of zeros on both
  ends and combined with a bit of noise.

2fsk_example_signal.cf32
--------------------------------------------------------------------------------
- Modulation: 2-Level FSK (CPFSK)
- Baseband Offset: +300000 Hz (+300 kHz)
- Frequency Deviation: +/- 25000 Hz (25 kHz)
- Baud Rate: 9600 baud
- Encoding: None (NRZL)
- Framing:
  - Preamble: 4 bytes (AA)
  - SOF: 1 byte (CC)
  - EOF: 1 byte (CC)
- Expected Message: "this is a 2FSK example signal with a NRZ-L encoding"

ook_example_signal.cf32
--------------------------------------------------------------------------------
- Modulation: On-Off Keying (OOK)
- Baseband Offset: -300000 Hz (-300 kHz)
- Baud Rate: 2400 baud (post-Manchester symbol rate)
- Encoding: Manchester (IEEE: 1 = 10, 0 = 01)
- Framing (pre-Manchester):
  - Preamble: 16 bytes (AA)
  - SOF: 2 bytes (FF FF)
  - EOF: 2 bytes (FF FF)
- Expected Message: "this is an OOK example signal with a Manchester encoding scheme"

bpsk_example_signal.cf32
--------------------------------------------------------------------------------
- Modulation: Binary Phase Shift Keying (BPSK)
- Baseband Offset: +200000 Hz (+200 kHz)
- Baud Rate: 4800 baud
- Encoding: Differential (0 = no flip, 1 = flip)
- Framing (pre-differential):
  - Preamble: 8 bytes (FF)
  - SOF: 1 byte (D5)
  - EOF: None
- Expected Message: "this is a BPSK example signal with a differential encoding"

4fsk_example_signal.cf32
--------------------------------------------------------------------------------
- Modulation: 4-Level FSK (CPFSK)
- Baseband Offset: +300000 Hz (+300 kHz)
- Frequency Deviation: 10000 Hz (10 kHz)
  - symbol 0 = -30 kHz
  - symbol 1 = -10 kHz
  - symbol 2 = +10 kHz
  - symbol 3 = +30 kHz
- Baud Rate: 9600 baud
- Encoding: None (NRZL)
  - 2 bits per symbol with:
  - symbol 0 = 00
  - symbol 1 = 01
  - symbol 2 = 10
  - symbol 3 = 11
- Framing:
  - Preamble: 16 alternating symbols (3, 0, 3, 0, etc)
  - SOF: Stair-step symbols (3, 2, 1, 0, 3, 2, 1, 0)
  - EOF: Stair-step symbols (3, 2, 1, 0, 3, 2, 1, 0)
- Expected Message: "this is a 4FSK example signal with no encoding (NRZL), we can send
two bits-per-symbol with this modulation scheme"

"""
    readme_path = os.path.join(output_dir, "readme.txt")
    logging.info(f"Writing example signals documentation to {readme_path}")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_text)

def main():
    samp_rate = 2000000
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "example_signals",
    )
    os.makedirs(output_dir, exist_ok=True)

    # 1. 2FSK
    logging.info("Generating 2FSK example signal")
    hex_2fsk = "AAAAAAAACC746869732069732061203246534B206578616D706C65207369676E616C20776974682061204E525A2D4C20656E636F64696E67CC"
    symbols_2fsk = hex_to_bits(hex_2fsk)
    samps_per_sym = int(samp_rate / 9600)
    expanded = expand_to_samps_per_sym(symbols_2fsk, samps_per_sym)
    modulated = modulate_2fsk(expanded, 25000, samp_rate)
    final_iq = mix_to_baseband_offset(modulated, 300000, samp_rate)
    final_iq = add_padding_and_noise(final_iq)
    final_iq.tofile(os.path.join(output_dir, "2fsk_example_signal.cf32"))

    # 2. OOK
    logging.info("Generating OOK example signal")
    hex_ook = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFFFF7468697320697320616E204F4F4B206578616D706C65207369676E616C20776974682061204D616E6368657374657220656E636F64696E6720736368656D65FFFF"
    bits_ook = hex_to_bits(hex_ook)
    symbols_ook = manchester_encode(bits_ook)
    samps_per_sym = int(samp_rate / 2400)
    expanded = expand_to_samps_per_sym(symbols_ook, samps_per_sym)
    modulated = modulate_ook(expanded, samp_rate)
    final_iq = mix_to_baseband_offset(modulated, -300000, samp_rate)
    final_iq = add_padding_and_noise(final_iq)
    final_iq.tofile(os.path.join(output_dir, "ook_example_signal.cf32"))

    # 3. BPSK
    logging.info("Generating BPSK example signal")
    hex_bpsk = "FFFFFFFFFFFFFFFFD5746869732069732061204250534B206578616D706C65207369676E616C2077697468206120646966666572656E7469616C20656E636F64696E67"
    bits_bpsk = hex_to_bits(hex_bpsk)
    symbols_bpsk = differential_encode(bits_bpsk)
    samps_per_sym = int(samp_rate / 4800)
    expanded = expand_to_samps_per_sym(symbols_bpsk, samps_per_sym)
    modulated = modulate_bpsk(expanded, samp_rate)
    final_iq = mix_to_baseband_offset(modulated, 200000, samp_rate)
    final_iq = add_padding_and_noise(final_iq)
    final_iq.tofile(os.path.join(output_dir, "bpsk_example_signal.cf32"))

    # 4. 4FSK
    logging.info("Generating 4FSK example signal")
    preamble_4fsk = np.array([3, 0] * 8, dtype=np.uint8)
    sof_4fsk = np.array([3, 2, 1, 0, 3, 2, 1, 0], dtype=np.uint8)
    eof_4fsk = np.array([3, 2, 1, 0, 3, 2, 1, 0], dtype=np.uint8)
    hex_4fsk_msg = "746869732069732061203446534B206578616D706C65207369676E616C2077697468206E6F20656E636F64696E6720284E525A4C292C2077652063616E2073656E642074776F20626974732D7065722D73796D626F6C20776974682074686973206D6F64756C6174696F6E20736368656D65"
    bits_4fsk_msg = hex_to_bits(hex_4fsk_msg)
    msg_symbols_4fsk = (bits_4fsk_msg[0::2] << 1) | bits_4fsk_msg[1::2]
    symbols_4fsk = np.concatenate((preamble_4fsk, sof_4fsk, msg_symbols_4fsk, eof_4fsk))
    samps_per_sym = int(samp_rate / 9600)
    expanded = expand_to_samps_per_sym(symbols_4fsk, samps_per_sym)
    modulated = modulate_4fsk(expanded, 10000, samp_rate)
    final_iq = mix_to_baseband_offset(modulated, 300000, samp_rate)
    final_iq = add_padding_and_noise(final_iq)
    final_iq.tofile(os.path.join(output_dir, "4fsk_example_signal.cf32"))

    write_readme(output_dir)


if __name__ == "__main__":
    main()
