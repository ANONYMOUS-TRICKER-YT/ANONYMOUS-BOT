import time
from datetime import datetime

LOGS_FILE = "admin_logs.json"

def log_admin_action(load_json_fn, save_json_fn, admin_id: int, action: str, details: str):
    """Log an admin action with timestamp and details."""
    logs = load_json_fn(LOGS_FILE)
    if not isinstance(logs, list):
        logs = []
    
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "unix_time": int(time.time()),
        "admin_id": admin_id,
        "action": action,
        "details": details
    }
    logs.insert(0, entry)
    # Keep last 500 logs
    if len(logs) > 500:
        logs = logs[:500]
    
    save_json_fn(LOGS_FILE, logs)

def get_admin_logs(load_json_fn, limit: int = 20):
    logs = load_json_fn(LOGS_FILE)
    if not isinstance(logs, list):
        return []
    return logs[:limit]
