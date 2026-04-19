"""
ALS V2 global configuration.
Parameters proven to produce 6/6 autopoietic score over 81 consecutive runs.
All parameters live here. No hardcoded values elsewhere.
"""
import sys

GRID_SIZE = 128
RANDOM_SEED = 42

# -- Diffusion --
D_S = 0.20
D_P = 0.001
D_M = 0.0

# -- Membrane barrier (exponential) --
ALPHA_EXP_P = 15.0
ALPHA_EXP_S = 4.0

# -- Reaction: Hill-function autocatalysis --
K1 = 0.12
K_M = 0.08
K_BG = 0.0001
K_INHIBIT = 0.10
P_INHIBIT_THRESH = 0.35
P_DECAY = 0.10

# -- Decay ramp --
DECAY_RAMP_START = 5000
DECAY_RAMP_END = 15000

# -- Membrane --
K_GROWTH = 1.5
K_DECAY_M = 0.1
MEMBRANE_DETECT_WINDOW = 5
MEMBRANE_PROTECT_COEFF = 0.8
MEMBRANE_PROTECT_NORM = 0.3
NEIGHBOR_INHIBIT_STRENGTH = 10.0

# -- Environment --
S_SUPPLY = 0.015
S_MIN_INTERIOR = 0.01
S_INITIAL = 0.5
NOISE_AMP = 0.003

# -- Numerics --
DT = 0.05
S_CLIP_MAX = 10.0
P_CLIP_MAX = 10.0
M_CLIP_MAX = 1.0

# -- Simulation control --
MAX_STEPS = 60000
MONITOR_INTERVAL = 2000
SNAPSHOT_INTERVAL = 10000
VIZ_INTERVAL = 10000

# -- Performance --
INTERIOR_CACHE_INTERVAL = 50

# -- Diagnostics --
EXCISION_POST_STEPS = 3000
PARTIAL_EXCISION_RATIO = 0.5
MEMBRANE_THRESHOLD = 0.05
MIN_INTERIOR_PIXELS = 9
PERMEABILITY_TEST_STEPS = 500
PERMEABILITY_PULSE = 0.5


def validate_config():
    """Check parameter validity and CFL stability."""
    errors = []
    warnings = []

    cfl_s = DT * D_S
    cfl_p = DT * D_P
    if cfl_s >= 0.5:
        errors.append(f"CFL unstable: DT*D_S={cfl_s:.4f}>=0.5")
    if cfl_p >= 0.5:
        errors.append(f"CFL unstable: DT*D_P={cfl_p:.4f}>=0.5")

    for name, val in [('D_S', D_S), ('D_P', D_P), ('K1', K1), ('K_M', K_M),
                      ('K_BG', K_BG), ('K_INHIBIT', K_INHIBIT),
                      ('K_GROWTH', K_GROWTH), ('K_DECAY_M', K_DECAY_M),
                      ('S_SUPPLY', S_SUPPLY), ('DT', DT), ('P_DECAY', P_DECAY)]:
        if val < 0:
            errors.append(f"{name}={val} < 0")
        if val == 0 and name in ('K1', 'K_BG', 'DT'):
            errors.append(f"{name}=0, system won't evolve")

    if D_P > 0.05:
        warnings.append(f"D_P={D_P} high, P may not concentrate")
    if ALPHA_EXP_P < 5:
        warnings.append(f"ALPHA_EXP_P={ALPHA_EXP_P} low, suggest >=10")
    if DECAY_RAMP_START >= DECAY_RAMP_END:
        errors.append(f"DECAY_RAMP_START({DECAY_RAMP_START}) >= END({DECAY_RAMP_END})")

    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")
    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        sys.exit(1)

    print(f"  Config OK. CFL(S)={cfl_s:.4f} CFL(P)={cfl_p:.6f}")
