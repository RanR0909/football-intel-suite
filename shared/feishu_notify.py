"""feishu_notify — 飞书自定义机器人 Webhook 推送（文本 + 交互卡片）。

用法：
    from shared.feishu_notify import send_text, send_card, is_enabled

    if is_enabled():
        send_text("简单文本")
        send_card("INTEL-OPS 每日抓取", fields=[
            {"label": "Phase 1", "value": "✓ 9 / ✗ 1"},
        ], color="green")

未配置 FEISHU_WEBHOOK_URL 时所有调用静默返回（不抛异常、不阻塞主流程）。

设置：
1. 飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 安全设置选"关键词"，填 "INTEL-OPS"（或其他）
3. 复制 Webhook URL → 填到 .env.local：
     FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
     FEISHU_KEYWORD=INTEL-OPS
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

WEBHOOK_ENV = "FEISHU_WEBHOOK_URL"
KEYWORD_ENV = "FEISHU_KEYWORD"
DASHBOARD_URL_ENV = "DASHBOARD_BASE_URL"
DEFAULT_KEYWORD = "INTEL-OPS"
DEFAULT_DASHBOARD_URL = "http://localhost:5173"
TIMEOUT = 10


# ─────────────────────────── Dashboard URL helpers ────────────────────────────


def _dashboard_base() -> str:
    return (os.environ.get(DASHBOARD_URL_ENV) or DEFAULT_DASHBOARD_URL).rstrip("/")


def dashboard_url(path: str = "/", **query) -> str:
    """构造 dashboard URL，自动拼 query 参数。"""
    from urllib.parse import urlencode
    base = _dashboard_base()
    if not path.startswith("/"):
        path = "/" + path
    qs = urlencode({k: v for k, v in query.items() if v is not None and v != ""})
    return f"{base}{path}{('?' + qs) if qs else ''}"


def alert_url(alert_type: str, app_name: str = "", alert_id: int | None = None) -> str:
    """alert 类型 → 对应 dashboard 子页 URL（与前端 AlertRow.buildDetailHref 对齐）。"""
    page_map = {
        "ranking":    ("/data/rankings", {"competitor": app_name}),
        "commercial": ("/data/iap",      {"competitor": app_name}),
        "news":       ("/content/news",  {"competitor": app_name}),
        "release":    ("/content/releases", {"competitor": app_name}),
        "rating":     ("/content/gp-reviews", {"competitor": app_name}),
        "churn":      ("/content/gp-reviews", {"competitor": app_name, "label": "churn_signal"}),
        "ads":        ("/content/ads",   {"competitor": app_name}),
    }
    path, params = page_map.get(alert_type, ("/alerts", {}))
    if alert_id:
        params["id"] = str(alert_id)
    return dashboard_url(path, **params)


def is_enabled() -> bool:
    """检查 webhook 是否已配置。"""
    return bool((os.environ.get(WEBHOOK_ENV) or "").strip())


def _keyword() -> str:
    return (os.environ.get(KEYWORD_ENV) or DEFAULT_KEYWORD).strip()


def _post(payload: dict) -> bool:
    """POST payload 到 webhook。失败返回 False（不抛）。

    SSL 验证：默认开。公司网络做 HTTPS 中间人代理（自签名根 CA）时验不过，
    会拿到 `CERTIFICATE_VERIFY_FAILED`。在 .env.local 设置 FEISHU_VERIFY_SSL=false
    可绕过验证，跟 ai_tasks.json 里 endpoint 的 verify_ssl 一个思路。
    """
    url = (os.environ.get(WEBHOOK_ENV) or "").strip()
    if not url:
        return False
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    verify = (os.environ.get("FEISHU_VERIFY_SSL", "true").strip().lower()
              not in ("false", "0", "no"))
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") not in (0, None):
            print(f"[feishu] webhook 返回错误: {data}")
            return False
        return True
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
        print(f"[feishu] 推送失败: {e}")
        return False


def send_text(text: str) -> bool:
    """发纯文本消息（自动在前面拼关键词，触发飞书安全策略）。"""
    if not is_enabled():
        return False
    full = f"[{_keyword()}] {text}"
    return _post({"msg_type": "text", "content": {"text": full}})


# 颜色映射（飞书卡片 template）
_TEMPLATE_BY_COLOR = {
    "green":  "green",
    "blue":   "blue",
    "orange": "orange",
    "red":    "red",
    "grey":   "grey",
}


def send_card(
    title: str,
    fields: list[dict],
    *,
    color: str = "blue",
    footer: str | None = None,
    actions: list[dict] | None = None,
) -> bool:
    """发交互卡片消息。

    Args:
        title:   顶部标题（前缀自动加 keyword）
        fields:  list[{"label": str, "value": str}]，每项一行
        color:   green / blue / orange / red / grey（决定头部色块）
        footer:  底部备注（可选，如时间戳）
        actions: 底部按钮，list[{"text": str, "url": str, "type"?: str}]
                 用 dashboard_url() / alert_url() helper 构造 URL 到看板对应子页
    """
    if not is_enabled():
        return False
    template = _TEMPLATE_BY_COLOR.get(color, "blue")
    elements: list[dict] = []
    for f in fields:
        label = f.get("label", "")
        value = f.get("value", "")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{label}**\n{value}",
            },
        })
    if actions:
        valid = [a for a in actions if a.get("url")]
        if valid:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": a.get("text", "查看")},
                        "type": a.get("type", "primary"),
                        "url": a["url"],
                    }
                    for a in valid
                ],
            })
    if footer:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": footer}],
        })
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": f"[{_keyword()}] {title}"},
            },
            "elements": elements,
        },
    }
    return _post(payload)


if __name__ == "__main__":
    # 调试入口：python3 -m shared.feishu_notify "测试文本"
    import sys
    if not is_enabled():
        print("FEISHU_WEBHOOK_URL 未设置；先在 .env.local 配置")
        sys.exit(2)
    msg = sys.argv[1] if len(sys.argv) > 1 else "smoke test"
    ok = send_text(msg)
    print(f"send_text → {ok}")
    ok = send_card("测试卡片", fields=[
        {"label": "字段一", "value": "值 1"},
        {"label": "字段二", "value": "值 2"},
    ], color="green", footer="自动同步测试")
    print(f"send_card → {ok}")
