# -*- coding: utf-8 -*-
"""
fix_mojibake.py — 修复 multi_raw.jsonl 中 B 站条目的 GBK->UTF-8 mojibake
=====================================================================
背景：multi_site_crawler.py 的 requests 默认按 ISO-8859-1 解码 B 站搜索
API 返回的 UTF-8 字节，B 站条目的 title/description/author/
search_keyword/top_comments 在 jsonl 里是 GBK 字节被按单字节字符
记录的乱码。YouTube 条目（yt-dlp）正常。

B 站条目在 jsonl 里有两种形态（爬虫中途环境变化导致）：
  A. 字段值直接是 GBK 字节乱码，整行 JSON 合法
  B. 字段值嵌套了 json.dumps 转义（字面 反斜杠引号 序列），整行看似
     合法 JSON 但实际是双重转义

策略：逐行处理——先试形态 A（直接 GBK 字段修复），再试形态 B
（先还原嵌套转义再 GBK 修复）；修复结果必须通过 json.loads 校验，
否则保留原始行（不污染管线）。
输出：data/raw/multi_raw_fixed.jsonl（新文件，不覆盖原始数据）。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "drone_crawler")  # 爬虫数据在 drone_crawler
SRC = os.path.join(ROOT, "data", "raw", "multi_raw.jsonl")
OUT = os.path.join(ROOT, "data", "raw", "multi_raw_fixed.jsonl")

# 单字节乱码字符（GBK 字节被按 latin-1 记录后的形态）
BYTE = r"[\u0000-\u00ff]"

FIELD_RES = {
    "title":          re.compile(r'"title"\s*:\s*"' + BYTE + r'+"'),
    "description":    re.compile(r'"description"\s*:\s*"' + BYTE + r'+"'),
    "author":         re.compile(r'"author"\s*:\s*"' + BYTE + r'+"'),
    "search_keyword": re.compile(r'"search_keyword"\s*:\s*"' + BYTE + r'+"'),
}
COMMENTS_RE = re.compile(r'"top_comments"\s*:\s*\[(.*?)\]', re.S)
COMMENT_ITEM_RE = re.compile(r'"' + BYTE + r'+"')


def _gbk_to_json_str(raw: str):
    """GBK 字节串 -> 正确的 JSON 字符串字面量；失败返回 None。"""
    try:
        fixed = raw.encode("latin-1").decode("gbk")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return None
    return '"%s"' % json.dumps(fixed, ensure_ascii=False)[1:-1]


def _fix_field(m):
    out = _gbk_to_json_str(m.group(0)[1:-1])
    return out if out is not None else m.group(0)


def _fix_comments(m):
    seg = m.group(1)
    def one(mm):
        out = _gbk_to_json_str(mm.group(0)[1:-1])
        return out if out is not None else mm.group(0)
    return '"top_comments": [' + COMMENT_ITEM_RE.sub(one, seg) + ']'


def _unescape_nested(line: str) -> str:
    """形态 B：还原嵌套 json.dumps 转义。"""
    q = chr(34)   # 双引号
    b = chr(92)   # 反斜杠
    line = line.replace(b + b + b + b + q, b + b + q)
    line = line.replace(b * 8, b * 4)
    return line


def _gbk_pass(s: str) -> str:
    for rx in FIELD_RES.values():
        s = rx.sub(_fix_field, s)
    return COMMENTS_RE.sub(_fix_comments, s)


def fix_line(line: str) -> str:
    """B 站行：依次尝试 [形态A, 形态B]，结果必须通过 JSON 校验。"""
    if "bilibili" not in line:
        return line
    for cand in (_gbk_pass(line), _gbk_pass(_unescape_nested(line))):
        try:
            json.loads(cand)
            return cand
        except Exception:
            continue
    return line  # 修复失败 -> 保留原始行，不污染管线


def run():
    n_fix = 0
    n_keep = 0
    with open(SRC, encoding="utf-8") as fin, \
         open(OUT, "w", encoding="utf-8") as fout:
        for raw_line in fin:
            s = raw_line.strip()
            if not s:
                continue
            new = fix_line(s)
            if new != s:
                n_fix += 1
            else:
                n_keep += 1
            fout.write(new + "\n")
    print(f"[fix_mojibake] 修复 {n_fix} 行 / 透传 {n_keep} 行 -> {OUT}")
    return OUT


if __name__ == "__main__":
    run()
    # 自检：全量 JSON 校验 + B 站样本抽查
    n_bad = 0
    seen = 0
    for line in open(OUT, encoding="utf-8"):
        s = line.strip()
        if not s:
            continue
        try:
            json.loads(s)
        except Exception:
            n_bad += 1
            continue
        if "bilibili" in s and seen < 3:
            r = json.loads(s)
            print("  bili sample:", r.get("title", "")[:40],
                  "| kw:", r.get("search_keyword", ""))
            seen += 1
    print(f"  JSON 校验: 非法行 {n_bad}")
