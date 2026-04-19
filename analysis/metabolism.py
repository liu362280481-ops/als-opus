"""Metabolism test: measure ongoing S/P flux inside closed units."""
import numpy as np
from core.engine import step
from core.substrate import set_diagnostic_mode
from analysis.detector import detect_closed_units


def metabolism_test(S, P, M, config, test_steps=1000):
    print(f"\n=== Metabolism Test ({test_steps} steps) ===")
    units, _ = detect_closed_units(M, P, S, config)
    if not units:
        print("  No closed units, skipping")
        return None

    all_interior = np.zeros(S.shape, dtype=bool)
    for u in units:
        all_interior |= u['interior']
    if not all_interior.any():
        print("  No interior region")
        return None

    S_t, P_t, M_t = S.copy(), P.copy(), M.copy()
    s_deltas, p_deltas = [], []

    set_diagnostic_mode(True)
    for i in range(test_steps):
        s_before = float(S_t[all_interior].mean())
        p_before = float(P_t[all_interior].mean())
        S_t, P_t, M_t = step(S_t, P_t, M_t, config,
                              step_count=config.MAX_STEPS + i)
        s_deltas.append(abs(float(S_t[all_interior].mean()) - s_before))
        p_deltas.append(abs(float(P_t[all_interior].mean()) - p_before))
    set_diagnostic_mode(False)

    avg_s = float(np.mean(s_deltas))
    avg_p = float(np.mean(p_deltas))
    is_met = (avg_s > 1e-7) and (avg_p > 1e-7)

    print(f"  Avg |dS|: {avg_s:.2e}")
    print(f"  Avg |dP|: {avg_p:.2e}")
    print(f"  Metabolizing: {is_met}")

    return {'s_flux': avg_s, 'p_flux': avg_p, 'is_metabolizing': is_met}
