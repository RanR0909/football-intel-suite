"""统一 AI 调用入口。

业务模块只需：
    from shared.ai_client import run_task
    result = run_task("review_3d", context={"competitor": "SofaScore", ...})

所有 HTTP / SSL / 重试 / 解析 / 配置合并都在此完成。
密钥从环境变量读取（建议用 shared.env_loader 加载 .env.local）。
"""

from __future__ import annotations

import importlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "ai_tasks.json"

_config_cache: dict | None = None


# ─────────────────────────── 配置加载 ───────────────────────────

def load_config() -> dict:
    """读 ai_tasks.json，缓存到内存。"""
    global _config_cache
    if _config_cache is None:
        if not _CONFIG_PATH.exists():
            raise FileNotFoundError(f"ai 配置文件不存在: {_CONFIG_PATH}")
        _config_cache = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return _config_cache


def reload_config() -> dict:
    """强制重读（开发期改完 JSON 立刻生效）。"""
    global _config_cache
    _config_cache = None
    return load_config()


def _resolve(task_name: str) -> dict:
    """合并 endpoint < model < task < env override，返回最终 cfg dict。"""
    cfg = load_config()
    if task_name not in cfg["tasks"]:
        raise KeyError(f"未知 AI 任务: {task_name}")
    task = cfg["tasks"][task_name]
    model = cfg["models"][task["model"]]
    endpoint = cfg["endpoints"][model["endpoint"]]

    resolved: dict = {
        # 来自 model（含 fallback_endpoint 等）
        **model,
        # 来自 task（除 model 引用 / prompt spec 外都覆盖 model）
        **{k: v for k, v in task.items() if k not in ("model", "prompt")},
        # 来自 endpoint
        "endpoint_url": endpoint["url"],
        "provider": endpoint.get("provider", "anthropic"),
        "auth_header": endpoint["auth_header"],
        "auth_prefix": endpoint.get("auth_prefix", ""),
        "api_key_env": endpoint["api_key_env"],
        "extra_headers": endpoint.get("extra_headers", {}),
        "verify_ssl": endpoint.get("verify_ssl", True),
        "prompt_spec": task["prompt"],
        # fallback endpoint 的字段（如配置）
        "_fallback_endpoint": model.get("fallback_endpoint"),
        "_fallback_on_status": model.get("fallback_on_status", []),
    }

    # env override：AI_OVERRIDE__<task>__<field>=value
    prefix = f"AI_OVERRIDE__{task_name}__"
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue
        field = k[len(prefix):].lower()
        try:
            resolved[field] = json.loads(v)
        except json.JSONDecodeError:
            resolved[field] = v
    return resolved


def _resolve_endpoint_for_fallback(endpoint_name: str) -> dict:
    """临时拉一个 endpoint 的字段（fallback 用）。"""
    cfg = load_config()
    e = cfg["endpoints"][endpoint_name]
    return {
        "endpoint_url": e["url"],
        "provider": e.get("provider", "anthropic"),
        "auth_header": e["auth_header"],
        "auth_prefix": e.get("auth_prefix", ""),
        "api_key_env": e["api_key_env"],
        "extra_headers": e.get("extra_headers", {}),
        "verify_ssl": e.get("verify_ssl", True),
    }


# ─────────────────────────── Prompt 构造 ───────────────────────────

def _build_prompt(spec: dict, context: dict) -> str:
    """支持 inline template 或 module+function 引用。"""
    if "template" in spec:
        return spec["template"].format(**(context or {}))
    if "module" in spec and "function" in spec:
        mod = importlib.import_module(spec["module"])
        fn = getattr(mod, spec["function"])
        return fn(**(context or {}))
    raise ValueError("prompt spec 必须含 'template' 或 ('module' + 'function')")


# ─────────────────────────── Provider 适配 ───────────────────────────

def _request_anthropic(cfg: dict, prompt: str) -> tuple[dict, Callable[[dict], str]]:
    body = {
        "model": cfg["name"],
        "max_tokens": int(cfg["max_tokens"]),
        "temperature": float(cfg.get("temperature", 0.3)),
        "messages": [{"role": "user", "content": prompt}],
    }
    return body, lambda r: r["content"][0]["text"]


def _request_openai(cfg: dict, prompt: str) -> tuple[dict, Callable[[dict], str]]:
    body = {
        "model": cfg["name"],
        "max_tokens": int(cfg["max_tokens"]),
        "temperature": float(cfg.get("temperature", 0.3)),
        "messages": [{"role": "user", "content": prompt}],
    }
    return body, lambda r: r["choices"][0]["message"]["content"]


PROVIDERS: dict[str, Callable[[dict, str], tuple[dict, Callable[[dict], str]]]] = {
    "anthropic": _request_anthropic,
    "openai": _request_openai,
}


