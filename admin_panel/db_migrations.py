import os
import json
import logging

logger = logging.getLogger(__name__)

# Keys used in kv_store
CATEGORIES_FILE = "categories.json"
COUPONS_FILE = "coupons.json"
PAYMENTS_FILE = "payments.json"
SETTINGS_FILE = "settings.json"
ADMIN_USERS_FILE = "admin_users.json"
MENU_BUILDER_FILE = "menu_builder.json"
ADMIN_LOGS_FILE = "admin_logs.json"
BACKUPS_FILE = "backups.json"

DEFAULT_CATEGORIES = {
    "cat_1": {"id": "cat_1", "name": "AI Subscriptions", "emoji": "🚀", "hidden": False, "position": 1},
    "cat_2": {"id": "cat_2", "name": "Design & Editing", "emoji": "🎨", "hidden": False, "position": 2},
}

DEFAULT_SETTINGS = {
    "shop_name": "CHEAP AI TOOLS",
    "shop_logo": "",
    "welcome_message": "👋 Welcome to *CHEAP AI TOOLS* Store!\nChoose a product below or top up your wallet to get started.",
    "support_username": "cheapAiTools_Support",
    "currency": "USDT",
    "tax_percent": 0.0,
    "delivery_message": "Thank you for your purchase! Your account/invite details have been delivered.",
    "footer_text": "💯 Safe • Secure • Instant Access 🚀",
    "terms_text": "📜 *Terms of Service*\n\n1. All sales are final once credentials/links are delivered.\n2. Do not attempt to modify owner settings unless permitted.\n3. Contact support for any warranty inquiries.",
    "privacy_text": "🛡️ *Privacy Policy*\n\nYour data is confidential and securely stored."
}

DEFAULT_PAYMENTS = {
    "binance": {
        "id": "binance",
        "name": "🟡 Binance Pay (UID)",
        "enabled": True,
        "type": "crypto",
        "details": "UID: 719439083",
        "instructions": "1. Open Binance App -> Pay -> Send\n2. Enter UID: 719439083\n3. Send USDT and copy Order ID."
    },
    "nayapay": {
        "id": "nayapay",
        "name": "📲 NayaPay (PKR)",
        "enabled": True,
        "type": "bank",
        "details": "IBAN: PK83NAYA1234503043320730\nName: AHMED ZAIB KHAN",
        "instructions": "1. Send PKR to NayaPay IBAN\n2. Save reference number / screenshot."
    }
}

DEFAULT_MENU = {
    "products": {"label": "🛍️ Shop Products", "enabled": True, "order": 1},
    "wallet": {"label": "💳 Wallet & Top Up", "enabled": True, "order": 2},
    "referral": {"label": "🎁 Referral Program", "enabled": True, "order": 3},
    "support": {"label": "📩 Support", "enabled": True, "order": 4},
    "github": {"label": "🐙 GitHub Integration", "enabled": True, "order": 5}
}

def run_safe_migrations(load_json_fn, save_json_fn, db_execute_fn):
    """Executes safe, non-destructive database migrations.
    Never overwrites existing data or drops existing keys."""
    logger.info("Running safe database migrations...")

    # 1. Categories
    cats = load_json_fn(CATEGORIES_FILE)
    if not cats or not isinstance(cats, dict):
        save_json_fn(CATEGORIES_FILE, DEFAULT_CATEGORIES)
        logger.info("Seeded default categories.")

    # 2. Settings
    settings = load_json_fn(SETTINGS_FILE)
    if not settings or not isinstance(settings, dict):
        save_json_fn(SETTINGS_FILE, DEFAULT_SETTINGS)
    else:
        # Fill missing key defaults without overwriting existing settings
        updated = False
        for k, v in DEFAULT_SETTINGS.items():
            if k not in settings:
                settings[k] = v
                updated = True
        if updated:
            save_json_fn(SETTINGS_FILE, settings)

    # 3. Payments
    payments = load_json_fn(PAYMENTS_FILE)
    if not payments or not isinstance(payments, dict):
        save_json_fn(PAYMENTS_FILE, DEFAULT_PAYMENTS)

    # 4. Coupons
    coupons = load_json_fn(COUPONS_FILE)
    if not coupons or not isinstance(coupons, dict):
        save_json_fn(COUPONS_FILE, {})

    # 5. Menu Builder
    menu = load_json_fn(MENU_BUILDER_FILE)
    if not menu or not isinstance(menu, dict):
        save_json_fn(MENU_BUILDER_FILE, DEFAULT_MENU)

    # 6. Admin Users / Roles
    admins = load_json_fn(ADMIN_USERS_FILE)
    if not admins or not isinstance(admins, dict):
        save_json_fn(ADMIN_USERS_FILE, {"admins": [], "roles": {}})

    # 7. Audit Logs
    logs = load_json_fn(ADMIN_LOGS_FILE)
    if not logs or not isinstance(logs, list):
        save_json_fn(ADMIN_LOGS_FILE, [])

    logger.info("Safe database migrations completed successfully.")
