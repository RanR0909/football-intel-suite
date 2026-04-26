"""产品更新日志关键词字典（中英多语种）。

匹配逻辑：substring 命中即归该类。一条更新可同时命中多个类（用 tags 数组），
主类型 type 用 TYPE_PRIORITY 解决冲突。

业务排序考量：
- pricing 优先：商业模式变化是最强信号，竞品分析必须最优先识别
- localization 次之：涉及市场扩张 / 区域策略调整
- bugfix 第三：防御性更新，重要性中等
- feature 兜底：大部分模糊更新归这里
"""

CHANGE_TYPE_KEYWORDS = {
    "feature": [
        "new", "feature", "redesign", "redesigned", "added", "support for",
        "introducing", "launch", "launched", "widget", "widgets", "multiview",
        "ai ", "ai-", "depth chart", "lineup", "insight", "analytics",
        "新增", "上线", "重新设计", "新功能", "支持",
    ],
    "bugfix": [
        "fix", "fixes", "fixed", "bug", "crash", "issue", "resolve", "resolved",
        "stability", "performance", "improvement", "improvements", "minor fixes",
        "smoother", "patch",
        "修复", "崩溃", "稳定性", "性能优化", "已知问题",
    ],
    "pricing": [
        "price", "pricing", "subscription", "subscriptions", "premium", "trial",
        "upgrade", "plan", "plans", "billing", "tier", "iap", "in-app purchase",
        "free trial", "discount",
        "订阅", "价格", "会员", "试用", "付费",
    ],
    "localization": [
        "language", "languages", "locale", "translation", "translations",
        "now available in", "spanish", "portuguese", "japanese", "arabic",
        "german", "french", "italian", "korean",
        "本地化", "语言", "翻译", "葡语", "日语", "西班牙语",
    ],
}

# 主 type 优先级（命中多类时取最靠前的）
TYPE_PRIORITY = ["pricing", "localization", "bugfix", "feature"]
