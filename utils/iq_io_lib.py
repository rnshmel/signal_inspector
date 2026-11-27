import os
import numpy as np


# Format specifications: fmt -> (numpy_dtype, elements_per_sample, bytes_per_sample, zero_offset, scale)
_FORMAT_SPECS = {
    "cf32": (np.complex64, 1, 8, 0.0, 1.0),
    "cs16": (np.int16, 2, 4, 0.0, 1.0 / 32768.0),
    "cs8": (np.int8, 2, 2, 0.0, 1.0 / 128.0),
    "cu8": (np.uint8, 2, 2, 127.5, 1.0 / 128.0),
}


class MappedIQWrapper:
    """Proxy class wrapping IQ file memmaps with single-pass decoding and sparse pread support."""

    def __init__(self, filepath, fmt):
        self.fmt = fmt.split()[0]
        if self.fmt not in _FORMAT_SPECS:
            raise ValueError(f"Unknown format: {self.fmt}")

        raw_dtype, elems_per_sample, bytes_per_sample, offset, scale = _FORMAT_SPECS[self.fmt]
        self._raw_dtype = raw_dtype
        self._bytes_per_sample = bytes_per_sample
        self._offset = float(offset)
        self._scale = float(scale)

        self._mmap = np.memmap(filepath, dtype=raw_dtype, mode="r")
        self.length = len(self._mmap) // elems_per_sample
        self._pairs = (
            None
            if self.fmt == "cf32"
            else self._mmap[: self.length * 2].reshape(self.length, 2)
        )

        # Separate fd hinted with POSIX_FADV_RANDOM for sparse reads without hurting mmap readahead
        self._fd = os.open(filepath, os.O_RDONLY)
        if hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_RANDOM"):
            try:
                os.posix_fadvise(self._fd, 0, 0, os.POSIX_FADV_RANDOM)
            except OSError:
                pass

    def __len__(self):
        return self.length

    def _decode_pairs(self, pairs):
        """Decode an (N, 2) interleaved I/Q array into complex64 in a single float32 pass."""
        n = len(pairs)
        if n == 0:
            return np.empty(0, dtype=np.complex64)

        out = np.empty(n, dtype=np.complex64)
        out_f32 = out.view(np.float32).reshape(n, 2)
        np.copyto(out_f32, pairs)
        if self._offset != 0.0:
            out_f32 -= np.float32(self._offset)
        out_f32 *= np.float32(self._scale)
        return out

    def __getitem__(self, key):
        if self.fmt == "cf32":
            return self._mmap[key]

        if isinstance(key, slice):
            return self._decode_pairs(self._pairs[key])

        if isinstance(key, (int, np.integer)):
            idx = int(key)
            if idx < 0:
                idx += self.length
            if idx < 0 or idx >= self.length:
                raise IndexError("Index out of bounds")
            i_val = (float(self._pairs[idx, 0]) - self._offset) * self._scale
            q_val = (float(self._pairs[idx, 1]) - self._offset) * self._scale
            return np.complex64(i_val + 1j * q_val)

        raise TypeError("Invalid index type")

    def _pread_exact(self, offset, nbytes):
        """Read nbytes from self._fd starting at byte offset using pread (or lseek/read fallback)."""
        if self._fd is None:
            raise ValueError("MappedIQWrapper is closed.")

        chunks = []
        remaining = nbytes
        pos = int(offset)
        use_pread = hasattr(os, "pread")

        while remaining > 0:
            if use_pread:
                block = os.pread(self._fd, remaining, pos)
            else:
                os.lseek(self._fd, pos, os.SEEK_SET)
                block = os.read(self._fd, remaining)
            if not block:
                break
            chunks.append(block)
            read_len = len(block)
            pos += read_len
            remaining -= read_len

        return b"".join(chunks) if len(chunks) > 1 else (chunks[0] if chunks else b"")

    def read_sparse_chunks(self, starts, chunk_len, progress_cb=None):
        """Read and decode (len(starts), chunk_len) complex64 chunks via random-access pread."""
        starts_arr = np.asarray(starts, dtype=np.int64)
        chunk_len = int(chunk_len)
        n_chunks = len(starts_arr)

        if n_chunks == 0 or chunk_len <= 0 or self.length == 0:
            return np.empty((n_chunks, max(0, chunk_len)), dtype=np.complex64)
        if chunk_len > self.length:
            raise ValueError(f"chunk_len ({chunk_len}) exceeds signal length ({self.length}).")

        starts_clamped = np.clip(starts_arr, 0, self.length - chunk_len)
        chunk_bytes = chunk_len * self._bytes_per_sample
        buf = bytearray(n_chunks * chunk_bytes)
        mv = memoryview(buf)

        for idx, sample_start in enumerate(starts_clamped):
            byte_offset = int(sample_start) * self._bytes_per_sample
            data = self._pread_exact(byte_offset, chunk_bytes)
            if len(data) != chunk_bytes:
                raise IOError(
                    f"Short read at sample {int(sample_start)}: expected {chunk_bytes} bytes, got {len(data)}."
                )
            dst_start = idx * chunk_bytes
            mv[dst_start : dst_start + chunk_bytes] = data
            if progress_cb is not None:
                progress_cb(idx + 1, n_chunks)

        if self.fmt == "cf32":
            return np.frombuffer(buf, dtype=np.complex64).reshape(n_chunks, chunk_len)

        pairs = np.frombuffer(buf, dtype=self._raw_dtype).reshape(n_chunks * chunk_len, 2)
        return self._decode_pairs(pairs).reshape(n_chunks, chunk_len)

    def close(self):
        """Close the random-access file descriptor and underlying memmap."""
        fd = getattr(self, "_fd", None)
        if fd is not None:
            self._fd = None
            try:
                os.close(fd)
            except OSError:
                pass

        mmap_obj = getattr(self, "_mmap", None)
        if mmap_obj is not None:
            self._pairs = None
            self._mmap = None
            inner = getattr(mmap_obj, "_mmap", None)
            if inner is not None:
                try:
                    inner.close()
                except Exception:
                    pass

    def __del__(self):
        self.close()
