"""轻量 .env.local 解析器，零依赖。

用法：
    from shared.env_loader import load_env_file
    load_env_file()  # 自动找：项目根 .env.local + 兜底 ~/.intelops-secrets

设计：
- 加载顺序：项目内 .env.local → ~/.intelops-secrets（兜底跨机器使用）
- 已存在的 env var 优先（不覆盖 shell export 的值）
- 支持 KEY=VALUE / KEY="VALUE" / KEY='VALUE' / # 注释 / 空行
- 不支持嵌套引号、变量插值（保持简单）

跨机器迁移：
- 项目根的 .env.local 是 gitignored，每台机器单独维护
- 如果你想"换台 Mac 不用重填"：把 ~/.intelops-secrets 这一份在多机间同步
  （iCloud Drive / Dropbox / Syncthing 都行），所有项目都能读
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME_SECRETS_PATH = Path.home() / ".intelops-secrets"


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


def load_all(override: bool = False) -> int:
    """加载所有已知配置位置。返回总注入数。

    顺序（先到先得，已存在的不覆盖）：
      1. 项目根 .env.local         — 项目专属，per-clone
      2. ~/.intelops-secrets       — 用户级，跨项目 / 跨机器（推荐放在 iCloud Drive）

    第二个文件不存在不报错（可选）。
    """
    n = 0
    n += load_env_file(_PROJECT_ROOT / ".env.local", override=override)
    n += load_env_file(HOME_SECRETS_PATH, override=override)
    return n


if __name__ == "__main__":
    # CLI: 显示可加载到的 key 名（值不打印，避免泄露）
    n = load_all()
    print(f"[env_loader] 注入 {n} 个变量；扫描位置：")
    print(f"  - {_PROJECT_ROOT / '.env.local'}: {'存在' if (_PROJECT_ROOT / '.env.local').exists() else '不存在'}")
    print(f"  - {HOME_SECRETS_PATH}: {'存在' if HOME_SECRETS_PATH.exists() else '不存在'}")
    print(f"\n当前可用 key 名（值不打印）：")
    for k in sorted(os.environ.keys()):
        if k.endswith("_KEY") or k.endswith("_TOKEN") or "API" in k or k.startswith("FEISHU"):
            print(f"  - {k}: {'<set>' if os.environ.get(k) else '<empty>'}")
