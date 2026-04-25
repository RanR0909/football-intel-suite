#!/usr/bin/env python3
"""Headless runner for commercial_strategy — exports JSON to data/"""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from commercial_strategy import run_all, export_json, generate_weekly_report, export_weekly_json, CLAUDE_API_KEY

def main():
    if not CLAUDE_API_KEY:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量")
        sys.exit(1)

    if "--weekly" in sys.argv:
        print("=" * 60)
        print("商业策略周报生成 (Headless)")
        print("=" * 60)
        data = generate_weekly_report()
        export_weekly_json(data)
    else:
        print("=" * 60)
        print("商业策略分析 (Headless)")
        print("=" * 60)
        data = run_all()
        export_json(data)
    print("完成")

if __name__ == "__main__":
    main()
