#!/usr/bin/env python3
# cleanup_missing_observations.py
# Purge les dates trop anciennes ou invalides dans un JSON:
# [
#   {"id": 38002401, "dates": ["YYYY-MM-DD", ...]},
#   ...
# ]
# - Conserve uniquement les dates >= today_utc - keep_days
# - Supprime les entrées dont "dates" devient vide
# - Ecriture atomique, --dry-run pour ne rien écrire
# - CLI: --days, --path, --dry-run

import os
import json
import argparse
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

DEFAULT_PATH = Path(os.getenv("MISSING_OBS_JSON", "data/metadonnees/missing_observations.json"))

# --- utils E/S ------------------------------------------------------------

def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

def _read_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        # JSON invalide: repartir d'une liste vide pour ne pas bloquer un cron.
        return []

def _atomic_write(path: Path, data: List[Dict[str, Any]]) -> None:
    _ensure_parent(path)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)

# --- logique métier -------------------------------------------------------

def _parse_date_ymd(s: Any) -> Tuple[bool, Any]:
    """Retourne (ok, date). ok=False si parsing échoue."""
    if not isinstance(s, str):
        return False, None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        return True, d
    except Exception:
        return False, None

def _normalize_entry(e: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Sécurise l'accès id/dates côté types."""
    id_val = e.get("id")
    try:
        id_val = int(id_val) if id_val is not None else None
    except Exception:
        id_val = None
    dates = e.get("dates")
    if not isinstance(dates, list):
        dates = []
    # Forcer des str
    dates = [str(x) for x in dates]
    return id_val, dates

def cleanup(path: Path, keep_days: int, dry_run: bool = False) -> Dict[str, Any]:
    """
    Conserve d >= cutoff pour chaque entrée. Supprime les entrées dont dates devient vide.
    Retourne un rapport agrégé.
    """
    today_utc = datetime.now(timezone.utc).date()
    cutoff = today_utc - timedelta(days=keep_days)

    data = _read_list(path)

    # Compteurs avant
    before_entries = len(data)
    before_dates = 0
    for e in data:
        _, ds = _normalize_entry(e)
        before_dates += len(ds)

    kept_entries: List[Dict[str, Any]] = []
    removed_bad_dates = 0     # dates au format invalide
    removed_old_dates = 0     # dates < cutoff
    removed_empty_entries = 0 # entrées dont dates devient vide

    # Filtrage
    for e in data:
        id_val, dates = _normalize_entry(e)

        new_dates: List[str] = []
        for s in dates:
            ok, d = _parse_date_ymd(s)
            if not ok:
                removed_bad_dates += 1
                continue
            if d >= cutoff:
                new_dates.append(s)
            else:
                removed_old_dates += 1

        if new_dates:
            kept_entries.append({"id": id_val, "dates": new_dates})
        else:
            removed_empty_entries += 1

    # Compteurs après
    after_entries = len(kept_entries)
    after_dates = sum(len(e["dates"]) for e in kept_entries)

    if not dry_run:
        _atomic_write(path, kept_entries)

    return {
        "path": str(path),
        "keep_days": keep_days,
        "today_utc": str(today_utc),
        "cutoff_inclusive": str(cutoff),
        "before_entries": before_entries,
        "before_dates": before_dates,
        "after_entries": after_entries,
        "after_dates": after_dates,
        "removed_old_dates": removed_old_dates,
        "removed_bad_dates": removed_bad_dates,
        "removed_empty_entries": removed_empty_entries,
        "dry_run": dry_run,
    }

# --- CLI ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Nettoie missing_observations.json (schema id+dates[]) au-delà de N jours.")
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH, help="Chemin du JSON")
    ap.add_argument("--days", type=int, default=11, help="Nombre de jours à conserver (par défaut 11)")
    ap.add_argument("--dry-run", action="store_true", help="N'écrit pas le fichier, affiche seulement le rapport")
    args = ap.parse_args()

    report = cleanup(args.path, args.days, dry_run=args.dry_run)

    # Sortie concise pour logs/cron
    # Exemple:
    # [cleanup_missing] path=... keep_days=11 cutoff>=2025-10-25 entries: 12->8 dates: 34->17
    # removed_old_dates=10 removed_bad_dates=7 removed_empty_entries=4 dry_run=False
    print(
        f"[cleanup_missing] path={report['path']} keep_days={report['keep_days']} "
        f"cutoff>={report['cutoff_inclusive']} "
        f"entries:{report['before_entries']}->{report['after_entries']} "
        f"dates:{report['before_dates']}->{report['after_dates']} "
        f"removed_old_dates={report['removed_old_dates']} "
        f"removed_bad_dates={report['removed_bad_dates']} "
        f"removed_empty_entries={report['removed_empty_entries']} "
        f"dry_run={report['dry_run']}"
    )

if __name__ == "__main__":
    main()
