# -*- coding: utf-8 -*-
"""
多站点视频爬虫（覆盖国际 + 国内主流视频平台）
主力源：
  - Bilibili   国内，走 B 站官方搜索 API（稳定）
  - YouTube    国际，走 yt-dlp 的 ytsearch（稳定）
自动探测源（可达才抓，不可达自动跳过，换网络后可自动纳入）：
  - Dailymotion / Vimeo / TikTok / Instagram / Twitch / Twitter / Rumble / Niconico / OK
增量写入，断点续爬，结果统一进 data/raw/multi_raw.jsonl
用法：python multi_site_crawler.py
"""
import json, os, re, time, random, subprocess
from datetime import datetime
import requests
from keywords import all_bili_keywords, all_yt_keywords, BILI_PER_KW, YT_PER_KW

OUT = "data/raw/multi_raw.jsonl"
BILI_HEADERS = {
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer":"https://search.bilibili.com/",
}

def open_out():
    os.makedirs("data/raw", exist_ok=True)
    if not os.path.exists(OUT):
        open(OUT, "w", encoding="utf-8").close()
    return open(OUT, "a", encoding="utf-8")

def load_seen():
    seen = set()
    if os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if line:
                    try:
                        r=json.loads(line); seen.add((r.get("source"), r.get("video_id")))
                    except Exception: pass
    return seen

# ================= B 站（国内主力） =================
def bili_search(kw):
    try:
        r=requests.get("https://api.bilibili.com/x/web-interface/search/type",
            params={"search_type":"video","keyword":kw,"page":1},
            headers=BILI_HEADERS, timeout=20)
        d=r.json()
        if d.get("code")!=0: print(f"    B站 {d.get('message')}", flush=True); return []
        return d.get("data",{}).get("result",[]) or []
    except Exception as e:
        print(f"    B站请求失败:{e}", flush=True); return []

def bili_comments(bvid, n=8):
    try:
        r=requests.get("https://api.bilibili.com/x/v2/reply",
            params={"type":1,"oid":0,"bvid":bvid,"sort":2,"ps":n},
            headers=BILI_HEADERS, timeout=15)
        d=r.json()
        if d.get("code")!=0: return []
        return [x.get("message","") for x in (d.get("data",{}).get("replies",[]) or [])]
    except Exception:
        return []

def crawl_bilibili(fh, seen):
    BILI_KW=all_bili_keywords()
    print(f"\n[国内主力] Bilibili ({len(BILI_KW)} 关键词)", flush=True)
    for kw in BILI_KW:
        if ("bili_kwdone",kw) in seen:
            print(f"    已完成 {kw}, 跳过", flush=True); continue
        items=bili_search(kw); added=0
        for it in items[:BILI_PER_KW]:
            bvid=it.get("bvid","")
            if not bvid or ("bilibili",bvid) in seen: continue
            title=re.sub(r"</?em[^>]*>","",it.get("title",""))
            seen.add(("bilibili",bvid)); seen.add(("bili_kwdone",kw))
            rec={"source":"bilibili","region":"CN","video_id":bvid,
                 "url":f"https://www.bilibili.com/video/{bvid}",
                 "title":title,"author":it.get("author",""),
                 "description":it.get("description",""),
                 "duration":it.get("duration",""),
                 "search_keyword":kw,"top_comments":bili_comments(bvid),
                 "collected_at":datetime.now().isoformat()}
            fh.write(json.dumps(rec,ensure_ascii=False)+"\n"); added+=1
        fh.flush()
        print(f"    {kw}: +{added} 条", flush=True)
        time.sleep(random.uniform(2,4))

# ================= YouTube（国际主力） =================
def yt_search(kw, n):
    try:
        out=subprocess.check_output(["python","-m","yt_dlp",f"ytsearch{n}:{kw}",
            "--flat-playlist","--print","%(id)s\t%(title)s\t%(uploader)s\t%(duration)s\t%(url)s",
            "--no-download"], text=True, stderr=subprocess.DEVNULL, timeout=120)
        recs=[]
        for line in out.splitlines():
            p=line.split("\t")
            if len(p)>=4: recs.append({"id":p[0],"title":p[1],"author":p[2],
                                       "duration":p[3],"url":p[4] if len(p)>4 else ""})
        return recs
    except Exception as e:
        print(f"    YT 失败:{e}", flush=True); return []

