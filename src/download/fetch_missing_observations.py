#!/usr/bin/env python3
# fetch_missing_observations.py
# Relance ciblée des observations manquantes au format groupé:
# [{"id": 38002401, "dates": ["YYYY-MM-DD", ...]}, ...]
# - Ne traite que les ids ayant ≤ --max-dates-per-id dates (défaut 3)
# - Appelle fetch_observations.py pour chaque (id,date) éligible
# - Agrège un seul header CSV sur stdout
# - Retire uniquement la date résolue ; supprime l'id si plus de dates
# - Écriture atomique du JSON

import os
import sys
import json
import csv
import argparse
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple

DEFAULT_MISSING = Path(os.getenv("MISSING_OBS_JSON", "data/metadonnees/missing_observations.json"))
DEFAULT_STATIONS = Path(os.getenv("STATIONS_JSON", "data/metadonnees/stations.json"))
DEFAULT_LOGDIR = Path(os.getenv("OBS_LOGDIR", "logs/observations"))

# --- I/O helpers -----------------------------------------------------------

def _read_missing_grouped(path: Path) -> List[Dict[str, Any]]:
    """Lit {id, dates:[...]} → liste normalisée triée, dates dédupliquées."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    if not isinstance(data, list):
        return out

    for item in data:
        if not isinstance(item, dict):
            continue
        if "id" not in item or "dates" not in item or not isinstance(item["dates"], list):
            continue
        try:
            sid = int(item["id"])
        except Exception:
            continue
        dates = sorted({str(d).strip() for d in item["dates"] if str(d).strip()})
        if dates:
            out.append({"id": sid, "dates": dates})
    out.sort(key=lambda e: e["id"])
    return out

def _atomic_write_json_grouped(path: Path, grouped: List[Dict[str, Any]]) -> None:
    """Écrit proprement la liste {id, dates:[...]}, en supprimant les entrées vides."""
    cleaned = []
    for e in grouped:
        dates = [d for d in e.get("dates", []) if str(d).strip()]
        if dates:
            cleaned.append({"id": int(e["id"]), "dates": sorted(set(dates))})
    cleaned.sort(key=lambda x: x["id"])

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        json.dump(cleaned, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)

# --- Core ------------------------------------------------------------------

def _run_fetch_observations(date_str: str, station_id: int, stations_path: Path, logdir: Path) -> Tuple[bool, List[List[str]]]:
    """Exécute src.download.fetch_observations et renvoie (success, rows CSV)."""
    cmd = [
        sys.executable,
        "-m", "src.download.fetch_observations",
        "--date", date_str,
        "--id", str(station_id),
        "--stations", str(stations_path),
        "--logdir", str(logdir),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as ex:
        sys.stderr.write(f"[spawn] échec lancement fetch_observations: {repr(ex)}\n")
        return False, []

    if proc.returncode != 0 and proc.stderr:
        sys.stderr.write(proc.stderr)

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return False, []

    reader = csv.reader(lines)
    rows = [row for row in reader]
    if not rows:
        return False, []

    # success si une data row possède une date non vide en col 1
    success = any((len(r) >= 2 and r[1].strip() != "") for r in rows[1:])
    return success, rows

def fetch_all(missing_path: Path, stations_path: Path, logdir: Path,
              dry_run: bool=False, max_dates_per_id: int=3) -> int:
    """Traite uniquement les ids avec ≤ max_dates_per_id dates."""
    items = _read_missing_grouped(missing_path)
    if not items:
        return 0

    # Filtrage des ids éligibles
    eligible_ids = {e["id"] for e in items if len(e["dates"]) <= max_dates_per_id}

    # Liste mutable pour MAJ du JSON
    remaining = [{ "id": e["id"], "dates": list(e["dates"]) } for e in items]

    # Plan de travail: seulement les éligibles
    work: List[Tuple[int, str]] = []
    for e in items:
        if e["id"] not in eligible_ids:
            continue
        for d in e["dates"]:
            work.append((e["id"], d))
    work.sort(key=lambda x: (x[0], x[1]))

    header_written = False
    writer = csv.writer(sys.stdout, lineterminator="\n")

    for sid, date_str in work:
        ok, rows = _run_fetch_observations(date_str, sid, stations_path, logdir)

        if rows:
            if not header_written:
                writer.writerow(rows[0])
                header_written = True
            for r in rows[1:]:
                writer.writerow(r)

        if ok:
            # Retire uniquement la date résolue pour cet id
            for ent in remaining:
                if ent["id"] == sid and date_str in ent["dates"]:
                    ent["dates"].remove(date_str)
                    break

    # Nettoyage + tri
    remaining = [{"id": ent["id"], "dates": sorted(set(ent["dates"]))} for ent in remaining if ent["dates"]]

    # Écriture JSON sauf en dry-run
    if not dry_run:
        _atomic_write_json_grouped(missing_path, remaining)

    # Code retour: 0 si tout résolu, 1 s'il reste des manquants
    return 0 if len(remaining) == 0 else 1

# --- CLI -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Récupère les observations manquantes (format groupé).")
    ap.add_argument("--missing", type=Path, default=DEFAULT_MISSING)
    ap.add_argument("--stations", type=Path, default=DEFAULT_STATIONS)
    ap.add_argument("--logdir", type=Path, default=DEFAULT_LOGDIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--soft-exit", action="store_true")
    ap.add_argument("--max-dates-per-id", type=int, default=3,
                    help="Ne traiter que les ids ayant ≤ N dates (défaut: 3)")
    args = ap.parse_args()

    rc = fetch_all(args.missing, args.stations, args.logdir,
                   dry_run=args.dry_run, max_dates_per_id=args.max_dates_per_id)
    sys.exit(0 if args.soft_exit else rc)

if __name__ == "__main__":
    main()
