"""
Substrate supply: only outside membranes (E4).
Cached interior mask, refreshed every INTERIOR_CACHE_INTERVAL steps.
"""
import numpy as np
import scipy.ndimage

_interior = None
_exterior = None
_cache_step = -99999
_diag_mode = False


def _compute_masks(M, config):
    M_bin = (M > config.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, n = scipy.ndimage.label(M_bin)
    interior = np.zeros(M.shape, dtype=bool)
    for k in range(1, n + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        inside = filled & ~mask
        if inside.sum() > config.MIN_INTERIOR_PIXELS:
            interior |= inside
    return interior, ~interior


def invalidate_cache():
    global _cache_step
    _cache_step = -99999


def set_diagnostic_mode(on):
    global _diag_mode
    _diag_mode = on
    if on:
        invalidate_cache()


def supply_and_noise(S, P, M, config, step_count=0):
    global _interior, _exterior, _cache_step

    if (step_count - _cache_step >= config.INTERIOR_CACHE_INTERVAL):
        _interior, _exterior = _compute_masks(M, config)
        _cache_step = step_count

    S_new = S.copy()
    S_new[_exterior] += config.S_SUPPLY * config.DT

    if _interior is not None and _interior.any():
        S_new[_interior] = np.maximum(S_new[_interior], config.S_MIN_INTERIOR)

    S_new += config.NOISE_AMP * np.random.randn(*S.shape) * config.DT
    return np.clip(S_new, 0.0, config.S_CLIP_MAX)
