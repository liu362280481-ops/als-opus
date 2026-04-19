#!/usr/bin/env python3
"""
Full diagnostic suite. Loads final_state.npz, runs 6 tests, outputs score.
"""
import os
import sys
import json
import numpy as np

import config
from core.substrate import invalidate_cache
from analysis.detector import detect_closed_units
from analysis.excision import full_excision_test, partial_excision_test
from analysis.permeability import permeability_test
from analysis.metabolism import metabolism_test


def main():
    print("=" * 60)
    print("  ALS V2 - Diagnostics")
    print("=" * 60)

    f = 'logs/final_state.npz'
    if not os.path.exists(f):
        print(f"  ERROR: {f} not found. Run simulation first.")
        sys.exit(1)

    data = np.load(f)
    S, P, M = data['S'], data['P'], data['M']
    sim_step = int(data['step'])

    print(f"  Loaded step {sim_step}")
    print(f"  S: mean={S.mean():.4f} max={S.max():.4f}")
    print(f"  P: mean={P.mean():.4f} max={P.max():.4f} min={P.min():.4f}")
    print(f"  M: sum={M.sum():.1f} max={M.max():.4f}")

    # -- Detect units --
    units, num_raw = detect_closed_units(M, P, S, config)
    print(f"\n  Closed units: {len(units)} (raw domains: {num_raw})")
    for u in units:
        print(f"    Unit{u['id']}: area={u['area']}px "
              f"P_in={u['P_inside']:.4f} P_out={u['P_outside']:.4f} "
              f"M_mean={u['M_membrane_mean']:.4f}")

    # -- Permeability --
    invalidate_cache()
    leakage = permeability_test(S, P, M, config) if units else None

    # -- Full excision --
    invalidate_cache()
    full_res = full_excision_test(S, P, M, config) if units else []

    # -- Partial excision --
    invalidate_cache()
    part_res = partial_excision_test(S, P, M, config) if units else []

    # -- Metabolism --
    invalidate_cache()
    metab = metabolism_test(S, P, M, config) if units else None

    # === SCORING ===
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)

    has_closed = len(units) > 0
    p_range = float(P.max() - P.min())
    has_gradient = p_range > 0.01
    perm_ok = leakage is not None and leakage < 0.1
    any_collapsed = any(r['verdict'] == 'COLLAPSED' for r in full_res)
    all_collapsed = all(r['verdict'] == 'COLLAPSED' for r in full_res) if full_res else False
    any_recovered = any(r['verdict'] == 'RECOVERED' for r in part_res)
    is_met = metab is not None and metab.get('is_metabolizing', False)

    checks = [
        ("1. Closed units exist",            has_closed),
        ("2. P gradient > 0.01",             has_gradient),
        ("3. Permeability < 0.1",            perm_ok),
        ("4. Full excision: any collapse",   any_collapsed),
        ("5. Partial excision: any recover",  any_recovered),
        ("6. Ongoing metabolism",            is_met),
    ]

    score = 0
    for name, passed in checks:
        score += int(passed)
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}")

    print(f"\n  Score: {score}/6")

    # Extended info
    if full_res:
        n_collapsed = sum(1 for r in full_res if r['verdict'] == 'COLLAPSED')
        print(f"\n  Excision detail: {n_collapsed}/{len(full_res)} units collapsed")
        if not all_collapsed:
            survived = [r for r in full_res if r['verdict'] != 'COLLAPSED']
            for r in survived:
                print(f"    Unit {r['unit_id']} SURVIVED "
                      f"(retention={r['ratio']:.3f}) - may be static structure")

    if leakage is not None:
        print(f"  Permeability: {leakage:.4f}")
    print(f"  P range: {p_range:.4f}")

    if score == 6:
        verdict = "FULLY_AUTOPOIETIC"
        print(f"\n  VERDICT: {verdict}")
    elif score >= 4:
        verdict = "PARTIAL"
        print(f"\n  VERDICT: {verdict} - needs tuning")
    elif has_closed:
        verdict = "STRUCTURED_BUT_STATIC"
        print(f"\n  VERDICT: {verdict}")
    else:
        verdict = "NO_STRUCTURE"
        print(f"\n  VERDICT: {verdict}")

    # Save results
    os.makedirs('results', exist_ok=True)
    result = {
        'verdict': verdict,
        'score': score,
        'seed': config.RANDOM_SEED,
        'sim_steps': sim_step,
        'num_closed': len(units),
        'p_range': p_range,
        'p_max': float(P.max()),
        'p_min': float(P.min()),
        'm_sum': float(M.sum()),
        'permeability': leakage,
        'full_excision': [r['verdict'] for r in full_res],
        'full_excision_detail': full_res,
        'partial_excision': [r['verdict'] for r in part_res],
        'is_metabolizing': is_met,
        'all_units_collapsed': all_collapsed,
        'config': {k: getattr(config, k) for k in [
            'D_P', 'K1', 'K_M', 'K_BG', 'P_DECAY', 'K_GROWTH',
            'K_DECAY_M', 'ALPHA_EXP_P', 'S_SUPPLY',
            'NEIGHBOR_INHIBIT_STRENGTH', 'MAX_STEPS', 'RANDOM_SEED']},
    }

    with open('results/diagnostic_results.json', 'w') as fh:
        json.dump(result, fh, indent=2, default=str)
    print(f"  Saved results/diagnostic_results.json")

    return verdict, score


if __name__ == '__main__':
    main()
