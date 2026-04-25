import json
from collections import Counter


REQUEST_KEYWORDS = [
    "wish", "would be nice", "please add", "i miss", "would love",
    "could you", "please bring back", "希望", "只是", "唯一", "最好",
    "请增加", "希望增加", "希望能", "如果能", "想要", "缺少",
]
CHURN_KEYWORDS = [
    "used to", "before", "anymore", "no longer", "once", "previously",
    "曾经", "以前", "原来", "之前", "不再", "现在却",
]
COMPARE_KEYWORDS = [
    "better than", "worse than", "compared to", "比", "不如", "相比", "竞品", "换到",
]


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text[:limit]


def _label_dist_text(rows: list[dict]) -> str:
    dist = Counter(row.get("label", "[其他]") for row in rows)
    return "、".join(f"{label}:{count}" for label, count in dist.items()) or "无标签"


def _contains_any(text: str, keywords: list[str]) -> bool:
    text = (text or "").lower()
    return any(keyword.lower() in text for keyword in keywords)


def _signal_priority(row: dict, competitor_names: list[str] | None = None) -> tuple:
    text = row.get("content", "") or ""
    text_lower = text.lower()
    score = row.get("score", 0) or 0
    competitors = [name.lower() for name in (competitor_names or [])]
    mentions_competitor = any(name in text_lower for name in competitors)
    request_signal = score >= 4 and _contains_any(text, REQUEST_KEYWORDS)
    churn_signal = score <= 2 and _contains_any(text, CHURN_KEYWORDS)
    compare_signal = mentions_competitor or _contains_any(text, COMPARE_KEYWORDS)
    negative_signal = score <= 2

    return (
        0 if request_signal else 1,
        0 if churn_signal else 1,
        0 if compare_signal else 1,
        0 if negative_signal else 1,
        score,
    )


def _sample_rows(
    rows: list[dict],
    limit: int,
    text_limit: int,
    include_region: bool = False,
    include_platform: bool = False,
    include_label: bool = True,
    competitor_names: list[str] | None = None,
) -> str:
    ordered = sorted(
        rows,
        key=lambda row: _signal_priority(row, competitor_names) + (row.get("label", ""), row.get("platform", "")),
    )
    lines = []
    for idx, row in enumerate(ordered[:limit], start=1):
        parts = [f"[{idx}]"]
        if include_platform:
            parts.append(f"[{row.get('platform', '?')}]")
        if include_region:
            parts.append(f"[{row.get('region_label') or row.get('region', '?')}]")
        parts.append(f"[{row.get('score', '?')}★]")
        version = row.get("version") or ""
        if version:
            parts.append(f"[v{version}]")
        if include_label:
            parts.append(f"[{row.get('label', '')}]")
        parts.append(_truncate(row.get("content", ""), text_limit))
        lines.append(" ".join(part for part in parts if part))
    return "\n".join(lines)


def build_label_prompt(id_map: dict[str, str], categories: str) -> str:
    return (
        f"对以下评论按 {categories} 归类。"
        "仅返回 JSON {id: 类别}，不输出其他内容。\n"
        f"{json.dumps(id_map, ensure_ascii=False)}"
    )


def build_daily_summary_prompt(
    app_name: str,
    region_code: str,
    days: int,
    rows: list[dict],
    competitor_names: list[str] | None = None,
) -> str:
    score_dist = dict(Counter(row.get("score", 0) for row in rows))
    return (
        f"以下是「{app_name}」近{days}天在 {region_code.upper()} 区的 App Store 与 Google Play 评论。\n"
        f"评论总数：{len(rows)}\n"
        f"评分分布：{json.dumps(score_dist, ensure_ascii=False)}\n"
        "请提炼：\n"
        "① 用户抱怨最多的 3 个问题（按频次排序）\n"
        "② 用户主动要求的 3 个功能（区分 5 星用户 vs 低星用户）\n"
        "③ 与竞品的对比提及（用户说“比 X 好/差”的场景）\n"
        "④ 忠实用户流失信号（曾经好评、现在差评的用户）\n"
        "⑤ 如果评论里能看出版本或评分变化趋势，补充一句判断；看不出来就明确说样本不足。\n"
        "使用纯文本格式，不要使用 Markdown 标记（不要用 #、*、-、| 等标记符号）。\n"
        "只基于提供的评论做判断，不要编造不存在的竞品、功能或趋势。\n"
        f"信号标签分布：{_label_dist_text(rows)}\n\n"
        f"评论样本：\n{_sample_rows(rows, limit=40, text_limit=140, competitor_names=competitor_names)}"
    )


