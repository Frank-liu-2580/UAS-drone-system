# -*- coding: utf-8 -*-
"""
异常事件库生成器
输入 data/raw/multi_raw.jsonl，输出 analyzer/output/Anomaly_Events.xlsx
按 anomaly_type 聚合去重，统计命中样本量作为置信度

修正（对应 weight_theory.md §2/§5）：
  - severity 不再写死常数，全部取自 classifier.classify 的证据强度计算
    （base_sev + SEV_BOOST/SEV_DOWN 修正，clamp(1,10)）
  - factor / priority 同理由 classify 给出，本模块不维护第二套常量表
  - 若 IN 文件缺失（原始数据被搁置），本脚本无法运行；
    下游矩阵改从既有 Anomaly_Events.xlsx 读取 severity/factor
    （见 decision_matrix.py 的 load_sev_and_factor 回落逻辑）
"""
import json, os
from collections import defaultdict
from openpyxl import Workbook
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer.classifier import classify


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
OUT = os.path.join(HERE, "output", "Anomaly_Events.xlsx")
FACTOR_CN = {"internal":"内部","natural":"自然","comm":"通信","logic":"逻辑","payload":"载荷","unknown":"未分类"}
PRIORITY_CN = {1:"内部(最高)",2:"自然/链路(中)",3:"其他(低)"}

def build():
    events = defaultdict(lambda: {"videos":[],"count":0,"descs":[],"factor":"unknown","priority":3,"severity":0})
    total = 0
    with open(IN, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            rec = json.loads(line); total += 1
            res = classify(rec)
            atype = res["anomaly_type"]
            e = events[atype]
            e["factor"] = res["factor"]; e["priority"] = res["priority"]
            e["severity"] = res["severity"]
            e["count"] += 1
            e["videos"].append(rec.get("url",""))
            e["descs"].append(rec.get("title","")[:50])
    rows = []
    for atype, e in sorted(events.items(), key=lambda kv:(kv[1]["priority"], -kv[1]["severity"])):
        rep = " ; ".join(e["videos"][:3]) if e["videos"] else ""
        desc = "；".join(e["descs"][:3]) if e["descs"] else ""
        rows.append([
            atype,
            FACTOR_CN.get(e.get("factor","unknown"),"未知"),
            PRIORITY_CN.get(e.get("priority",3),"低"),
            e.get("severity",0),
            e.get("count",0),
            rep,
            desc,
        ])
    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    wb = Workbook(); ws = wb.active; ws.title = "异常事件库"
    ws.append(["Anomaly_Type","Factor","Priority","Severity","Sample_Count","Representative_Videos","Description"])
    for r in rows:
        ws.append(r)
    widths = [16,10,12,8,12,60,60]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w
    wb.save(OUT)
    print(f"[完成] 共 {total} 条视频 -> {len(rows)} 个异常事件 -> {OUT}")
    return rows

if __name__ == "__main__":
    build()