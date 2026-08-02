import json
import logging
from typing import Dict, Any, List, Optional

PRODUCTS_FILE = "products.json"
PRICES_FILE = "prices.json"
ICONS_FILE = "icons.json"
BANNERS_FILE = "banners.json"
COLORS_FILE = "colors.json"
CATEGORIES_FILE = "categories.json"

logger = logging.getLogger(__name__)

# Category CRUD
def get_categories(load_json_fn) -> Dict[str, Dict[str, Any]]:
    data = load_json_fn(CATEGORIES_FILE)
    if not isinstance(data, dict):
        return {}
    return data

def save_categories(save_json_fn, categories: Dict[str, Dict[str, Any]]):
    save_json_fn(CATEGORIES_FILE, categories)

def add_category(load_json_fn, save_json_fn, name: str, emoji: str = "📁") -> str:
    cats = get_categories(load_json_fn)
    cid = f"cat_{len(cats) + 1}"
    cats[cid] = {
        "id": cid,
        "name": name,
        "emoji": emoji,
        "hidden": False,
        "position": len(cats) + 1
    }
    save_categories(save_json_fn, cats)
    return cid

def update_category(load_json_fn, save_json_fn, cid: str, updates: Dict[str, Any]):
    cats = get_categories(load_json_fn)
    if cid in cats:
        cats[cid].update(updates)
        save_categories(save_json_fn, cats)

def delete_category(load_json_fn, save_json_fn, cid: str):
    cats = get_categories(load_json_fn)
    if cid in cats:
        del cats[cid]
        save_categories(save_json_fn, cats)

# Product Helper Functions
def get_all_products(load_json_fn, base_products: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Merge base products with admin-added products and applied overrides."""
    # 1. Base copy
    prods = {k: v.copy() for k, v in base_products.items()}
    
    # 2. Add/Remove overrides from DB
    p_file = load_json_fn(PRODUCTS_FILE)
    if isinstance(p_file, dict):
        added = p_file.get("added", {})
        removed = p_file.get("removed", [])
        for pid, pdata in added.items():
            prods[pid] = pdata.copy()
        for pid in removed:
            prods.pop(pid, None)
            
    # 3. Price overrides
    prices = load_json_fn(PRICES_FILE)
    if isinstance(prices, dict):
        for pid, pr in prices.items():
            if pid in prods:
                try:
                    prods[pid]["price"] = float(pr)
                except (ValueError, TypeError):
                    pass

    # 4. Icon overrides
    icons = load_json_fn(ICONS_FILE)
    if isinstance(icons, dict):
        for pid, ic in icons.items():
            if pid in prods:
                prods[pid]["icon"] = ic

    # 5. Banner overrides
    banners = load_json_fn(BANNERS_FILE)
    if isinstance(banners, dict):
        for pid, bn in banners.items():
            if pid in prods:
                prods[pid]["banner"] = bn

    return prods

def add_product(load_json_fn, save_json_fn, base_products: Dict[str, Any], pid: str, pdata: Dict[str, Any]):
    p_file = load_json_fn(PRODUCTS_FILE)
    if not isinstance(p_file, dict):
        p_file = {"added": {}, "removed": []}
    if "added" not in p_file:
        p_file["added"] = {}
    p_file["added"][pid] = pdata
    if pid in p_file.get("removed", []):
        p_file["removed"].remove(pid)
    save_json_fn(PRODUCTS_FILE, p_file)

def update_product(load_json_fn, save_json_fn, base_products: Dict[str, Any], pid: str, updates: Dict[str, Any]):
    prods = get_all_products(load_json_fn, base_products)
    if pid in prods:
        prod = prods[pid]
        prod.update(updates)
        add_product(load_json_fn, save_json_fn, base_products, pid, prod)

def remove_product(load_json_fn, save_json_fn, pid: str):
    p_file = load_json_fn(PRODUCTS_FILE)
    if not isinstance(p_file, dict):
        p_file = {"added": {}, "removed": []}
    if "added" in p_file and pid in p_file["added"]:
        del p_file["added"][pid]
    if "removed" not in p_file:
        p_file["removed"] = []
    if pid not in p_file["removed"]:
        p_file["removed"].append(pid)
    save_json_fn(PRODUCTS_FILE, p_file)

def bulk_adjust_prices(load_json_fn, save_json_fn, base_products: Dict[str, Any], percentage_change: float):
    """Increase or decrease all product prices by a percentage (e.g. +10 or -5)."""
    prods = get_all_products(load_json_fn, base_products)
    prices = load_json_fn(PRICES_FILE)
    if not isinstance(prices, dict):
        prices = {}

    multiplier = 1.0 + (percentage_change / 100.0)
    for pid, pdata in prods.items():
        curr_price = float(pdata.get("price", 0))
        new_price = round(max(0.01, curr_price * multiplier), 2)
        prices[pid] = new_price

    save_json_fn(PRICES_FILE, prices)
