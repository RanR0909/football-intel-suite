"""Meta 广告投放策略 AI 分析 prompt。

输入：AdsInfo 字典（含 active_count / new_ads / trend / by_country / top_themes /
user_segments / creative_patterns / creative_diversity）+ top_creatives 列表。
输出：严格 JSON，schema 见 build_ads_strategy_prompt。

设计要点：
- "opportunities" 强制 AI 输出"我方该做什么"，不是"竞品在做什么"
- "risks" 强制带"建议响应时间"，避免空泛
- "alert_level" + "confidence" 双信号（即使 alert=high 但 confidence=low，运营会要求先收数据）
- 喂给 AI 的 creatives 按 days_running 排序，让 AI 优先看已验证素材
"""

from __future__ import annotations

import json


def build_ads_strategy_prompt(
    competitor: str,
    ads_info: dict,
    sample_creatives: list,
    sample_limit: int = 15,
) -> str:
    """构造 Claude 分析 prompt。

    Args:
        competitor: 竞品名
        ads_info: AdsInfo dict（aggregator 派生）
        sample_creatives: top_creatives 列表（按 days_running 倒序）
        sample_limit: 送给 Claude 的最大素材条数（控制 token）
    """
    sample = (sample_creatives or [])[:sample_limit]

    ctx = {
        "active_count": ads_info.get("active_count", 0),
        "new_ads": ads_info.get("new_ads", 0),
        "trend": ads_info.get("trend", "stable"),
        "trend_pct": ads_info.get("trend_pct"),
        "by_country": ads_info.get("by_country", {}),
        "top_themes": [{"theme": t.get("theme"), "count": t.get("count")} for t in (ads_info.get("top_themes") or [])],
        "user_segments": [{"segment": s.get("segment"), "count": s.get("count"), "signal_strength": s.get("signal_strength")}
                          for s in (ads_info.get("user_segments") or [])],
        "creative_patterns": [{"pattern": p.get("pattern"), "count": p.get("count")} for p in (ads_info.get("creative_patterns") or [])],
        "creative_diversity": ads_info.get("creative_diversity"),
    }

    creatives_text = "\n".join(
        f"[{c.get('country', '?')} · 已投 {c.get('days_running', 0)} 天 · "
        f"{','.join(c.get('themes') or []) or '无标签'}] "
        f"{(c.get('body_text') or '').strip()[:300]}"
        for c in sample
    )

    schema_example = json.dumps({
        "core_strategy": "300字内：竞品当前的核心投放策略（最多 3 句，含目的：拉新/付费/品牌/召回）",
        "target_persona": ["核心目标用户画像短语 1", "短语 2"],
        "value_props": ["主打卖点 1", "卖点 2", "卖点 3"],
        "geo_focus": ["重点市场 1", "市场 2"],
        "opportunities": ["可借鉴的素材模式 / 我方该补的卖点（执行视角）"],
        "risks": ["对我方业务的具体威胁（必须含建议响应时间，如'30 天内'、'下版本前'）"],
        "alert_level": "low | medium | high",
        "confidence": "low | medium | high",
    }, ensure_ascii=False, indent=2)

    return f"""你是体育 App 行业的资深增长营销负责人 + 竞品分析师。基于 Facebook Ad Library 数据
分析「{competitor}」当前的广告投放策略。

# 数据概览
{json.dumps(ctx, ensure_ascii=False, indent=2)}

# 代表性广告样本（按持续投放天数排序，越长 = 越可能是已验证素材）
{creatives_text}

# 分析要求
1. **core_strategy**：竞品在打什么仗？（不要泛泛说"投放广告"，要说清楚目的：拉新 / 召回 / 付费转化 / 品牌曝光，及其证据）
2. **target_persona**：从文案推断目标用户画像（如"东南亚高频博彩用户"、"欧洲硬核数据迷"）
3. **value_props**：竞品在主推的产品价值点（按优先级，3-5 个）
4. **geo_focus**：基于 by_country 和文案语种判断
5. **opportunities**：**给我方产品的可执行机会**（不是夸竞品，是说"竞品验证过 X 模式，我方可以用 Y 复用 / 反制"）
6. **risks**：**对我方的具体威胁**（必须含"建议响应时间"，如"30 天内"、"下版本前"）
7. **alert_level**：low（仅常规投放）/ medium（有针对性扩量）/ high（重大策略转向，需立即响应）
8. **confidence**：基于样本量和文案多样性自评

输出 **严格 JSON**，schema 示例：
{schema_example}

不要 markdown 包裹，不要前后噪声。
"""
