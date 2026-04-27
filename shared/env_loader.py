"""轻量 .env.local 解析器，零依赖。

用法：
    from shared.env_loader import load_env_file
    load_env_file()  # 自动找项目根的 .env.local

设计：
- 已存在的 env var 优先（不覆盖 shell export 的值）
- 支持 KEY=VALUE / KEY="VALUE" / KEY='VALUE' / # 注释 / 空行
- 不支持嵌套引号、变量插值（保持简单）
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path | str | None = None, override: bool = False) -> int:
    """加载一个 .env 风格文件到 os.environ。

    Args:
        path: 文件路径；缺省时找项目根 `.env.local`
        override: True 时覆盖已存在的 env var；False（默认）时不覆盖

    Returns:
        实际注入的变量数（不含被跳过的）
    """
    if path is None:
        path = _PROJECT_ROOT / ".env.local"
    else:
        path = Path(path)

    if not path.exists():
        return 0

    injected = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        # 去配对引号
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = val
        injected += 1
    return injected


if __name__ == "__main__":
    # CLI: 显示可加载到的 key 名（值不打印，避免泄露）
    n = load_env_file()
    print(f"[env_loader] 注入 {n} 个变量；当前可用 key 名（值不打印）：")
    for k in sorted(os.environ.keys()):
        if k.endswith("_KEY") or k.endswith("_TOKEN") or "API" in k:
            print(f"  - {k}: {'<set>' if os.environ.get(k) else '<empty>'}")
