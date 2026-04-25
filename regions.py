import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
REGIONS_PATH = DATA_DIR / "regions.json"


DEFAULT_REGIONS = {
    "us": {"label": "美国", "lang": "en"},
    "ng": {"label": "尼日利亚", "lang": "en"},
    "my": {"label": "马来西亚", "lang": "en"},
    "id": {"label": "印尼", "lang": "en"},
    "sa": {"label": "沙特", "lang": "en"},
    "ae": {"label": "阿联酋", "lang": "en"},
    "jp": {"label": "日本", "lang": "ja"},
    "ca": {"label": "加拿大", "lang": "en"},
    "vn": {"label": "越南", "lang": "en"},
    "gb": {"label": "英国", "lang": "en"},
    "br": {"label": "巴西", "lang": "en"},
}


def ensure_regions_file() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not REGIONS_PATH.exists():
        save_regions(DEFAULT_REGIONS)
    return REGIONS_PATH


def load_regions() -> dict[str, dict]:
    ensure_regions_file()
    try:
        data = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_REGIONS)

    if isinstance(data, dict) and data:
        result = {}
        for code, info in data.items():
            if not isinstance(info, dict):
                continue
            result[code] = {
                "label": info.get("label", code.upper()),
                "lang": info.get("lang", "en"),
            }
        if result:
            return result

    return dict(DEFAULT_REGIONS)


def save_regions(regions: dict[str, dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = {}
    for code, info in regions.items():
        if not isinstance(info, dict):
            continue
        normalized[code] = {
            "label": info.get("label", code.upper()),
            "lang": info.get("lang", "en"),
        }
    REGIONS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return REGIONS_PATH


def get_region_codes() -> list[str]:
    return list(load_regions().keys())
