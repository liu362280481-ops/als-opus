"""
Virtual excision tests.
Full: zero interior P -> membrane should collapse (retention < 0.3).
Partial: halve interior P -> membrane should recover (retention > 0.7).
"""
import numpy as np
import scipy.ndimage
from core.engine import step
from core.substrate import invalidate_cache, set_diagnostic_mode
from analysis.detector import detect_closed_units


def full_excision_test(S, P, M, config, post_steps=None):
    if post_steps is None:
        post_steps = config.EXCISION_POST_STEPS

    units, num_raw = detect_closed_units(M, P, S, config)
    results = []
    print(f"\n=== Full Excision Test ===")
    print(f"Closed units: {len(units)} (raw domains: {num_raw})")

    if not units:
        return results

    for i, unit in enumerate(units):
        print(f"\n  Unit {i+1}: area={unit['area']}px P_in={unit['P_inside']:.4f}")
        S_t, P_t, M_t = S.copy(), P.copy(), M.copy()

        # Metabolic inhibition: block P production AND flatten P to exterior mean
        # This eliminates the gradient signal that drives membrane growth
        inhibit_mask = unit['interior'].copy()
        P_exterior_mean = float(P_t[~scipy.ndimage.binary_fill_holes(unit['membrane'])].mean())
        P_t[unit['interior']] = P_exterior_mean

        M_before = float(M_t[unit['membrane']].sum())

        set_diagnostic_mode(True)
        for s in range(post_steps):
            S_t, P_t, M_t = step(S_t, P_t, M_t, config,
                                  step_count=config.MAX_STEPS + s,
                                  inhibit_mask=inhibit_mask)
        set_diagnostic_mode(False)

        M_after = float(M_t[unit['membrane']].sum())
        ratio = M_after / (M_before + 1e-9)

        if ratio < 0.3:
            verdict = "COLLAPSED"
        elif ratio < 0.7:
            verdict = "PARTIAL_COLLAPSE"
        else:
            verdict = "SURVIVED"

        print(f"    M_before={M_before:.2f} M_after={M_after:.2f} "
              f"retention={ratio:.3f} -> {verdict}")

        results.append({
            'unit_id': i + 1, 'area': unit['area'],
            'M_before': M_before, 'M_after': M_after,
            'ratio': ratio, 'verdict': verdict,
        })
    return results


def partial_excision_test(S, P, M, config, reduction=None, post_steps=None):
    if reduction is None:
        reduction = config.PARTIAL_EXCISION_RATIO
    if post_steps is None:
        post_steps = config.EXCISION_POST_STEPS

    units, _ = detect_closed_units(M, P, S, config)
    results = []
    print(f"\n=== Partial Excision Test (reduce {reduction*100:.0f}%) ===")
    print(f"Closed units: {len(units)}")

    if not units:
        return results

    for i, unit in enumerate(units):
        print(f"\n  Unit {i+1}: area={unit['area']}px")
        S_t, P_t, M_t = S.copy(), P.copy(), M.copy()
        P_t[unit['interior']] *= (1.0 - reduction)
        M_before = float(M_t[unit['membrane']].sum())

        set_diagnostic_mode(True)
        for s in range(post_steps):
            S_t, P_t, M_t = step(S_t, P_t, M_t, config,
                                  step_count=config.MAX_STEPS + s)
        set_diagnostic_mode(False)

        M_after = float(M_t[unit['membrane']].sum())
        ratio = M_after / (M_before + 1e-9)

        if ratio > 0.7:
            verdict = "RECOVERED"
        elif ratio > 0.3:
            verdict = "WEAK_RECOVERY"
        else:
            verdict = "COLLAPSED"

        print(f"    retention={ratio:.3f} -> {verdict}")
        results.append({
            'unit_id': i + 1, 'area': unit['area'],
            'ratio': ratio, 'verdict': verdict,
        })
    return results
