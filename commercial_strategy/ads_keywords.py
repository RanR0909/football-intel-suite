"""Meta 广告文案关键词字典（中英多语种）。

按"业务语义"分组（不是按"关键词分类"）。每个 label 的 value 是触发该业务标签的关键词列表
— 文案中命中任意一个关键词即归入该 label。

关键词全部以小写匹配，匹配方式是 substring（如 "live scores" 命中 "live"）。
若需精确边界匹配，需在 processor 内升级为 regex \\b 边界。

涵盖语种（基于 fb_adlib AD_COUNTRIES = US/GB/BR）：
  - 英文：US/GB
  - 葡萄牙语：BR
  - 西班牙语 / 中文 / 日语 / 阿拉伯语：覆盖未来扩展（regions.json 内已配 sa/ae/jp/vn）
"""

THEME_KEYWORDS = {
    "实时比分":     ["live", "real-time", "realtime", "实时", "直播", "ao vivo",
                    "tempo real", "en vivo", "ライブ"],
    "赛事数据":     ["stats", "statistics", "数据", "estatística", "estadística",
                    "lineup", "阵容", "xg", "heatmap"],
    "VIP / 订阅":   ["vip", "premium", "subscribe", "subscription", "会员",
                    "订阅", "ad-free", "no ads", "sem anúncios"],
    "博彩导流":     ["odds", "betting", "bet now", "tip", "predict", "投注",
                    "胜率", "apostas", "palpites"],
    "赛事预告":     ["fixture", "schedule", "kickoff", "赛程", "今日比赛",
                    "agenda", "próximos jogos"],
    "球员 / 球队":  ["messi", "ronaldo", "haaland", "mbappé", "transfer",
                    "team", "球员", "转会", "jogador", "time"],
    "新闻资讯":     ["news", "breaking", "新闻", "rumour", "report",
                    "notícias", "notícia"],
    "通知 / 速度":  ["notification", "alert", "fast", "instant", "通知",
                    "提醒", "alerta", "rápido"],
}

SEGMENT_KEYWORDS = {
    "硬核球迷":     ["analytics", "depth chart", "xg", "advanced stats",
                    "tactical", "深度", "战术", "análise tática"],
    "轻度用户":     ["simple", "easy", "quick check", "fast", "简洁",
                    "一键", "fácil", "rápido"],
    "博彩用户":     ["odds", "tip", "bet", "predict", "投注", "胜率",
                    "apostas", "palpites"],
    "经理玩家":     ["fpl", "fantasy", "manager", "draft", "梦幻", "fantasia"],
    "本地球迷":     ["premier league", "epl", "bundesliga", "serie a",
                    "la liga", "中超", "j-league", "brasileirão", "libertadores"],
}

PATTERN_KEYWORDS = {
    "比分截图":     ["screenshot", "截图", "tela", "captura"],
    "用户证言":     ["i love", "best app", "5 stars", "review", "推荐",
                    "好评", "melhor app", "amo"],
    "排行榜":       ["top 10", "ranking", "best", "排行", "榜单", "melhor"],
    "数据可视化":   ["heatmap", "chart", "graph", "图表", "gráfico"],
    "限时活动":     ["limited", "today only", "flash", "限时", "立即",
                    "agora", "oferta"],
    "明星驱动":     ["messi", "ronaldo", "haaland", "mbappé", "neymar"],
}
