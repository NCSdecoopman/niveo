#!/usr/bin/env python3
# Lit un CSV depuis STDIN et écrit en batch dans DynamoDB.
# Usage:
#   python -m src.upload.stdin_to_dynamodb --table Observations --pk id --sk date < input.csv
#   some_cmd | python -m src.upload.stdin_to_dynamodb --table Stations --pk id

import sys, csv, json, argparse, io
from decimal import Decimal, InvalidOperation
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
    args = ap.parse_args()

    if sys.stdin.isatty():
        print("ERROR: no stdin", file=sys.stderr)
        return 2

    # LIRE STDIN UNE SEULE FOIS
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
                        item[k] = int(v.strip())
                    except Exception:
                        item = None
                        break
                    continue
                if args.sk and k == args.sk:
                    item[k] = v.strip()
                    continue
                val = _to_decimal_or_str(v)
                if val is None:
                    continue
                item[k] = val

            if not item or args.pk not in item or (args.sk and args.sk not in item):
                skipped += 1
                continue

            bw.put_item(Item=item)
            wrote += 1

    print(f"WROTE={wrote} SKIPPED={skipped}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
