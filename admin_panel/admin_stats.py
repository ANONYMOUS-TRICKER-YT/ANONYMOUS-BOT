import time
from datetime import datetime, timedelta
from typing import Dict, Any

WALLETS_FILE = "wallets.json"
REFERRALS_FILE = "referrals.json"
ORDERS_FILE = "orders.json"
TOPUPS_FILE = "topups.json"

def calculate_dashboard_stats(load_json_fn) -> Dict[str, Any]:
    wallets = load_json_fn(WALLETS_FILE)
    if not isinstance(wallets, dict):
        wallets = {}
        
    referrals = load_json_fn(REFERRALS_FILE)
    if not isinstance(referrals, dict):
        referrals = {}

    orders = load_json_fn(ORDERS_FILE)
    if not isinstance(orders, dict):
        orders = {}

    topups = load_json_fn(TOPUPS_FILE)
    if not isinstance(topups, dict):
        topups = {}

    total_users = len(wallets)
    total_balance = sum([float(v) for v in wallets.values() if isinstance(v, (int, float))])

    # Orders stats
    total_orders = len(orders)
    completed_orders = 0
    total_revenue = 0.0
    product_sales = {}

    for oid, odata in orders.items():
        if isinstance(odata, dict):
            status = odata.get("status", "pending")
            if status in ["approved", "completed", "auto"]:
                completed_orders += 1
                price = float(odata.get("price", 0))
                total_revenue += price
                pname = odata.get("product", "Unknown Product")
                product_sales[pname] = product_sales.get(pname, 0) + 1

    # Top product
    top_product = "None"
    if product_sales:
        top_product = max(product_sales, key=product_sales.get)

    # Top referrer
    top_referrer_id = "None"
    max_refs = 0
    for uid, ref_data in referrals.items():
        if isinstance(ref_data, dict):
            count = len(ref_data.get("invited", []))
            if count > max_refs:
                max_refs = count
                top_referrer_id = uid

    return {
        "total_users": total_users,
        "total_balance": round(total_balance, 2),
        "total_orders": total_orders,
        "completed_orders": completed_orders,
        "total_revenue": round(total_revenue, 2),
        "top_product": top_product,
        "top_referrer": top_referrer_id,
        "top_referrer_count": max_refs
    }
