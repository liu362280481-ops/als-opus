"""
Anisotropic diffusion with exponential membrane barrier.
Uses flux-based Laplacian with periodic boundaries.
"""
import numpy as np


def laplacian_anisotropic(field, D_eff):
    """Flux-based anisotropic Laplacian with periodic boundaries."""
    D_right = 0.5 * (D_eff + np.roll(D_eff, -1, axis=0))
    flux_right = D_right * (np.roll(field, -1, axis=0) - field)
    flux_left = np.roll(flux_right, 1, axis=0)

    D_up = 0.5 * (D_eff + np.roll(D_eff, -1, axis=1))
    flux_up = D_up * (np.roll(field, -1, axis=1) - field)
    flux_down = np.roll(flux_up, 1, axis=1)

    return (flux_right - flux_left) + (flux_up - flux_down)


def diffuse(S, P, M, config):
    """Diffuse S and P with membrane barrier. M does not diffuse."""
    D_P_eff = config.D_P * np.exp(-config.ALPHA_EXP_P * M)
    D_S_eff = config.D_S * np.exp(-config.ALPHA_EXP_S * M)

    S_new = S + config.DT * laplacian_anisotropic(S, D_S_eff)
    P_new = P + config.DT * laplacian_anisotropic(P, D_P_eff)
    return S_new, P_new
