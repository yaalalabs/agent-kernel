#!/usr/bin/env python3
"""
Debug script to inspect DynamoDB Response Store.

This helps diagnose issues with response caching and UUID generation.

Usage:
    python debug_response_store.py [--table-name <name>] [--list] [--clear]
"""

import argparse
import sys
import boto3
from boto3.dynamodb.conditions import Attr
from decimal import Decimal


def decimal_default(obj):
    """JSON serializer for Decimal objects."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def list_responses(table_name: str):
    """List all responses in the DynamoDB table."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    
    print(f"\n=== Scanning DynamoDB Table: {table_name} ===\n")
    
    try:
        response = table.scan()
        items = response.get('Items', [])
        
        if not items:
            print("No items found in the table.")
            return
        
        print(f"Found {len(items)} item(s):\n")
        
        for idx, item in enumerate(items, 1):
            print(f"--- Item {idx} ---")
            print(f"request_id: {item.get('request_id', 'N/A')}")
            print(f"session_id: {item.get('session_id', 'N/A')}")
            
            body = item.get('body', {})
            if isinstance(body, dict):
                print(f"body.session_id: {body.get('session_id', 'N/A')}")
                print(f"body.message: {body.get('message', 'N/A')[:100] if body.get('message') else 'N/A'}...")
            else:
                print(f"body: {str(body)[:100]}...")
            
            if 'expiry_time' in item:
                print(f"expiry_time: {item['expiry_time']}")
            
            print()
        
    except Exception as e:
        print(f"Error scanning table: {e}")
        sys.exit(1)


def clear_responses(table_name: str):
    """Clear all responses from the DynamoDB table."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    
    print(f"\n=== Clearing DynamoDB Table: {table_name} ===\n")
    
    try:
        response = table.scan()
        items = response.get('Items', [])
        
        if not items:
            print("No items to delete.")
            return
        
        print(f"Deleting {len(items)} item(s)...")
        
        with table.batch_writer() as batch:
            for item in items:
                request_id = item.get('request_id')
                if request_id:
                    batch.delete_item(Key={'request_id': request_id})
                    print(f"  Deleted: request_id={request_id}, session_id={item.get('session_id', 'N/A')}")
        
        print(f"\nSuccessfully deleted {len(items)} item(s).")
        
    except Exception as e:
        print(f"Error clearing table: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Debug DynamoDB Response Store')
    parser.add_argument('--table-name', default='ak-oai-scl-ecs-dev-response-store',
                       help='DynamoDB table name (default: ak-oai-scl-ecs-dev-response-store)')
    parser.add_argument('--list', action='store_true',
                       help='List all responses in the table')
    parser.add_argument('--clear', action='store_true',
                       help='Clear all responses from the table')
    
    args = parser.parse_args()
    
    if not args.list and not args.clear:
        parser.print_help()
        print("\nError: Please specify --list or --clear")
        sys.exit(1)
    
    if args.list:
        list_responses(args.table_name)
    
    if args.clear:
        confirm = input(f"\nAre you sure you want to clear all items from {args.table_name}? (yes/no): ")
        if confirm.lower() == 'yes':
            clear_responses(args.table_name)
        else:
            print("Clear operation cancelled.")


if __name__ == '__main__':
    main()
