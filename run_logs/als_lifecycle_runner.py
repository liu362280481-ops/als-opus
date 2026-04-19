#!/usr/bin/env python3
"""
ALS V4 Long-Term Lifecycle Runner
无干预，只观察，直到自然死亡，记录数据。
"""
import os
import sys
import time
import json
import csv
import numpy as np
import scipy.ndimage

# 锁定项目路径（向上找到ALS-OPUS根目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # run_logs/ -> ALS-OPUS/
LOG_DIR = SCRIPT_DIR  # 日志写在 run_logs/ 里
os.makedirs(LOG_DIR, exist_ok=True)

# 导入ALS核心（不修改任何源码）
sys.path.insert(0, PROJECT_DIR)
import config
from core.engine import init_fields, step

# ============================================================================
# 监控记录（来自 run_simulation.py 的 monitor() 逻辑）
# ============================================================================
def get_field_stats(S, P, M, cfg):
    """采集当前场的所有统计指标"""
    M_bin = (M > cfg.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, num = scipy.ndimage.label(M_bin)
    closed = 0
    for k in range(1, num + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        inside = filled & ~mask
        if inside.sum() > cfg.MIN_INTERIOR_PIXELS:
            closed += 1
    return {
        "P_min": float(P.min()),
        "P_max": float(P.max()),
        "P_range": float(P.max() - P.min()),
        "S_mean": float(S.mean()),
        "M_sum": float(M.sum()),
        "M_mean": float(M.mean()),
        "M_max": float(M.max()),
        "num_domains": int(num),
        "closed_units": int(closed),
    }

# ============================================================================
# 死亡判定
# ============================================================================
DEATH_M_SUM_THRESHOLD = 0.5       # M.sum 低于此值认为死亡
DEATH_PEAK_RATIO = 0.05           # M.sum 跌至峰值的此比例认为死亡
STALL_CHECK_WINDOW = 5000          # 连续多少步无反弹则判定死亡

def detect_death(stats_history, peak_M_sum):
    """判断系统是否已死亡"""
    if len(stats_history) < 10:
        return False
    recent = stats_history[-STALL_CHECK_WINDOW:]
    if len(recent) < 10:
        return False
    # 条件1: M.sum 跌至峰值的 5% 以下
    if peak_M_sum > DEATH_M_SUM_THRESHOLD:
        if recent[-1]["M_sum"] < peak_M_sum * DEATH_PEAK_RATIO:
            return True
    # 条件2: M.sum 长期低于阈值
    if recent[-1]["M_sum"] < DEATH_M_SUM_THRESHOLD:
        # 确认连续多步没有反弹
        if all(s["M_sum"] < DEATH_M_SUM_THRESHOLD for s in recent[-10:]):
            return True
    return False

# ============================================================================
# 单周期运行
# ============================================================================
def run_cycle(cycle_num, max_steps=999999):
    """运行一个完整生命周期"""
    start_time = time.time()
    print(f"\n{'='*60}")
    print(f"  Cycle {cycle_num:03d}  START")
    print(f"{'='*60}")

    S, P, M = init_fields(config)
    step_count = 0
    peak_M_sum = 0.0
    peak_step = 0
    stats_history = []

    while step_count < max_steps:
        S, P, M = step(S, P, M, config, step_count=step_count)
        step_count += 1

        # 监控记录
        if step_count % config.MONITOR_INTERVAL == 0:
            stats = get_field_stats(S, P, M, config)
            stats["step"] = step_count
            stats["wall_time_s"] = round(time.time() - start_time, 2)
            stats_history.append(stats)

            # 更新峰值
            if stats["M_sum"] > peak_M_sum:
                peak_M_sum = stats["M_sum"]
                peak_step = step_count

            print(f"  Step {step_count:6d} | "
                  f"P=[{stats['P_min']:.4f},{stats['P_max']:.4f}] "
                  f"S_mean={stats['S_mean']:.4f} "
                  f"M_sum={stats['M_sum']:.2f} "
                  f"domains={stats['num_domains']} "
                  f"closed={stats['closed_units']}")

            # 死亡检测
            if detect_death(stats_history, peak_M_sum):
                death_stats = stats
                break
    else:
        # 达到最大步数仍未死（不太可能）
        death_stats = stats_history[-1] if stats_history else {}

    elapsed = time.time() - start_time
    print(f"\n  Cycle {cycle_num:03d}  DEAD at step {step_count} "
          f"(peak M_sum={peak_M_sum:.2f} at step {peak_step}, "
          f"elapsed={elapsed:.1f}s)")

    return {
        "cycle_num": cycle_num,
        "death_step": step_count,
        "peak_M_sum": peak_M_sum,
        "peak_step": peak_step,
        "elapsed_s": round(elapsed, 2),
        "stats_history": stats_history,
        "death_stats": death_stats,
    }

# ============================================================================
# 主程序：10小时连续压测
# ============================================================================
TOTAL_HOURS = 10
TOTAL_SECONDS = TOTAL_HOURS * 3600
WALL_START = time.time()

def main():
    print("=" * 60)
    print("  ALS V4 Long-Term Lifecycle Runner")
    print(f"  Total runtime: {TOTAL_HOURS} hours")
    print(f"  Log dir: {LOG_DIR}")
    print("=" * 60)

    cycle_num = 0
    all_cycle_results = []

    while (time.time() - WALL_START) < TOTAL_SECONDS:
        cycle_num += 1
        remaining = TOTAL_SECONDS - (time.time() - WALL_START)
        print(f"\n  [Wall clock: {remaining/3600:.1f}h remaining]")

        result = run_cycle(cycle_num)

        # 记录死亡时刻的场快照（只保存M场摘要，不保存完整数组以省空间）
        death_record = {
            "cycle": cycle_num,
            "death_step": result["death_step"],
            "peak_M_sum": result["peak_M_sum"],
            "peak_step": result["peak_step"],
            "elapsed_s": result["elapsed_s"],
            "final_M_stats": result["death_stats"],
            "peak_M_stats": next(
                (s for s in result["stats_history"]
                 if s["step"] == result["peak_step"]),
                result["stats_history"][-1] if result["stats_history"] else {}
            ),
        }

        # 保存CSV（所有监控点）
        csv_path = os.path.join(LOG_DIR, f"cycle_{cycle_num:03d}_stats.csv")
        with open(csv_path, "w", newline="") as f:
            if result["stats_history"]:
                writer = csv.DictWriter(f, fieldnames=result["stats_history"][0].keys())
                writer.writeheader()
                writer.writerows(result["stats_history"])
        print(f"  CSV saved: {csv_path}")

        # 保存JSON（周期总结）
        json_path = os.path.join(LOG_DIR, f"cycle_{cycle_num:03d}_summary.json")
        with open(json_path, "w") as f:
            json.dump(death_record, f, indent=2)
        print(f"  JSON saved: {json_path}")

        all_cycle_results.append(death_record)

    # =========================================================================
    # 10小时结束：生成总报告
    # =========================================================================
    print(f"\n{'='*60}")
    print("  10-HOUR RUN COMPLETE — SUMMARY")
    print(f"{'='*60}")
    total_elapsed = time.time() - WALL_START

    for r in all_cycle_results:
        print(f"  Cycle {r['cycle']:3d} | died@step {r['death_step']:6d} | "
              f"peak_M={r['peak_M_sum']:.1f}@step{r['peak_step']} | "
              f"life_span={r['elapsed_s']:.0f}s")

    # 保存总报告
    summary = {
        "total_hours": TOTAL_HOURS,
        "total_cycles": cycle_num,
        "total_elapsed_s": round(total_elapsed, 2),
        "all_cycles": all_cycle_results,
    }
    summary_path = os.path.join(LOG_DIR, "10hour_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary: {summary_path}")

if __name__ == "__main__":
    main()
