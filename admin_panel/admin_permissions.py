import os
from typing import List, Dict

ADMIN_USERS_FILE = "admin_users.json"

PERMISSIONS_LIST = [
    "manage_products",
    "manage_categories",
    "manage_orders",
    "manage_users",
    "manage_coupons",
    "manage_payments",
    "manage_broadcast",
    "view_stats",
    "manage_settings",
    "manage_backups",
    "view_logs"
]

def get_admin_data(load_json_fn) -> Dict:
    data = load_json_fn(ADMIN_USERS_FILE)
    if not isinstance(data, dict):
        data = {"admins": [], "roles": {}}
    return data

def is_owner(admin_id: int) -> bool:
    owner_id = int(os.getenv("ADMIN_ID", "0"))
    return admin_id == owner_id

def is_admin(load_json_fn, user_id: int) -> bool:
    if is_owner(user_id):
        return True
    data = get_admin_data(load_json_fn)
    return str(user_id) in [str(a) for a in data.get("admins", [])]

def has_permission(load_json_fn, user_id: int, permission: str) -> bool:
    if is_owner(user_id):
        return True
    if not is_admin(load_json_fn, user_id):
        return False
    data = get_admin_data(load_json_fn)
    user_perms = data.get("roles", {}).get(str(user_id), [])
    return permission in user_perms or "all" in user_perms

def add_admin_user(load_json_fn, save_json_fn, user_id: int, permissions: List[str] = None):
    data = get_admin_data(load_json_fn)
    admins = [str(a) for a in data.get("admins", [])]
    if str(user_id) not in admins:
        admins.append(str(user_id))
    data["admins"] = admins
    if "roles" not in data:
        data["roles"] = {}
    data["roles"][str(user_id)] = permissions or ["all"]
    save_json_fn(ADMIN_USERS_FILE, data)

def remove_admin_user(load_json_fn, save_json_fn, user_id: int):
    data = get_admin_data(load_json_fn)
    admins = [str(a) for a in data.get("admins", []) if str(a) != str(user_id)]
    data["admins"] = admins
    if "roles" in data and str(user_id) in data["roles"]:
        del data["roles"][str(user_id)]
    save_json_fn(ADMIN_USERS_FILE, data)
