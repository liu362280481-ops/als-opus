# ALS V2 FPGA 部署指南

> 给 OpenClaw 的完整执行方案
> Ubuntu 台机 (i5 + 32GB + 2TB SSD) → ALINX AXU2CGB-E 开发板

---

## 第一步：环境准备

### 1.1 检查系统环境
```bash
lsb_release -a
df -h /
free -h
uname -a
```

### 1.2 安装 Vivado 2024.1

1. 从 AMD/Xilinx 官网下载 Vivado 2024.1 WebPack（免费）
2. 安装时**只勾选** Zynq UltraScale+ MPSoC（节省空间）
3. 预计安装体积：约 30GB
4. 安装后配置环境变量：
```bash
echo 'source /tools/Xilinx/Vivado/2024.1/settings64.sh' >> ~/.bashrc
source ~/.bashrc
vivado -version
```

---

## 第二步：解压项目

```bash
# 将压缩包传到 Ubuntu 后解压
tar -xzf als_v2_final_20260323.tar.gz
cd als_v2

# 验证解压成功
ls -la
```

---

## 第三步：下载 ALINX BSP

```bash
# 创建 FPGA 项目目录
mkdir -p ~/fpga_projects
cd ~/fpga_projects

# 从 ALINX 官网下载 AXU2CGB-E 开发板支持包
# 官方链接: https://www.alinx.com/product/176.html

# 解压 BSP（根据下载的文件名）
unzip alinx_axu2cgb.zip
```

---

## 第四步：LED 闪烁验证（必做）

创建 `~/fpga_projects/led_blink/` 目录：

### 4.1 创建 Verilog 文件 led_blink.v
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

### 4.2 创建约束文件（根据原理图确定引脚）
```bash
# 参考 ALINX AXU2CGB-E 原理图
# 系统时钟: E3 (50MHz)
# LED: H5, H6, J4, J5
# 复位: T18
```

### 4.3 综合并烧录
```bash
source /tools/Xilinx/Vivado/2024.1/settings64.sh
cd ~/fpga_projects/led_blink
vivado -mode batch -source create_project.tcl
vivado -mode batch -source implement.tcl
```

LED 闪烁成功 → 工具链正常 → 进入下一步

---

## 第五步：ALS 移植

### 5.1 理解架构

```
┌─────────────────────────┐
│   ARM (PS)              │  ← 计算 interior mask, TCP 传输
└──────────┬──────────────┘
           │ AXI4-Lite
┌──────────▼──────────────┐
│   FPGA PL               │  ← 核心计算引擎
│  Phase 1: 扩散引擎      │
│  Phase 2: 反应引擎      │
│  Phase 3: 膜更新引擎    │
│  Phase 4: S补给+噪声    │
└─────────────────────────┘
```

### 5.2 数值格式
- **Q8.8 定点数**：8位整数 + 8位小数
- 范围：[-128, 127.996]
- 精度：1/256 ≈ 0.0039

### 5.3 BRAM 资源
```
3个场 × 双缓冲 × 128×128 × 16bit = 192KB
exp LUT: 256 × 8bit = 256B
interior mask: 128×128 × 1bit = 2KB
总计 ≈ 195KB (BRAM 约 32%)
```

### 5.4 实现步骤

#### Week 2：基础框架
- BRAM 双缓冲设计
- 行缓冲读取逻辑
- exp 查找表生成

#### Week 3：核心计算
- Phase 1: 各向异性扩散
- Phase 2: Hill 函数反应
- Phase 3: 膜更新
- Phase 4: S 补给 + LFSR 噪声

#### Week 4：PS 侧开发
- PetaLinux 部署
- C 程序：connected_component_labeling + binary_fill_holes
- TCP 传输到 Mac

---

## 第六步：与 Mac 联调

### Mac 端准备
```bash
# Mac 上运行 Python 可视化接收端
cd ~/novel2character
python3 app.py
# 访问 http://localhost:5001
```

### FPGA 端
- 100MHz 时钟 → 约 380 fps
- 通过 TCP 实时传输场数据
- Mac 端显示热图 + 诊断

---

## 第七步：验证

### 目标
- 运行 60000+ 帧
- 诊断分数 ≥ 5/6
- 长时间稳定运行 72 小时

### 诊断命令（在 Mac 上）
```bash
cd ~/als_v2
python3 run_diagnostics.py
```

---

## 关键参数（从 config.py）

| 参数 | 值 | 说明 |
|------|-----|------|
| GRID_SIZE | 128 | 场大小 |
| D_P | 0.001 | P 扩散系数 |
| D_S | 0.20 | S 扩散系数 |
| ALPHA_EXP_P | 15.0 | 膜屏障强度 |
| K1 | 0.12 | 反应速率 |
| K_M | 0.08 | Hill 常数 |
| K_GROWTH | 1.5 | 膜生长速率 |
| K_DECAY_M | 0.1 | 膜衰减速率 |
| S_SUPPLY | 0.015 | S 补给率 |
| DT | 0.05 | 时间步长 |

---

## 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| Q8.8 精度偏离 | 高 | Week 3 仿真对比 |
| PS-PL 延迟 | 中 | 允许 100 帧延迟 |
| BRAM 冲突 | 中 | 乒乓双缓冲 |
| 综合慢 | 低 | 32GB 内存足够 |

---

## 联系

- Mac 端实验结果：见 `results/diagnostic_results.json`
- 完整源码：见 `FPGA_HANDOFF.md`
- 项目压缩包：`als_v2_final_20260323.tar.gz`

---

*此 README 由 Claude Code 生成，按照步骤执行即可完成 FPGA 部署。*
