#!/usr/bin/env python3
# cleanup_no_ttl.py
# Scans the Observations table and deletes items that do not have 'expires_at'.

import boto3
import argparse
import sys
from botocore.exceptions import ClientError

def scan_missing_ttl(table_name):
    """
    Scans the table for items missing 'expires_at'.
    Returns a list of keys to delete (id, date).
    """
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)
    
    scan_kwargs = {
        "ProjectionExpression": "id, #d, expires_at",
        "ExpressionAttributeNames": {"#d": "date"},
    }
    
    items_to_delete = []
    done = False
    start_key = None
    
    print(f"Scanning table '{table_name}' for items without 'expires_at'...")
    
    while not done:
        if start_key:
            scan_kwargs["ExclusiveStartKey"] = start_key
            
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        
        for item in items:
            if "expires_at" not in item:
                # Keep key for deletion
                items_to_delete.append({
                    "id": item["id"],
                    "date": item["date"]
                })
        
        start_key = response.get("LastEvaluatedKey", None)
        done = start_key is None
        
    return items_to_delete

def batch_delete(table_name, keys):
    """
    Deletes items in batches.
    """
    if not keys:
        print("No items to delete.")
        return

    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)
    
    print(f"Deleting {len(keys)} items...")
    
    with table.batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key=key)
            
    print("Deletion complete.")

def main():
    parser = argparse.ArgumentParser(description="Delete DynamoDB items missing expires_at")
    parser.add_argument("--table", default="Observations", help="DynamoDB table name")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, do not delete")
    args = parser.parse_args()
    
    try:
        keys = scan_missing_ttl(args.table)
        print(f"Found {len(keys)} items missing 'expires_at'.")
        
        if args.dry_run:
            print("Dry run: skipping deletion.")
            return
            
        if keys:
            confirm = input(f"Are you sure you want to delete {len(keys)} items? [y/N] ")
            if confirm.lower() == 'y':
                batch_delete(args.table, keys)
            else:
                print("Aborted.")
    except ClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
