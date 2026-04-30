import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
COMPETITORS_PATH = DATA_DIR / "competitors.json"


DEFAULT_COMPETITORS = {
    "SofaScore": {
        "gp": "com.sofascore.results",
        "ios": 1176147574,
        "app_id": "1176147574",
        "bundle_id": "com.SofaScore.iOS",
    },
    "FlashScore": {
        "gp": "com.flashscore.app",
        "ios": 766443283,
        "app_id": "766443283",
        "bundle_id": "eu.livesport.FlashScore-com",
    },
    "OneFootball": {
        "gp": "com.onefootball.onefootball.google",
        "ios": 382002079,
        "app_id": "382002079",
        "bundle_id": "de.motain.iliga",
    },
    "365Scores": {
        "gp": "com.scores365.android",
        "ios": 571801488,
        "app_id": "571801488",
        "bundle_id": "com.365scores.365scroesapp",
    },
    "Fotmob": {
        "gp": "com.fotmob.fotmob",
        "ios": 488575683,
        "app_id": "488575683",
        "bundle_id": "com.mobilefootie.fotmobpro",
    },
    "LiveScore": {
        "gp": "com.livescore.livescores",
        "ios": 356928178,
        "app_id": "356928178",
        "bundle_id": "com.livescore.ios",
    },
}


def _normalize_entry(name: str, raw: dict) -> dict:
    entry = dict(raw)
    entry["name"] = entry.get("name", name)

    if entry.get("ios") and not entry.get("app_id"):
        entry["app_id"] = str(entry["ios"])
    if entry.get("app_id") and not entry.get("ios"):
        try:
            entry["ios"] = int(entry["app_id"])
        except (TypeError, ValueError):
            pass

    return entry


def _coerce_registry(data) -> dict[str, dict]:
    if isinstance(data, dict) and isinstance(data.get("competitors"), dict):
        return {
            name: _normalize_entry(name, raw)
            for name, raw in data["competitors"].items()
            if isinstance(raw, dict)
        }

    if isinstance(data, dict) and isinstance(data.get("apps"), list):
        result = {}
        for item in data["apps"]:
            if isinstance(item, dict) and item.get("name"):
                result[item["name"]] = _normalize_entry(item["name"], item)
        return result

    if isinstance(data, dict):
        return {
            name: _normalize_entry(name, raw)
            for name, raw in data.items()
            if isinstance(raw, dict)
        }

    return {}


def ensure_competitors_file() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not COMPETITORS_PATH.exists():
        save_competitors(DEFAULT_COMPETITORS)
    return COMPETITORS_PATH


def load_competitors() -> dict[str, dict]:
    ensure_competitors_file()
    try:
        data = json.loads(COMPETITORS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_COMPETITORS)

    registry = _coerce_registry(data)
    return registry or dict(DEFAULT_COMPETITORS)


def save_competitors(competitors: dict[str, dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = {
        name: _normalize_entry(name, raw)
        for name, raw in competitors.items()
        if isinstance(raw, dict)
    }
    COMPETITORS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return COMPETITORS_PATH


def get_comment_competitors() -> dict[str, dict]:
    return {
        name: entry
        for name, entry in load_competitors().items()
        if entry.get("gp") and entry.get("ios")
    }


def get_website_competitors() -> dict[str, str]:
    """{name: domain} — 仅返回带 website 字段的竞品（给 similarweb 抓取用）。"""
    return {
        name: entry["website"].strip().lower().lstrip("www.")
        for name, entry in load_competitors().items()
        if entry.get("website")
    }


def get_strategy_monitor_apps() -> dict[str, int]:
    return {
        name: int(entry["ios"])
        for name, entry in load_competitors().items()
        if entry.get("ios")
    }


def get_market_rank_competitors() -> dict[str, dict[str, str]]:
    result = {}
    for name, entry in load_competitors().items():
        app_id = entry.get("app_id") or entry.get("ios")
        if not app_id:
            continue
        result[name] = {
            "app_id": str(app_id),
            "bundle_id": entry.get("bundle_id", ""),
        }
    return result
