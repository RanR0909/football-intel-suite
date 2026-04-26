"""更新日志关键词分类。

输入：release_notes 字符串 + changes 列表
输出：(主类型, 全部命中标签列表)
"""

from __future__ import annotations

from .changelog_keywords import CHANGE_TYPE_KEYWORDS, TYPE_PRIORITY


def classify_changelog(text: str | None, changes: list | None = None) -> tuple[str, list[str]]:
    """返回 (主类型, 全部命中标签)。空文本默认 feature。"""
    haystack = (text or "").lower()
    if changes:
        haystack += " " + " ".join(changes).lower()

    if not haystack.strip():
        return "feature", []

    tags: list[str] = []
    for label, keywords in CHANGE_TYPE_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            tags.append(label)

    if not tags:
        return "feature", []

    # 主类型按优先级
    for t in TYPE_PRIORITY:
        if t in tags:
            return t, tags
    return tags[0], tags
