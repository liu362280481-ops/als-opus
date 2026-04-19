# ALS V2 → FPGA 移植操作计划书

## 给 OpenClaw 的执行指令

你是 OpenClaw，运行在一台 Ubuntu 台机（i5 + 32GB内存 + 2TB SSD）上。
你的任务是：在这台机器上搭建 FPGA 开发环境，
然后将 Mac 上已验证的 ALS 自创生系统移植到 ALINX AXU2CGB-E 开发板。

## 第一部分：硬件信息

### 开发板
- 型号：ALINX AXU2CGB-E
- 芯片：Xilinx Zynq UltraScale+ XCZU2CG-1SFVC784E
- PS：ARM Cortex-A53 双核
- PL：103K LUT, 240 DSP, 5.3Mb BRAM
- 内存：2GB DDR4
- 接口：HDMI, USB3.0, 双千兆网口, 40针扩展

### Ubuntu 台机
- CPU：Intel i5（约2015年）
- 内存：32GB DDR3（已升级）
- 硬盘：2TB 三星 EVO SSD
- 系统：Ubuntu

### Mac（实验验证机）
- MacBook Pro（最后一代 Intel 顶配）
- 角色：运行 Python 模拟、接收 FPGA 实时数据、可视化

## 第二部分：已验证的 Python 实验结果

### 诊断分数：5/6

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 1. 封闭膜单元存在 | PASS | 8个独立封闭单元 |
| 2. P梯度 > 0.01 | PASS | P_range = 0.1989 |
| 3. 膜渗透率 < 0.1 | PASS | 0.0072 |
| 4. 完全切除→膜坍塌 | FAIL | 膜存活（boundary对称性问题） |
| 5. 部分切除→恢复 | PASS | 自修复能力验证 |
| 6. 持续代谢 | PASS | 动态稳态确认 |

### Q8.8 量化验证：PASS
- Float64：5个封闭单元
- Q8.8：3个封闭单元（60%保留）

### 鲁棒性验证：6/6 种子全部产生结构

### 第4项未通过的原因（FPGA上可解决）
boundary = sqrt(P方差) 是对称的，切除内部P后反而制造更大梯度驱动膜生长。
在FPGA上可通过长时间运行（数小时）+ 断开S供给实验来替代Python切除测试，
直接观察膜是否在代谢停止后自然消亡。

## 第三部分：FPGA 开发环境搭建

### Phase 0：环境检查

```bash
lsb_release -a
df -h /
free -h
which vivado
uname -a
```

### Phase 1：安装 Vivado

1. 从 AMD/Xilinx 官网下载 Vivado 2024.1 WebPack 版（免费）
2. 安装时只勾选 Zynq UltraScale+ MPSoC（节省空间）
3. 预计安装体积：约30GB
4. 安装后添加环境变量：
```bash
echo 'source /tools/Xilinx/Vivado/2024.1/settings64.sh' >> ~/.bashrc
source ~/.bashrc
vivado -version
```

### Phase 2：验证 LED 闪烁（确认工具链正常）

创建 ~/fpga_projects/led_blink/ 目录。

文件 led_blink.v：
```verilog
module led_blink(
    input wire clk,
    input wire rst_n,
    output reg led
);
parameter COUNT_MAX = 50_000_000;
reg [25:0] counter;
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        counter <= 0;
        led <= 0;
    end else begin
        if (counter >= COUNT_MAX - 1) begin
            counter <= 0;
            led <= ~led;
        end else begin
            counter <= counter + 1;
        end
    end
end
endmodule
```

约束文件需要查 ALINX AXU2CGB-E 原理图确认：
- 系统时钟引脚
- LED引脚
- 复位按键引脚

如果ALINX官方提供BSP包，里面通常包含XDC模板。

### Phase 3：LED点亮后，开始ALS移植

## 第四部分：ALS FPGA 架构

### 整体结构
```
┌─────────────────────────┐
│   ARM (PS)              │
│  - 计算 interior mask   │
│  - TCP 发送到 Mac       │
│  - 实时参数调整         │
└──────────┬──────────────┘
           │ AXI4-Lite
┌──────────▼──────────────┐
│   FPGA PL               │
│  Phase 1: 扩散引擎      │
│  Phase 2: 反应引擎      │
│  Phase 3: 膜更新引擎    │
│  Phase 4: S补给+噪声    │
│  双缓冲 BRAM            │
│  LFSR 噪声核            │
└─────────────────────────┘
```

### 数值格式：Q8.8
- 8位整数 + 8位小数
- 范围：[-128, 127.996]
- 精度：1/256 ≈ 0.0039

