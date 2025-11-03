# src/api/fetch_stations_all_scales.py
#
# Objectif: récupérer les listes de stations pour 3 échelles (6 min, horaire, quotidienne)
# par département, avec sauvegarde en JSON par {échelle}/{departement}.
# Auth: header "apikey: <token_portail_MF>"
# Pas de parametre de filtre ici: on veut les métadonnées de stations uniquement.

import os
import json
from pathlib import Path
from typing import Dict, List, Union

import requests
from requests import HTTPError


# --- Config globale ---

# Base de l’API
BASE_URL = os.getenv("METEO_BASE_URL", "https://public-api.meteofrance.fr/public/DPClim/v1")

# Dossier de sortie
SAVE_DIR = Path(os.getenv("METEO_SAVE_DIR", "data/metadonnees/download/stations"))

# Départements à interroger (adapte si nécessaire)
DEPARTMENTS: List[int] = [38, 73, 74]

# Mapping échelle -> suffixe d’endpoint
SCALES: Dict[str, str] = {
    "infrahoraire-6m": "/liste-stations/infrahoraire-6m",
    "horaire":         "/liste-stations/horaire",
    "quotidienne":     "/liste-stations/quotidienne",
}


# --- Auth helpers ---

def _read_api_key() -> str:
    """
    Lis la clé API (JWT portail MF) depuis, par ordre de priorité:
      1) var d'env METEO_API_KEY
      2) fichier pointé par METEO_API_KEY_FILE
      3) fallback local ./.secrets/meteo_api_key_stations
    """
    key = os.getenv("METEO_API_KEY")
    if key:
        return key.strip()

    key_file = os.getenv("METEO_API_KEY_FILE")
    if key_file and Path(key_file).exists():
        return Path(key_file).read_text(encoding="utf-8").strip()

    # fallback simple pour dev local
    fallback = Path(__file__).resolve().parents[2] / ".secrets" / "meteo_api_key_stations"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8").strip()

    raise RuntimeError("METEO_API_KEY manquante (ou fichier introuvable).")


def _headers_json() -> Dict[str, str]:
    """
    Headers standard JSON pour l’API MF.
    """
    return {
        "accept": "application/json",
        "apikey": _read_api_key(),
    }


# --- Appels cœur ---

def fetch_stations_for_scale(
    department: int,
    scale: str,
    save_dir: Union[Path, str] = SAVE_DIR,
) -> list:
    """
    Appelle GET /liste-stations/{scale}?id-departement=DD
    Sauvegarde data/{scale}/stations_{DD}.json
    Retourne la liste JSON renvoyée par l’API.
    """
    # Vérif échelle
    if scale not in SCALES:
        raise ValueError(f"Échelle inconnue: {scale}. Attendu: {list(SCALES.keys())}")

    # URL complète + params
    url = f"{BASE_URL}{SCALES[scale]}"
    params = {"id-departement": department}

    # Requête
    resp = requests.get(url, headers=_headers_json(), params=params, timeout=30)

    # 204 = pas de contenu
    if resp.status_code == 204:
        raise RuntimeError(f"{scale} dept {department}: Pas de contenu (204).")

    # Contrôle HTTP
    try:
        resp.raise_for_status()
    except HTTPError as e:
        # Log court et utile
        code = resp.status_code
        body = resp.text[:400]
        raise RuntimeError(f"{scale} dept {department}: HTTP {code} {body}") from e

    # Parsing JSON
    data = resp.json()

    # Écriture disque: un fichier par échelle+département
    out_dir = Path(save_dir) / scale
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"stations_{department}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return data


def fetch_all_scales_all_departments(
    departments: List[int] = DEPARTMENTS,
    scales: List[str] = list(SCALES.keys()),
    save_dir: Union[Path, str] = SAVE_DIR,
) -> Dict[str, Dict[int, Union[list, dict]]]:
    """
    Boucle sur toutes les échelles et tous les départements.
    Retour: {scale: {dept: list | {"error": "..."} } }
    """
    results: Dict[str, Dict[int, Union[list, dict]]] = {s: {} for s in scales}

    for s in scales:
        for d in departments:
            try:
                results[s][d] = fetch_stations_for_scale(d, s, save_dir=save_dir)
            except Exception as e:
                # On capture l’erreur pour continuer les autres appels
                results[s][d] = {"error": str(e)}

    return results


# --- CLI simple ---

if __name__ == "__main__":
    """
    Exécution directe:
      - Lit la clé via _read_api_key()
      - Récupère 3 échelles pour chaque département
      - Écrit les JSON dans data/metadonnees/{échelle}/stations_{dept}.json
      - Log minimal sur stdout
    """
    res = fetch_all_scales_all_departments()

    for scale, per_dept in res.items():
        for dept, data in per_dept.items():
            if isinstance(data, dict) and "error" in data:
                print(f"[{scale}] Dept {dept}: error: {data['error']}")
            else:
                n = len(data) if isinstance(data, list) else "unknown"
                print(f"[{scale}] Dept {dept}: saved -> {SAVE_DIR}/{scale}/stations_{dept}.json (items: {n})")