def crawl_youtube(fh, seen):
    YT_KW=all_yt_keywords()
    print(f"\n[国际主力] YouTube ({len(YT_KW)} 关键词)", flush=True)
    for kw in YT_KW:
        if ("yt_kwdone",kw) in seen:
            print(f"    已完成 {kw}, 跳过", flush=True); continue
        recs=yt_search(kw, YT_PER_KW); added=0
        for r in recs:
            key=("youtube",r["id"])
            if key in seen or not r["id"]: continue
            seen.add(key); seen.add(("yt_kwdone",kw))
            allr={"source":"youtube","region":"International/US","video_id":r["id"],
                  "url":r["url"] or f"https://www.youtube.com/watch?v={r['id']}",
                  "title":r["title"],"author":r["author"],
                  "description":"","duration":r["duration"],
                  "search_keyword":kw,"top_comments":[],
                  "collected_at":datetime.now().isoformat()}
            fh.write(json.dumps(allr,ensure_ascii=False)+"\n"); added+=1
        fh.flush()
        print(f"    {kw}: +{added} 条", flush=True)
        time.sleep(1)

# ================= 自动探测的国际站（可达才抓） =================
# 名称 -> (yt-dlp 搜索 URL 模板, 区域)
PROBE_SITES = [
    ("dailymotion","dailymotionsearch","International/FR"),
    ("vimeo","vimeosearch","International/US"),
    ("tiktok","tiktoksearch","International/CN"),
    ("instagram","instagramsearch","International"),
    ("twitch","twitchsearch","International/US"),
    ("twitter","twittersearch","International"),
    ("rumble","rumblesearch","International/US"),
    ("niconico","niconicosearch","JP"),
    ("okru","oksearch","RU"),
    ("pinterest","pinterestsearch","International"),
    # 新增 13 个（当前网络不可达则自动跳过，换网络后自动纳入）
    ("facebook","facebooksearch","International"),
    ("metacafe","metacafesearch","International"),
    ("tumblr","tumblrsearch","International"),
    ("soundcloud","soundcloudsearch","International"),
    ("youku","youkusearch","CN"),
    ("qq","qqsearch","CN"),
    ("douyin","douyinsearch","CN"),
    ("kuaishou","kuaishousearch","CN"),
    ("bilibili_live","bililivesearch","CN"),
]
PROBE_KWS = ["drone crash","drone motor failure","drone wind","drone rain"]

def crawl_probe(fh, seen):
    print(f"\n[自动探测国际站] {len(PROBE_SITES)} 个候选站（可达才抓）", flush=True)
    for name, prefix, region in PROBE_SITES:
        if f"probe_reach_{name}" in seen:
            print(f"  {name}: 已记录可达性，跳过", flush=True); continue
        try:
            out=subprocess.check_output(["python","-m","yt_dlp",f"{prefix}3:drone",
                "--flat-playlist","--print","%id","--no-download"],
                text=True, stderr=subprocess.DEVNULL, timeout=35)
            n=len([l for l in out.splitlines() if l.strip()])
        except Exception:
            n=0
        seen.add(f"probe_reach_{name}")
        if n==0:
            print(f"  {name}: 当前不可达，跳过", flush=True); continue
        print(f"  {name}: 可达，开始抓取", flush=True)
        for kw in PROBE_KWS:
            tag=f"opt_{name}_{kw}"
            if tag in seen: continue
            try:
                out=subprocess.check_output(["python","-m","yt_dlp",f"{prefix}10:{kw}",
                    "--flat-playlist","--print","%(id)s\t%(title)s\t%(uploader)s\t%(duration)s\t%(url)s",
                    "--no-download"], text=True, stderr=subprocess.DEVNULL, timeout=120)
            except Exception:
                continue
            added=0
            for line in out.splitlines():
                p=line.split("\t")
                if len(p)<4: continue
                key=(name,p[0])
                if key in seen or not p[0]: continue
                seen.add(key); seen.add(tag)
                fh.write(json.dumps({"source":name,"region":region,"video_id":p[0],
                    "url":p[4] if len(p)>4 else f"{name}:{p[0]}",
                    "title":p[1],"author":p[2],"duration":p[3],
                    "description":"","search_keyword":kw,"top_comments":[],
                    "collected_at":datetime.now().isoformat()},ensure_ascii=False)+"\n")
                added+=1
            fh.flush()
            print(f"    {name}/{kw}: +{added}", flush=True)
            time.sleep(1)

def run():
    seen=load_seen()
    with open_out() as fh:
        crawl_bilibili(fh, seen)
        crawl_youtube(fh, seen)
        crawl_probe(fh, seen)
    total=sum(1 for _ in open(OUT,encoding="utf-8"))
    print(f"\n[完成] 累计 {total} 条 -> {OUT}", flush=True)

if __name__=="__main__":
    run()