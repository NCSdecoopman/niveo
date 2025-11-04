#!/usr/bin/env python3
# fetch_stations_stream_csv.py
# But:
#   - Récupérer les stations par échelle et département depuis DPClim
#   - Dédupliquer par id et fusionner les _scales
#   - Filtrer par altitude (ALT_SELECT, env)
#   - Émettre UNIQUEMENT du CSV sur stdout: id,nom,lon,lat,alt,_scales
#   - Logs: stderr + logs/stations/AAAAMMJJHHMMSS.log
#
# Remplace l’usage de combine_stations + fichiers intermédiaires.

import argparse
import os
import sys
import json
import csv
import time
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List
import requests

# --- Config (env + défauts) ---
BASE_URL = os.getenv("METEO_BASE_URL", "https://public-api.meteofrance.fr/public/DPClim/v1")
ALT_SELECT = float(os.getenv("ALT_SELECT", "1000"))
MAX_RPM = int(os.getenv("METEO_MAX_RPM", "50"))
RATE_PERIOD = 60.0

SCALES = {
    "infrahoraire-6m": "/liste-stations/infrahoraire-6m",
    "horaire": "/liste-stations/horaire",
    "quotidienne": "/liste-stations/quotidienne",
}

# --- Auth ---
from ..api.token_provider import get_api_key, clear_token_cache  # noqa: E402

# --- Logs fichier + stderr ---
def _init_log_file() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    p = Path("logs/stations")
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{ts}.log"

_LOG_PATH = _init_log_file()

def _log(msg: str) -> None:
    # fichier
    with _LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(msg.rstrip() + "\n")
    # stderr
    print(msg, file=sys.stderr)

# --- Rate limiting basique ---
class RateLimiter:
    def __init__(self, max_calls: int, period_sec: float):
        self.max_calls = max_calls
        self.period = period_sec
        self.calls = deque()

    def wait(self) -> None:
        now = time.time()
        while self.calls and (now - self.calls[0]) > self.period:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            sleep_for = self.period - (now - self.calls[0]) + 0.01
            if sleep_for > 0:
                time.sleep(sleep_for)
        self.calls.append(time.time())

_rl = RateLimiter(MAX_RPM, RATE_PERIOD)

def _headers_json() -> Dict[str, str]:
    token = get_api_key(use_cache=True)
    return {"accept": "application/json", "authorization": f"Bearer {token}"}

def _annotate_with_scale(items, scale: str):
    # Ajoute _scale et fusionne _scales si présent
    for it in items:
        if not isinstance(it, dict):
            continue
        prev = it.get("_scales") or []
        if scale not in prev:
            it["_scales"] = [*prev, scale]

def _fetch_one(dept: int, scale: str) -> List[dict]:
    # Requête DPClim robuste avec retry token et 429
    url = f"{BASE_URL}{SCALES[scale]}"
    params = {"id-departement": dept}
    _rl.wait()
    r = requests.get(url, headers=_headers_json(), params=params, timeout=30)

    if r.status_code == 204:
        raise RuntimeError(f"{scale} dept {dept}: 204 No Content")

    if r.status_code in (401, 403):
        clear_token_cache()
        _rl.wait()
        r = requests.get(url, headers=_headers_json(), params=params, timeout=30)
        r.raise_for_status()
    elif r.status_code == 429:
        retry_after = r.headers.get("Retry-After", "60")
        time.sleep(float(retry_after))
        _rl.wait()
        r = requests.get(url, headers=_headers_json(), params=params, timeout=30)
        r.raise_for_status()
    else:
        r.raise_for_status()

    data = r.json()
    if not isinstance(data, list):
        return []

    _annotate_with_scale(data, scale)
    return data

def _merge_in_memory(departments: List[int], scales: List[str]) -> Dict[int, dict]:
    """
    Déduplique par id. Conserve nom/lon/lat/alt du premier vu.
    Fusionne _scales. Retourne dict {id: station_dict}
    """
    merged: Dict[int, dict] = {}
    errors = 0
    for s in scales:
        if s not in SCALES:
            _log(f"[warn] échelle inconnue ignorée: {s}")
            continue
        for d in departments:
            try:
                items = _fetch_one(d, s)
                _log(f"[count] scale={s} dept={d} items={len(items)}")
            except Exception as e:
                errors += 1
                _log(f"[error] scale={s} dept={d} -> {e}")
                items = []

            for st in items:
                sid = st.get("id")
                if sid is None:
                    continue
                try:
                    sid_int = int(sid)
                except Exception:
                    # ids non numériques: garder tel quel en clé str
                    sid_int = sid

                # Premier vu: copier champs utiles
                if sid_int not in merged:
                    merged[sid_int] = {
                        "id": sid_int,
                        "nom": st.get("nom"),
                        "lon": st.get("lon"),
                        "lat": st.get("lat"),
                        "alt": st.get("alt"),
                        "_scales": list(st.get("_scales") or []),
                    }
                else:
                    # Fusion _scales
                    prev = merged[sid_int].get("_scales") or []
                    cur = st.get("_scales") or []
                    merged[sid_int]["_scales"] = sorted(set(prev).union(cur))

    _log(f"[merge] unique_ids={len(merged)} errors={errors}")
    return merged

def _emit_csv(merged: Dict[int, dict], min_alt: float) -> int:
    """
    Écrit sur stdout: CSV header + lignes.
    Filtre alt >= min_alt si alt numérique, sinon garde la ligne.
    Retourne le nombre de lignes émises (hors header).
    """
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["id", "nom", "lon", "lat", "alt", "_scales"])

    n = 0
    for st in merged.values():
        alt = st.get("alt")
        try:
            alt_val = float(alt)
            if alt_val < min_alt:
                continue
        except Exception:
            # alt manquante ou non numérique -> on ne filtre pas
            pass

        # Sécurité sur nom et scales sérialisés
        nom = str(st.get("nom") or "").replace(",", " ")
        scales_json = json.dumps(st.get("_scales") or [], ensure_ascii=False, separators=(",", ":"))

        w.writerow([
            st.get("id", ""),
            nom,
            st.get("lon", ""),
            st.get("lat", ""),
            st.get("alt", ""),
            scales_json
        ])
        n += 1

    _log(f"[emit] csv_rows={n}")
    return n

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scales", type=lambda s: [x.strip() for x in s.split(",")], default=["quotidienne"])
    p.add_argument("--departments", type=lambda s: [int(x) for x in s.split(",")], default=[38, 73, 74])
    p.add_argument("--min-alt", type=float, default=ALT_SELECT, help="filtre alt >= min-alt")
    args = p.parse_args()

    _log(f"[run] start min_alt={args.min_alt} scales={args.scales} departments={args.departments}")

    merged = _merge_in_memory(args.departments, args.scales)
    rows = _emit_csv(merged, args.min_alt)

    if rows == 0:
        # Permet de faire échouer un pipeline si rien à émettre
        print("id,nom,lon,lat,alt,_scales")  # garantit un header
        _log("[warn] no rows emitted (post-filter)")
        # exit 0 si tu veux éviter l'échec CI
        # sys.exit(1)

if __name__ == "__main__":
    main()
