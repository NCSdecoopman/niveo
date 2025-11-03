# src/api/mf_auth.py
# Rôle: obtenir et mettre en cache le token OAuth2 portail MF.
# Sortie: une chaîne "access_token" à placer dans le header "apikey".
#
# Entrées possibles:
# - MF_BASIC_AUTH_B64: "base64(client_id:client_secret)"
# - OU MF_CLIENT_ID + MF_CLIENT_SECRET
# - SINON fichier .secrets/mf_api_id contenant "id:secret" OU sa base64
#
# Cache:
# - fichier JSON .secrets/mf_token.json: {access_token, expires_at}
# - marge d'anticipation (skew) par défaut 300 s

from __future__ import annotations
import os, json, base64, time
from pathlib import Path
from typing import Optional
import requests
from requests import HTTPError

# Config par défaut
REPO_ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = Path(os.getenv("SECRETS_DIR", REPO_ROOT / ".secrets"))
MF_ID_FILE = Path(os.getenv("MF_ID_FILE", SECRETS_DIR / "mf_api_id"))
TOKEN_CACHE = Path(os.getenv("METEO_TOKEN_CACHE", SECRETS_DIR / "mf_token.json"))
TOKEN_URL = os.getenv("METEO_TOKEN_URL", "https://portail-api.meteofrance.fr/token")

def _basic_auth_b64() -> str:
    """Retourne la chaîne base64(client_id:client_secret)."""
    # 1) déjà fourni en base64
    b64 = os.getenv("MF_BASIC_AUTH_B64")
    if b64:
        return b64.strip()

    # 2) id + secret en env
    cid, sec = os.getenv("MF_CLIENT_ID"), os.getenv("MF_CLIENT_SECRET")
    if cid and sec:
        return base64.b64encode(f"{cid}:{sec}".encode()).decode()

    # 3) fichier .secrets/mf_api_id
    if not MF_ID_FILE.exists():
        raise RuntimeError(f"Identifiants manquants. Fournir MF_BASIC_AUTH_B64, ou MF_CLIENT_ID+MF_CLIENT_SECRET, ou {MF_ID_FILE}")
    raw = MF_ID_FILE.read_text(encoding="utf-8").strip()
    if ":" in raw:
        return base64.b64encode(raw.encode()).decode()
    # sinon on suppose déjà base64, vérification rapide
    try:
        base64.b64decode(raw.encode())
    except Exception:
        raise RuntimeError("mf_api_id invalide. Expected 'id:secret' ou base64(id:secret).")
    return raw

def _read_cache(skew_sec: int = 300) -> Optional[str]:
    """Lit le token si non expiré (avec marge skew_sec)."""
    if not TOKEN_CACHE.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        if time.time() < float(data.get("expires_at", 0)) - skew_sec:
            return data.get("access_token")
    except Exception:
        return None
    return None

def _write_cache(access_token: str, expires_in: int) -> None:
    """Écrit le cache avec expires_at absolu."""
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": access_token,
        "expires_at": time.time() + int(expires_in),
        "written_at": time.time(),
    }
    TOKEN_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def fetch_new_token() -> str:
    """Appelle l'OAuth2 client_credentials et retourne un 'access_token' neuf."""
    headers = {"Authorization": f"Basic {_basic_auth_b64()}"}
    data = {"grant_type": "client_credentials"}
    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=20)
    try:
        resp.raise_for_status()
    except HTTPError as e:
        raise RuntimeError(f"OAuth2 MF échec {resp.status_code}: {resp.text[:300]}") from e
    body = resp.json()
    token = body.get("access_token")
    expires_in = int(body.get("expires_in", 3600))
    if not token:
        raise RuntimeError("OAuth2 sans access_token.")
    _write_cache(token, expires_in)
    return token

def get_api_key(use_cache: bool = True, skew_sec: int = 300) -> str:
    """Retourne un token valide. Utilise le cache si demandé, sinon force un nouveau."""
    if use_cache:
        cached = _read_cache(skew_sec=skew_sec)
        if cached:
            return cached
    return fetch_new_token()

def clear_token_cache() -> None:
    """Supprime le cache de token si présent."""
    try:
        TOKEN_CACHE.unlink(missing_ok=True)
    except Exception:
        pass

# CLI simple: python -m src.api.mf_auth [--fresh] [--print]
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Génère un token MF et le met en cache.")
    p.add_argument("--fresh", action="store_true", help="Ignore le cache. Force un nouveau token.")
    p.add_argument("--print", dest="do_print", action="store_true", help="Affiche le token sur stdout.")
    args = p.parse_args()

    if args.fresh:
        clear_token_cache()
        token = fetch_new_token()
    else:
        token = get_api_key(use_cache=True)

    if args.do_print:
        print(token)
