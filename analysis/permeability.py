"""
Control-corrected membrane permeability test.

Runs TWO parallel simulations with identical random noise:
  - Control branch: no intervention
  - Test branch: external P pulse added

Leakage = (test_interior - control_interior) / pulse_amount

This eliminates P_DECAY artifacts that caused false-negative permeability
readings in V1 (negative permeability from internal P decay, not actual
membrane quality).
"""
import numpy as np
from core.engine import step
from core.substrate import set_diagnostic_mode
from analysis.detector import detect_closed_units
import scipy.ndimage


def permeability_test(S, P, M, config):
    print("\n=== Permeability Test (control-corrected) ===")
    units, _ = detect_closed_units(M, P, S, config)
    if not units:
        print("  No closed units, skipping")
        return None

    unit = units[0]
    interior = unit['interior']
    filled = scipy.ndimage.binary_fill_holes(unit['membrane'])
    exterior = ~filled

    # Save random state for reproducible parallel runs
    rng_state = np.random.get_state()

    # -- Control branch (no pulse) --
    S_c, P_c, M_c = S.copy(), P.copy(), M.copy()
    np.random.set_state(rng_state)
    set_diagnostic_mode(True)
    for i in range(config.PERMEABILITY_TEST_STEPS):
        S_c, P_c, M_c = step(S_c, P_c, M_c, config,
                              step_count=config.MAX_STEPS + i)

    # -- Test branch (with external pulse) --
    S_t, P_t, M_t = S.copy(), P.copy(), M.copy()
    P_t[exterior] += config.PERMEABILITY_PULSE
    np.random.set_state(rng_state)
    for i in range(config.PERMEABILITY_TEST_STEPS):
        S_t, P_t, M_t = step(S_t, P_t, M_t, config,
                              step_count=config.MAX_STEPS + i)
    set_diagnostic_mode(False)

    # Corrected leakage: how much of the pulse leaked inside
    P_in_diff = float(P_t[interior].mean() - P_c[interior].mean())
    leakage = P_in_diff / config.PERMEABILITY_PULSE

    # Also report raw values for transparency
    print(f"  Control interior P: {P_c[interior].mean():.6f}")
    print(f"  Test interior P:    {P_t[interior].mean():.6f}")
    print(f"  Difference:         {P_in_diff:.6f}")
    print(f"  Corrected leakage:  {leakage:.4f}")

    if leakage < 0.1:
        print("  -> Membrane isolation effective (PASS)")
    elif leakage < 0.3:
        print("  -> Minor leakage")
    else:
        print("  -> Severe leakage (FAIL)")

    return float(leakage)