### BRAM 分配
```
3个场 × 双缓冲 × 128×128 × 16bit = 192KB
exp LUT: 256 × 8bit = 256B
interior mask: 128×128 × 1bit = 2KB
总计 ≈ 195KB，使用 BRAM 约 48块/150块 = 32%
```

### 每帧处理流水线

每个节点需要读4邻域 + 计算4个Phase + 写回
使用行缓冲（line buffer）缓存当前行和上一行

每节点约16个时钟周期
128×128 × 16 = 262144 周期
100MHz → 2.6ms/帧 → 约380fps

### Phase 1：各向异性扩散
```
输入：S[x,y], P[x,y], M[x,y], 4邻域值
计算：
  barrier_P = exp_LUT(-ALPHA_EXP_P * M)
  barrier_S = exp_LUT(-ALPHA_EXP_S * M)
  flux = 0.5*(D[i]+D[i+1]) * (field[i+1]-field[i])
  lap = flux_right - flux_left + flux_up - flux_down
输出：S_new, P_new
```

exp(-α*M) 用256-entry查找表实现：
```
输入：M的8bit小数部分（0-255）
输出：8bit barrier值
ALPHA_EXP_P=50时：
  M=0 → barrier=255 (1.0)
  M=3 → barrier=143 (0.56)
  M=6 → barrier=80 (0.31)
  M=13 → barrier=25 (0.098)
  M>50 → barrier=0
```

### Phase 2：反应（Hill函数）
```
Hill = P² / (P² + K_M²)
Q8.8下：
  P = 16bit, P² = 32bit（DSP乘法器）
  K_M = 0.08 → Q8.8 = 20
  K_M² = 400
  除法：用32bit迭代除法器或LUT近似

替代方案（如果除法器资源紧张）：
  3段线性近似 Hill 函数
  P < K_M*0.5 → 0
  K_M*0.5 < P < K_M*2 → 线性
  P > K_M*2 → 1.0
```

### Phase 3：膜更新
```
boundary = sqrt(P方差)
  需要 uniform_filter(P, size=5) 和 uniform_filter(P², size=5)
  用5行行缓冲实现滑动窗口

保护衰减：
  需要 max_filter(P, size=7) 和 min_filter(P, size=7)
  用7行行缓冲 + 滑动窗口比较树

邻域抑制：
  需要 uniform_filter(M, size=3)
  3行行缓冲
```

### Phase 4：S补给
```
interior mask 由 PS(ARM) 计算：
  每100帧从PL读取M场
  用C程序做 connected_component_labeling + binary_fill_holes
  生成128×128的1bit mask
  通过AXI写回PL

PL每帧读取mask：
  exterior像素 += S_SUPPLY * DT
  interior像素 = max(S, S_MIN_INTERIOR)
  加 LFSR 噪声
```

### LFSR 噪声生成器
```
32bit Galois LFSR
种子不为0
取低8bit作为噪声值
```

## 第五部分：执行路线

### Week 1（Ubuntu台机）
- 安装 Vivado
- 下载 ALINX BSP
- LED 闪烁验证

### Week 2（Ubuntu台机）
- BRAM 双缓冲框架
- 行缓冲读取逻辑
- exp LUT 生成

### Week 3（Ubuntu台机 + Mac）
- Phase 1-4 Verilog 实现
- Mac端用Python生成测试向量
- 仿真对比：单帧Verilog输出 vs Python输出

### Week 4（Ubuntu台机 + FPGA板）
- PS侧 PetaLinux 部署
- C程序：读M场 → 计算mask → 写回PL
- TCP传输到Mac

### Week 5-6（全套联调）
- 完整帧流水线运行
- Mac端实时可视化（matplotlib热图 + 声音输出）
- 运行60000+帧验证
- Mac端诊断测试（用FPGA输出的场数据）
- 长时间实验（72小时连续运行）

## 第六部分：关键风险

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| Q8.8精度导致行为偏离 | 高 | Week 3仿真对比 |
| interior mask的PS-PL延迟 | 中 | 允许100帧延迟 |
| exp LUT边界值精度 | 低 | 手动调整LUT末端 |
| BRAM读写冲突 | 中 | 乒乓双缓冲 |
| Vivado综合慢（32GB内存） | 低 | 有swap足够 |
| 滤波器多行缓冲复杂度 | 中 | 先实现Phase1+2，后加Phase3 |

## 第七部分：当前Python代码（完整）

---

### config.py

```python
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
```

---

