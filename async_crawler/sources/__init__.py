from async_crawler.sources import (
    appstore_rank,
    reviews,
    androidrank,
    reddit,
    google_news,
    app_versions,
)
# fb_adlib / sensor_tower / iap_pricing 已迁移到 market_rank/scrape_*.py（Playwright 持久 profile）
# iap_pricing 改用 qimai.cn（Apple 直抓被 IP redirect 到 CN storefront 卡死）
# app_versions: iTunes Lookup → app_versions 表（spec 后端协作清单 §3.2）
