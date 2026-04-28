"""Alembic env — 从 MYSQL_DSN env 读 DSN，关联 shared.models.Base.metadata。"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 把项目根加到 path 让 shared.models / shared.env_loader 可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 自动加载 .env.local + ~/.intelops-secrets
try:
    from shared.env_loader import load_all
    load_all()
except Exception:
    pass

from shared.models import Base  # noqa: E402

config = context.config

# 从 env 注入 DSN（覆盖 alembic.ini 里的空值）
_dsn = (os.environ.get("MYSQL_DSN") or "").strip()
if _dsn:
    config.set_main_option("sqlalchemy.url", _dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    if not cfg.get("sqlalchemy.url"):
        raise RuntimeError("MYSQL_DSN 未配置；alembic 无法运行迁移。请先 `docker compose up -d` "
                           "并在 .env.local 设置 MYSQL_DSN")
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
