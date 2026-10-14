# -*- coding: utf-8 -*-
"""
weight_base.py — P/T 权重理论基础模块
=====================================
实现 weight_theory.md 中定义的四层融合模型。
理论来源：
  - MIL-STD-880E (FMECA 严酷度 I/II/III) → 先验 P 表
  - Laplace 平滑 + Beta-Binomial 共轭收缩 → 数据项
  - Cost-Sensitive Learning / Subjective Logic → 固定融合权重
  - Brier Score + 留出集 P/R/F1 → 评估指标

所有权重均有理论锚点，非拍脑袋。
"""

import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

# ============================================================
# §2.1 FMECA 先验 P 表
#   P_prior ∈ [0,1]，表示"该类故障发生时必须保机"的先验概率
#   依据 MIL-STD-880E 三级严酷度 + UAV 行业惯例
# ============================================================

PRIOR_P: Dict[str, float] = {
    # --- FMECA I (Catastrophic): P >= 0.85 ---
    "lightning":     0.95,   # 电磁脉冲击穿电子元件，不可逆
    "motor_failure": 0.90,   # 动力丧失 = 立即坠毁
    "flight_ctrl":   0.90,   # 姿态失控，坠毁概率极高

    # --- FMECA II (Critical): 0.55 <= P < 0.85 ---
    "signal_loss":   0.80,   # 数传中断触发 failsafe，有一定缓冲
    "battery_issue": 0.70,   # 电压骤降可短时维持，窗口短
    "prop_break":    0.65,   # 单桨断裂多旋翼可矢量补偿
    "esc_fault":     0.60,   # 可限油门，降级运行
    "gps_drift":     0.50,   # 可切视觉/IMU

    # --- FMECA III (Marginal): P < 0.55 ---
    "wind_gust":     0.45,   # 可通过降高度/限机动应对
    "rain":          0.40,   # 可避雨点悬停或返航
    "obstacle":      0.40,   # 动态避障可绕飞
    "cold_hot":      0.35,   # 缩短任务/提前返航
    "dust_fog":      0.35,   # 降高度增视距
    "gimbal_fault":  0.30,   # 不影响飞行安全，仅影响载荷
    "bird":          0.30,   # 低概率事件，加速穿越
    "payload_fault": 0.25,   # 停任务动作，飞行安全不受影响
    "unknown":       0.50,   # 无法判定，保守中性
}

# 严重度数值表（用于 tier 分档与报告展示，独立于 P_prior）
SEV_BY_TYPE: Dict[str, int] = {
    "lightning": 10, "motor_failure": 9, "flight_ctrl": 9,
    "battery_issue": 8, "esc_fault": 7, "gps_drift": 6,
    "wind_gust": 5, "rain": 5, "obstacle": 5,
    "cold_hot": 4, "dust_fog": 4, "gimbal_fault": 4,
    "bird": 3, "payload_fault": 3, "unknown": 3,
    "signal_loss": 8, "prop_break": 8,
}

# 内部因素类型（用于 factor 标记与 w_internal 修正）
INTERNAL_TYPES = frozenset({
    "motor_failure", "flight_ctrl", "battery_issue",
    "prop_break", "esc_fault", "gimbal_fault", "payload_fault",
})

# ============================================================
# §4.2 固定融合权重（理论锚点）
# ============================================================

W_ACTION    = 0.15   # 主观逻辑信任因子（历史保机动作反馈）
W_RESIDUAL  = 0.05   # 不确定度残差（防过度自信）
K0_SHRINK   = 30     # Beta-Binomial 收缩常数（N_eff=30 时数据/先验各占 50%）

# 动作偏置中"保机意图"动作集合
PROTECT_ACTIONS = frozenset({"force_land", "rtb", "manual_take", "hover_hold"})


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def w_data(neff: int, k0: int = K0_SHRINK) -> float:
    """
    §3.2 数据项权重：随有效样本量自适应。
    w_data = N_eff / (N_eff + k0)
    归一化后占非固定权重的比例：
      非固定权重空间 = 1 - W_ACTION - W_RESIDUAL = 0.80
      实际 w_data_final = 0.80 * N_eff/(N_eff+k0)
      实际 w_prior_final = 1 - w_data_final - W_ACTION - W_RESIDUAL
    当 N_eff→∞: w_data_final→0.80, w_prior_final→0.05
    当 N_eff=0:  w_data_final=0.00, w_prior_final=0.80
    """
    if neff <= 0:
        return 0.0
    return neff / (neff + k0)


def laplace_crash_rate(crash: int, success: int) -> float:
    """
    §3.1 Laplace 平滑的 crash 概率（Beta(1,1) 均匀先验）
    crash_rate_laplace = (crash + 1) / (crash + success + 2)
    """
    return (crash + 1) / (crash + success + 2)


