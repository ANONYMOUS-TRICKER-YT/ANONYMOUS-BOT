import time
from typing import Dict, Any, Optional

COUPONS_FILE = "coupons.json"

def get_coupons(load_json_fn) -> Dict[str, Dict[str, Any]]:
    coupons = load_json_fn(COUPONS_FILE)
    if not isinstance(coupons, dict):
        return {}
    return coupons

def save_coupons(save_json_fn, coupons: Dict[str, Dict[str, Any]]):
    save_json_fn(COUPONS_FILE, coupons)

def add_coupon(
    load_json_fn,
    save_json_fn,
    code: str,
    discount_type: str, # "percent" or "fixed"
    discount_value: float,
    max_uses: int = 0, # 0 = unlimited
    expiry_days: int = 0 # 0 = never
) -> Dict[str, Any]:
    code_clean = code.strip().upper()
    coupons = get_coupons(load_json_fn)
    
    expiry_time = 0
    if expiry_days > 0:
        expiry_time = int(time.time()) + (expiry_days * 86400)

    coupon = {
        "code": code_clean,
        "type": discount_type,
        "value": discount_value,
        "max_uses": max_uses,
        "used_count": 0,
        "expiry_time": expiry_time,
        "active": True,
        "used_by": []
    }
    coupons[code_clean] = coupon
    save_coupons(save_json_fn, coupons)
    return coupon

def delete_coupon(load_json_fn, save_json_fn, code: str) -> bool:
    code_clean = code.strip().upper()
    coupons = get_coupons(load_json_fn)
    if code_clean in coupons:
        del coupons[code_clean]
        save_coupons(save_json_fn, coupons)
        return True
    return False

def validate_coupon(load_json_fn, code: str, user_id: int, original_amount: float) -> tuple[bool, str, float]:
    """Validates coupon code. Returns (is_valid, message, discounted_amount)."""
    code_clean = code.strip().upper()
    coupons = get_coupons(load_json_fn)
    
    if code_clean not in coupons:
        return False, "❌ Invalid coupon code.", original_amount

    cp = coupons[code_clean]
    if not cp.get("active", True):
        return False, "❌ Coupon is disabled.", original_amount

    # Check expiry
    expiry = cp.get("expiry_time", 0)
    if expiry > 0 and int(time.time()) > expiry:
        return False, "❌ Coupon has expired.", original_amount

    # Check max uses
    max_uses = cp.get("max_uses", 0)
    used_count = cp.get("used_count", 0)
    if max_uses > 0 and used_count >= max_uses:
        return False, "❌ Coupon usage limit reached.", original_amount

    # Check user one-time usage
    used_by = cp.get("used_by", [])
    if str(user_id) in [str(u) for u in used_by]:
        return False, "❌ You have already redeemed this coupon.", original_amount

    # Calculate discount
    ctype = cp.get("type", "percent")
    val = cp.get("value", 0.0)
    
    if ctype == "percent":
        discount = (original_amount * val) / 100.0
    else:
        discount = val

    final_price = round(max(0.0, original_amount - discount), 2)
    return True, f"✅ Coupon applied! ({val}% off)" if ctype == "percent" else f"✅ Coupon applied! (-${val})", final_price

def mark_coupon_used(load_json_fn, save_json_fn, code: str, user_id: int):
    code_clean = code.strip().upper()
    coupons = get_coupons(load_json_fn)
    if code_clean in coupons:
        cp = coupons[code_clean]
        cp["used_count"] = cp.get("used_count", 0) + 1
        if "used_by" not in cp:
            cp["used_by"] = []
        if str(user_id) not in [str(u) for u in cp["used_by"]]:
            cp["used_by"].append(str(user_id))
        save_coupons(save_json_fn, coupons)
