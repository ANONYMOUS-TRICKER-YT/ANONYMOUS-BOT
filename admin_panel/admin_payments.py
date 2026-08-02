from typing import Dict, Any

PAYMENTS_FILE = "payments.json"

def get_payment_methods(load_json_fn) -> Dict[str, Dict[str, Any]]:
    payments = load_json_fn(PAYMENTS_FILE)
    if not isinstance(payments, dict):
        return {}
    return payments

def save_payment_methods(save_json_fn, payments: Dict[str, Dict[str, Any]]):
    save_json_fn(PAYMENTS_FILE, payments)

def add_payment_method(load_json_fn, save_json_fn, p_id: str, name: str, p_type: str, details: str, instructions: str) -> Dict[str, Any]:
    payments = get_payment_methods(load_json_fn)
    pm = {
        "id": p_id,
        "name": name,
        "enabled": True,
        "type": p_type,
        "details": details,
        "instructions": instructions
    }
    payments[p_id] = pm
    save_payment_methods(save_json_fn, payments)
    return pm

def update_payment_method(load_json_fn, save_json_fn, p_id: str, updates: Dict[str, Any]):
    payments = get_payment_methods(load_json_fn)
    if p_id in payments:
        payments[p_id].update(updates)
        save_payment_methods(save_json_fn, payments)

def delete_payment_method(load_json_fn, save_json_fn, p_id: str):
    payments = get_payment_methods(load_json_fn)
    if p_id in payments:
        del payments[p_id]
        save_payment_methods(save_json_fn, payments)
