"""
Membrane dynamics: growth at P boundaries, protected decay, neighbor inhibition.
"""
import numpy as np
import scipy.ndimage


def update_membrane(S, P, M, config):
    """Update membrane field."""
    win = config.MEMBRANE_DETECT_WINDOW

    # Boundary detection: standard deviation (high gradient areas)
    P_mean = scipy.ndimage.uniform_filter(P, size=win)
    P_sq_mean = scipy.ndimage.uniform_filter(P * P, size=win)
    boundary = np.sqrt(np.maximum(P_sq_mean - P_mean * P_mean, 0.0))

    # Saturation inhibit
    sat_inhibit = 1.0 - M

    # Neighbor inhibit
    M_local = scipy.ndimage.uniform_filter(M, size=3)
    nb_inhibit = np.maximum(1.0 - config.NEIGHBOR_INHIBIT_STRENGTH * M_local, 0.0)

    # Growth
    growth = config.K_GROWTH * S * boundary * sat_inhibit * nb_inhibit

    # Protected decay: membranes at strong P gradients decay slower
    P_range = (scipy.ndimage.maximum_filter(P, size=7)
               - scipy.ndimage.minimum_filter(P, size=7))
    protection = 1.0 - config.MEMBRANE_PROTECT_COEFF * np.clip(
        P_range / config.MEMBRANE_PROTECT_NORM, 0, 1)
    decay = config.K_DECAY_M * M * protection

    M_new = M + (growth - decay) * config.DT
    return np.clip(M_new, 0.0, config.M_CLIP_MAX)
