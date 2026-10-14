# -*- coding: utf-8 -*-
"""
校准：用 Video_Action_DB_cleaned.xlsx 的真实 outcome 分布，
按 weight_theory.md 的四层融合模型（先验 + Laplace 数据项 + 动作偏置 + 残差）
重生成 Decision_Matrix.xlsx。
输出 Calibrate_Report.md 记录：
  - 参数来源（理论锚点）
  - 留出集 P/R/F1 + 混淆矩阵
  - Brier Score
  - 权重敏感性分析
"""
import os, json, random
from collections import Counter
from openpyxl import load_workbook, Workbook

from weight_base import (
    PRIOR_P, SEV_BY_TYPE, INTERNAL_TYPES,
    compute_P, compute_Tier, recommend_mode,
    brier_score, precision_recall_f1, holdout_split,
    sensitivity_analysis, format_sensitivity_table,
    K0_SHRINK, W_ACTION, W_RESIDUAL, PROTECT_ACTIONS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "output", "Video_Action_DB_cleaned.xlsx")
AE  = os.path.join(HERE, "output", "Anomaly_Events.xlsx")
OUT = os.path.join(HERE, "output", "Decision_Matrix_Calibrated.xlsx")
REP = os.path.join(HERE, "output", "Calibrate_Report.md")

# ---------- 读源数据 ----------
wb = load_workbook(SRC)
ws = wb.active
hdr = [c.value for c in ws[1]]
idx = {n: i for i, n in enumerate(hdr)}

outcome_by_type = {}      # accident_type -> [outcome_labels]  (1=crash, 0=success, None=unknown)
action_by_type = {}       # accident_type -> Counter(actions)
type_outcomes_binary = {} # accident_type -> [1 if crash else 0]（排除 unknown）

for r in ws.iter_rows(min_row=2, values_only=True):
    t = r[idx["accident_type"]]
    if not t or t in ("unknown",):
        continue
    o = r[idx["outcome"]]
    outcome_by_type.setdefault(t, []).append(o)
    if o == "crash":
        type_outcomes_binary.setdefault(t, []).append(1)
    elif o == "success":
        type_outcomes_binary.setdefault(t, []).append(0)
    if r[idx["actions"]]:
        ac = action_by_type.setdefault(t, Counter())
        for a in str(r[idx["actions"]]).split(","):
            ac[a.strip()] += 1

# ---------- 从 Anomaly_Events 读 factor（若存在） ----------
factor_map = {}
wb2 = load_workbook(AE)
ws2 = wb2.active
ae_hdr = [c.value for c in ws2[1]]
ae_idx = {n: i for i, n in enumerate(ae_hdr)}
for r in ws2.iter_rows(min_row=2, values_only=True):
    at = r[ae_idx["Anomaly_Type"]]
    if at:
        factor_map[at] = r[ae_idx["Factor"]]

# 类型名映射：Video_Action 用名 -> Anomaly 事件名
type_map = {
    "battery": "battery_issue", "motor_fault": "motor_failure",
    "gimbal": "gimbal_fault", "signal_loss": "signal_loss",
    "gps": "gps_drift", "wind": "wind_gust", "rain": "rain",
    "lightning": "lightning", "bird": "bird", "obstacle": "obstacle",
    "cold": "cold_hot", "prop_break": "prop_break", "crash_general": "unknown",
}

def action_bias_of(t):
    acts = action_by_type.get(t, Counter())
    total = sum(acts.values()) or 1
    prot = sum(v for k, v in acts.items() if k in PROTECT_ACTIONS)
    return prot / total

def norm_type(t):
    """Video_Action 名 -> Anomaly 事件名（供 PRIOR_P / SEV_BY_TYPE 查询）"""
    return type_map.get(t, t)

