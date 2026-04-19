import numpy as np
import scipy.ndimage
import sys
sys.path.insert(0, '/Users/apple/als_v2')

from core.engine import step
import config
np.random.seed(42)

S = np.full((config.GRID_SIZE, config.GRID_SIZE), 0.5)
P = np.zeros((config.GRID_SIZE, config.GRID_SIZE))
M = np.zeros((config.GRID_SIZE, config.GRID_SIZE))
P += 0.001 * np.random.randn(config.GRID_SIZE, config.GRID_SIZE)
P = np.clip(P, 0, None)

print("运行到稳定态（40000步）...")
for i in range(40000):
    S, P, M = step(S, P, M, config, step_count=i)
    if i % 10000 == 0:
        print(f"  Step {i}: M.sum={M.sum():.1f}")

print("\n=== 虚拟切除测试 ===")
M_binary = (M > 0.05).astype(int)
labeled, num_units = scipy.ndimage.label(M_binary)

closed_units = []
for k in range(1, num_units + 1):
    unit_mask = (labeled == k)
    filled = scipy.ndimage.binary_fill_holes(unit_mask)
    interior = filled & ~unit_mask
    if interior.sum() > 9:
        closed_units.append({
            'id': k,
            'membrane': unit_mask,
            'interior': interior,
            'area': int(interior.sum()),
            'P_inside_before': float(P[interior].mean()),
            'M_before': float(M[unit_mask].sum())
        })

print(f"检测到 {len(closed_units)} 个封闭单元")
if not closed_units:
    print("没有封闭单元，退出")
    sys.exit(0)

for u in closed_units:
    print(f"\n--- 单元{u['id']} 面积={u['area']}格 ---")
    print(f"切除前: P内部={u['P_inside_before']:.6f} M膜量={u['M_before']:.4f}")
    S_t = S.copy()
    P_t = P.copy()
    M_t = M.copy()
    P_t[u['interior']] = 0.0
    for i in range(3000):
        S_t, P_t, M_t = step(S_t, P_t, M_t, config, step_count=50000+i)
    M_after = float(M_t[u['membrane']].sum())
    P_after = float(P_t[u['interior']].mean())
    ratio = M_after / (u['M_before'] + 1e-9)
    print(f"切除后3000步: P内部={P_after:.6f} M膜量={M_after:.4f}")
    print(f"膜保留率: {ratio:.3f}")
    if ratio < 0.3:
        print("★ 膜崩溃 → 真正自创生")
    elif ratio < 0.7:
        print("△ 膜部分保留 → 弱依赖")
    else:
        print("✗ 膜不崩溃 → 静态结构")