def build_competitor_detail_prompt(
    app_name: str,
    days: int,
    rows: list[dict],
    region_names: list[str],
    competitor_names: list[str] | None = None,
) -> str:
    label_dist = dict(Counter(r.get("label", "[其他]") for r in rows))
    platform_dist = dict(Counter(r.get("platform", "unknown") for r in rows))
    region_dist = dict(Counter(r.get("region_label", "") for r in rows))
    samples = _sample_rows(
        rows,
        limit=60,
        text_limit=180,
        include_region=True,
        include_platform=True,
        competitor_names=competitor_names,
    )
    return f"""你是一名资深体育 App 产品经理，正在对竞品「{app_name}」进行深度评论分析。

分析目标：从过去{days}天的全部用户评论中提取高价值产品信号。

配置地区：
{", ".join(region_names)}

数据概况：
- 总评论数：{len(rows)} 条
- 标签分布：{json.dumps(label_dist, ensure_ascii=False)}
- 平台分布：{json.dumps(platform_dist, ensure_ascii=False)}
- 地区分布：{json.dumps(region_dist, ensure_ascii=False)}

请生成《竞品评论深度分析报告》，要求：
1. 必须覆盖配置中的主要地区差异；如果某些地区样本不足，要明确写出“样本不足”
2. 提炼用户抱怨最多的 3 个问题，并说明它们主要集中在哪些地区/平台
3. 提炼用户主动要求的 3 个功能，明确区分 5 星用户的请求和低星用户的请求
4. 找出与竞品的直接对比提及，说明用户把它和谁比较、比较点是什么
5. 找出忠实用户流失信号，如“used to”“以前很好”“现在越来越差”
6. 如果能从评分或评论内容看出情感变化趋势，做简要判断；看不出来就写样本不足
7. 给出 3 条可执行的产品改进建议
8. 引用用户原句作为证据
9. 只基于提供的数据判断，不要编造未出现的地区、样本量或结论

格式要求：
- 使用纯文本方括号标签，如 [高价值功能请求]
- 禁止使用 emoji
- 使用纯文本格式，不要使用 Markdown 标记
- 结构化输出，每个痛点带地区/平台标注

评论样本：
{samples}"""


