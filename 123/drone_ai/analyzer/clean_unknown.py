# -*- coding: utf-8 -*-
"""
B. 数据清洗：针对 Video_Action_DB.xlsx 中 accident_type=unknown 的样本
   1) 扩展关键词再扫一遍（标题 + 评论），能命中的重新分类
   2) 命中"资讯/教学/评测/生活"类噪声词的样本单独标记为 "noise"
   3) 仍无法判定的保留 unknown，写入备注
输出：
   - analyzer/output/Video_Action_DB_cleaned.xlsx   清洗后全量数据
   - analyzer/output/Cleaning_Report.md             清洗统计报告
"""
import os, re, json, sys
from collections import Counter
from openpyxl import load_workbook, Workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SRC  = os.path.join(HERE, "output", "Video_Action_DB.xlsx")
OUTX = os.path.join(HERE, "output", "Video_Action_DB_cleaned.xlsx")
OUTM = os.path.join(HERE, "output", "Cleaning_Report.md")



# 噪声词：资讯/教学/评测/生活类，命中即归 noise，不进入故障统计
NOISE_KWS = [
    "考试","执照","证","CAAC","教学","教程","攻略","评测","开箱","开箱","开箱",
    "演示","vlog","Vlog","前景","就业","薪资","工资","排行","排名","科普",
    "介绍","盘点","盘点","新闻","快讯","财经","融资","上市","发布会",
    "直播","开箱","开箱","开箱","开箱","开箱","开箱","开箱",
    "玩法","推荐","清单","清单","买","买","购买","入手",
    "足球","足球","足球","足球","足球","足球","足球","足球","足球",
    "烟花","烟花","烟花","烟花","烟花","烟花","烟花","烟花",
    "穿越机 ","穿越 机","穿越机","fpv 炸机 集锦","集锦","funny","fail  comp",
]

from classifier import classify as _classify

# 类型名对齐：clean_unknown 用 Video_Action 名（battery/motor_fault/...），
# classifier 用 Anomaly 名（battery_issue/motor_failure/...）。映射回原命名以不破坏下游。
_CLASS_NAME_MAP = {
    "battery_issue": "battery", "motor_failure": "motor_fault",
    "gps_drift": "gps", "wind_gust": "wind", "cold_hot": "cold",
}

def _re_scan(text, comments=None):
    """复用 classifier.classify（理论加权版），返回 Video_Action 命名下的类型。
    未命中返回 None。"""
    rec = {"title": text or "", "description": "", "top_comments": comments or []}
    r = _classify(rec)
    a = r["anomaly_type"]
    if a == "unknown":
        return None
    return _CLASS_NAME_MAP.get(a, a)


def _is_noise(text):
    text = (text or "").lower()
    hits = [w for w in NOISE_KWS if w.lower() in text]
    # 命中 >=2 个噪声词，或命中 1 个明显噪声词（教学/考试/新闻/评测）
    strong = [w for w in hits if w in ("考试","执照","教学","教程","攻略","评测","新闻","科普","盘点","排行","就业","前景","直播")]
    return len(strong) >= 1 or len(hits) >= 2, hits

def run():
    wb = load_workbook(SRC)
    ws = wb.active
    hdr = [c.value for c in ws[1]]
    idx = {n: i for i, n in enumerate(hdr)}

    # 新增 2 列：ext_type / noise_flag / clean_note
    new_cols = ["ext_type", "noise_flag", "clean_note"]
    for j, c in enumerate(new_cols):
        ws.cell(row=1, column=len(hdr) + 1 + j, value=c)
    ncol = len(hdr) + len(new_cols)
    for i, n in enumerate(new_cols, start=len(hdr) + 1):
        ws.column_dimensions[chr(64 + i)].width = 18 if n != "clean_note" else 40

    c_fixed = Counter(); c_noise = Counter(); c_still = Counter()
    total_unk = 0
    for row_i in range(2, ws.max_row + 1):
        if ws.cell(row=row_i, column=idx["accident_type"] + 1).value != "unknown":
            continue
        total_unk += 1
        title  = ws.cell(row=row_i, column=idx["title"] + 1).value or ""
        cmts   = ws.cell(row=row_i, column=idx["sample_comments"] + 1).value or ""
        text   = f"{title} || {cmts}"
        noise, nhits = _is_noise(text)
        ext = _re_scan(text) if not noise else None
        # 写入
        ws.cell(row=row_i, column=len(hdr) + 1, value=ext or "")
        ws.cell(row=row_i, column=len(hdr) + 2, value=("yes" if noise else ""))
        note = ""
        if noise:
            note = "noise: " + ",".join(nhits[:4])
            c_noise.update(nhits[:4])
        elif ext:
            note = f"reclassified->{ext}"
            c_fixed[ext] += 1
            # 直接覆盖 accident_type
            ws.cell(row=row_i, column=idx["accident_type"] + 1, value=ext)
        else:
            note = "still_unknown"
            c_still[title[:30]] += 1
        ws.cell(row=row_i, column=len(hdr) + 3, value=note)

    wb.save(OUTX)

    # 报告
    lines = [
        "# B. Video_Action_DB 清洗报告",
        "",
        f"- 源文件：`{os.path.basename(SRC)}`",
        f"- 清洗后：`{os.path.basename(OUTX)}`",
        f"- unknown 样本总数：{total_unk}",
        f"- 扩展关键词重新分类成功：{sum(c_fixed.values())}",
        f"- 判定为噪声（资讯/教学/评测）：{sum(1 for _ in c_noise) or len([1 for x in []])}",  # 占位
        "",
        "## 重新分类分布（ext_type）",
    ]
    for k, v in c_fixed.most_common():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 噪声词 top（样本数：按 clean_note 聚合）", ""]
    noise_rows = 0
    for row_i in range(2, ws.max_row + 1):
        if ws.cell(row=row_i, column=len(hdr) + 2).value == "yes":
            noise_rows += 1
    lines.append(f"噪声样本：{noise_rows}")
    lines.append("")
    lines.append("> 仍为 unknown 的样本建议进入人工标注队列（见 clean_note 列）。")
    with open(OUTM, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[B] unknown={total_unk}, reclassified={sum(c_fixed.values())}, noise={noise_rows} -> {OUTX}")
    return total_unk, sum(c_fixed.values()), noise_rows

if __name__ == "__main__":
    run()