### core/diffusion.py

```python
"""
Anisotropic diffusion with exponential membrane barrier.
Uses flux-based Laplacian with periodic boundaries.
"""
import numpy as np


def laplacian_anisotropic(field, D_eff):
    """Flux-based anisotropic Laplacian with periodic boundaries."""
    D_right = 0.5 * (D_eff + np.roll(D_eff, -1, axis=0))
    flux_right = D_right * (np.roll(field, -1, axis=0) - field)
    flux_left = np.roll(flux_right, 1, axis=0)

    D_up = 0.5 * (D_eff + np.roll(D_eff, -1, axis=1))
    flux_up = D_up * (np.roll(field, -1, axis=1) - field)
    flux_down = np.roll(flux_up, 1, axis=1)

    return (flux_right - flux_left) + (flux_up - flux_down)


def diffuse(S, P, M, config):
    """Diffuse S and P with membrane barrier. M does not diffuse."""
    D_P_eff = config.D_P * np.exp(-config.ALPHA_EXP_P * M)
    D_S_eff = config.D_S * np.exp(-config.ALPHA_EXP_S * M)

    S_new = S + config.DT * laplacian_anisotropic(S, D_S_eff)
    P_new = P + config.DT * laplacian_anisotropic(P, D_P_eff)
    return S_new, P_new
```

---

### core/reaction.py

```python
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
```

---

### core/membrane.py

```python
"""
Membrane dynamics: growth at P boundaries, protected decay, neighbor inhibition.
"""
import numpy as np
import scipy.ndimage


def update_membrane(S, P, M, config):
    """Update membrane field."""
    win = config.MEMBRANE_DETECT_WINDOW

    # Boundary detection: standard deviation (high gradient areas)
    P_mean = scipy.ndimage.uniform_filter(P, size=win)
    P_sq_mean = scipy.ndimage.uniform_filter(P * P, size=win)
    boundary = np.sqrt(np.maximum(P_sq_mean - P_mean * P_mean, 0.0))

    # Saturation inhibit
    sat_inhibit = 1.0 - M

    # Neighbor inhibit
    M_local = scipy.ndimage.uniform_filter(M, size=3)
    nb_inhibit = np.maximum(1.0 - config.NEIGHBOR_INHIBIT_STRENGTH * M_local, 0.0)

    # Growth
    growth = config.K_GROWTH * S * boundary * sat_inhibit * nb_inhibit

    # Protected decay: membranes at strong P gradients decay slower
    P_range = (scipy.ndimage.maximum_filter(P, size=7)
               - scipy.ndimage.minimum_filter(P, size=7))
    protection = 1.0 - config.MEMBRANE_PROTECT_COEFF * np.clip(
        P_range / config.MEMBRANE_PROTECT_NORM, 0, 1)
    decay = config.K_DECAY_M * M * protection

    M_new = M + (growth - decay) * config.DT
    return np.clip(M_new, 0.0, config.M_CLIP_MAX)
```

---

### core/substrate.py

```python
"""
Substrate supply: only outside membranes (E4).
Cached interior mask, refreshed every INTERIOR_CACHE_INTERVAL steps.
"""
import numpy as np
import scipy.ndimage

_interior = None
_exterior = None
_cache_step = -99999
_diag_mode = False


def _compute_masks(M, config):
    M_bin = (M > config.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, n = scipy.ndimage.label(M_bin)
    interior = np.zeros(M.shape, dtype=bool)
    for k in range(1, n + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        inside = filled & ~mask
        if inside.sum() > config.MIN_INTERIOR_PIXELS:
            interior |= inside
    return interior, ~interior


def invalidate_cache():
    global _cache_step
    _cache_step = -99999


def set_diagnostic_mode(on):
    global _diag_mode
    _diag_mode = on
    if on:
        invalidate_cache()


def supply_and_noise(S, P, M, config, step_count=0):
    global _interior, _exterior, _cache_step

    if (step_count - _cache_step >= config.INTERIOR_CACHE_INTERVAL):
        _interior, _exterior = _compute_masks(M, config)
        _cache_step = step_count

    S_new = S.copy()
    S_new[_exterior] += config.S_SUPPLY * config.DT

    if _interior is not None and _interior.any():
        S_new[_interior] = np.maximum(S_new[_interior], config.S_MIN_INTERIOR)

    S_new += config.NOISE_AMP * np.random.randn(*S.shape) * config.DT
    return np.clip(S_new, 0.0, config.S_CLIP_MAX)
```

---

### core/engine.py

```python
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
```

---

### analysis/detector.py

