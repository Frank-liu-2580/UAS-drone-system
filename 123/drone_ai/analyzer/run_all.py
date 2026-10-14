# -*- coding: utf-8 -*-
"""一键运行分析层（现位于 drone_ai/analyzer/，爬虫数据在 drone_crawler/data/raw/）：
  1) event_builder   -> Anomaly_Events.xlsx
  2) video_action_db -> Video_Action_DB.xlsx
  3) clean_unknown   -> Video_Action_DB_cleaned.xlsx
  4) calibrate_pt    -> Decision_Matrix_Calibrated.xlsx + Calibrate_Report.md
用法：可从任意目录运行  python -m analyzer.run_all（P1-1：不再限定 CWD）
"""
import os, sys, runpy

HERE = os.path.dirname(os.path.abspath(__file__))          # .../drone_ai/analyzer
PARENT = os.path.dirname(HERE)                              # .../drone_ai
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def _run_script(modname):
    """以脚本方式逐个运行（它们用 if __name__=='__main__' 组织流程）。"""
    p = os.path.join(HERE, modname + ".py")
    print("=" * 50)
    print("运行 " + modname)
    print("=" * 50)
    runpy.run_path(p, run_name="__main__")
    print()


def main():
    # P1-1：子脚本用 HERE 绝对路径，但 os.chdir(HERE) 仍保留以兼容
    # 任何尚未改绝对路径的残留相对路径引用
    os.chdir(HERE)
    _run_script("event_builder")
    _run_script("video_action_db")
    _run_script("clean_unknown")
    _run_script("calibrate_pt")
    print("[全部完成] 输出在 drone_ai/analyzer/output/ 下")


if __name__ == "__main__":
    main()
