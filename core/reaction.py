"""
Autocatalytic reaction: Hill function + background + inhibition + ramped decay.
CRITICAL: Hill function P^2/(P^2+K_M^2) is zero at P=0. Never use sigmoid.
"""
import numpy as np


def get_effective_decay(step_count, config):
    """Ramp P decay: 0 before START, linear to END, constant after."""
    if step_count < config.DECAY_RAMP_START:
        return 0.0
    if step_count < config.DECAY_RAMP_END:
        t = (step_count - config.DECAY_RAMP_START) / \
            float(config.DECAY_RAMP_END - config.DECAY_RAMP_START)
        return config.P_DECAY * t
    return config.P_DECAY


def react(S, P, config, step_count=0, inhibit_mask=None):
    """One reaction step."""
    # Background nucleation
    background = config.K_BG * S * config.DT

    # Hill autocatalysis (n=2)
    P_sq = P * P
    hill = P_sq / (P_sq + config.K_M ** 2 + 1e-12)
    autocatalysis = config.K1 * S * hill * config.DT

    # High-P inhibition
    inhibition = 1.0 / (1.0 + np.exp(-20.0 * (P - config.P_INHIBIT_THRESH)))
    inhibit_factor = np.maximum(1.0 - config.K_INHIBIT * inhibition / config.K1, 0.0)

    # Net production (cannot exceed available S)
    delta_P = background + autocatalysis * inhibit_factor
    if inhibit_mask is not None:
        delta_P[inhibit_mask] = 0.0
    delta_P = np.minimum(delta_P, S)

    S_new = S - delta_P
    P_new = P + delta_P

    # Ramped decay
    decay = get_effective_decay(step_count, config)
    if decay > 0:
        P_new *= (1.0 - decay * config.DT)

    return np.clip(S_new, 0, None), np.clip(P_new, 0, None)
