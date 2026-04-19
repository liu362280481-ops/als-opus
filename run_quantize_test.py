#!/usr/bin/env python3
"""Q8.8 quantization verification."""
import numpy as np
import os

import config
from core.engine import step
from analysis.quantize import quantize_fields
from analysis.detector import detect_closed_units


def main():
    print("=" * 60)
    print("  ALS V2 - Q8.8 Quantization Test")
    print("=" * 60)

    f = 'logs/final_state.npz'
    if not os.path.exists(f):
        print(f"  ERROR: {f} not found.")
        return

    data = np.load(f)
    S, P, M = data['S'], data['P'], data['M']
    test_steps = 5000

    # Float64 branch
    S_a, P_a, M_a = S.copy(), P.copy(), M.copy()
    # Q8.8 branch
    S_b, P_b, M_b = quantize_fields(S.copy(), P.copy(), M.copy())

    rng = np.random.RandomState(42)
    seeds = rng.randint(0, 2**31, size=test_steps)

    print(f"  Running {test_steps} steps...\n")
    for i in range(test_steps):
        sc = config.MAX_STEPS + i

        np.random.seed(seeds[i])
        S_a, P_a, M_a = step(S_a, P_a, M_a, config, step_count=sc)

        np.random.seed(seeds[i])
        S_b, P_b, M_b = step(S_b, P_b, M_b, config, step_count=sc)
        S_b, P_b, M_b = quantize_fields(S_b, P_b, M_b)

        if i % 1000 == 0:
            ua, _ = detect_closed_units(M_a, P_a, S_a, config)
            ub, _ = detect_closed_units(M_b, P_b, S_b, config)
            print(f"  +{i}: float64={len(ua)} Q8.8={len(ub)} "
                  f"M_diff={np.abs(M_a-M_b).mean():.6f}")

    ua, _ = detect_closed_units(M_a, P_a, S_a, config)
    ub, _ = detect_closed_units(M_b, P_b, S_b, config)

    print(f"\n  Final: float64={len(ua)} units, Q8.8={len(ub)} units")
    print(f"  M.sum: float64={M_a.sum():.1f} Q8.8={M_b.sum():.1f}")
    print(f"  M_diff_mean={np.abs(M_a-M_b).mean():.6f}")

    if len(ua) == 0:
        print("\n  WARNING: float64 branch lost structure")
    elif len(ub) >= max(len(ua) * 0.5, 1):
        print("\n  PASS: Q8.8 preserves structure - FPGA viable")
    else:
        print("\n  FAIL: Q8.8 destroys structure")


if __name__ == '__main__':
    main()
