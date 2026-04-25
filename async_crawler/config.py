"""全局配置"""
import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = "football_intel"

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
    "iap_pricing":   86400 * 7,  # 每周
    "fb_adlib":      86400,
}
