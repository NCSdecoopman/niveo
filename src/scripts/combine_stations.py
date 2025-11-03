# Script: combine all stations JSON (different scales/depts) into one deduplicated file.
import json
import re
from pathlib import Path

SRC_DIR = Path("data/metadonnees/download/stations")
OUT_DIR = Path("data/metadonnees")
OUT_FILE = OUT_DIR / "stations.json"

ID_KEY = "id"
NAME_KEY = "nom"
KEEP_KEYS = ("lon", "lat", "alt")

# regex to turn " d Allevard" -> "d'Allevard" (and same for l/L)
_RE_D_APOST = re.compile(r"\b([dDlL])\s+([A-Za-zÀ-ÖØ-öø-ÿ])")
# remove occurrences like "-NIVO", "_NIVO", "NIVOSE" etc. case-insensitive
_RE_REMOVE_NIVO = re.compile(r"[-_]?\bNIVO(?:SE)?\b", flags=re.I)
# collapse multiple spaces
_RE_SPACES = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    if raw is None:
        return ""
    s = raw.strip()
    # fix d / l cases -> d'Allevard
    s = _RE_D_APOST.sub(r"\1'\2", s)
    # remove NIVO tokens
    s = _RE_REMOVE_NIVO.sub("", s)
    # normalize spaces and strip
    s = _RE_SPACES.sub(" ", s).strip()
    # lowercase final
    return s.lower()


# list of small words/particles to keep lowercased when not at the start
_PARTICLES = {
    "de", "du", "des", "la", "le", "les", "et", "à", "au", "aux", "sur",
    "sous", "par", "en", "chez", "l", "d", "au", "aux"
}


def _cap_first(s: str) -> str:
    if not s:
        return s
    return s[0].upper() + s[1:].lower()


def capitalize_name(normalized: str) -> str:
    """
    Turn a normalized lower-case name into pretty form:
      - first character of the full name is uppercase
      - particles like "de","la","d" remain lowercase when not first token
      - handle hyphens and apostrophes:
          Bourg-d'oisans -> Bourg-d'Oisans
          col d'allevard -> Col d'Allevard
    """
    if not normalized:
        return normalized

    parts = normalized.split(" ")
    out_parts = []

    for i, part in enumerate(parts):
        is_first = (i == 0)

        # handle hyphenated subparts
        hy_parts = part.split("-")
        out_hy = []
        for j, h in enumerate(hy_parts):
            # handle apostrophe inside hyphen-part
            if "'" in h:
                pre, post = h.split("'", 1)
                if is_first:
                    # capitalize pre at start of full name
                    pre_fmt = _cap_first(pre)
                else:
                    # keep small particle lowercased if single letter or known particle
                    if pre in _PARTICLES:
                        pre_fmt = pre.lower()
                    else:
                        pre_fmt = _cap_first(pre)
                post_fmt = _cap_first(post)
                out_hy.append(f"{pre_fmt}'{post_fmt}")
            else:
                # not containing apostrophe
                if is_first:
                    out_hy.append(_cap_first(h))
                else:
                    if h in _PARTICLES:
                        out_hy.append(h.lower())
                    else:
                        out_hy.append(_cap_first(h))
            # subsequent hy-parts in same token are not "first" in full name
            is_first = False

        out_parts.append("-".join(out_hy))

    return " ".join(out_parts)


def pick_better(existing: dict, candidate: dict) -> dict:
    """
    Merge candidate into existing, preferring non-null numeric lon/lat/alt.
    existing is mutated and returned.
    """
    for k in KEEP_KEYS:
        ex = existing.get(k)
        ca = candidate.get(k)
        if (ex is None or ex == "") and (ca is not None and ca != ""):
            existing[k] = ca
    # keep existing name/id (we normalized when first seen)
    return existing


def main():
    files = list(SRC_DIR.glob("**/stations_*.json"))
    if not files:
        print(f"No input files found under {SRC_DIR}")
        return

    by_id: dict[str, dict] = {}

    for fp in files:
        try:
            arr = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Skipping {fp} (read error): {e}")
            continue

        if not isinstance(arr, list):
            print(f"Skipping {fp} (not a list)")
            continue

        for item in arr:
            sid = str(item.get(ID_KEY, "")).strip()
            if not sid:
                continue
            # normalize name
            raw_name = item.get(NAME_KEY) or ""
            name = normalize_name(raw_name)

            entry = {
                "id": sid,
                "nom": name,
                # copy lon/lat/alt if present (keep numeric types)
            }
            for k in KEEP_KEYS:
                if k in item:
                    entry[k] = item[k]

            if sid in by_id:
                # merge / keep best coordinates
                by_id[sid] = pick_better(by_id[sid], entry)
            else:
                by_id[sid] = entry

    # prepare output list sorted by id
    out_list = [by_id[k] for k in sorted(by_id.keys())]

    # Capitalize names nicely before writing
    for e in out_list:
        e["nom"] = capitalize_name(e.get("nom", ""))

    # Filtre: ne garder que les stations avec altitude strictement supérieure à 500 m
    filtered = []
    for e in out_list:
        alt = e.get("alt")
        try:
            # accepter int/float ou chaînes numériques
            alt_val = float(alt) if alt is not None and alt != "" else None
        except (ValueError, TypeError):
            alt_val = None

        if alt_val is not None and alt_val > 500:
            filtered.append(e)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Combined {len(files)} files -> {len(filtered)} unique stations (alt > 500 m) saved to {OUT_FILE}")


if __name__ == "__main__":
    main()