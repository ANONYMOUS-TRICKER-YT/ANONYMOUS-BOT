import time
import json
from datetime import datetime
from typing import Dict, Any

BACKUPS_FILE = "backups.json"

ALL_DB_KEYS = [
    "wallets.json",
    "referrals.json",
    "orders.json",
    "topups.json",
    "inventory.json",
    "sales.json",
    "prices.json",
    "rewards.json",
    "banners.json",
    "products.json",
    "colors.json",
    "icons.json",
    "categories.json",
    "coupons.json",
    "payments.json",
    "settings.json",
    "admin_users.json",
    "menu_builder.json",
    "github_tokens.json"
]

def create_database_backup(load_json_fn, save_json_fn) -> Dict[str, Any]:
    """Generates a complete snapshot of all database tables/keys."""
    backup_data = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "unix_time": int(time.time()),
        "data": {}
    }
    for key in ALL_DB_KEYS:
        backup_data["data"][key] = load_json_fn(key)
        
    backups = load_json_fn(BACKUPS_FILE)
    if not isinstance(backups, list):
        backups = []
    
    backups.insert(0, {
        "timestamp": backup_data["timestamp"],
        "unix_time": backup_data["unix_time"]
    })
    # Keep last 20 backup metadata
    save_json_fn(BACKUPS_FILE, backups[:20])
    return backup_data

def restore_database_backup(save_json_fn, backup_data: Dict[str, Any]) -> bool:
    """Restores database from a snapshot."""
    if not isinstance(backup_data, dict) or "data" not in backup_data:
        return False
    
    data_dict = backup_data["data"]
    for key, content in data_dict.items():
        if key in ALL_DB_KEYS:
            save_json_fn(key, content)
    return True