# ---------- 核心校准 ----------
calib = {}
all_P, all_outcome = [], []
for t, outs in outcome_by_type.items():
    n_crash = sum(1 for o in outs if o == "crash")
    n_succ  = sum(1 for o in outs if o == "success")
    ab = action_bias_of(t)
    nt = norm_type(t)

    # §4 理论融合 P 值（先验 + Laplace 数据项 + 动作偏置 + 残差）
    r = compute_P(nt, n_crash, n_succ, action_bias=ab)
    P, T = r["P"], r["T"]
    tier = compute_Tier(P)
    mode = recommend_mode(P, tier)
    sev  = SEV_BY_TYPE.get(nt, 3)
    factor = factor_map.get(nt, "unknown")

    # 收集 Brier 数据
    for o in type_outcomes_binary.get(t, []):
        all_P.append(P)
        all_outcome.append(o)

    calib[t] = {
        "P": P, "T": T, "L": sev, "tier": tier, "mode": mode,
        "basis": {
            "crash": n_crash, "success": n_succ,
            "unknown": sum(1 for o in outs if o == "unknown"),
            "crash_rate_laplace": r["crash_rate_laplace"],
            "severity": sev,
            "P_prior": r["P_prior"],
            "w_prior": r["w_prior"], "w_data": r["w_data"],
            "w_action": W_ACTION, "w_residual": W_RESIDUAL,
            "factor": factor,
            "action_bias": ab,
            "neff": r["neff"],
        },
    }

# crash_general（"炸/坠"宽命中）降权：P 封顶 0.40，避免污染保机判断
# 依据：calibrate_pt 旧版规则（日志第六节），宽泛词命中样本 crash 占比被
# 无关视频稀释，不能直接驱动 PROTECT
CRASH_GENERAL_P_CAP = 0.40
for t, c in calib.items():
    if t == "crash_general":
        c["P"] = min(c["P"], CRASH_GENERAL_P_CAP)
        c["T"] = round(1.0 - c["P"], 3)
        c["tier"] = compute_Tier(c["P"])
        c["mode"] = recommend_mode(c["P"], c["tier"])

# ---------- 评估指标（§6） ----------
# 留出集 P/R/F1：对每类用全部样本训练，留出 30% 测试
train, test = holdout_split(type_outcomes_binary, holdout_frac=0.30, seed=42)
y_true_all, y_pred_all = [], []
per_type_metrics = {}
for t, labels in test.items():
    nt = norm_type(t)
    # 用训练集算该类的融合 P（这里近似：用训练集统计 + 同 action_bias）
    tr_crash = sum(1 for x in train.get(t, []) if x == 1)
    tr_succ  = sum(1 for x in train.get(t, []) if x == 0)
    ab = action_bias_of(t)
    P_train = compute_P(nt, tr_crash, tr_succ, action_bias=ab)["P"]
    # 预测：P >= 0.55 -> 1 (应该保机)，否则 0
    pred = 1 if P_train >= 0.55 else 0
    per_type_metrics[t] = {
        "n_test": len(labels),
        "P_train": round(P_train, 3),
        "pred_label": pred,
        "y_true": labels,
        "y_pred": [pred] * len(labels),
    }
    y_true_all += labels
    y_pred_all += [pred] * len(labels)

overall_prf1 = precision_recall_f1(y_true_all, y_pred_all, pos_label=1)
bs = brier_score(all_P, all_outcome) if all_P else float("nan")

# ---------- 敏感性分析（选代表性类型） ----------
repr_types = ["battery_issue", "motor_failure", "lightning", "bird"]
sens_sections = []
for nt in repr_types:
    t_map_inv = {v: k for k, v in type_map.items()}
    t = t_map_inv.get(nt, nt)
    outs = outcome_by_type.get(t, [])
    nc = sum(1 for o in outs if o == "crash")
    ns = sum(1 for o in outs if o == "success")
    ab = action_bias_of(t)
    rows = sensitivity_analysis(nt, nc, ns, action_bias=ab)
    sens_sections.append((nt, rows))