def build_weekly_report_prompt(
    days: int,
    competitor_names: list[str],
    region_names: list[str],
    total_reviews: int,
    label_dist: dict,
    platform_dist: dict,
    region_dist: dict,
    competitor_lines: list[str],
    region_lines: list[str],
    comp_samples: dict[str, list[dict]],
    competitor_names_for_signal: list[str] | None = None,
) -> str:
    sample_sections = []
    for comp_name in competitor_names:
        reviews = comp_samples.get(comp_name, [])
        sample_sections.append(f"=== {comp_name} ===")
        sample_sections.append(
            _sample_rows(
                reviews,
                limit=10,
                text_limit=150,
                include_region=True,
                include_platform=True,
                competitor_names=competitor_names_for_signal,
            ) or "无样本"
        )
    sample_text = "\n".join(sample_sections)

    return f"""你是一名资深体育 App 产品经理，正在撰写《竞品评论周报》。

分析周期：过去 {days} 天
总评论数：{total_reviews} 条
涉及竞品：{", ".join(competitor_names)}
涉及地区：{", ".join(region_names)}
标签分布：{json.dumps(label_dist, ensure_ascii=False)}
平台分布：{json.dumps(platform_dist, ensure_ascii=False)}
地区分布：{json.dumps(region_dist, ensure_ascii=False)}

竞品汇总：
{chr(10).join(competitor_lines)}

地区汇总：
{chr(10).join(region_lines)}

请生成周报，要求：

一、本周核心发现（3-5条）
- 跨竞品的关键趋势（正面与负面均需覆盖）
- 最突出的用户痛点
- 5 星评论里的高价值功能请求
- 用户好评最集中的功能亮点
- 忠实用户流失信号

二、各竞品分析摘要
必须覆盖以下每一个竞品，不能遗漏，也不能编造名单外竞品：
{", ".join(competitor_names)}
对每个竞品给出：
- 评论数量与评分分布趋势
- Top 2 用户抱怨
- Top 2 功能请求，并区分 5 星用户 vs 低星用户
- Top 2 用户好评亮点（用户满意的功能或体验）
- 竞品对比提及与流失信号
- 结合不同地区反馈差异的改进建议
- 若某竞品在某些地区评论很少，也要明确写出”样本较少”

三、本地化专题分析（重点）
- 必须覆盖以下每一个地区，不能遗漏，也不能编造名单外地区：
{", ".join(region_names)}
- 按地区分析本地化问题（翻译质量、本地联赛覆盖、地区特有功能需求）
- 哪些地区对本地化抱怨最多？
- 哪些地区用户满意度最高？原因是什么？
- 具体本地化问题举例

四、跨竞品功能对比
- 哪些功能问题是多个竞品共有的？
- 哪些是某个竞品独有的问题？
- 哪些竞品被用户频繁拿来比较？
- 哪些功能获得跨竞品的一致好评？

五、评分趋势与正面信号
- 各竞品的高分评论（4-5星）集中在哪些功能或体验上？
- 哪些竞品的用户忠诚度信号最强（长期用户好评、主动推荐）？
- 有哪些值得我方借鉴的产品亮点？

格式要求：
- 使用纯文本方括号标签，如 [竞品对比]
- 禁止使用 emoji
- 使用纯文本格式，不要使用 Markdown 标记
- 结构化输出，每个部分用标题分隔
- 只基于提供的数据做判断，不要杜撰未出现的国家、竞品、数据量或结论
- 如果发现某地区或某竞品样本明显不足，要明确标注”样本不足”

评论样本：
{sample_text}"""


def build_localization_prompt(
    region_names: list[str],
    localization_reviews: list[dict],
    competitor_names: list[str] | None = None,
) -> str:
    by_region = {}
    for review in localization_reviews:
        region = review.get("region_label", "unknown")
        by_region.setdefault(region, []).append(review)

    region_summary = {region: len(items) for region, items in by_region.items()}
    region_sections = []
    for region_name in region_names:
        region_label = region_name.split("(")[0]
        rows = by_region.get(region_label, [])
        region_sections.append(f"=== {region_name} ===")
        region_sections.append(
            _sample_rows(
                rows,
                limit=8,
                text_limit=140,
                include_region=False,
                include_platform=True,
                competitor_names=competitor_names,
            ) or "无明显本地化样本"
        )

    return f"""分析以下体育 App 用户评论中的地区化问题。

地区相关评论数：{len(localization_reviews)} 条
配置地区：{", ".join(region_names)}
按地区分布：{json.dumps(region_summary, ensure_ascii=False)}

请生成《地区化问题专题分析》，要求：
1. 必须逐个检查配置中的每个地区，即使某地区没有明显相关评论，也要说明“未发现明显样本”
2. 按地区列出用户关注点类型（翻译质量、本地联赛覆盖、地区特有功能、内容偏好）
3. 尽量指出问题涉及的竞品
4. 给出 3 条面向地区运营/产品的改进建议
5. 不能编造配置之外的地区
6. 只基于提供的数据判断

评论样本：
{chr(10).join(region_sections)}"""
