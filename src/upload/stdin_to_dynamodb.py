#!/usr/bin/env python3
# Lit un CSV depuis STDIN et écrit en batch dans DynamoDB.
# Ajout: option --ttl-days pour écrire expires_at (TTL) depuis la date.

import sys, csv, json, argparse
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
import boto3

def _to_decimal_or_str(v: str):
    s = v.strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return s

def _parse_scales(v: str):
    s = v.strip()
    if not s:
        return []
    try:
        arr = json.loads(s)
        return [str(x) for x in arr] if isinstance(arr, list) else []
    except Exception:
        return []

# -- util TTL
def _parse_date_utc(date_str: str) -> datetime | None:
    # Supporte "YYYY-MM-DD" ou ISO "YYYY-MM-DDTHH:MM:SSZ"
    ds = date_str.strip()
    if not ds:
        return None
    try:
        d0 = datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return d0
    except ValueError:
        pass
    try:
        # ISO 8601 avec Z
        if ds.endswith("Z"):
            ds = ds.replace("Z", "+00:00")
        return datetime.fromisoformat(ds).astimezone(timezone.utc)
    except Exception:
        return None

def _compute_expires_at(date_str: str, days: int) -> int | None:
    d0 = _parse_date_utc(date_str)
    if d0 is None:
        return None
    # fin de journée + N jours
    d_exp = d0 + timedelta(days=days, hours=23, minutes=59, seconds=59)
    return int(d_exp.timestamp())  # epoch seconds (Number)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--pk", required=True)          # ex: id
    ap.add_argument("--sk")                         # ex: date
    # --- TTL options (facultatives) ---
    ap.add_argument("--ttl-days", type=int, default=0,
                    help="si >0, calcule expires_at= date + N jours")
    ap.add_argument("--ttl-field", default="expires_at",
                    help="nom d'attribut TTL (def=expires_at)")
    args = ap.parse_args()

    if sys.stdin.isatty():
        print("ERROR: no stdin", file=sys.stderr)
        return 2

    buf = sys.stdin.read()
    if not buf.strip():
        print("ERROR: 0 input lines", file=sys.stderr)
        return 3

    data_lines = buf.splitlines()
    reader = csv.DictReader(data_lines)
    header = reader.fieldnames or []
    if not header or args.pk not in header or (args.sk and args.sk not in header):
        print(f"ERROR: missing header or keys. header={header}", file=sys.stderr)
        return 4

    ddb = boto3.resource("dynamodb")
    table = ddb.Table(args.table)

    pkeys = [args.pk] + ([args.sk] if args.sk else [])
    wrote = 0
    skipped = 0

    # Idempotent upsert
    with table.batch_writer(overwrite_by_pkeys=pkeys) as bw:
        for row in reader:
            item = {}
            for k, v in row.items():
                if k == "" or v is None:
                    continue
                if k == "_scales":
                    lst = _parse_scales(v)
                    if lst:
                        item[k] = lst
                    continue
                if k == args.pk:
                    try:
                        item[k] = int(v.strip())  # PK en Number
                    except Exception:
                        item = None
                        break
                    continue
                if args.sk and k == args.sk:
                    item[k] = v.strip()          # SK en String
                    continue
                # Si le CSV fournit déjà expires_at, on le prend tel quel
                if k == args.ttl_field:
                    try:
                        item[k] = int(str(v).strip())
                    except Exception:
                        pass
                    continue
                val = _to_decimal_or_str(v)
                if val is None:
                    continue
                item[k] = val

            if not item or args.pk not in item or (args.sk and args.sk not in item):
                skipped += 1
                continue

            # Injecte expires_at si demandé et absent
            if args.ttl_days > 0 and args.ttl_field not in item:
                date_col = item.get(args.sk) if args.sk else item.get("date")
                if isinstance(date_col, str):
                    exp = _compute_expires_at(date_col, args.ttl_days)
                    if exp is not None:
                        item[args.ttl_field] = exp  # int → Number DynamoDB

            bw.put_item(Item=item)
            wrote += 1

    print(f"WROTE={wrote} SKIPPED={skipped}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
