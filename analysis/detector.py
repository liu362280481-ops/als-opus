"""Detect closed membrane units."""
import numpy as np
import scipy.ndimage


def detect_closed_units(M, P, S, config):
    M_bin = (M > config.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, num = scipy.ndimage.label(M_bin)
    units = []
    for k in range(1, num + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        interior = filled & ~mask
        if interior.sum() > config.MIN_INTERIOR_PIXELS:
            exterior = ~filled
            units.append({
                'id': k,
                'membrane': mask,
                'interior': interior,
                'area': int(interior.sum()),
                'membrane_pixels': int(mask.sum()),
                'P_inside': float(P[interior].mean()) if interior.any() else 0.0,
                'P_outside': float(P[exterior].mean()) if exterior.any() else 0.0,
                'S_inside': float(S[interior].mean()) if interior.any() else 0.0,
                'S_outside': float(S[exterior].mean()) if exterior.any() else 0.0,
                'M_membrane_mean': float(M[mask].mean()),
            })
    return units, num