# ─────────────────────────── HTTP ───────────────────────────

def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _do_http(url: str, body: bytes, headers: dict, timeout: int, verify_ssl: bool) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers)
    ctx = _ssl_context(verify_ssl)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read())


def _http_call(cfg: dict, prompt: str) -> str:
    api_key = os.environ.get(cfg["api_key_env"], "").strip()
    if not api_key:
        raise RuntimeError(
            f"缺少环境变量 {cfg['api_key_env']}。配置方法：\n"
            f"  1) 项目根 .env.local 添加 {cfg['api_key_env']}=...\n"
            f"  2) 或浏览器顶部 API Key 框填入"
        )

    provider = cfg.get("provider", "anthropic")
    if provider not in PROVIDERS:
        raise ValueError(f"不支持的 provider: {provider}")
    builder = PROVIDERS[provider]
    body_dict, parser = builder(cfg, prompt)
    body = json.dumps(body_dict).encode("utf-8")

    auth_value = (cfg.get("auth_prefix") or "") + api_key
    headers = {"Content-Type": "application/json", cfg["auth_header"]: auth_value}
    headers.update(cfg.get("extra_headers", {}))

    try:
        resp = _do_http(cfg["endpoint_url"], body, headers, int(cfg.get("timeout", 60)), cfg.get("verify_ssl", True))
        return parser(resp)
    except urllib.error.HTTPError as e:
        # 是否需要 fallback
        fb = cfg.get("_fallback_endpoint")
        fb_codes = set(cfg.get("_fallback_on_status") or [])
        if fb and e.code in fb_codes:
            fallback_cfg = {**cfg, **_resolve_endpoint_for_fallback(fb)}
            return _http_call_no_fallback(fallback_cfg, prompt)
        raise


def _http_call_no_fallback(cfg: dict, prompt: str) -> str:
    """fallback 调用（不再递归）。复用 builder 逻辑。"""
    api_key = os.environ.get(cfg["api_key_env"], "").strip()
    if not api_key:
        raise RuntimeError(f"fallback 端点缺少 {cfg['api_key_env']}")
    builder = PROVIDERS[cfg.get("provider", "anthropic")]
    body_dict, parser = builder(cfg, prompt)
    body = json.dumps(body_dict).encode("utf-8")
    auth_value = (cfg.get("auth_prefix") or "") + api_key
    headers = {"Content-Type": "application/json", cfg["auth_header"]: auth_value}
    headers.update(cfg.get("extra_headers", {}))
    resp = _do_http(cfg["endpoint_url"], body, headers, int(cfg.get("timeout", 60)), cfg.get("verify_ssl", True))
    return parser(resp)


# ─────────────────────────── 输出解析 ───────────────────────────

def _strip_json(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]
    return s.strip()


def _parse_output(text: str, cfg: dict) -> Any:
    fmt = cfg.get("output_format", "text")
    if fmt == "json":
        candidate = _strip_json(text) if cfg.get("json_strip_markdown") else text
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return {"_raw": text, "_parse_error": True}
    return text


# ─────────────────────────── 主入口 ───────────────────────────

def run_task(task_name: str, context: dict | None = None, overrides: dict | None = None) -> Any:
    """统一 AI 任务调用入口。

    Args:
        task_name: ai_tasks.json::tasks 里的 key
        context:   填充 prompt 模板的变量（dict）
        overrides: 临时覆盖（model / max_tokens / temperature / timeout 等）

    Returns:
        text  当 output_format == "text"
        dict  当 output_format == "json"
    """
    cfg = _resolve(task_name)
    if overrides:
        cfg.update(overrides)

    prompt = _build_prompt(cfg["prompt_spec"], context or {})

    retries = int(cfg.get("retries", 3))
    backoff = cfg.get("retry_backoff", [2, 4, 6])
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            text = _http_call(cfg, prompt)
            return _parse_output(text, cfg)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                delay = backoff[min(attempt, len(backoff) - 1)]
                time.sleep(delay)
    assert last_err is not None
    raise last_err


# ─────────────────────────── 调试 ───────────────────────────

def explain_task(task_name: str) -> dict:
    """返回某个 task 解析后的完整配置（用于调试 / 看实际生效值）。"""
    return _resolve(task_name)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("task_name", help="ai_tasks.json::tasks 里的 key")
    ap.add_argument("--explain", action="store_true", help="只打印解析后的配置，不实际调用")
    args = ap.parse_args()
    if args.explain:
        print(json.dumps(explain_task(args.task_name), ensure_ascii=False, indent=2, default=str))
    else:
        print("用法: python -m shared.ai_client <task_name> --explain")
