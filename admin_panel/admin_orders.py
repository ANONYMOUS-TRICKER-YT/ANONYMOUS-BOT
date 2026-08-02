from typing import Dict, Any, List, Optional

ORDERS_FILE = "orders.json"
WALLETS_FILE = "wallets.json"

def get_all_orders(load_json_fn) -> Dict[str, Dict[str, Any]]:
    orders = load_json_fn(ORDERS_FILE)
    if not isinstance(orders, dict):
        return {}
    return orders

def save_all_orders(save_json_fn, orders: Dict[str, Dict[str, Any]]):
    save_json_fn(ORDERS_FILE, orders)

def search_order(load_json_fn, search_term: str) -> List[Dict[str, Any]]:
    term = search_term.strip().lower()
    orders = get_all_orders(load_json_fn)
    results = []
    for oid, odata in orders.items():
        if not isinstance(odata, dict):
            continue
        if term in str(oid).lower() or term in str(odata.get("user_id")).lower() or term in str(odata.get("product")).lower():
            results.append(odata)
    return results

def update_order_status(load_json_fn, save_json_fn, order_id: str, new_status: str) -> bool:
    orders = get_all_orders(load_json_fn)
    if order_id in orders and isinstance(orders[order_id], dict):
        orders[order_id]["status"] = new_status
        save_all_orders(save_json_fn, orders)
        return True
    return False

def refund_order(load_json_fn, save_json_fn, order_id: str) -> tuple[bool, str]:
    orders = get_all_orders(load_json_fn)
    if order_id not in orders or not isinstance(orders[order_id], dict):
        return False, "Order not found."

    order = orders[order_id]
    if order.get("refunded", False):
        return False, "Order is already refunded."

    user_id = str(order.get("user_id"))
    price = float(order.get("price", 0.0))

    wallets = load_json_fn(WALLETS_FILE)
    if not isinstance(wallets, dict):
        wallets = {}

    curr_bal = float(wallets.get(user_id, 0.0))
    wallets[user_id] = round(curr_bal + price, 2)
    save_json_fn(WALLETS_FILE, wallets)

    order["status"] = "refunded"
    order["refunded"] = True
    save_all_orders(save_json_fn, orders)

    return True, f"Refunded ${price} to user {user_id}."

def generate_order_invoice(order: Dict[str, Any]) -> str:
    """Formats an ASCII invoice string for an order."""
    oid = order.get("id") or order.get("order_id", "N/A")
    date_str = order.get("created_at") or order.get("timestamp", "N/A")
    pname = order.get("product", "N/A")
    price = order.get("price", 0.0)
    uid = order.get("user_id", "N/A")
    status = str(order.get("status", "pending")).upper()

    invoice = (
        "🧾 *OFFICIAL INVOICE*\n"
        "─────────────────────\n"
        f"📋 *Order ID:* `{oid}`\n"
        f"👤 *Customer ID:* `{uid}`\n"
        f"📅 *Date:* {date_str}\n"
        f"📦 *Item:* {pname}\n"
        f"💰 *Total Paid:* ${price} USDT\n"
        f"📌 *Status:* {status}\n"
        "─────────────────────\n"
        "Thank you for shopping with CHEAP AI TOOLS!"
    )
    return invoice
