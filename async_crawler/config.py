"""全局配置（2026-04-28：MongoDB 已弃用，主存储改为 MySQL，配置见 shared/db.py）"""

# 并发控制
MAX_CONCURRENT = 5       # 同时最多 5 个请求
REQUEST_TIMEOUT = 30     # 秒

# 调度间隔（秒）
SCHEDULE = {
    "appstore_rank": 3600,       # 每小时
    "reviews":       86400,      # 每天
    "sensor_tower":  86400,
    "androidrank":   86400,
    "reddit":        3600,
    "fb_adlib":      86400,
}