# ---------- 写 Decision_Matrix.xlsx ----------
ACTIONS = {
    "battery":    ("关载荷 + 计算续航 → 返航或就近降", "Shadow_AI"),
    "motor_fault":("切换三轴冗余 / 极速软降 / 手动接管", "FlightController"),
    "gimbal":     ("保持机身水平禁机动", "Shadow_AI"),
    "prop_break": ("极速降油门软着陆", "FlightController"),
    "signal_loss":("执行预设 Failsafe 返航 / 悬停", "FlightController"),
    "gps":        ("切视觉/IMU 导航, 限时悬停", "Shadow_AI"),
    "wind":       ("降高度 / 顺风提速穿过", "Shadow_AI"),
    "rain":       ("避雨点悬停 或 直接返航", "Shadow_AI"),
    "lightning":  ("立即接地断电", "FlightController"),
    "bird":       ("加速穿越鸟群 / 避让 / 手动接管", "Shadow_AI"),
    "obstacle":   ("动态避障绕飞 / 急停", "Shadow_AI"),
    "cold":       ("缩短任务 / 提前返航", "Shadow_AI"),
    "crash_general": ("保守悬停待命, 请求接管", "Shadow_AI"),
}

out_wb = Workbook()
o = out_wb.active
o.title = "Decision_Matrix"
o.append(["accident_type", "factor", "severity", "crash_rate_laplace", "P_prior",
          "w_prior", "w_data", "risk_L", "tier",
          "action", "execution_target",
          "P", "T", "recommended_mode", "calibration_basis"])
for t in sorted(calib, key=lambda x: -calib[x]["P"]):
    c = calib[t]
    act, tgt = ACTIONS.get(t, ("保守悬停待命", "Shadow_AI"))
    b = c["basis"]
    o.append([
        t, b["factor"], b["severity"], b["crash_rate_laplace"], b["P_prior"],
        b["w_prior"], b["w_data"], b["severity"], c["tier"],
        act, tgt,
        c["P"], c["T"], c["mode"],
        json.dumps(b, ensure_ascii=False),
    ])
for i, w in enumerate([14,10,9,14,9,9,9,8,7,36,18,8,8,16,50], 1):
    o.column_dimensions[chr(64 + i)].width = w
o.freeze_panes = "A2"

# 模式页
o2 = out_wb.create_sheet("Mode_Reference")
o2.append(["mode", "P_range", "T_range", "trigger_condition"])
for m, pr, tr, trig in [
    ("CRUISE",  "0.05-0.35", "0.65-0.95", "P<0.35 且 tier=L0/L1 且 T-P>0.30"),
    ("PROTECT", ">=0.75",    "<=0.25",    "P>=0.75 或 tier=L3"),
    ("MISSION", "<0.35",     ">0.65",     "P<0.35 且 tier=L0/L1"),
    ("RTB",     "0.55-0.75", "0.25-0.45", "tier=L2/L3 且 0.55<=P<0.75"),
]:
    o2.append([m, pr, tr, trig])

# 评估指标页
o3 = out_wb.create_sheet("Evaluation")
o3.append(["metric", "value"])
o3.append(["brier_score", round(bs, 4) if bs == bs else "n/a"])
o3.append(["holdout_fraction", 0.30])
o3.append(["precision", overall_prf1["precision"]])
o3.append(["recall", overall_prf1["recall"]])
o3.append(["f1", overall_prf1["f1"]])
o3.append(["accuracy", overall_prf1["accuracy"]])
o3.append(["TP", overall_prf1["TP"]])
o3.append(["FP", overall_prf1["FP"]])
o3.append(["FN", overall_prf1["FN"]])
o3.append(["TN", overall_prf1["TN"]])
o3.append(["confusion_matrix", json.dumps(overall_prf1["confusion_matrix"])])
for i, w in enumerate([24, 40], 1):
    o3.column_dimensions[chr(64 + i)].width = w

out_wb.save(OUT)

