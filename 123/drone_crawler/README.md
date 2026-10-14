# 无人机视频爬虫（纯数据层）
==========================
本目录**只**包含：
- 多站点爬虫脚本（B 站 API + YouTube yt-dlp + 10 国际站自动探针）
- 关键词库
- 爬取数据 data/raw/（multi_raw.jsonl / drone_videos.xlsx）
- 按站点出 xlsx 的数据整理脚本

**所有 AI 相关代码（P/T 权重、分类器、校准、机载决策、模拟器）已全部移至 `123/drone_ai`。**

## 使用
```
双击 start_all.bat        爬取视频 -> data/raw/multi_raw.jsonl + drone_videos.xlsx
```
爬完数据后，AI 分析在 drone_ai 里跑：
```
cd 123/drone_ai
python -m analyzer.run_all    # 4 步：事件库/动作库/清洗/P-T 校准
```

## 文件说明
- multi_site_crawler.py   多站爬虫
- keywords.py             关键词库（72 中文 + 54 英文，6 大类）
- xlsx_generator.py       按站点出 xlsx（纯数据整理，非 AI）
- serial_bridge.py        5 路串口桥接（机载/仿真用）
- data/raw/               爬取数据（jsonl + xlsx）

## 扩充数据
- 加关键词：改 keywords.py
- 调爬取量：改 keywords.py 的 BILI_PER_KW / YT_PER_KW
- 加站点：multi_site_crawler.py 的 PROBE_SITES
