#!/usr/bin/env python3
# Lit un CSV depuis STDIN et écrit en batch dans DynamoDB.

import sys, csv, json, argparse
from decimal import Decimal, InvalidOperation
import os
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--pk", required=True)    # ex: id
    ap.add_argument("--sk")                   # ex: date
    ap.add_argument("--region")               # pour forcer la région si besoin
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if sys.stdin.isatty():
        print("ERROR: no stdin", file=sys.stderr)
        return 2

    raw = sys.stdin.read()
    if not raw.strip():
        print("ERROR: 0 input bytes", file=sys.stderr)
        return 3

    lines = [l for l in raw.splitlines() if l.strip()]
    reader = csv.DictReader(lines)
    header = reader.fieldnames or []
    if not header:
        print("ERROR: missing CSV header", file=sys.stderr)
        return 4
    if args.pk not in header or (args.sk and args.sk not in header):
        print(f"ERROR: header must contain {args.pk}" + (f" and {args.sk}" if args.sk else ""), file=sys.stderr)
        return 5

    region = args.region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(args.table)

    items = []
    for row in reader:
        item = {}
        try:
            for k, v in row.items():
                if k == "" or v is None:
                    continue
                if k == "_scales":
                    lst = _parse_scales(v)
                    if lst: item[k] = lst
                    continue
                if k == args.pk:
                    item[k] = int(v.strip())  # PK Number; passe en str(...) si ta PK est String
                    continue
                if args.sk and k == args.sk:
                    item[k] = v.strip()
                    continue
                val = _to_decimal_or_str(v)
                if val is None:
                    continue
                item[k] = val
        except Exception as e:
            print(f"PARSE_SKIP id={row.get(args.pk)} err={e}", file=sys.stderr)
            item = None
        if not item: 
            continue
        if args.pk not in item or (args.sk and args.sk not in item):
            print(f"SKIP_MISSING_KEYS row_pk={row.get(args.pk)}", file=sys.stderr)
            continue
        items.append(item)

    if args.dry_run:
        print(f"DRY_RUN items_ready={len(items)}", file=sys.stderr)
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False))
        return 0

    wrote = 0
    with table.batch_writer(overwrite_by_pkeys=[args.pk] + ([args.sk] if args.sk else [])) as bw:
        for it in items:
            bw.put_item(Item=it)
            wrote += 1

    print(f"WROTE={wrote}", file=sys.stderr)
    return 0 if wrote > 0 else 6

if __name__ == "__main__":
    sys.exit(main())