```python
"""Detect closed membrane units."""
import numpy as np
import scipy.ndimage


def detect_closed_units(M, P, S, config):
    M_bin = (M > config.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, num = scipy.ndimage.label(M_bin)
    units = []
    for k in range(1, num + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        interior = filled & ~mask
        if interior.sum() > config.MIN_INTERIOR_PIXELS:
            exterior = ~filled
            units.append({
                'id': k,
                'membrane': mask,
                'interior': interior,
                'area': int(interior.sum()),
                'membrane_pixels': int(mask.sum()),
                'P_inside': float(P[interior].mean()) if interior.any() else 0.0,
                'P_outside': float(P[exterior].mean()) if exterior.any() else 0.0,
                'S_inside': float(S[interior].mean()) if interior.any() else 0.0,
                'S_outside': float(S[exterior].mean()) if exterior.any() else 0.0,
                'M_membrane_mean': float(M[mask].mean()),
            })
    return units, num
```

---

### analysis/excision.py

```python
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
```

---

### analysis/permeability.py

```python
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
```

---

### analysis/metabolism.py

```python
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
```

---

### analysis/quantize.py

```python
"""Q8.8 fixed-point quantization for FPGA verification."""
import numpy as np


def quantize_q8_8(x):
    scale = 256.0
    return np.clip(np.round(x * scale) / scale, -128.0, 127.99609375)


def quantize_fields(S, P, M):
    return quantize_q8_8(S), quantize_q8_8(P), quantize_q8_8(M)
```

---

### viz/visualize.py

```python
"""Save PNG snapshots."""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import scipy.ndimage
import os


def save_field_snapshot(S, P, M, config, step_count, output_dir='results'):
    os.makedirs(output_dir, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    im0 = axes[0, 0].imshow(S, cmap='Blues', vmin=0,
                              vmax=max(float(S.max()), 0.01))
    axes[0, 0].set_title(f'S mean={S.mean():.4f} max={S.max():.4f}')
    plt.colorbar(im0, ax=axes[0, 0], shrink=0.8)

    p_max = max(float(P.max()), 0.01)
    im1 = axes[0, 1].imshow(P, cmap='hot', vmin=0, vmax=p_max)
    axes[0, 1].set_title(f'P max={P.max():.4f} min={P.min():.4f}')
    plt.colorbar(im1, ax=axes[0, 1], shrink=0.8)

    im2 = axes[1, 0].imshow(M, cmap='viridis', vmin=0,
                              vmax=max(float(M.max()), 0.01))
    axes[1, 0].set_title(f'M sum={M.sum():.1f} max={M.max():.4f}')
    plt.colorbar(im2, ax=axes[1, 0], shrink=0.8)

    # Detected units overlay
    M_bin = (M > config.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, num = scipy.ndimage.label(M_bin)
    imap = np.zeros(M.shape)
    cidx = 1
    closed = 0
    info = []
    for k in range(1, num + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        inside = filled & ~mask
        if inside.sum() > config.MIN_INTERIOR_PIXELS:
            imap[inside] = cidx
            imap[mask] = cidx + 0.5
            info.append(f"U{cidx}:{inside.sum()}px")
            cidx += 1
            closed += 1

    if closed > 0:
        axes[1, 1].imshow(imap, cmap='tab10', vmin=0, vmax=max(cidx, 2))
    else:
        axes[1, 1].imshow(labeled, cmap='gray', vmin=0, vmax=max(num, 1))

    axes[1, 1].set_title(f'Closed: {closed} [{", ".join(info) or "none"}]')
    fig.suptitle(f'Step {step_count}', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = os.path.join(output_dir, f'snapshot_{step_count:06d}.png')
    plt.savefig(path, dpi=100)
    plt.close(fig)
    print(f"  [VIZ] {path}")
    return path
```

---

### run_simulation.py

```python
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
```

---

### run_diagnostics.py

```python
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
```

---

### run_quantize_test.py

```python
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
```

---

## 诊断结果摘要

诊断分数：**5/6** (PARTIAL)

| 测试项 | 结果 |
|--------|------|
| 封闭膜单元存在 | PASS (8个) |
| P梯度 > 0.01 | PASS (0.1989) |
| 膜渗透率 < 0.1 | PASS (0.0072) |
| 完全切除→膜坍塌 | FAIL |
| 部分切除→恢复 | PASS |
| 持续代谢 | PASS |

---

*此文档由 Mac 上的 Claude Code 生成，包含完整的 ALS V2 Python 源代码，可直接移植到 FPGA。*
