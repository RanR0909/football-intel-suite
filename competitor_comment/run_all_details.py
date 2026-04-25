#!/usr/bin/env python3
import subprocess, sys, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from competitors import get_comment_competitors

COMPETITORS = list(get_comment_competitors().keys())
script = Path(__file__).parent / "competitor_detail.py"

for name in COMPETITORS:
    print(f"[{name}] 分析中...")
    subprocess.run([sys.executable, str(script), name], env=os.environ.copy())

print("全部完成")
