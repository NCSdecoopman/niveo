# src/api/token_provider.py
# Fournit un token valide (lit cache, sinon régénère).

import os, json, time
from pathlib import Path
from src.api.mf_auth import fetch_new_token  # dépendance unique vers le générateur

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = Path(os.getenv("SECRETS_DIR", REPO_ROOT / ".secrets"))
TOKEN_CACHE = Path(os.getenv("METEO_TOKEN_CACHE", SECRETS_DIR / "mf_token.json"))

def _read_cache(skew_sec: int = 300) -> str | None:
    if not TOKEN_CACHE.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        if time.time() < float(data.get("expires_at", 0)) - skew_sec:
            return data.get("access_token")
    except Exception:
        return None
    return None

def get_api_key(use_cache: bool = True, skew_sec: int = 300) -> str:
    # use_cache=True → tente cache avant régénération
    if use_cache:
        cached = _read_cache(skew_sec=skew_sec)
        if cached:
            return cached
    return fetch_new_token()

def clear_token_cache() -> None:
    try:
        TOKEN_CACHE.unlink(missing_ok=True)
    except Exception:
        pass

if __name__ == "__main__":
    # CLI: python -m src.api.token_provider  -> imprime un token valide
    print(get_api_key(use_cache=True))