# ---------- 报告 ----------
lines = [
    "# P/T 校准报告（理论加权版）",
    "",
    "## 方法说明",
    "",
    f"- 源：`{os.path.basename(SRC)}`（已分类样本 {sum(len(v) for v in outcome_by_type.values())} 条）",
    "- 模型：先验(FMECA §2.1) + Laplace 数据项(§3) + 动作偏置(§4.2) + 不确定度残差(§4.2)",
    f"- 固定权重：w_action={W_ACTION}, w_residual={W_RESIDUAL}, k0={K0_SHRINK}",
    "- P = w_prior·P_prior + w_data·crash_rate_laplace + w_action·action_bias + w_residual·0.5；T = 1 - P",
    f"- 输出：`{os.path.basename(OUT)}`",
    "",
    "## 校准结果",
    "",
    "| type | crash | success | unknown | crash_rate_laplace | P_prior | w_prior | w_data | P | T | tier | mode |",
    "|---|---|---|---|---|---|---|---|---|---|---|---|",
]
for t in sorted(calib, key=lambda x: -calib[x]["P"]):
    c = calib[t]; b = c["basis"]
    lines.append(
        f"| {t} | {b['crash']} | {b['success']} | {b['unknown']} "
        f"| {b['crash_rate_laplace']:.3f} | {b['P_prior']:.2f} "
        f"| {b['w_prior']:.3f} | {b['w_data']:.3f} "
        f"| {c['P']} | {c['T']} | {c['tier']} | {c['mode']} |"
    )

lines += [
    "",
    "## 评估指标（留出集 30%）",
    "",
    "| 指标 | 值 | 说明 |",
    "|---|---|---|",
    f"| Brier Score | {bs:.4f} | <0.25=校准良好（随机基准 0.25） |" if bs == bs else "| Brier Score | n/a | 无已标注样本 |",
    f"| Precision | {overall_prf1['precision']} | TP/(TP+FP) |",
    f"| Recall | {overall_prf1['recall']} | TP/(TP+FN) |",
    f"| F1 | {overall_prf1['f1']} | 2PR/(P+R) |",
    f"| Accuracy | {overall_prf1['accuracy']} | (TP+TN)/N |",
    f"| 混淆矩阵 | TN={overall_prf1['TN']}, FP={overall_prf1['FP']}, FN={overall_prf1['FN']}, TP={overall_prf1['TP']} | [[TN,FP],[FN,TP]] |",
    "",
    "## 每类留出集指标",
    "",
    "| type | n_test | P_train | pred_label | 实际标签分布 |",
    "|---|---|---|---|---|",
]
for t in sorted(per_type_metrics):
    m = per_type_metrics[t]
    c = Counter(m["y_true"])
    dist = f"crash={c.get(1,0)} succ={c.get(0,0)}"
    lines.append(
        f"| {t} | {m['n_test']} | {m['P_train']} | {m['pred_label']} | {dist} |"
    )

lines += ["", "## 权重敏感性分析（w_action × k0 网格）", ""]
for nt, rows in sens_sections:
    lines.append(f"### {nt}")
    lines.append("")
    lines.append(format_sensitivity_table(rows))
    lines.append("")

lines += [
    "## 备注",
    "- 所有权重理论依据见 `weight_theory.md`。",
    "- P + T = 1 严格成立，消除原代码 battery 类 P=0.55 被 severity 顶上去的自相矛盾。",
    "- 0/0 样本类型（lightning/bird/gimbal）纯由 FMECA 先验主导，不再是拍脑袋常数。",
    "- thresholds.py 占位符不影响本 P/T 权重体系（P/T 只依赖故障类型先验 + 数据频率）。",
]
open(REP, "w", encoding="utf-8").write("\n".join(lines))
print(f"[Calibrate] {len(calib)} 类已校准 -> {OUT}")
for t in sorted(calib, key=lambda x: -calib[x]["P"]):
    c = calib[t]
    print(f"  {t:14s} P={c['P']:.3f} T={c['T']:.3f} tier={c['tier']} mode={c['mode']}")
print(f"\n  Brier={bs:.4f}  P/R/F1={overall_prf1['precision']}/{overall_prf1['recall']}/{overall_prf1['f1']}  ACC={overall_prf1['accuracy']}")
