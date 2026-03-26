import numpy as np

def invert_symbols(symbols, modulus):
    return (modulus - 1) - symbols

def decode_differential(symbols, modulus):
    # Calculates the transition values between consecutive symbols.
    # The output represents phase changes or frequency deviations.
    
    # Create output array of same shape.
    diff = np.zeros_like(symbols)
    
    # Calculate diff.
    # Slice to vectorize and use modulo to handle wrapping
    d = np.mod(symbols[1:] - symbols[:-1], modulus)
    
    # Assign to output, leaving first element as 0 (default).
    diff[1:] = d
    
    return diff

def generate_mapping_dict(num_levels, mode='binary'):
    # Generates a standard absolute mapping dictionary.
    # Modes: 'binary' or 'gray'
    
    mapping = {}
    bits_per_sym = int(np.ceil(np.log2(num_levels)))
    
    for i in range(num_levels):
        if mode == 'binary':
            val = i
        elif mode == 'gray':
            val = i ^ (i >> 1)
        else:
            val = i
            
        fmt = f"{{0:0{bits_per_sym}b}}"
        mapping[i] = fmt.format(val)
        
    return mapping

def map_symbols_to_bits(symbols, mapping_dict):
    # Maps integer symbols (or diff transitions) to bit strings using a dictionary.
    # Returns a single concatenated string for the bit workbench.
    
    if symbols is None or len(symbols) == 0:
        return ""
        
    # Initialize output array of object type (strings) with a fallback character.
    # "E" indicates an unmapped symbol error.
    full_text_arr = np.full(len(symbols), 'E', dtype=object)
    
    for sym, bit_str in mapping_dict.items():
        mask = (symbols == sym)
        full_text_arr[mask] = bit_str
        
    # Join into one massive string and return
    return "".join(full_text_arr)

def invert_bit_string(bit_string):
    trans = str.maketrans('01', '10')
    return bit_string.translate(trans)

def decode_manchester_string(bit_string, scheme):
    # Decodes a Manchester encoded bit string based on IEEE or GE Thomas conventions.
    
    # Ensure even length
    if len(bit_string) % 2 != 0:
        bit_string = bit_string[:-1]
    
    # We process the string as chunks of 2.
    # Simple list comprehension approach, easy in Python.
    pairs = [bit_string[i:i+2] for i in range(0, len(bit_string), 2)]
    decoded = []
    
    if scheme == 'IEEE':
        # 10 = 1 and 01 = 0
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
