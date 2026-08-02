from typing import Dict, Any, List

def universal_search(load_json_fn, get_all_products_fn, query: str) -> Dict[str, List[Any]]:
    q = query.strip().lower()
    results = {
        "products": [],
        "orders": [],
        "users": [],
        "coupons": []
    }

    # 1. Products
    prods = get_all_products_fn()
    for pid, pdata in prods.items():
        if q in str(pid).lower() or q in pdata.get("name", "").lower() or q in pdata.get("description", "").lower():
            results["products"].append(pdata)

    # 2. Orders
    orders = load_json_fn("orders.json")
    if isinstance(orders, dict):
        for oid, odata in orders.items():
            if isinstance(odata, dict):
                if q in str(oid).lower() or q in str(odata.get("user_id")).lower() or q in odata.get("product", "").lower():
                    results["orders"].append(odata)

    # 3. Users
    wallets = load_json_fn("wallets.json")
    if isinstance(wallets, dict):
        for uid in wallets.keys():
            if q in str(uid).lower():
                results["users"].append({"user_id": uid, "balance": wallets[uid]})

    # 4. Coupons
    coupons = load_json_fn("coupons.json")
    if isinstance(coupons, dict):
        for ccode, cdata in coupons.items():
            if q in ccode.lower():
                results["coupons"].append(cdata)

    return results
