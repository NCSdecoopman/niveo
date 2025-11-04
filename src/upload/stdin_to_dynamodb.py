#!/usr/bin/env python3
# Lit un CSV depuis STDIN et écrit en batch dans DynamoDB.
# Usage:
#   python -m src.upload.stdin_to_dynamodb --table Observations --pk id --sk date < input.csv
#   some_cmd_produisant_csv | python -m src.upload.stdin_to_dynamodb --table Stations --pk id

import sys, csv, json, argparse
from decimal import Decimal, InvalidOperation
import boto3

def _to_decimal_or_str(v: str):
    s = v.strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        # tente Decimal (entiers et flottants)
        return Decimal(s)
    except InvalidOperation:
        return s  # garde en string

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

    ddb = boto3.resource("dynamodb")
    table = ddb.Table(args.table)

    # csv sur stdin
    data = sys.stdin.read().strip().splitlines()
    if not data:
        # rien à écrire
        return 0

    reader = csv.DictReader(data)
    header = reader.fieldnames or []
    if not header or args.pk not in header or (args.sk and args.sk not in header):
        # stdin invalide ou sans header attendu
        return 0

    # overwrite_by_pkeys garantit l’idempotence
    pkeys = [args.pk] + ([args.sk] if args.sk else [])
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
                    # id en entier
                    try:
                        item[k] = int(v.strip())
                    except Exception:
                        # PK invalide -> ignore la ligne
                        item = None
                        break
                    continue
                if args.sk and k == args.sk:
                    item[k] = v.strip()
                    continue
                # valeur générique
                val = _to_decimal_or_str(v)
                if val is None:
                    continue
                item[k] = val
            if not item:
                continue
            if args.pk not in item or (args.sk and args.sk not in item):
                continue
            bw.put_item(Item=item)

    return 0

if __name__ == "__main__":
    sys.exit(main())
