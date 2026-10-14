# -*- coding: utf-8 -*-
"""
视频应对做法数据库生成器（纯整理，不涉及 AI）
================================================
读取 data/raw/multi_raw.jsonl，用 video_action_extractor 逐条提取
事故类别 / 环境 / 应对动作 / 结果，输出一张"按视频逐条"的数据库 xlsx。
输出：analyzer/output/Video_Action_DB.xlsx
列（供人工审阅标注）：
  source | region | video_id | url | title |
  accident_type | environment | actions | outcome |
  sample_comments | collected_at
"""
import json, os, sys
from openpyxl import Workbook

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_action_extractor import extract


def _load_in():
    import os as _o
    _data_root = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                              "..", "drone_crawler", "data", "raw")
    fixed = _o.path.join(_data_root, "multi_raw_fixed.jsonl")
    orig  = _o.path.join(_data_root, "multi_raw.jsonl")
    return fixed if _o.path.exists(fixed) else orig

IN  = _load_in()

# P1-1 修复：OUT 用 HERE 绝对路径，不再依赖 CWD
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output", "Video_Action_DB.xlsx")

COLUMNS = ["source","region","video_id","url","title",
           "accident_type","environment","actions","outcome",
           "sample_comments","collected_at",
           # 人工标注列（留空供审阅修正）
           "manual_fix_type","manual_fix_action","manual_outcome","notes","reviewer"]

def _comments(rec, n=3):
    tc = rec.get("top_comments")
    if isinstance(tc, list):
        return " | ".join(str(x) for x in tc[:n] if x)
    return str(tc or "")

def build():
    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    if not os.path.exists(IN):
        print(f"未找到 {IN}，请先运行 start_all.bat 爬取数据")
        return 0
    wb = Workbook(); ws = wb.active; ws.title = "视频应对做法库"
    ws.append(COLUMNS)
    seen = set(); n = 0
    with open(IN, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            rec = json.loads(line)
            key = (rec.get("source"), rec.get("video_id"))
            if key in seen: continue
            seen.add(key)
            e = extract(rec)
            ws.append([
                rec.get("source",""), rec.get("region",""),
                rec.get("video_id",""), rec.get("url",""),
                rec.get("title",""),
                e["accident_type"],
                ",".join(e["environment"]) if e["environment"] else "",
                ",".join(e["actions"]) if e["actions"] else "",
                e["outcome"],
                _comments(rec),
                rec.get("collected_at",""),
                "", "", "", "", "",  # 人工标注列留空
            ])
            n += 1
    # 列宽
    widths = [14,16,16,55,45,16,14,28,10,60,20, 18,30,14,30,12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w
    # 冻结首行
    ws.freeze_panes = "A2"
    wb.save(OUT)
    print(f"[完成] {n} 条视频 -> {OUT}")
    return n

if __name__ == "__main__":
    build()
