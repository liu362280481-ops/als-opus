"""Main engine: init + step."""
import numpy as np
from core.diffusion import diffuse
from core.reaction import react
from core.membrane import update_membrane
from core.substrate import supply_and_noise


def init_fields(config):
    if config.RANDOM_SEED is not None:
        np.random.seed(config.RANDOM_SEED)
    config.validate_config()
    n = config.GRID_SIZE
    S = np.full((n, n), config.S_INITIAL, dtype=np.float64)
    P = np.random.uniform(0.0, 0.002, (n, n)).astype(np.float64)
    M = np.zeros((n, n), dtype=np.float64)
    return S, P, M


def step(S, P, M, config, step_count=0, inhibit_mask=None):
    S, P = diffuse(S, P, M, config)
    S, P = react(S, P, config, step_count=step_count, inhibit_mask=inhibit_mask)
    M = update_membrane(S, P, M, config)
    S = supply_and_noise(S, P, M, config, step_count=step_count)
    S = np.clip(S, 0, config.S_CLIP_MAX)
    P = np.clip(P, 0, config.P_CLIP_MAX)
    M = np.clip(M, 0, config.M_CLIP_MAX)
    if np.any(np.isnan(S)) or np.any(np.isnan(P)) or np.any(np.isnan(M)):
        raise ValueError(f"NaN at step {step_count}")
    if np.any(np.isinf(S)) or np.any(np.isinf(P)) or np.any(np.isinf(M)):
        raise ValueError(f"Inf at step {step_count}")
    return S, P, M
