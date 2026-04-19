#!/usr/bin/env python3
"""Run the ALS simulation."""
import os
import sys
import time
import numpy as np
import scipy.ndimage

import config
from core.engine import init_fields, step
from viz.visualize import save_field_snapshot


def monitor(S, P, M, i, cfg):
    M_bin = (M > cfg.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, num = scipy.ndimage.label(M_bin)
    closed = 0
    for k in range(1, num + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        inside = filled & ~mask
        if inside.sum() > cfg.MIN_INTERIOR_PIXELS:
            closed += 1
    print(f"  Step {i:6d}: P[{P.min():.4f},{P.max():.4f}] "
          f"S.mean={S.mean():.4f} M.sum={M.sum():.1f} "
          f"domains={num} closed={closed}")
    return closed


def main():
    print("=" * 60)
    print("  ALS V2 - Simulation")
    print("=" * 60)
    print(f"  RANDOM_SEED = {config.RANDOM_SEED}")
    print(f"  MAX_STEPS   = {config.MAX_STEPS}")
    print(f"  Key params: D_P={config.D_P} ALPHA_EXP_P={config.ALPHA_EXP_P} "
          f"P_DECAY={config.P_DECAY} K_DECAY_M={config.K_DECAY_M}")

    os.makedirs('logs', exist_ok=True)
    os.makedirs('results', exist_ok=True)

    S, P, M = init_fields(config)
    t0 = time.time()

    for i in range(config.MAX_STEPS):
        S, P, M = step(S, P, M, config, step_count=i)

        if i % config.MONITOR_INTERVAL == 0:
            monitor(S, P, M, i, config)
            if i > 0:
                rate = i / (time.time() - t0)
                rem = (config.MAX_STEPS - i) / rate
                print(f"           {rate:.0f} steps/s, ~{rem:.0f}s remaining")

        if i > 0 and i % config.SNAPSHOT_INTERVAL == 0:
            np.savez_compressed(f'logs/fields_{i:06d}.npz',
                                S=S, P=P, M=M, step=i)

        if i > 0 and i % config.VIZ_INTERVAL == 0:
            save_field_snapshot(S, P, M, config, i)

    elapsed = time.time() - t0
    print(f"\n  Done. {elapsed:.1f}s ({config.MAX_STEPS/elapsed:.0f} steps/s)")

    np.savez_compressed('logs/final_state.npz',
                        S=S, P=P, M=M, step=config.MAX_STEPS)
    save_field_snapshot(S, P, M, config, config.MAX_STEPS)
    print("  Saved logs/final_state.npz")
    print("  Next: python3 run_diagnostics.py")


if __name__ == '__main__':
    main()