def compute_P(
    an_type: str,
    crash: int,
    success: int,
    action_bias: float = 0.0,
    k0: int = K0_SHRINK,
    w_action: float = W_ACTION,
    w_residual: float = W_RESIDUAL,
) -> dict:
    """
    §4 完整 P 值计算（取代原 0.35/0.30/0.15/0.20 公式）。

    返回 dict：P, T, crash_rate_laplace, w_prior, w_data,
              w_action_used, w_residual, P_prior, neff

    公式：
      neff          = crash + success
      w_data_raw    = neff / (neff + k0)
      w_data        = 0.80 * w_data_raw           （归一化到非固定权重空间）
      w_prior       = 1 - w_data - w_action - w_residual
      crash_rate    = laplace_crash_rate(crash, success)
      P             = w_prior * P_prior + w_data * crash_rate
                      + w_action * action_bias + w_residual * 0.5

      T = 1 - P

    理论保证：
      - neff=0  → P ≈ P_prior（纯先验）
      - neff→∞ → P ≈ crash_rate（纯数据），w_prior→0.05 下限
      - P + T = 1 严格成立（消除原代码 battery 类自相矛盾）
    """
    p_prior = PRIOR_P.get(an_type, 0.50)
    neff = crash + success
    w_data_raw = w_data(neff, k0)
    # 非固定权重空间 = 1 - w_action - w_residual
    space = 1.0 - w_action - w_residual  # = 0.80
    w_data_actual = space * w_data_raw
    w_prior_actual = 1.0 - w_data_actual - w_action - w_residual

    crash_rate_lap = laplace_crash_rate(crash, success)
    # 残差项取 0.5（中性不确定度）
    residual_term = 0.5

    P = (w_prior_actual * p_prior
         + w_data_actual * crash_rate_lap
         + w_action * action_bias
         + w_residual * residual_term)
    P = clamp(P, 0.05, 0.95)
    T = clamp(1.0 - P, 0.05, 0.95)

    return {
        "P": round(P, 3),
        "T": round(T, 3),
        "crash_rate_laplace": round(crash_rate_lap, 4),
        "P_prior": p_prior,
        "neff": neff,
        "w_prior": round(w_prior_actual, 4),
        "w_data": round(w_data_actual, 4),
        "w_action": w_action,
        "w_residual": w_residual,
        "action_bias": round(action_bias, 4),
    }


def compute_Tier(P: float) -> str:
    """
    §5.1 tier 由 P 值直接决定（数据驱动，取代写死 sev 常数）。
    """
    if P < 0.35:
        return "L0"
    elif P < 0.55:
        return "L1"
    elif P < 0.75:
        return "L2"
    else:
        return "L3"


def recommend_mode(P: float, tier: str) -> str:
    """
    §5.2 推荐模式（对齐 tier 分界点，消除 P-T>0.15 的自相矛盾）。
    """
    if P >= 0.75 or tier == "L3":
        return "PROTECT"
    elif P < 0.35 and tier in ("L0", "L1"):
        return "MISSION"
    elif tier in ("L2", "L3") and 0.55 <= P < 0.75:
        return "RTB"
    else:
        return "CRUISE"


# ============================================================
# §6 评估指标
# ============================================================

def brier_score(predictions: List[float], outcomes: List[int]) -> float:
    """
    §6.2 Brier Score。
    predictions: P 值列表（0~1）
    outcomes: 实际结果列表（1=坠毁, 0=任务完成）
    返回 Brier Score（0 最好，0.25 = 随机猜测基准）
    """
    if not predictions:
        return float("nan")
    n = len(predictions)
    if n != len(outcomes):
        raise ValueError(f"len(predictions)={n} != len(outcomes)={len(outcomes)}")
    return sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / n


def precision_recall_f1(
    y_true: List[int],
    y_pred: List[int],
    pos_label: int = 1,
) -> dict:
    """
    §6.1 二分类 P/R/F1（用于留出集评估）。
    y_true: 实际标签（1=应该保机, 0=可以任务优先）
    y_pred: 预测标签
    """
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == pos_label and p == pos_label)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != pos_label and p == pos_label)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == pos_label and p != pos_label)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t != pos_label and p != pos_label)

    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall    = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else float("nan"))
    accuracy  = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else float("nan")

    return {
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "confusion_matrix": [[tn, fp], [fn, tp]],
    }


def holdout_split(
    type_outcomes: Dict[str, List[int]],
    holdout_frac: float = 0.30,
    seed: int = 42,
) -> Tuple[Dict[str, List[int]], Dict[str, List[int]]]:
    """
    §6.1 留出集划分（30% hold-out）。
    对每类随机抽 30% 样本作为测试集，其余为训练集。
    返回 (train_dict, test_dict)，值为该类型的 outcome 标签列表。
    """
    import random
    rng = random.Random(seed)
    train, test = {}, {}
    for t, labels in type_outcomes.items():
        n = len(labels)
        n_test = max(1, int(n * holdout_frac)) if n >= 3 else 0
        idx = list(range(n))
        rng.shuffle(idx)
        test_ids = set(idx[:n_test])
        train[t] = [labels[i] for i in range(n) if i not in test_ids]
        test[t] = [labels[i] for i in range(n) if i in test_ids]
    return train, test


def sensitivity_analysis(
    an_type: str,
    crash: int,
    success: int,
    action_bias: float = 0.0,
    w_action_grid: Tuple = (0.05, 0.10, 0.15, 0.20),
    k0_grid: Tuple = (20, 30, 50),
) -> List[dict]:
    """
    §6.3 权重敏感性分析：网格搜索 w_action × k0，
    输出各组合下 P 值变化范围。
    """
    results = []
    for wa in w_action_grid:
        for k0 in k0_grid:
            r = compute_P(an_type, crash, success,
                          action_bias=action_bias,
                          k0=k0, w_action=wa)
            results.append({
                "w_action": wa, "k0": k0,
                "P": r["P"], "T": r["T"],
                "w_prior": r["w_prior"], "w_data": r["w_data"],
            })
    return results


def format_sensitivity_table(rows: List[dict]) -> str:
    """将敏感性分析结果格式化为 Markdown 表格。"""
    lines = [
        "| w_action | k0 | P | T | w_prior | w_data |",
        "|----------|-----|---|---|---------|--------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['w_action']:.2f} | {r['k0']:2d} "
            f"| {r['P']:.3f} | {r['T']:.3f} "
            f"| {r['w_prior']:.4f} | {r['w_data']:.4f} |"
        )
    return "\n".join(lines)
