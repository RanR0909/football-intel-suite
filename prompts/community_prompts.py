"""社媒舆情分析 prompt（Reddit 等）。

prompt 函数返回纯字符串，由调用方拼入 Claude API 请求。
所有 prompt 强制要求 Claude 输出 JSON，便于下游程序化解析。
"""

from __future__ import annotations

import json


def _format_post_block(post: dict, max_selftext: int = 280, max_comments: int = 3) -> str:
    """单条 Reddit 帖子转 prompt 文本块（含 top 评论）。"""
    parts = [
        f"[r/{post.get('subreddit', '?')} · {post.get('score', 0)}↑ · {post.get('num_comments', 0)}💬] "
        f"{(post.get('title') or '').strip()}"
    ]
    selftext = (post.get("selftext") or "").strip()
    if selftext:
        parts.append(f"  正文: {selftext[:max_selftext]}")
    comments = post.get("comments") or []
    for c in comments[:max_comments]:
        body = (c.get("body") or "").strip().replace("\n", " ")
        if body:
            parts.append(f"  > [{c.get('score', 0)}↑] {body[:200]}")
    return "\n".join(parts)


def build_community_insights_prompt(
    competitor: str,
    posts: list,
    days: int = 7,
    sample_limit: int = 60,
) -> str:
    """构造社媒舆情分析 prompt。

    Args:
        competitor: 竞品名（如 "SofaScore"）
        posts: 已按时间窗过滤的 Reddit 帖子列表（aggregator/ai_analyzer 上游负责过滤）
        days: 时间窗（仅用于在 prompt 文本中描述）
        sample_limit: 送给 Claude 的最大帖子数（控制 token 成本）
    """
    sample = posts[:sample_limit]
    blocks = "\n\n".join(_format_post_block(p) for p in sample)

    schema_example = json.dumps({
        "overall_summary": "300 字内整体舆情",
        "sentiment": {"positive": 0.4, "neutral": 0.4, "negative": 0.2},
        "top_topics": ["话题1", "话题2"],
        "pain_points": ["抱怨1", "抱怨2"],
        "opportunities": ["产品机会1"],
        "competitor_mentions": ["FlashScore", "OneFootball"],
        "representative_quotes": ["原话1", "原话2"],
        "alert_level": "low | medium | high",
    }, ensure_ascii=False, indent=2)

    return f"""你是一名资深体育 App 产品经理 + 社媒舆情分析师，正在分析 Reddit 上关于「{competitor}」近 {days} 天内的讨论。

# 任务
基于下方 {len(sample)} 条 Reddit 帖子（含 top 评论），输出结构化舆情分析。

# 分析要求
1. overall_summary：用中性、可执行的语气写整体舆情（300 字内）。说清楚用户主要在讨论什么、整体情绪、是否有突发事件。
2. sentiment：基于全部样本估算正面 / 中性 / 负面比例（三者之和接近 1.0，保留 1 位小数）。
3. top_topics：用户讨论最多的 3-5 个话题（功能、版本、体验等），用短语而非整句。
4. pain_points：用户抱怨的具体问题（如崩溃、UI、广告、数据延迟），用短语，按频次排序。
5. opportunities：从用户讨论中能识别出的产品机会点（用户希望、对手做得好的、新需求），具体可落地。
6. competitor_mentions：被拿来对比的其他产品名（不含 {competitor} 本身）。
7. representative_quotes：3-5 条最能代表整体舆情的原话片段（保留英文原文，不翻译，剪到 80 字内）。
8. alert_level：基于 pain_points 的严重度和频次判断 — 仅出现常规反馈用 low；有反复出现的核心抱怨用 medium；出现大规模差评 / 流失信号 / 竞品超车信号用 high。

# 输出格式
严格输出 **单个 JSON 对象**，不要 markdown 包裹（不要 ```json），不要前后多余文字。schema 示例：
{schema_example}

# Reddit 原始数据（{len(sample)} 条）
{blocks}
"""
