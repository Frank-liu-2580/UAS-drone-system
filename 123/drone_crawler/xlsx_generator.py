# -*- coding: utf-8 -*-
"""
把多站点爬虫结果存成 xlsx（每个视频站点一个工作表 + 汇总 + 人工标注列）
数据源：data/raw/multi_raw.jsonl（爬虫统一输出）
输出：  data/raw/drone_videos.xlsx
自动列：source, region, video_id, url, title, author,
        duration, search_keyword, collected_at, top_comments
人工标注列（留空供审阅）：
        manual_fix_type / manual_fix_action / manual_outcome / notes / reviewer
依赖：  openpyxl
用法：  python xlsx_generator.py
"""
import json, os
from collections import Counter
from openpyxl import Workbook

IN  = "data/raw/multi_raw.jsonl"
OUT = "data/raw/drone_videos.xlsx"

FIELDS = ["source","region","video_id","url","title","author",
          "duration","search_keyword","collected_at","top_comments",
          "manual_fix_type","manual_fix_action","manual_outcome","notes","reviewer"]

def load_records():
    if not os.path.exists(IN):
        return []
    recs = []
    with open(IN, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    # 按 source+video_id 去重
    seen = set(); out = []
    for r in recs:
        key = (r.get("source"), r.get("video_id"))
        if key in seen or not r.get("video_id"):
            continue
        seen.add(key); out.append(r)
    return out

def norm_cell(rec, field):
    v = rec.get(field, "")
    if field == "top_comments":
        if isinstance(v, list):
            return " | ".join(str(x) for x in v if x)
        return str(v)
    return str(v)

def write_xlsx(recs):
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "汇总"

    cnt = Counter(r.get("source","unknown") for r in recs)
    ws0.append(["source","region","count"])
    for src, n in sorted(cnt.items()):
        region = next((r.get("region","") for r in recs if r.get("source")==src), "")
        ws0.append([src, region, n])
    ws0.append(["TOTAL","-",len(recs)])
    # 列宽
    ws0.column_dimensions["A"].width = 16
    ws0.column_dimensions["B"].width = 18
    ws0.column_dimensions["C"].width = 8

    for src in sorted(cnt.keys()):
        rows = [r for r in recs if r.get("source")==src]
        sheet_name = (str(src).replace("/","_")[:30]) or "site"
        ws = wb.create_sheet(sheet_name)
        ws.append(FIELDS)
        for r in rows:
            row = []
            for f in FIELDS:
                if f in ("manual_fix_type","manual_fix_action","manual_outcome","notes","reviewer"):
                    row.append("")
                else:
                    row.append(norm_cell(r, f))
            ws.append(row)
        widths = {"source":14,"region":16,"video_id":16,"url":60,
                  "title":50,"author":18,"duration":10,
                  "search_keyword":16,"collected_at":22,"top_comments":60,
                  "manual_fix_type":18,"manual_fix_action":30,
                  "manual_outcome":14,"notes":30,"reviewer":12}
        for i, f in enumerate(FIELDS, start=1):
            ws.column_dimensions[chr(64+i) if i<=26 else "A"].width = widths.get(f,12)
        ws.freeze_panes = "A2"

    os.makedirs("data/raw", exist_ok=True)
    wb.save(OUT)
    print(f"[完成] 共 {len(recs)} 条 -> {OUT}")
    print("各站点:", dict(cnt))

if __name__ == "__main__":
    recs = load_records()
    if not recs:
        print(f"未找到 {IN}，请先运行 multi_site_crawler.py")
    else:
        write_xlsx(recs)