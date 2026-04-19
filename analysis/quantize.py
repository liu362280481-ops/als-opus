"""Q8.8 fixed-point quantization for FPGA verification."""
import numpy as np


def quantize_q8_8(x):
    scale = 256.0
    return np.clip(np.round(x * scale) / scale, -128.0, 127.99609375)


def quantize_fields(S, P, M):
    return quantize_q8_8(S), quantize_q8_8(P), quantize_q8_8(M)
