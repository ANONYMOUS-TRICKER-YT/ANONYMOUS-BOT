from typing import Dict, Any, Optional

WALLETS_FILE = "wallets.json"
REFERRALS_FILE = "referrals.json"
ORDERS_FILE = "orders.json"
BANNED_USERS_FILE = "banned_users.json"

def get_banned_users(load_json_fn) -> list:
    data = load_json_fn(BANNED_USERS_FILE)
    if isinstance(data, list):
        return data
    return []

def ban_user(load_json_fn, save_json_fn, user_id: int):
    banned = get_banned_users(load_json_fn)
    uid_str = str(user_id)
    if uid_str not in banned:
        banned.append(uid_str)
        save_json_fn(BANNED_USERS_FILE, banned)

def unban_user(load_json_fn, save_json_fn, user_id: int):
    banned = get_banned_users(load_json_fn)
    uid_str = str(user_id)
    if uid_str in banned:
        banned.remove(uid_str)
        save_json_fn(BANNED_USERS_FILE, banned)

def is_user_banned(load_json_fn, user_id: int) -> bool:
    banned = get_banned_users(load_json_fn)
    return str(user_id) in banned

def get_user_profile_summary(load_json_fn, user_id: int) -> Dict[str, Any]:
    wallets = load_json_fn(WALLETS_FILE)
    balance = float(wallets.get(str(user_id), 0.0)) if isinstance(wallets, dict) else 0.0

    referrals = load_json_fn(REFERRALS_FILE)
    ref_info = referrals.get(str(user_id), {}) if isinstance(referrals, dict) else {}
    invited_list = ref_info.get("invited", []) if isinstance(ref_info, dict) else []

    orders = load_json_fn(ORDERS_FILE)
    user_orders = []
    if isinstance(orders, dict):
        for oid, odata in orders.items():
            if isinstance(odata, dict) and str(odata.get("user_id")) == str(user_id):
                user_orders.append(odata)

    return {
        "user_id": user_id,
        "balance": round(balance, 2),
        "referral_count": len(invited_list),
        "invited_users": invited_list,
        "orders_count": len(user_orders),
        "user_orders": user_orders,
        "is_banned": is_user_banned(load_json_fn, user_id)
    }
