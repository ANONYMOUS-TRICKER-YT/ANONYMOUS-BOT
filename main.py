import os
import re
import json
import math
import time
import random
import asyncio
import threading
import psycopg2
from psycopg2.extras import Json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ApplicationHandlerStop
from telegram.request import HTTPXRequest
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import logging
from github_service import github_service
from admin_panel.db_migrations import run_safe_migrations
from admin_panel.admin_permissions import is_admin, is_owner, has_permission, add_admin_user, remove_admin_user
from admin_panel import admin_products, admin_users, admin_orders, admin_payments, admin_coupons, admin_broadcast, admin_stats, admin_settings, admin_backup, admin_logs, search_engine

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BANK_DETAILS = os.getenv("BANK_DETAILS")
CRYPTO_ADDRESS = os.getenv("CRYPTO_ADDRESS")
PROXY_URL = os.getenv("PROXY_URL", None)

# ============== ALERTS CHANNEL + FORCE JOIN ==============
# Public channel for alerts + force-join gate. CHANNEL_ID is used both to POST
# alerts and to CHECK membership (bot MUST be admin in the channel). CHANNEL_LINK
# is the join URL shown to users.
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

# ============== NAYAPAY ==============
NAYAPAY_IBAN = os.getenv("NAYAPAY_IBAN", "PK83NAYA1234503043320730")
NAYAPAY_NAME = os.getenv("NAYAPAY_NAME", "AHMED ZAIB KHAN")
# Fallback PKR rate used only if the live API is unreachable
try:
    FALLBACK_USDT_PKR = float(os.getenv("FALLBACK_USDT_PKR", "280"))
except (TypeError, ValueError):
    FALLBACK_USDT_PKR = 280.0

# ============== WALLET TOP-UP PROVIDERS ==============
# Binance UID shown to customers for payment. Configurable via env/secret,
# defaults to the live account UID so customers never need to contact admin.
BINANCE_UID = os.getenv("BINANCE_UID", "719439083")

def _val(v):
    """Show a configured value or a clear placeholder."""
    return f"`{v}`" if v else "_admin se rabta karein_"

TOPUP_METHODS = {
    "binance": {
        "label": "🟡 Binance Pay (UID)",
        "title": "🟡 *Top Up via Binance Pay*",
        "steps": lambda: (
            f"1️⃣ Apni *Binance app* kholein\n"
            f"2️⃣ *Pay → Send* par jayein\n"
            f"3️⃣ Send to UID: {_val(BINANCE_UID)}\n"
            f"4️⃣ Koi bhi amount *USDT* mein bhejein"
        ),
        "ref": "Binance Pay history mein jaa kar *Order ID* (18-19 digit number) copy karein.",
    },
    "nayapay": {
        "label": "📲 NayaPay",
        "title": "📲 *Top Up via NayaPay*",
        "steps": lambda: (
            f"1️⃣ NayaPay / kisi bhi bank app se transfer karein\n"
            f"2️⃣ IBAN: `{NAYAPAY_IBAN}`\n"
            f"3️⃣ Name: {NAYAPAY_NAME}\n"
            f"4️⃣ Koi bhi amount (PKR) bhejein"
        ),
        "ref": "Payment ka *screenshot* ya *reference number* bhejein.",
    },
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Support contact (direct DM link shown on the Support screen)
SUPPORT_USERNAME = "cheapAiTools_Support"
SUPPORT_URL = f"https://t.me/{SUPPORT_USERNAME}"

# Shown when a buyer opens a full-account product (Leonardo 8500 / Trail account)
ACCOUNT_INFO = (
    "✨ *Account Information* ✨\n\n"
    "🔐 Agar aap account ka Email ya Password change karwana chahte hain, "
    "to Support Team se contact karein.\n\n"
    "✅ Otherwise, aap account ko bilkul privately aur smoothly use kar sakte hain.\n"
    "🛡️ Kisi bhi qisam ka issue, restriction, ya problem nahi aayegi.\n\n"
    "💯 Safe • Secure • Private Use 🚀\n\n"
    "📩 Need changes? Contact Support.\n"
    "😊 No changes needed? Enjoy hassle-free access! ✨"
)

# ============== PRODUCTS ==============
PRODUCTS = {
    "1": {
        "name": "🚀 Replit - 1 Month",
        "price": 15,
        "stock": 50,
        "description": "Replit subscription - 1 month access",
        "delivery": "Your Replit account access will be shared by admin.",
        "per_seat": False,
    },
    "2": {
        "name": "🎨 Canva + Leonardo AI 8500 Points - Account (1 Month)",
        "price": 20,
        "stock": 25,
        "description": "Full account, 1 month, 100 seats available, 8500 points",
        "delivery": "Your account login details will be shared by admin.",
        "per_seat": False,
        "account_info": ACCOUNT_INFO,
    },
    "3": {
        "name": "🪑 Canva + Leonardo AI 8500 Points - Seat",
        "price": 0.2,
        "stock": 250,
        "description": "Per seat invite (0.2 USDT each)",
        "delivery": "Your seat invite will be shared by admin.",
        "per_seat": True,
    },
    "4": {
        "name": "🖌 Canva Business Trail - Account (1 Month)",
        "price": 4,
        "stock": 30,
        "description": "Trail Canva Business account - 1 month",
        "delivery": "Your account access will be shared by admin.",
        "per_seat": False,
        "account_info": ACCOUNT_INFO,
    },
    "5": {
        "name": "✨ Gemini Pro 18M",
        "price": 3,
        "stock": 0,
        "description": (
            "🎁 *Key Features:*\n"
            "💥 5TB Storage & Family Admin: Aapke personal email ko Owner status par "
            "upgrade karta hai. 5 family members tak invite kar saktay hain.\n"
            "💥 Premium AI Access: Gemini Pro features unlock — advanced image generation "
            "(Nano Banana Pro) aur video creation (Veo 3).\n"
            "💥 Hassle-Free Activation: Prepaid Redeem Link. Koi payment card nahi chahiye — "
            "bas redeem click karein, instantly activate ho jayega.\n\n"
            "🚨 *Note:*\n"
            "⚠️ Redeem ke dauran koi issue ho to foran support team se rabta karein.\n"
            "❌ No Hold warranty aur No warranty after successful activation (link single-use hai).\n"
            "❌ No warranty after redeem.\n\n"
            "🎉 Delivery payment confirmation ke baad automatic hai."
        ),
        "delivery": "Your prepaid redeem link(s) will be sent automatically.",
        "per_seat": False,
    },
}

def product_card(pid, product):
    """Styled product card (price + stock) — matches the shop's stock style."""
    suffix = " / seat" if product.get('per_seat') else ""
    stock = current_stock(pid, product)
    stock_line = (
        f"📦 Stock: *{stock}* available" if stock > 0 else "📦 Stock: *Out of stock* ❌"
    )
    return (
        f"🛒 *{product['name']}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💲 Price: {price_label(pid, product, suffix)}\n"
        f"{stock_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 {product['description']}\n"
    )

PRODUCT_IMAGES_DIR = "product_images"

def product_image_path(pid):
    """Return this product's banner image path if the file exists, else None.
    Images live in product_images/<pid>.png so no DB/code change is needed to swap art."""
    path = os.path.join(PRODUCT_IMAGES_DIR, f"{pid}.png")
    return path if os.path.exists(path) else None

async def send_banner(context, chat_id, pid, caption=None, reply_markup=None):
    """Send a product's banner photo. Prefers an admin-uploaded file_id (DB-backed,
    survives redeploys), falls back to product_images/<pid>.png. Returns the sent
    Message, or None if there's no banner / sending failed."""
    pm = ParseMode.MARKDOWN if caption else None
    fid = banner_file_id(pid)
    if fid:
        try:
            return await context.bot.send_photo(
                chat_id=chat_id, photo=fid, caption=caption,
                parse_mode=pm, reply_markup=reply_markup,
            )
        except Exception as e:
            # Stored file_id may have gone stale → fall back to a local PNG below.
            logging.warning(f"send_banner file_id failed (pid={pid}): {e}")
    path = product_image_path(pid)
    if path:
        try:
            with open(path, "rb") as fh:
                return await context.bot.send_photo(
                    chat_id=chat_id, photo=fh, caption=caption,
                    parse_mode=pm, reply_markup=reply_markup,
                )
        except Exception as e:
            logging.warning(f"send_banner local failed (pid={pid}): {e}")
    return None

async def send_product_view(context, chat_id, pid, product, body, reply_markup):
    """Show a product: send its banner image (if available) followed by the text
    body with its inline keyboard. Falls back to text-only when no image exists."""
    context.user_data['banner_msg_id'] = None
    msg = await send_banner(context, chat_id, pid, caption=f"🛒 *{product['name']}*")
    if msg:
        context.user_data['banner_msg_id'] = msg.message_id
    await context.bot.send_message(
        chat_id=chat_id,
        text=body,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
    )

# Fixed quick-pick amounts shown as tappable boxes / chairs
QTY_PRESETS = [1, 2, 3, 5, 10, 15, 20, 25]

def quantity_keyboard(pid, product):
    """Tappable quantity picker: boxes for normal products, chairs for seats,
    plus a Custom Amount option (matches the shop's box-style selector)."""
    icon = "🪑" if product.get('per_seat') else "📦"
    stock = current_stock(pid, product)
    rows, row = [], []
    for n in QTY_PRESETS:
        if n > stock:
            continue
        row.append(InlineKeyboardButton(f"{icon} {n}", callback_data=f"qty_{pid}_{n}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📝 Custom Amount", callback_data=f"qtyc_{pid}")])
    rows.append([
        InlineKeyboardButton("🔙 Back", callback_data="back_products"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(rows)

def products_list_markup():
    """Text + inline keyboard for the product list (reused by Back navigation)."""
    text = "🎁 *Available Products:*\n\nNeeche se product par 1 click karein 👇"
    keyboard = []
    colors = get_button_colors()
    icons = get_product_icons()
    for pid, product in PRODUCTS.items():
        suffix = "/seat" if product.get('per_seat') else ""
        stock = current_stock(pid, product)
        stock_tag = f"📦 {stock}" if stock > 0 else "❌ Out"
        s = active_sale(pid)
        if s:
            price_txt = f"{_strike(fmt(product['price']) + ' USDT')} ➡️ {fmt(s['sale_price'])} USDT 🔥{suffix}"
        else:
            price_txt = f"{fmt(product['price'])} USDT{suffix}"
        label = f"{product_display_name(pid, product, icons)} — {price_txt} ({stock_tag})"
        keyboard.append([_styled_button(label, f"select_{pid}", colors.get(pid))])
    return text, InlineKeyboardMarkup(keyboard)

def quantity_prompt_text(pid, product):
    """Product card + (optional) account info + quantity question."""
    unit = "seats" if product.get('per_seat') else "quantity"
    parts = [product_card(pid, product)]
    if product.get('account_info'):
        parts.append(product['account_info'])
    parts.append(f"Aap kitni {unit} lena chahte hain? 👇")
    return "\n".join(parts)

def back_to_products_markup():
    """Single Back button that returns to the product list."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back to Products", callback_data="back_products")]]
    )

def payment_keyboard(pid):
    """Payment options + Back (to quantity) and Cancel."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 NayaPay", callback_data="pay_bank")],
        [InlineKeyboardButton("🟡 Binance Pay (UID)", callback_data="pay_binance")],
        [InlineKeyboardButton("💳 Wallet", callback_data="pay_wallet")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"back_qty_{pid}"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])

def decrement_stock(order):
    """Reduce a product's stock by the delivered order quantity (in-memory).
    Idempotent: marks the order so a re-approval can't double-decrement."""
    if order.get('stock_decremented'):
        return
    try:
        qty = int(order.get('quantity', 1) or 1)
    except (TypeError, ValueError):
        qty = 1
    for product in PRODUCTS.values():
        if product['name'] == order.get('product'):
            product['stock'] = max(0, product.get('stock', 0) - qty)
            break
    order['stock_decremented'] = True

# ============== DATABASE FILES ==============
WALLETS_FILE = "wallets.json"
REFERRALS_FILE = "referrals.json"
ORDERS_FILE = "orders.json"
TOPUPS_FILE = "topups.json"
# Timed flash sales: {pid: {"sale_price": float, "original_price": float, "until": unix_ts}}
SALES_FILE = "sales.json"
# Stored account credentials per product (admin-loaded). Stock = how many are left.
INVENTORY_FILE = "inventory.json"
# Admin-set permanent price overrides: {pid: new_price}. Applied onto PRODUCTS on startup.
PRICES_FILE = "prices.json"
# Referral reward pool: {"items": [reward_string, ...]}. Each item is sent once,
# at random, to a user who hits a referral milestone (then removed from the pool).
REWARDS_FILE = "rewards.json"
# Referral counts at which a reward is auto-sent, and the per-user cap.
REWARD_MILESTONES = [5, 10]
MAX_REWARDS = len(REWARD_MILESTONES)
# Admin-uploaded banner images: {pid: telegram_file_id}. Stored in DB (NOT as files)
# so banners survive redeploys. Takes priority over any product_images/<pid>.png.
BANNERS_FILE = "banners.json"
# Admin-added / removed products (survives redeploy). Shape:
#   {"added": {pid: {product dict}}, "removed": [pid, ...]}
PRODUCTS_FILE = "products.json"
# Admin-set colors for the product-list buttons (Bot API 9.4+):
#   {pid: "primary"|"success"|"danger"}
COLORS_FILE = "colors.json"
# Admin-set icon (emoji) shown before each product name: {pid: "emoji"}
ICONS_FILE = "icons.json"

# ============== PERSISTENT STORAGE (PostgreSQL) ==============
# Data lives in a PostgreSQL key-value table instead of local JSON files. This is
# the fix for data loss on redeploy: the Replit deployment snapshots the whole
# workspace (incl. gitignored files), so every republish used to overwrite the
# live wallets/referrals/inventory with the stale repo copy. The database persists
# across deploys, so balances, referrals, stock, sales etc. are no longer reset.
# The old JSON files are kept ONLY as one-time seed data (see seed_db_from_files).
_DB_CONN = None

def _get_conn():
    """Return a live DB connection, (re)connecting and ensuring the table exists."""
    global _DB_CONN
    if _DB_CONN is None or _DB_CONN.closed:
        _DB_CONN = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)
        _DB_CONN.autocommit = True
        with _DB_CONN.cursor() as cur:
            # Cap query time so a hung DB call can't freeze the bot's event loop.
            cur.execute("SET statement_timeout = '15s'")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS kv_store ("
                "key TEXT PRIMARY KEY, value JSONB NOT NULL)"
            )
    return _DB_CONN

def _db_execute(query, params=(), fetch=False):
    """Run a query with one automatic reconnect if the connection went stale."""
    global _DB_CONN
    for attempt in range(2):
        try:
            conn = _get_conn()
            with conn.cursor() as cur:
                cur.execute(query, params)
                if fetch:
                    return cur.fetchone()
            return None
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            try:
                if _DB_CONN is not None:
                    _DB_CONN.close()
            except Exception:
                pass
            _DB_CONN = None
            if attempt == 1:
                raise
    return None

def load_json(filename):
    """Read a JSON blob by key from the DB. Returns {} when absent."""
    row = _db_execute("SELECT value FROM kv_store WHERE key = %s", (filename,), fetch=True)
    if row and row[0] is not None:
        return row[0]
    return {}

def save_json(filename, data):
    """Upsert a JSON blob by key. A single UPSERT is atomic, so lock-free readers
    (e.g. active_sale) never see a half-written value."""
    _db_execute(
        "INSERT INTO kv_store (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (filename, Json(data)),
    )

def seed_db_from_files():
    """One-time migration: if a key is NOT yet in the DB, load it from the bundled
    JSON file (if present) so existing data is carried over on first run. Because we
    only seed keys that are ABSENT, later redeploys never clobber live DB data."""
    for fn in (WALLETS_FILE, REFERRALS_FILE, ORDERS_FILE, TOPUPS_FILE,
               INVENTORY_FILE, SALES_FILE, PRICES_FILE, REWARDS_FILE, BANNERS_FILE,
               PRODUCTS_FILE, COLORS_FILE, ICONS_FILE):
        row = _db_execute("SELECT 1 FROM kv_store WHERE key = %s", (fn,), fetch=True)
        if row:
            continue
        data = {}
        if os.path.exists(fn):
            try:
                with open(fn, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        save_json(fn, data)
        print(f"🌱 Seeded '{fn}' into database ({len(data)} entries)")

# ============== STOCK / INVENTORY ==============
# Serialize all read-modify-write access to inventory.json so concurrent
# /addstock and order approvals can't clobber each other or double-allocate.
INVENTORY_LOCK = asyncio.Lock()
# Guards money/order JSON files (wallets, orders, topups, referrals). With
# concurrent update processing on, this prevents lost updates when many users
# buy/top-up at the same moment (read-modify-write on the same file).
# NOTE: this is the SAME object as INVENTORY_LOCK — one global lock for every
# JSON read-modify-write. asyncio.Lock is NOT reentrant, so a single critical
# section must acquire it only once (never nest the two names).
DATA_LOCK = INVENTORY_LOCK

def apply_price_overrides():
    """Apply admin-set permanent price changes (prices.json) onto PRODUCTS in memory.
    Called once on startup so /setprice changes survive restarts/redeploys."""
    overrides = load_json(PRICES_FILE)
    for pid, price in overrides.items():
        if pid in PRODUCTS:
            try:
                PRODUCTS[pid]["price"] = float(price)
            except (TypeError, ValueError):
                pass

def apply_product_overrides():
    """Merge admin-added products into PRODUCTS and drop admin-removed ones.
    Called once on startup so /addproduct and /removeproduct survive redeploys."""
    data = load_json(PRODUCTS_FILE)
    for pid, prod in (data.get("added") or {}).items():
        PRODUCTS[pid] = prod
    for pid in (data.get("removed") or []):
        PRODUCTS.pop(pid, None)

def next_product_id():
    """Smallest unused numeric product id as a string (e.g. '6')."""
    used = [int(p) for p in PRODUCTS.keys() if str(p).isdigit()]
    n = 1
    while n in used:
        n += 1
    return str(n)

# Telegram button colors (Bot API 9.4+, needs python-telegram-bot >= 22.7).
# These 3 are the ONLY colors Telegram supports for bot buttons.
BUTTON_COLORS = {
    "primary": "🔵 Blue",
    "success": "🟢 Green",
    "danger": "🔴 Red",
}

def get_button_colors():
    """{pid: style} — admin-set colors for the product-list buttons."""
    return load_json(COLORS_FILE)

def get_product_icons():
    """{pid: emoji} — admin-set icon shown before each product name."""
    return load_json(ICONS_FILE)

# Leading emoji / symbol at the very start of a product name (so /seticon can
# swap it without leaving a duplicate icon behind).
_LEADING_EMOJI_RE = re.compile(
    "^(?:[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF\U0000FE00-\U0000FE0F"
    "\U0001F3FB-\U0001F3FF\U000020E3\U0000200D\U00002122\U00002139]+)\\s*"
)

def _strip_leading_emoji(text):
    """Remove a leading emoji/symbol from a product name, if present."""
    return _LEADING_EMOJI_RE.sub("", text or "").strip()

def product_display_name(pid, product, icons=None):
    """Product name with the admin-set icon override applied (if any)."""
    if icons is None:
        icons = get_product_icons()
    icon = icons.get(pid)
    if icon:
        return f"{icon} {_strip_leading_emoji(product.get('name', ''))}".strip()
    return product.get("name", "")

def _styled_button(text, callback_data, style=None):
    """InlineKeyboardButton with an optional color (primary/success/danger).
    Falls back to a normal button if the installed python-telegram-bot version
    predates Bot API 9.4, so an older library can never crash the bot."""
    if style:
        try:
            return InlineKeyboardButton(text, callback_data=callback_data, style=style)
        except TypeError:
            pass
    return InlineKeyboardButton(text, callback_data=callback_data)

def get_reward_items():
    """Referral reward pool as a list of strings (stored under {"items": [...]})."""
    data = load_json(REWARDS_FILE)
    items = data.get("items", []) if isinstance(data, dict) else []
    return items if isinstance(items, list) else []

# A reward whose text starts with '*' or '♻️' is REPEATABLE: it is given out every
# time it's picked but never removed from the pool (e.g. a public/shared link the
# admin wants to keep handing out). Plain items are consumed (removed) once given.
REPEAT_MARKS = ("*", "♻️")

def is_repeat_reward(item):
    return isinstance(item, str) and item.lstrip().startswith(REPEAT_MARKS)

def clean_reward(item):
    """Reward text as the user should see it — leading repeat mark stripped."""
    s = item.lstrip() if isinstance(item, str) else item
    for mark in REPEAT_MARKS:
        if s.startswith(mark):
            return s[len(mark):].lstrip()
    return item

def rewards_active():
    """True if the referral reward campaign is currently running (admin-started via
    /startrewards and not yet expired). Lock-free read. When off, referrals still
    count but no rewards are given."""
    data = load_json(REWARDS_FILE)
    if not isinstance(data, dict):
        return False
    try:
        return time.time() < float(data.get("active_until", 0))
    except (TypeError, ValueError):
        return False

def reward_time_left():
    """Human remaining-time string for the active reward campaign, e.g. '2 ghante'."""
    data = load_json(REWARDS_FILE)
    until = data.get("active_until", 0) if isinstance(data, dict) else 0
    try:
        return time_left_text(float(until))
    except (TypeError, ValueError):
        return "0 min"

def banner_file_id(pid):
    """Admin-uploaded banner file_id for a product (DB-backed), or None."""
    data = load_json(BANNERS_FILE)
    if isinstance(data, dict):
        fid = data.get(str(pid))
        if isinstance(fid, str) and fid:
            return fid
    return None

def get_inventory():
    """{pid: [credential_string, ...]} — each entry is one ready account."""
    return load_json(INVENTORY_FILE)

def current_stock(pid, product):
    """Account products: stock = number of stored credentials admin ne add kiye.
    Seat products: numeric stock field (delivered via email invite)."""
    if product.get('per_seat'):
        return product.get('stock', 0)
    return len(get_inventory().get(str(pid), []))

def add_credentials(pid, creds):
    """Append ready account credentials to a product's inventory."""
    inv = get_inventory()
    inv.setdefault(str(pid), []).extend(creds)
    save_json(INVENTORY_FILE, inv)
    return len(inv[str(pid)])

def pop_credentials(pid, n):
    """Remove and return up to n stored credentials for a product."""
    inv = get_inventory()
    creds = inv.get(str(pid), [])
    taken = creds[:n]
    inv[str(pid)] = creds[n:]
    save_json(INVENTORY_FILE, inv)
    return taken

def remove_credentials(pid, n):
    """Delete up to n stored credentials for a product. Returns (removed, remaining)."""
    inv = get_inventory()
    creds = inv.get(str(pid), [])
    removed = min(n, len(creds))
    inv[str(pid)] = creds[removed:]
    save_json(INVENTORY_FILE, inv)
    return removed, len(inv[str(pid)])

def clear_credentials(pid):
    """Delete ALL stored credentials for a product. Returns how many were removed."""
    inv = get_inventory()
    removed = len(inv.get(str(pid), []))
    inv[str(pid)] = []
    save_json(INVENTORY_FILE, inv)
    return removed

def find_pid(product_name):
    """Return the product id whose name matches, else None."""
    for pid, p in PRODUCTS.items():
        if p['name'] == product_name:
            return pid
    return None

# ============== HELPERS ==============
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def fmt(amount):
    """Format USDT amount: drop trailing .0 for whole numbers."""
    if amount == int(amount):
        return str(int(amount))
    return f"{amount:.2f}"

def _strike(text):
    """Unicode strikethrough — works in any parse mode (legacy Markdown can't do ~~)."""
    return "".join(ch + "\u0336" for ch in str(text))

def active_sale(pid):
    """Return the sale dict for pid if an unexpired sale exists, else None.
    Pure synchronous read (no DATA_LOCK) so it's safe to call inside locked sections.
    Auto-expiry is handled here: once 'until' passes, the price reverts automatically."""
    s = load_json(SALES_FILE).get(str(pid))
    if not s:
        return None
    if time.time() >= s.get("until", 0):
        return None
    return s

def effective_price(pid, product):
    """Unit price charged right now: sale price if a sale is active, else base price."""
    s = active_sale(pid)
    return s["sale_price"] if s else product.get("price", 0)

def price_label(pid, product, suffix=""):
    """Markdown price text for cards: crossed-out original + sale price when on sale."""
    base = product.get("price", 0)
    s = active_sale(pid)
    if s:
        return f"{_strike(fmt(base) + ' USDT')} ➡️ *{fmt(s['sale_price'])} USDT* 🔥{suffix}"
    return f"*{fmt(base)} USDT*{suffix}"

def order_amount(context):
    """Total amount = effective price * quantity (quantity defaults to 1)."""
    product = context.user_data.get('product', {})
    pid = context.user_data.get('product_id')
    qty = context.user_data.get('quantity', 1)
    return effective_price(pid, product) * qty

def emails_block(order):
    """Build an admin-facing block listing order emails (if any)."""
    emails = order.get('emails') or []
    if not emails:
        return ""
    listing = "\n".join(emails)
    if len(listing) > 3000:
        return f"\n📧 Emails: {len(emails)} (saved in orders file)"
    return f"\n📧 Emails ({len(emails)}):\n{listing}"

# ============== LIVE USDT -> PKR RATE ==============
_rate_cache = {"rate": None, "ts": 0.0}
_RATE_TTL = 1800  # refresh at most every 30 minutes

async def get_usdt_pkr_rate():
    """Live 1 USDT -> PKR rate (CoinGecko), cached 30 min, with fallback."""
    import time
    now = time.time()
    if _rate_cache["rate"] and (now - _rate_cache["ts"] < _RATE_TTL):
        return _rate_cache["rate"]
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "tether", "vs_currencies": "pkr"},
            )
            resp.raise_for_status()
            rate = float(resp.json()["tether"]["pkr"])
            if rate > 0:
                _rate_cache["rate"] = rate
                _rate_cache["ts"] = now
                return rate
    except Exception as e:
        logger.warning(f"USDT->PKR rate fetch failed: {e}")
    return _rate_cache["rate"] or FALLBACK_USDT_PKR

def pkr_line(amount_usdt, rate):
    """Build a clean PKR conversion line for a USDT amount."""
    pkr = amount_usdt * rate
    return (
        f"≈ PKR {pkr:,.0f}\n"
        f"(Rate: 1 USDT = PKR {rate:,.2f})"
    )

def new_order_id(user_id):
    """Collision-resistant order id (millisecond ts + short random suffix)."""
    import uuid
    return f"ORD-{user_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}"

# ============== WAITING / VERIFY PROGRESS BAR ==============
# In-memory registries: order_id -> running task / (chat_id, message_id)
WAITING_TASKS = {}
WAITING_MSGS = {}
BAR_MAX_LIFETIME = 24 * 3600  # auto-stop a bar after 24h to avoid leaks

def render_progress(pct):
    """20-cell text progress bar."""
    pct = max(0, min(100, int(pct)))
    filled = pct // 5
    return "▓" * filled + "░" * (20 - filled)

async def waiting_bar(context, chat_id, message_id, order_id):
    """Slowly fill a verify bar toward ~99% over hours; never reaches 100
    on its own — only admin approval completes it. Asymptotic so it keeps
    creeping even after 5+ hours without spamming Telegram with edits."""
    start = time.time()
    TAU = 3600.0          # characteristic time (~1h) for the curve
    interval = 4.0
    last_pct = -1
    try:
        while time.time() - start < BAR_MAX_LIFETIME:
            elapsed = time.time() - start
            pct = int(99 * (1 - math.exp(-elapsed / TAU)))
            pct = max(1, min(99, pct))
            if pct != last_pct:
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            f"🔄 *Verifying Payment...*\n\n"
                            f"`{render_progress(pct)}` {pct}%\n\n"
                            f"Order: {order_id}\n"
                            f"Admin aapki payment verify kar raha hai.\n"
                            f"Please wait... ⏳"
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                last_pct = pct
            await asyncio.sleep(interval)
            interval = min(interval * 1.25, 120.0)
        # Timed out after max lifetime — nudge the user, then let cleanup run
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=(
                    f"⌛ Order {order_id} abhi verify ho raha hai.\n"
                    f"Thoda time lag raha hai — please admin se rabta karein."
                ),
            )
        except Exception:
            pass
    except asyncio.CancelledError:
        return

async def start_waiting_bar(context, chat_id, order_id):
    """Send the initial verify message and launch the animated bar task."""
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔄 *Verifying Payment...*\n\n"
                f"`{render_progress(1)}` 1%\n\n"
                f"Order: {order_id}\n"
                f"Admin aapki payment verify kar raha hai.\n"
                f"Please wait... ⏳"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        return
    # Cancel any pre-existing bar for this order id before replacing it
    old = WAITING_TASKS.pop(order_id, None)
    if old:
        old.cancel()
    WAITING_MSGS[order_id] = (msg.chat_id, msg.message_id)
    task = asyncio.create_task(
        waiting_bar(context, msg.chat_id, msg.message_id, order_id)
    )
    WAITING_TASKS[order_id] = task
    # Auto-clean registry entries when the task ends for any reason
    def _cleanup(t, _oid=order_id):
        if WAITING_TASKS.get(_oid) is t:
            WAITING_TASKS.pop(_oid, None)
            WAITING_MSGS.pop(_oid, None)
    task.add_done_callback(_cleanup)

def _stop_bar_task(order_id):
    task = WAITING_TASKS.pop(order_id, None)
    if task:
        task.cancel()
    return WAITING_MSGS.pop(order_id, None)

async def complete_waiting_bar(context, order, extra_message=None):
    """Finish the bar at 100% (instant) with an approval message, plus an
    optional second message containing whatever the admin typed."""
    order_id = order['order_id']
    chat_id = order['user_id']
    msg = _stop_bar_task(order_id)
    approved_text = (
        f"✅ *Payment Approved!*\n\n"
        f"`{render_progress(100)}` 100%\n\n"
        f"Order: {order_id}\n"
        f"Product: {order['product']}\n"
        f"🎉 Your order is confirmed!"
    )
    if msg:
        bchat, bmid = msg
        try:
            await context.bot.edit_message_text(
                chat_id=bchat, message_id=bmid,
                text=approved_text, parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id, text=approved_text, parse_mode=ParseMode.MARKDOWN,
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=approved_text, parse_mode=ParseMode.MARKDOWN,
        )
    # Second message (admin's typed details) — plain text so special chars are safe
    if extra_message:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📩 Message from Admin:\n\n{extra_message}\n\n⚠️ Ise kisi ke saath share na karein.",
        )

    # ===== Channel alerts: new sale (banner + one-click buy) + out-of-stock =====
    pid = find_pid(order['product'])
    product = PRODUCTS.get(pid) if pid else None
    await notify_channel(
        context,
        f"🛒 *New Sale!*\n\n"
        f"📦 Product: {order['product']}\n"
        f"🔢 Qty: {order.get('quantity', 1)}\n"
        f"💰 Amount: {fmt(order.get('amount', 0))} USDT",
        pid=pid,
        buy_button=True,
    )
    if product and current_stock(pid, product) <= 0:
        await notify_channel(
            context,
            f"❌ *Out of Stock!*\n\n"
            f"📦 {order['product']}\n"
            f"Stock khatam ho gaya — naya stock add karein.",
        )

async def fail_waiting_bar(context, order, text):
    """Stop the bar and show a rejected/failed message to the user."""
    order_id = order['order_id']
    chat_id = order['user_id']
    msg = _stop_bar_task(order_id)
    if msg:
        bchat, bmid = msg
        try:
            await context.bot.edit_message_text(chat_id=bchat, message_id=bmid, text=text)
            return
        except Exception:
            pass
    await context.bot.send_message(chat_id=chat_id, text=text)

# ============== CONVERSATION STATES ==============
CHOOSING, CONFIRMING_ORDER, PAYMENT_METHOD, AWAITING_APPROVAL, ASK_QUANTITY, ASK_EMAILS = 1, 2, 3, 4, 5, 6
# Wallet top-up states: choosing a provider, then sending proof
TOPUP_METHOD, TOPUP_PROOF = 7, 8
# Admin-side states: typing login/access details, or crediting a top-up amount
ADMIN_DELIVER = 10
TOPUP_ADMIN_AMOUNT = 11
# Admin stock: pick a product, then paste account credentials
ADMIN_STOCK_PID, ADMIN_STOCK_ADD = 12, 13
# Admin remove-stock: pick a product, then how many to remove (or "all")
ADMIN_RMSTOCK_PID, ADMIN_RMSTOCK_QTY = 14, 15
# Admin add referral rewards: paste items (one per line)
ADMIN_REWARD_ADD = 16
# Admin set banner: pick a product, then send a photo
ADMIN_BANNER_PID, ADMIN_BANNER_IMG = 17, 18
# Admin add product: name -> price -> description
ADMIN_ADDPROD_NAME, ADMIN_ADDPROD_PRICE, ADMIN_ADDPROD_DESC = 19, 20, 21

# Reply-keyboard main-menu buttons (used to let users escape sub-flows)
MENU_BUTTONS = {
    "🛍️ Browse Products", "🪑 My Orders", "👥 Referral",
    "💰 Wallet", "❓ Support/FAQ", "💵 Top Up", "👤 Profile",
}

# ============== REFERRAL CAPTURE ==============
async def capture_referral(context, referrer_id, new_user_id, new_user_name):
    """Record that a new user joined via someone's referral link and bump the
    referrer's count. Ignores self-referrals and duplicates."""
    referrer_id = "".join(ch for ch in str(referrer_id) if ch.isdigit())
    if not referrer_id or referrer_id == new_user_id:
        return
    
    won_items = []
    pool_empty = False
    async with DATA_LOCK:
        referrals = load_json(REFERRALS_FILE)
        entry = referrals.get(referrer_id) or {"code": f"REF{referrer_id}", "count": 0, "earnings": 0, "referred": []}
        referred = entry.setdefault("referred", [])
        if new_user_id in referred:
            return
        referred.append(new_user_id)
        entry["count"] = len(referred)

        # ---- Referral rewards: give a random saved item at each milestone (max MAX_REWARDS) ----
        # Only while the admin-started reward campaign is running. When off, the
        # referral still counts but no reward is given (claimed not advanced, so an
        # owed reward will be granted on the next referral once a campaign is active).
        claimed = entry.get("rewards_claimed", 0)
        eligible = sum(1 for m in REWARD_MILESTONES if entry["count"] >= m)  # 0..MAX_REWARDS
        due = eligible - claimed
        if due > 0 and rewards_active():
            data = load_json(REWARDS_FILE)
            if not isinstance(data, dict):
                data = {}
            pool = data.get("items", [])
            if not isinstance(pool, list):
                pool = []
            while due > 0 and pool:
                idx = random.randrange(len(pool))
                raw = pool[idx]
                if is_repeat_reward(raw):
                    won_items.append(clean_reward(raw))  # repeatable → keep in pool
                else:
                    won_items.append(pool.pop(idx))      # one-time → remove from pool
                claimed += 1
                due -= 1
            entry["rewards_claimed"] = claimed
            if due > 0:
                pool_empty = True  # earned but nothing left to give → alert admin, retry next time
            data["items"] = pool
            save_json(REWARDS_FILE, data)

        referrals[referrer_id] = entry
        save_json(REFERRALS_FILE, referrals)
    
    # Let the referrer know (best-effort)
    try:
        await context.bot.send_message(
            chat_id=int(referrer_id),
            text=(
                f"🎉 *Naya Referral!* 🎉\n\n"
                f"👤 {new_user_name} aapke link se join hua.\n"
                f"👥 Total Referrals: *{entry['count']}*"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    # Send any reward(s) the user just unlocked (header in markdown, item as plain text)
    for item in won_items:
        try:
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=(
                    f"🎁 *Referral Reward Unlock!* 🎁\n\n"
                    f"Mubarak ho! Aap ne *{entry['count']}* referrals complete kiye 🎉\n"
                    f"Ye raha aapka reward 👇"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=f"{item}\n\n⚠️ Ise kisi ke saath share na karein.",
            )
        except Exception:
            pass

    # Reward earned but pool empty → tell admin to restock (user retries on next referral)
    if pool_empty:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"⚠️ *Reward pool khali!*\n\n"
                    f"User `{referrer_id}` ne referral reward earn kiya, lekin pool mein "
                    f"koi item nahi bacha.\n\n/addreward se naye rewards add karein — "
                    f"user ko agle referral par mil jayega."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

# ============== START COMMAND ==============
async def notify_channel(context, text, pid=None, buy_button=False):
    """Post an alert to the alerts channel (best-effort; never breaks the flow).
    If pid has a banner image, post it as a photo with the text as caption.
    If buy_button, attach a one-click 'Buy Now' deep-link button to the bot."""
    if not CHANNEL_ID:
        return
    reply_markup = None
    if buy_button and pid:
        try:
            username = await get_bot_username(context)
            if username:
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🛒 Buy Now", url=f"https://t.me/{username}?start=buy_{pid}")
                ]])
        except Exception:
            pass
    sent = None
    if pid:
        sent = await send_banner(context, CHANNEL_ID, pid, caption=text, reply_markup=reply_markup)
    if not sent:
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID, text=text,
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logging.warning(f"notify_channel failed: {e}")

async def is_channel_member(context, user_id):
    """True if the user has joined the alerts channel (force-join gate).
    Gate is disabled when no channel is configured; the admin is always allowed;
    and on any API error we fail-open so a misconfigured channel (e.g. bot not yet
    admin) never locks the whole shop."""
    if not CHANNEL_ID:
        return True
    if user_id == ADMIN_ID:
        return True
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logging.warning(f"membership check failed: {e}")
        return True

def join_gate_markup():
    rows = []
    if CHANNEL_LINK:
        rows.append([InlineKeyboardButton("📢 Channel Join Karein", url=CHANNEL_LINK)])
    rows.append([InlineKeyboardButton("✅ Maine Join Kar Liya", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)

async def send_join_gate(context, chat_id):
    """Show the force-join screen. Bot won't proceed until the user joins."""
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🔒 *Ek Chhota Sa Step!*\n\n"
            "Bot use karne se pehle hamara channel join karna zaroori hai 👇\n\n"
            "1️⃣ Neeche *Channel Join Karein* par tap karein\n"
            "2️⃣ Channel join karein\n"
            "3️⃣ Wapas aa kar *Maine Join Kar Liya* dabayein\n\n"
            "Join ke baad hi bot aage chalega. 🙏"
        ),
        reply_markup=join_gate_markup(),
        parse_mode=ParseMode.MARKDOWN,
    )

def main_menu_markup():
    keyboard = [
        [KeyboardButton("🛍️ Browse Products")],
        [KeyboardButton("🪑 My Orders"), KeyboardButton("👥 Referral")],
        [KeyboardButton("💰 Wallet"), KeyboardButton("💵 Top Up")],
        [KeyboardButton("👤 Profile"), KeyboardButton("❓ Support/FAQ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def send_welcome_menu(context, chat_id, first_name):
    text = (
        f"🚀 *Welcome to CHEAP AI TOOLS!* 🚀\n\n"
        f"السلام علیکم {first_name}! 💎\n\n"
        f"🔥 *Premium AI Tools at Best Prices* 🔥\n\n"
        f"✨ Why Choose Us:\n"
        f"✅ Instant Delivery (Payment confirm hote hi)\n"
        f"✅ Secure Payment Methods\n"
        f"✅ Invite Friends (Referral Link)\n"
        f"✅ Wallet System\n"
        f"✅ 24/7 Support\n"
        f"✅ Money-back Guarantee\n\n"
        f"Choose below 👇"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=text,
        reply_markup=main_menu_markup(), parse_mode=ParseMode.MARKDOWN,
    )

async def start(update: Update, context):
    """CHEAP AI TOOLS start"""
    user = update.effective_user
    
    # Initialize wallet
    async with DATA_LOCK:
        wallets = load_json(WALLETS_FILE)
        is_new_user = str(user.id) not in wallets
        if is_new_user:
            wallets[str(user.id)] = {"balance": 0, "total_spent": 0}
            save_json(WALLETS_FILE, wallets)
    
    # Capture referral deep link: /start ref_<referrer_id> (before the gate so the
    # referrer still gets credited even if the new user hasn't joined yet).
    if is_new_user and context.args and context.args[0].startswith("ref_"):
        await capture_referral(context, context.args[0][4:], str(user.id), user.first_name)
    
    # Force-join gate: bina channel join kiye bot aage nahi chalega
    if not await is_channel_member(context, user.id):
        await send_join_gate(context, update.effective_chat.id)
        return
    
    # One-click buy deep link from channel: /start buy_<pid> -> seedha us product par
    if context.args and context.args[0].startswith("buy_"):
        pid = context.args[0][4:]
        if pid in PRODUCTS:
            return await confirm_product(update, context, pid)
    
    await send_welcome_menu(context, update.effective_chat.id, user.first_name)

async def check_join(update: Update, context):
    """Re-check membership when the user taps 'Maine Join Kar Liya'."""
    query = update.callback_query
    user = update.effective_user
    if await is_channel_member(context, user.id):
        await query.answer("✅ Shukriya! Ab bot use karein.")
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_welcome_menu(context, query.message.chat_id, user.first_name)
    else:
        await query.answer(
            "❌ Abhi tak join nahi kiya. Pehle channel join karein, phir dobara dabayein.",
            show_alert=True,
        )

async def global_join_gate(update: Update, context):
    """Runs before everything (group -1): blocks ANY non-member action — messages
    AND inline-button taps — so old buttons can't bypass the gate. Exemptions:
    /start (so referral capture + its own gate run) and the 'check_join' verify
    button. Admin is exempt inside is_channel_member()."""
    user = update.effective_user
    if user is None:
        return
    msg = update.message
    if msg and msg.text and msg.text.startswith("/start"):
        return
    if update.callback_query and update.callback_query.data == "check_join":
        return
    if await is_channel_member(context, user.id):
        return
    # Not a member -> block here and show the join screen
    chat_id = update.effective_chat.id if update.effective_chat else user.id
    if update.callback_query:
        try:
            await update.callback_query.answer("🔒 Pehle channel join karein.", show_alert=True)
        except Exception:
            pass
    await send_join_gate(context, chat_id)
    raise ApplicationHandlerStop

# ============== MAIN MENU ==============
async def menu_handler(update: Update, context):
    """Main menu handler"""
    # Force-join gate: bina channel join kiye koi menu action allow nahi
    if not await is_channel_member(context, update.effective_user.id):
        await send_join_gate(context, update.effective_chat.id)
        return CHOOSING
    text = update.message.text
    
    if text == "🛍️ Browse Products":
        return await show_products(update, context)
    elif text == "🪑 My Orders":
        return await show_orders(update, context)
    elif text == "👥 Referral":
        return await show_referral(update, context)
    elif text == "💰 Wallet":
        return await show_wallet(update, context)
    elif text == "💵 Top Up":
        return await show_topup(update, context)
    elif text == "👤 Profile":
        return await show_profile(update, context)
    elif text == "❓ Support/FAQ":
        return await show_support(update, context)
    elif text.isdigit() and text in PRODUCTS:
        return await confirm_product(update, context, text)
    else:
        await update.message.reply_text("❌ Invalid option")
        return CHOOSING

# ============== PRODUCTS ==============
async def show_products(update: Update, context):
    """Show products"""
    text, markup = products_list_markup()
    await update.message.reply_text(
        text,
        reply_markup=markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return CHOOSING

async def product_select(update: Update, context):
    """Handle 1-click product selection from inline buttons."""
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("select_", "")
    product = PRODUCTS.get(pid)
    if not product:
        await query.answer("❌ Product not found", show_alert=True)
        return CHOOSING
    
    context.user_data['product_id'] = pid
    context.user_data['product'] = product
    context.user_data['quantity'] = 1
    context.user_data['emails'] = []
    
    chat_id = query.message.chat_id
    try:
        await query.message.delete()
    except Exception:
        pass

    if current_stock(pid, product) <= 0:
        await send_product_view(
            context, chat_id, pid, product,
            f"{product_card(pid, product)}\n❌ Ye product abhi *out of stock* hai.",
            back_to_products_markup(),
        )
        return CHOOSING

    await send_product_view(
        context, chat_id, pid, product,
        quantity_prompt_text(pid, product),
        quantity_keyboard(pid, product),
    )
    return CONFIRMING_ORDER

async def confirm_product(update: Update, context, pid):
    """Confirm product"""
    product = PRODUCTS[pid]
    context.user_data['product_id'] = pid
    context.user_data['product'] = product
    context.user_data['quantity'] = 1
    context.user_data['emails'] = []
    context.user_data['payment_method'] = None

    chat_id = update.effective_chat.id
    if current_stock(pid, product) <= 0:
        await send_product_view(
            context, chat_id, pid, product,
            f"{product_card(pid, product)}\n❌ Ye product abhi *out of stock* hai.",
            back_to_products_markup(),
        )
        return CHOOSING

    await send_product_view(
        context, chat_id, pid, product,
        quantity_prompt_text(pid, product),
        quantity_keyboard(pid, product),
    )
    return CONFIRMING_ORDER

async def apply_quantity_and_proceed(update: Update, context, product, pid, qty):
    """Quantity tay hone ke baad: seat products -> emails maango, baaki ->
    seedha payment options dikhao."""
    chat_id = update.effective_chat.id
    context.user_data['product_id'] = pid
    context.user_data['product'] = product
    context.user_data['quantity'] = qty
    context.user_data['emails'] = []
    total = effective_price(pid, product) * qty
    
    if product.get('per_seat'):
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"*{product['name']}*\n\n"
                f"🪑 Seats: {qty}\n"
                f"💵 Total: {fmt(total)} USDT\n\n"
                f"Ab *{qty} emails* bhejein jin par seats add karni hain.\n"
                f"Har email nayi line par likhein 👇"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return ASK_EMAILS
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🧾 *Order Summary*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📦 Product: {product['name']}\n"
            f"📦 Quantity: {qty}\n"
            f"💲 Total: *{fmt(total)} USDT*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Choose Payment 👇"
        ),
        reply_markup=payment_keyboard(pid),
        parse_mode=ParseMode.MARKDOWN
    )
    return PAYMENT_METHOD

async def quantity_pick(update: Update, context):
    """Handle the tappable quantity boxes/chairs and the Custom Amount button."""
    query = update.callback_query
    data = query.data
    
    # Custom Amount -> ask the user to type a number
    if data.startswith("qtyc_"):
        pid = data.replace("qtyc_", "")
        product = PRODUCTS.get(pid)
        if not product:
            await query.answer("❌ Product not found", show_alert=True)
            return CHOOSING
        await query.answer()
        context.user_data['product_id'] = pid
        context.user_data['product'] = product
        unit = "seats" if product.get('per_seat') else "quantity"
        await query.edit_message_text(
            f"{product_card(pid, product)}\n"
            f"📝 Apni {unit} ka number bhejein 👇 (max {current_stock(pid, product)})",
            parse_mode=ParseMode.MARKDOWN
        )
        return ASK_QUANTITY
    
    # Fixed quick-pick box: qty_<pid>_<n>
    rest = data[len("qty_"):]
    pid, _, nstr = rest.rpartition("_")
    product = PRODUCTS.get(pid)
    if not product or not nstr.isdigit():
        await query.answer("❌ Product not found", show_alert=True)
        return CHOOSING
    
    qty = int(nstr)
    stock = current_stock(pid, product)
    if stock <= 0:
        await query.answer("❌ Out of stock!", show_alert=True)
        return CHOOSING
    if qty > stock:
        await query.answer(f"❌ Sirf {stock} available hain!", show_alert=True)
        return CONFIRMING_ORDER
    
    await query.answer()
    await query.edit_message_text(
        f"{product_card(pid, product)}\n✅ Selected: *{qty}*",
        parse_mode=ParseMode.MARKDOWN
    )
    return await apply_quantity_and_proceed(update, context, product, pid, qty)

async def handle_quantity(update: Update, context):
    """Handle a typed Custom Amount (works for both normal qty and seats)."""
    text = (update.message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ Valid number bhejein (jaise: 5)")
        return ASK_QUANTITY
    
    qty = int(text)
    product = context.user_data.get('product')
    pid = context.user_data.get('product_id')
    if not product or not pid:
        await update.message.reply_text("❌ Error. /start se shuru karo")
        return ConversationHandler.END
    
    stock = current_stock(pid, product)
    if stock <= 0:
        await update.message.reply_text("❌ Ye product abhi out of stock hai.")
        return CHOOSING
    if qty > stock:
        await update.message.reply_text(
            f"❌ Sirf *{stock}* available hain. Kam number bhejein 👇",
            parse_mode=ParseMode.MARKDOWN
        )
        return ASK_QUANTITY
    
    return await apply_quantity_and_proceed(update, context, product, pid, qty)

async def handle_emails(update: Update, context):
    """Collect the email list for per-seat orders, verify, then go to payment."""
    qty = context.user_data.get('quantity', 0)
    product = context.user_data.get('product')
    if not product or qty <= 0:
        await update.message.reply_text("❌ Error. /start se shuru karo")
        return ConversationHandler.END
    
    raw = update.message.text or ""
    tokens = [t.strip() for t in re.split(r"[\s,;]+", raw) if t.strip()]
    valid = [t for t in tokens if EMAIL_RE.match(t)]
    
    if len(tokens) != qty or len(valid) != qty:
        await update.message.reply_text(
            f"❌ Aap ne {qty} seats select ki thi.\n"
            f"Mujhe {qty} valid emails chahiye (har email nayi line par).\n\n"
            f"Aap ne {len(tokens)} bheji, valid: {len(valid)}.\n"
            f"Dobara {qty} emails bhejein 👇"
        )
        return ASK_EMAILS
    
    context.user_data['emails'] = valid
    
    # Verifying loading bar animation
    msg = await update.message.reply_text(
        "🔄 *Verifying emails...*\n`[▒▒▒▒▒▒▒▒▒▒] 0%`",
        parse_mode=ParseMode.MARKDOWN
    )
    for pct in (10, 30, 55, 75, 90, 100):
        filled = pct // 10
        bar = "█" * filled + "▒" * (10 - filled)
        try:
            await msg.edit_text(
                f"🔄 *Verifying emails...*\n`[{bar}] {pct}%`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await asyncio.sleep(0.4)
    try:
        await msg.edit_text(f"✅ *{qty} emails verified!*", parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass
    
    # Proceed to payment
    pid = context.user_data.get('product_id')
    total = effective_price(pid, product) * qty
    await update.message.reply_text(
        f"*Choose Payment:*\n\n"
        f"Product: {product['name']}\n"
        f"Seats: {qty}\n"
        f"Amount: {fmt(total)} USDT",
        reply_markup=payment_keyboard(pid),
        parse_mode=ParseMode.MARKDOWN
    )
    return PAYMENT_METHOD

# ============== BACK NAVIGATION ==============
async def nav_back(update: Update, context):
    """Handle all Back buttons across the shop flow."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # Back to the product list
    if data == "back_products":
        # Remove the product banner photo so it doesn't linger above the list
        bmid = context.user_data.pop('banner_msg_id', None)
        if bmid:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id, message_id=bmid
                )
            except Exception:
                pass
        text, markup = products_list_markup()
        await query.edit_message_text(
            text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
        )
        return CHOOSING

    # Back to the quantity picker for a specific product
    if data.startswith("back_qty_"):
        pid = data.replace("back_qty_", "")
        product = PRODUCTS.get(pid)
        if not product:
            text, markup = products_list_markup()
            await query.edit_message_text(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
            return CHOOSING
        context.user_data['product_id'] = pid
        context.user_data['product'] = product
        if current_stock(pid, product) <= 0:
            await query.edit_message_text(
                f"{product_card(pid, product)}\n❌ Ye product abhi *out of stock* hai.",
                reply_markup=back_to_products_markup(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return CHOOSING
        await query.edit_message_text(
            quantity_prompt_text(pid, product),
            reply_markup=quantity_keyboard(pid, product),
            parse_mode=ParseMode.MARKDOWN,
        )
        return CONFIRMING_ORDER

    # Back to the payment-method screen (from a payment-instructions screen)
    if data == "back_pay":
        product = context.user_data.get('product')
        pid = context.user_data.get('product_id')
        qty = context.user_data.get('quantity', 1)
        if not product or not pid:
            await query.edit_message_text("❌ Error. /start se shuru karo")
            return ConversationHandler.END
        total = effective_price(pid, product) * qty
        unit_line = f"🪑 Seats: {qty}\n" if product.get('per_seat') else f"📦 Quantity: {qty}\n"
        await query.edit_message_text(
            f"🧾 *Order Summary*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📦 Product: {product['name']}\n"
            f"{unit_line}"
            f"💲 Total: *{fmt(total)} USDT*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Choose Payment 👇",
            reply_markup=payment_keyboard(pid),
            parse_mode=ParseMode.MARKDOWN,
        )
        return PAYMENT_METHOD

    return CHOOSING

# ============== PAYMENT ==============
async def button_callback(update: Update, context):
    """Button handler"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("buy_"):
        pid = query.data.replace("buy_", "")
        product = PRODUCTS[pid]
        context.user_data['product_id'] = pid
        context.user_data['product'] = product
        qty = context.user_data.get('quantity', 1)
        amount = effective_price(pid, product) * qty
        
        seats_line = f"Seats: {qty}\n" if product.get('per_seat') else ""
        await query.edit_message_text(
            f"*Choose Payment:*\n\n"
            f"Product: {product['name']}\n"
            f"{seats_line}"
            f"Amount: {fmt(amount)} USDT",
            reply_markup=payment_keyboard(pid),
            parse_mode=ParseMode.MARKDOWN
        )
        return PAYMENT_METHOD
    
    elif query.data == "pay_bank":
        amount = order_amount(context)
        rate = await get_usdt_pkr_rate()
        text = (
            f"📲 *NayaPay Transfer*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🏦 IBAN:\n`{NAYAPAY_IBAN}`\n\n"
            f"👤 Name:\n{NAYAPAY_NAME}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💵 Amount: {fmt(amount)} USDT\n"
            f"💸 {pkr_line(amount, rate)}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Payment ke baad screenshot send karo 👇"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_pay")]]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data['payment_method'] = 'nayapay'
        return AWAITING_APPROVAL
    
    elif query.data == "pay_binance":
        amount = order_amount(context)
        text = (
            f"🟡 *Binance Pay (USDT)*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"1️⃣ Apni *Binance app* kholein\n"
            f"2️⃣ *Pay → Send* par jayein\n"
            f"3️⃣ Send to UID: {_val(BINANCE_UID)}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💵 Amount: {fmt(amount)} USDT\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Payment ke baad *Order ID* ya screenshot bhejein 👇"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_pay")]]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data['payment_method'] = 'binance'
        return AWAITING_APPROVAL
    
    elif query.data == "pay_wallet":
        user_id = str(query.from_user.id)
        product = context.user_data['product']
        pid = context.user_data.get('product_id')
        qty = context.user_data.get('quantity', 1)
        amount = effective_price(pid, product) * qty
        order_id = new_order_id(user_id)
        
        # Balance check + deduct + order create happen atomically under the lock
        # so two simultaneous purchases can't both spend the same balance.
        async with DATA_LOCK:
            wallets = load_json(WALLETS_FILE)
            if user_id not in wallets or wallets[user_id]['balance'] < amount:
                insufficient = True
            else:
                insufficient = False
                wallets[user_id]['balance'] -= amount
                wallets[user_id]['total_spent'] += amount
                save_json(WALLETS_FILE, wallets)
                orders = load_json(ORDERS_FILE)
                orders[order_id] = {
                    "order_id": order_id,
                    "user_id": int(user_id),
                    "product": product['name'],
                    "quantity": qty,
                    "amount": amount,
                    "emails": context.user_data.get('emails', []),
                    "payment_method": "wallet",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                }
                save_json(ORDERS_FILE, orders)
        
        if insufficient:
            await query.answer("❌ Insufficient balance!", show_alert=True)
            return
        
        # Notify admin
        keyboard = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{order_id}")]
        ]
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 Wallet Order!\n\nOrder: {order_id}\nAmount: {fmt(amount)} USDT{emails_block(orders[order_id])}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        await query.edit_message_text(
            f"✅ Order Placed!\n\nOrder ID: `{order_id}`\n"
            f"Product: {product['name']}\n"
            f"Wallet: -{fmt(amount)} USDT",
            parse_mode=ParseMode.MARKDOWN
        )
        await start_waiting_bar(context, int(user_id), order_id)
        return ConversationHandler.END
    
    elif query.data == "cancel":
        await query.edit_message_text("❌ Cancelled")
        return ConversationHandler.END

async def handle_payment_proof(update: Update, context):
    """Collect a single payment proof (Order ID / reference and/or screenshot),
    notify admin (forwarding the screenshot) and start the user's verifying
    progress bar."""
    user = update.effective_user
    product = context.user_data.get('product')
    
    if not product:
        await update.message.reply_text("❌ Error. /start se shuru karo")
        return ConversationHandler.END
    
    method = context.user_data.get('payment_method', 'unknown')
    msg = update.message
    photo_id = msg.photo[-1].file_id if msg.photo else None
    text = (msg.text or msg.caption or "").strip()
    
    # NayaPay: payment proof MUST be a screenshot. Text-only is not acceptable,
    # so don't create an order / bother the admin — keep asking for the image.
    if method == 'nayapay' and not photo_id:
        await msg.reply_text(
            "❌ Sirf text acceptable nahi hai.\n"
            "📸 NayaPay payment ka *screenshot* bhejein 👇",
            parse_mode=ParseMode.MARKDOWN,
        )
        return AWAITING_APPROVAL
    
    screenshot_id = photo_id
    txid = text
    
    pid = context.user_data.get('product_id')
    qty = context.user_data.get('quantity', 1)
    amount = effective_price(pid, product) * qty
    order_id = new_order_id(user.id)
    async with DATA_LOCK:
        orders = load_json(ORDERS_FILE)
        orders[order_id] = {
            "order_id": order_id,
            "user_id": user.id,
            "product": product['name'],
            "quantity": qty,
            "amount": amount,
            "emails": context.user_data.get('emails', []),
            "payment_method": method,
            "txid": txid,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }
        save_json(ORDERS_FILE, orders)
    
    seats_line = f"Seats: {qty}\n" if product.get('per_seat') else ""
    txid_line = f"TXID: {txid}\n" if txid else ""
    
    # Notify admin: forward screenshot (if any), then a text with the buttons
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_{order_id}")]
    ]
    if screenshot_id:
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID, photo=screenshot_id,
                caption=f"📸 Payment proof — {order_id}"
            )
        except Exception:
            pass
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 New Order!\n\nOrder: {order_id}\nCustomer: {user.first_name}\n"
            f"{seats_line}Amount: {fmt(amount)} USDT\nMethod: {method}\n{txid_line}"
            f"{emails_block(orders[order_id])}"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # Start the slow verifying progress bar for the user
    await start_waiting_bar(context, user.id, order_id)
    
    return ConversationHandler.END

# ============== ADMIN APPROVAL ==============
async def admin_approve(update: Update, context):
    """Admin approve. Seat/email orders auto-deliver; login products ask
    the admin to type the access details which are then sent to the user."""
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.answer("❌ Unauthorized", show_alert=True)
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()

    # Don't let admin start a second delivery while a top-up credit is pending
    if context.user_data.get('credit_topup_id'):
        await query.answer(
            "⚠️ Pehle pending top-up credit finish karein (amount bhejein ya /skip).",
            show_alert=True,
        )
        return ConversationHandler.END

    order_id = query.data.replace("approve_", "")
    
    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        await query.answer("❌ Not found", show_alert=True)
        return ConversationHandler.END
    
    order = orders[order_id]
    # Idempotency: never re-process an order that's already finalized
    # (double-tap / retry would otherwise re-deliver or re-pop inventory).
    if order.get('status') in ('delivered', 'rejected'):
        await query.answer(f"⚠️ Order {order_id} already {order['status']}.", show_alert=True)
        return ConversationHandler.END
    pid = find_pid(order['product'])
    product = PRODUCTS.get(pid) if pid else None
    emails = order.get('emails') or []
    is_seat = bool(product and product.get('per_seat'))
    qty = int(order.get('quantity', 1) or 1)
    
    # Seat / email products: nothing to type, auto-deliver + complete bar
    if is_seat and emails:
        async with DATA_LOCK:
            orders = load_json(ORDERS_FILE)
            order = orders.get(order_id, order)
            if order.get('status') in ('delivered', 'rejected'):
                already = True
            else:
                already = False
                order['status'] = 'delivered'
                decrement_stock(order)
                orders[order_id] = order
                save_json(ORDERS_FILE, orders)
        if already:
            await query.edit_message_text(f"✅ Order {order_id} pehle hi process ho chuka.")
            return ConversationHandler.END
        await complete_waiting_bar(
            context, order,
            extra_message=(
                f"✅ All {len(emails)} emails added!\n"
                f"📧 Check your mail (inbox & spam) — invite aapke email par bhej diya gaya hai."
            ),
        )
        await query.edit_message_text(f"✅ Order {order_id} delivered!")
        return ConversationHandler.END
    
    # Account products: auto-deliver stored credentials from inventory.
    # Check-and-pop happen together under the lock so two approvals can't
    # both see stock and grab the same accounts.
    if product and not is_seat:
        async with INVENTORY_LOCK:
            available = len(get_inventory().get(str(pid), []))
            creds = pop_credentials(pid, qty) if available >= qty else []
            if creds:
                orders = load_json(ORDERS_FILE)
                order = orders.get(order_id, order)
                order['status'] = 'delivered'
                orders[order_id] = order
                save_json(ORDERS_FILE, orders)
            remaining = len(get_inventory().get(str(pid), []))
        if creds:
            lines = "\n".join(f"{i}) {c}" for i, c in enumerate(creds, 1))
            await complete_waiting_bar(
                context, order,
                extra_message=f"🔐 Aapke account details:\n\n{lines}",
            )
            await query.edit_message_text(
                f"✅ Order {order_id} delivered!\n"
                f"📦 {qty} account(s) auto-sent. Baqi stock: {remaining}"
            )
            return ConversationHandler.END
        # Not enough stored accounts -> tell admin, let them type manually
        await query.answer(
            f"⚠️ Stock kam hai ({available}/{qty}). Manually details type karein.",
            show_alert=True,
        )
    
    # Fallback: let admin optionally type a message (login/pass/anything)
    context.user_data['deliver_order_id'] = order_id
    await query.edit_message_text(
        f"✅ Approving Order {order_id}\n"
        f"Product: {order['product']}\n\n"
        f"📝 Customer ko bhejne ke liye *message* type karein\n"
        f"(email, password, link — jo bhi access dena hai).\n\n"
        f"Ye message approve-message ke saath customer ko bhej diya jayega.\n"
        f"Agar sirf approve karna hai (koi message nahi) to /skip dabayein.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADMIN_DELIVER

async def admin_send_credentials(update: Update, context):
    """Admin typed a message -> approve + forward it to the customer."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    
    order_id = context.user_data.get('deliver_order_id')
    details = update.message.text
    async with DATA_LOCK:
        orders = load_json(ORDERS_FILE)
        order = orders.get(order_id) if order_id else None
        if order:
            order['status'] = 'delivered'
            decrement_stock(order)
            orders[order_id] = order
            save_json(ORDERS_FILE, orders)
    
    if not order:
        await update.message.reply_text("❌ Order nahi mila. Cancelled.")
        context.user_data.pop('deliver_order_id', None)
        return ConversationHandler.END
    # Note: the typed message is forwarded to the customer only, never stored on disk.
    
    await complete_waiting_bar(context, order, extra_message=details)
    await update.message.reply_text(f"✅ Order {order_id} approved + message sent!")
    context.user_data.pop('deliver_order_id', None)
    return ConversationHandler.END

async def admin_skip_delivery(update: Update, context):
    """Approve the order without sending any extra message."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    
    order_id = context.user_data.get('deliver_order_id')
    async with DATA_LOCK:
        orders = load_json(ORDERS_FILE)
        order = orders.get(order_id) if order_id else None
        if order:
            order['status'] = 'delivered'
            decrement_stock(order)
            orders[order_id] = order
            save_json(ORDERS_FILE, orders)
    
    if order:
        await complete_waiting_bar(context, order, extra_message=None)
        await update.message.reply_text(f"✅ Order {order_id} approved (no extra message).")
    else:
        await update.message.reply_text("❌ Order nahi mila. Cancelled.")
    
    context.user_data.pop('deliver_order_id', None)
    return ConversationHandler.END

async def admin_reject(update: Update, context):
    """Admin reject -> stop the bar and tell the user."""
    if update.effective_user.id != ADMIN_ID:
        return
    
    query = update.callback_query
    await query.answer()
    order_id = query.data.replace("reject_", "")
    
    async with DATA_LOCK:
        orders = load_json(ORDERS_FILE)
        order = orders.get(order_id)
        if order:
            order['status'] = 'rejected'
            orders[order_id] = order
            save_json(ORDERS_FILE, orders)
    if not order:
        await query.answer("❌ Not found", show_alert=True)
        return
    
    await fail_waiting_bar(
        context, order,
        f"❌ Order {order_id} rejected.\n\nRefund processing..."
    )
    await query.edit_message_text(f"❌ Rejected")

# ============== ADMIN STOCK ==============
def _stock_overview():
    """Admin view of every product's current stock."""
    lines = []
    for pid, p in PRODUCTS.items():
        kind = "seats" if p.get('per_seat') else "accounts"
        lines.append(f"`{pid}` — {p['name']}\n   📦 {current_stock(pid, p)} {kind}")
    return "\n".join(lines)

async def admin_stock_view(update: Update, context):
    """/stock — show current stock for all products (admin only)."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    await update.message.reply_text(
        f"📦 *Current Stock*\n\n{_stock_overview()}",
        parse_mode=ParseMode.MARKDOWN,
    )

async def admin_viewstock(update: Update, context):
    """/viewstock <pid> — admin: kisi product ke saved account credentials dekhe."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    args = context.args
    if not args:
        await update.message.reply_text(
            f"👁️ *Saved Accounts Dekhein*\n\n{_stock_overview()}\n\n"
            f"Kis product ke accounts dekhne hain?\n"
            f"Usage: `/viewstock <product_number>`\nMisaal: `/viewstock 1`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    pid = args[0].strip()
    product = PRODUCTS.get(pid)
    if not product:
        await update.message.reply_text("❌ Ye product number nahi mila.")
        return
    if product.get('per_seat'):
        await update.message.reply_text(
            f"ℹ️ *{product['name']}* ek seat product hai (email invite se deliver hota hai).\n"
            f"Iska account stock nahi hota.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    creds = get_inventory().get(pid, [])
    if not creds:
        await update.message.reply_text(
            f"📭 *{product['name']}* mein abhi koi account save nahi.\n"
            f"/addstock se add karein.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    # Plain text (no markdown) so codes/links with special chars don't break;
    # chunked to respect Telegram's ~4096-char message limit.
    chunk = f"👁️ {product['name']} — {len(creds)} saved account(s):\n\n"
    for i, c in enumerate(creds, 1):
        line = f"{i}. {c}\n"
        if len(chunk) + len(line) > 3500:
            await update.message.reply_text(chunk)
            chunk = ""
        chunk += line
    if chunk.strip():
        await update.message.reply_text(chunk)
    await update.message.reply_text("⚠️ Ye list confidential hai — kisi ke saath share na karein.")

async def admin_addstock_start(update: Update, context):
    """/addstock — admin loads ready account credentials into a product."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return ConversationHandler.END
    await update.message.reply_text(
        f"➕ *Add Stock*\n\n{_stock_overview()}\n\n"
        f"Kis product mein accounts add karne hain? Product number bhejein 👇\n"
        f"(band karne ke liye /cancel)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_STOCK_PID

async def admin_addstock_pid(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    pid = (update.message.text or "").strip()
    product = PRODUCTS.get(pid)
    if not product:
        await update.message.reply_text("❌ Ye product number nahi mila. Dobara bhejein 👇")
        return ADMIN_STOCK_PID
    if product.get('per_seat'):
        await update.message.reply_text(
            "❌ Ye seat product hai (email invite se deliver hota hai), iska account stock nahi hota.\n"
            "Kisi account product ka number bhejein 👇"
        )
        return ADMIN_STOCK_PID
    context.user_data['stock_pid'] = pid
    await update.message.reply_text(
        f"✅ *{product['name']}*\n\n"
        f"Ab accounts paste karein — *har account nayi line par*.\n"
        f"Misaal:\n`email@gmail.com | password123`\n\n"
        f"Ek message mein jitne chahein bhej saktay hain 👇",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_STOCK_ADD

async def admin_addstock_save(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    pid = context.user_data.get('stock_pid')
    product = PRODUCTS.get(pid)
    if not pid or not product:
        await update.message.reply_text("❌ Error. /addstock se dobara shuru karein.")
        return ConversationHandler.END
    creds = [ln.strip() for ln in (update.message.text or "").splitlines() if ln.strip()]
    if not creds:
        await update.message.reply_text("❌ Koi account nahi mila. Har account nayi line par bhejein 👇")
        return ADMIN_STOCK_ADD
    async with INVENTORY_LOCK:
        total = add_credentials(pid, creds)
    context.user_data.pop('stock_pid', None)
    await notify_channel(
        context,
        f"📦 *Stock Added!*\n\n"
        f"🛒 {product['name']}\n"
        f"➕ {len(creds)} naye account(s)\n"
        f"📊 Ab total stock: {total}",
    )
    await update.message.reply_text(
        f"✅ {len(creds)} account(s) add ho gaye!\n"
        f"📦 *{product['name']}* ka naya stock: *{total}*\n\n"
        f"📣 Sab users ko notification bheji ja rahi hai...",
        parse_mode=ParseMode.MARKDOWN,
    )
    # Notify every known user that this product is back in stock
    sent, failed = await broadcast_restock(context, product, len(creds), total)
    await update.message.reply_text(
        f"📣 Notification bhej di gayi!\n"
        f"✅ {sent} users ko mili"
        + (f"\n⚠️ {failed} fail (bot block kiya hua)" if failed else "")
    )
    return ConversationHandler.END

def all_known_user_ids():
    """Every Telegram user id the bot has ever seen — across wallets, referrals,
    topups and orders. Broadcasts use this so no known user is missed (a user who
    bought/topped-up but somehow isn't in wallets still gets reached). Returns a set
    of numeric id strings. NOTE: Telegram only lets a bot message users who have
    started a chat with it; unknown people can never be reached."""
    ids = set()
    for uid in load_json(WALLETS_FILE).keys():
        ids.add(str(uid))
    for uid, info in load_json(REFERRALS_FILE).items():
        ids.add(str(uid))
        for r in (info.get("referred") or []):
            ids.add(str(r))
    for t in load_json(TOPUPS_FILE).values():
        if t.get("user_id") is not None:
            ids.add(str(t["user_id"]))
    for o in load_json(ORDERS_FILE).values():
        if o.get("user_id") is not None:
            ids.add(str(o["user_id"]))
    return {i for i in ids if i.isdigit()}

def time_left_text(until):
    """Human remaining-time string for a sale, e.g. '2 ghante 30 min'."""
    secs = max(int(until - time.time()), 0)
    h, m = secs // 3600, (secs % 3600) // 60
    if h and m:
        return f"{h} ghante {m} min"
    if h:
        return f"{h} ghante"
    return f"{m} min"

async def broadcast_restock(context, product, added, total):
    """Tell all known users a product just got restocked. Returns (sent, failed)."""
    text = (
        f"🎉 *Stock Update!*\n\n"
        f"🛒 *{product['name']}*\n"
        f"➕ {added} naye add huye — ab *{total}* available!\n"
        f"💲 Price: *{fmt(product['price'])} USDT*\n\n"
        f"Jaldi order karein 👇 /start"
    )
    sent = failed = 0
    for uid in all_known_user_ids():
        try:
            await context.bot.send_message(
                chat_id=int(uid), text=text, parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    return sent, failed

async def broadcast_sale(context, items, time_text, reminder=False):
    """Notify all known users about a flash sale (one or many products in a single
    message), or re-send it as a reminder. `items` is a list of
    (product, base, sale_price) tuples. Returns (sent, failed)."""
    if reminder:
        header = "⏰ *SALE REMINDER!* ⏰"
        time_line = f"⏳ Sale khatam hone mein sirf *{time_text}* baqi!"
    else:
        header = "🔥🔥 *FLASH SALE!* 🔥🔥"
        time_line = f"⏳ Sirf *{time_text}* ke liye!"
    blocks = []
    for product, base, sale_price in items:
        blocks.append(
            f"🛒 *{product['name']}*\n"
            f"💰 {_strike(fmt(base) + ' USDT')} ➡️ *{fmt(sale_price)} USDT* 🎉"
        )
    text = (
        f"{header}\n\n"
        + "\n\n".join(blocks)
        + f"\n\n{time_line}\n\n"
        + "Jaldi order karein, offer khatam hone se pehle 👇 /start"
    )
    sent = failed = 0
    for uid in all_known_user_ids():
        try:
            await context.bot.send_message(
                chat_id=int(uid), text=text, parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    return sent, failed

async def broadcast_rewards(context, time_text):
    """Announce a just-started referral reward campaign to all known users.
    Returns (sent, failed)."""
    text = (
        "🎁🎉 *REFERRAL REWARD OFFER ON!* 🎉🎁\n\n"
        "Apne doston ko bot refer karein aur *MUFT rewards* jeetein!\n\n"
        "🏆 *5 referrals* = 1 reward\n"
        "🏆 *10 referrals* = 1 aur reward\n\n"
        f"⏳ Offer sirf *{time_text}* ke liye!\n\n"
        "Apna referral link lene ke liye 👉 /referral\n"
        "Abhi shuru karein 👇 /start"
    )
    sent = failed = 0
    for uid in all_known_user_ids():
        try:
            await context.bot.send_message(
                chat_id=int(uid), text=text, parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    return sent, failed

async def notify_channel_sale(context, items, time_text, reminder=False):
    """Post a flash-sale announcement to the alerts channel with a per-product
    'Buy Now' deep-link button (each opens that product inside the bot). `items` is a
    list of (pid, product, base, sale_price) tuples. Best-effort; no-op without a
    configured channel."""
    if not CHANNEL_ID:
        return
    header = "⏰ *SALE REMINDER!* ⏰" if reminder else "🔥🔥 *FLASH SALE!* 🔥🔥"
    time_line = (
        f"⏳ Khatam hone mein *{time_text}* baqi!" if reminder
        else f"⏳ Sirf *{time_text}* ke liye!"
    )
    blocks = [
        f"🛒 *{product['name']}*\n"
        f"💰 {_strike(fmt(base) + ' USDT')} ➡️ *{fmt(sale_price)} USDT* 🎉"
        for pid, product, base, sale_price in items
    ]
    text = f"{header}\n\n" + "\n\n".join(blocks) + f"\n\n{time_line}\n\n👇 Abhi kharidein:"
    reply_markup = None
    try:
        username = await get_bot_username(context)
        if username:
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🛒 {product['name']}"[:60],
                    url=f"https://t.me/{username}?start=buy_{pid}",
                )]
                for pid, product, base, sale_price in items
            ])
    except Exception:
        pass
    # Single-product sale → include its banner; multi-product → text + buttons.
    sent = None
    if len(items) == 1:
        sent = await send_banner(context, CHANNEL_ID, items[0][0], caption=text, reply_markup=reply_markup)
    if not sent:
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID, text=text,
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logging.warning(f"notify_channel_sale failed: {e}")

def parse_pids(raw):
    """Split a product-id argument that may be comma/space separated, e.g.
    '1,2,3' or '1, 2, 3'. Returns a de-duplicated list preserving order."""
    parts = [p.strip() for p in raw.replace(" ", ",").split(",")]
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out

async def admin_sale(update: Update, context):
    """Admin: start a timed flash sale on one OR many products at once.
    Usage: /sale <product_ids> <sale_price|N%> <hours>
      • /sale 2 15 3        → product 2 ko 15 USDT, 3 ghante
      • /sale 1,2,3 20% 5   → products 1,2,3 par 20% off, 5 ghante
      • /sale 1,2 10 4      → 1 aur 2 dono ko 10 USDT (har ek ki base price se kam honi chahiye)"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Usage: /sale <product_ids> <sale_price ya N%> <hours>\n\n"
            "Misaalein:\n"
            "• /sale 2 15 3  → 1 product, fixed price\n"
            "• /sale 1,2,3 20% 5  → kai products, 20% off\n"
            "• /sale 1 2 3 20% 5  → spaces bhi chalte hain\n"
            "• /sale 1,2 10 4  → kai products, fixed price"
        )
        return

    pids = parse_pids(" ".join(args[:-2]))
    bad = [p for p in pids if p not in PRODUCTS]
    if bad:
        await update.message.reply_text(f"❌ Yeh product(s) nahi mile: {', '.join(bad)}")
        return

    price_arg = args[-2].strip()
    is_pct = price_arg.endswith("%")
    try:
        price_val = float(price_arg[:-1] if is_pct else price_arg)
        hours = float(args[-1])
    except ValueError:
        await update.message.reply_text("❌ Price/percentage aur hours number hone chahiye.")
        return

    if is_pct and not (0 < price_val < 100):
        await update.message.reply_text("❌ Percentage 0 se zyada aur 100 se kam hona chahiye. Misaal: 20%")
        return
    if not (0 < hours <= 168):
        await update.message.reply_text("❌ Hours 0 se zyada aur 168 (7 din) se kam hona chahiye.")
        return

    items = []
    errors = []
    for pid in pids:
        product = PRODUCTS[pid]
        base = product.get("price", 0)
        if is_pct:
            sale_price = round(base * (1 - price_val / 100), 2)
        else:
            sale_price = price_val
        if not (0 < sale_price < base):
            errors.append(f"• {product['name']} (base {fmt(base)} USDT): sale price {fmt(sale_price)} theek nahi")
            continue
        items.append((pid, product, base, sale_price))

    if not items:
        await update.message.reply_text(
            "❌ Koi sale set nahi hui. Sale price har product ki base price se kam honi chahiye:\n"
            + "\n".join(errors)
        )
        return

    until = time.time() + hours * 3600
    async with DATA_LOCK:
        sales = load_json(SALES_FILE)
        for pid, product, base, sale_price in items:
            sales[pid] = {
                "sale_price": sale_price,
                "original_price": base,
                "until": until,
            }
        save_json(SALES_FILE, sales)

    sent, failed = await broadcast_sale(
        context,
        [(product, base, sale_price) for pid, product, base, sale_price in items],
        f"{fmt(hours)} ghante",
    )
    await notify_channel_sale(context, items, f"{fmt(hours)} ghante")
    lines = "\n".join(
        f"🛒 {product['name']}: {fmt(base)} ➡️ {fmt(sale_price)} USDT"
        for pid, product, base, sale_price in items
    )
    skipped = ("\n\n⚠️ Skip hue:\n" + "\n".join(errors)) if errors else ""
    await update.message.reply_text(
        f"✅ *Flash Sale shuru!* ({len(items)} product)\n\n"
        f"{lines}\n"
        f"⏳ {fmt(hours)} ghante (phir khud purana rate bahaal)\n\n"
        f"📣 Notification: {sent} users ko mili"
        + (f"\n⚠️ {failed} fail (bot block kiya hua)" if failed else "")
        + skipped,
        parse_mode=ParseMode.MARKDOWN,
    )

async def admin_multisale(update: Update, context):
    """Admin: ek hi command me alag-alag products ki alag-alag sale price set karo,
    sab par ek hi (shared) duration.
    Usage: /multisale <pid=price> <pid=price> ... <hours>
      • /multisale 2=7 5=2 5        → product 2 ko 7 USDT, product 5 ko 2 USDT, dono 5 ghante
      • /multisale 1:20 3:15 2:9 12 → 1->20, 3->15, 2->9, 12 ghante (':' bhi chalta hai)"""
    if update.effective_user.id != ADMIN_ID:
        return

    # Flatten args: spaces ya commas se alag tokens, e.g. "2=7,5=2 5"
    tokens = []
    for a in context.args:
        for t in a.replace(",", " ").split():
            if t.strip():
                tokens.append(t.strip())

    usage = (
        "❌ Usage: /multisale <pid=price> <pid=price> ... <hours>\n\n"
        "Misaalein:\n"
        "• /multisale 2=7 5=2 5  → 2 ko 7 USDT, 5 ko 2 USDT, dono 5 ghante\n"
        "• /multisale 1:20 3:15 12  → alag-alag price, 12 ghante"
    )
    if len(tokens) < 2:
        await update.message.reply_text(usage)
        return

    # Aakhri token = hours (price-pair NAHI hona chahiye)
    hours_tok = tokens[-1]
    if ("=" in hours_tok) or (":" in hours_tok):
        await update.message.reply_text(
            "❌ Aakhri value sirf hours honi chahiye (jaise 5).\n\n" + usage
        )
        return
    try:
        hours = float(hours_tok)
    except ValueError:
        await update.message.reply_text("❌ Hours number hona chahiye. Misaal: /multisale 2=7 5=2 5")
        return
    if not (0 < hours <= 168):
        await update.message.reply_text("❌ Hours 0 se zyada aur 168 (7 din) se kam hona chahiye.")
        return

    items = []
    errors = []
    seen = set()
    for tok in tokens[:-1]:
        sep = "=" if "=" in tok else (":" if ":" in tok else None)
        if not sep:
            errors.append(f"• '{tok}' theek nahi (format: pid=price, jaise 2=7)")
            continue
        pid, _, price_part = tok.partition(sep)
        pid = pid.strip()
        price_part = price_part.strip()
        if not pid or pid in seen:
            continue
        if pid not in PRODUCTS:
            errors.append(f"• Product '{pid}' nahi mila")
            continue
        try:
            sale_price = float(price_part)
        except ValueError:
            errors.append(f"• '{tok}': price number hona chahiye")
            continue
        product = PRODUCTS[pid]
        base = product.get("price", 0)
        if not (0 < sale_price < base):
            errors.append(
                f"• {product['name']} (base {fmt(base)} USDT): sale price {fmt(sale_price)} theek nahi (0 se base ke darmiyan honi chahiye)"
            )
            continue
        seen.add(pid)
        items.append((pid, product, base, sale_price))

    if not items:
        await update.message.reply_text(
            "❌ Koi sale set nahi hui:\n" + ("\n".join(errors) if errors else usage)
        )
        return

    until = time.time() + hours * 3600
    async with DATA_LOCK:
        sales = load_json(SALES_FILE)
        for pid, product, base, sale_price in items:
            sales[pid] = {
                "sale_price": sale_price,
                "original_price": base,
                "until": until,
            }
        save_json(SALES_FILE, sales)

    sent, failed = await broadcast_sale(
        context,
        [(product, base, sale_price) for pid, product, base, sale_price in items],
        f"{fmt(hours)} ghante",
    )
    await notify_channel_sale(context, items, f"{fmt(hours)} ghante")
    lines = "\n".join(
        f"🛒 {product['name']}: {fmt(base)} ➡️ {fmt(sale_price)} USDT"
        for pid, product, base, sale_price in items
    )
    skipped = ("\n\n⚠️ Skip hue:\n" + "\n".join(errors)) if errors else ""
    await update.message.reply_text(
        f"✅ *Flash Sale shuru!* ({len(items)} product, alag-alag price)\n\n"
        f"{lines}\n"
        f"⏳ {fmt(hours)} ghante (phir khud purana rate bahaal)\n\n"
        f"📣 Notification: {sent} users ko mili"
        + (f"\n⚠️ {failed} fail (bot block kiya hua)" if failed else "")
        + skipped,
        parse_mode=ParseMode.MARKDOWN,
    )

async def admin_endsale(update: Update, context):
    """Admin: end a flash sale early on one OR many products.
    Usage: /endsale <product_ids>  (e.g. /endsale 2  ya  /endsale 1,2,3)"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ Usage: /endsale <product_ids>\nMisaal: /endsale 2  ya  /endsale 1,2,3"
        )
        return
    pids = parse_pids(" ".join(args))
    ended, none = [], []
    async with DATA_LOCK:
        sales = load_json(SALES_FILE)
        for pid in pids:
            if pid in sales:
                del sales[pid]
                ended.append(pid)
            else:
                none.append(pid)
        if ended:
            save_json(SALES_FILE, sales)
    msg = ""
    if ended:
        msg += f"✅ Sale khatam (purana rate bahaal): {', '.join(ended)}\n"
    if none:
        msg += f"ℹ️ In par koi active sale nahi thi: {', '.join(none)}"
    await update.message.reply_text(msg.strip() or "ℹ️ Kuch nahi mila.")

async def admin_remindsale(update: Update, context):
    """Admin: re-send running sale notifications as a reminder, for one OR many
    products in a single message (use as many times as you like while sales are
    active). Usage: /remindsale <product_ids>  (e.g. /remindsale 2  ya  /remindsale 1,2,3)"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ Usage: /remindsale <product_ids>\nMisaal: /remindsale 2  ya  /remindsale 1,2,3"
        )
        return
    pids = parse_pids(" ".join(args))
    items, channel_items, latest_until, inactive = [], [], 0, []
    for pid in pids:
        if pid not in PRODUCTS:
            inactive.append(pid)
            continue
        s = active_sale(pid)
        if not s:
            inactive.append(pid)
            continue
        product = PRODUCTS[pid]
        base = s.get("original_price", product.get("price", 0))
        items.append((product, base, s["sale_price"]))
        channel_items.append((pid, product, base, s["sale_price"]))
        latest_until = max(latest_until, s["until"])

    if not items:
        await update.message.reply_text(
            "ℹ️ In par abhi koi active sale nahi (ya khatam ho chuki): "
            f"{', '.join(pids)}\nPehle /sale se sale lagayein."
        )
        return

    left = time_left_text(latest_until)
    sent, failed = await broadcast_sale(context, items, left, reminder=True)
    await notify_channel_sale(context, channel_items, left, reminder=True)
    lines = "\n".join(f"🛒 {p['name']} — {fmt(sp)} USDT" for p, b, sp in items)
    skipped = ("\n\n⚠️ Sale active nahi (skip): " + ", ".join(inactive)) if inactive else ""
    await update.message.reply_text(
        f"📣 *Reminder bhej diya!* ({len(items)} product)\n\n"
        f"{lines}\n"
        f"⏳ Baqi waqt: {left}\n\n"
        f"✅ {sent} users ko mila"
        + (f"\n⚠️ {failed} fail (bot block kiya hua)" if failed else "")
        + skipped,
        parse_mode=ParseMode.MARKDOWN,
    )

async def admin_addstock_cancel(update: Update, context):
    context.user_data.pop('stock_pid', None)
    await update.message.reply_text("❌ Stock add cancel.")
    return ConversationHandler.END

async def admin_rmstock_start(update: Update, context):
    """/removestock — admin deletes account credentials from a product."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return ConversationHandler.END
    await update.message.reply_text(
        f"🗑️ *Remove Stock*\n\n{_stock_overview()}\n\n"
        f"Kis product se stock remove karna hai? Product number bhejein 👇\n"
        f"(band karne ke liye /cancel)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_RMSTOCK_PID

async def admin_rmstock_pid(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    pid = (update.message.text or "").strip()
    product = PRODUCTS.get(pid)
    if not product:
        await update.message.reply_text("❌ Ye product number nahi mila. Dobara bhejein 👇")
        return ADMIN_RMSTOCK_PID
    if product.get('per_seat'):
        await update.message.reply_text(
            "❌ Ye seat product hai, iska account stock nahi hota.\n"
            "Kisi account product ka number bhejein 👇"
        )
        return ADMIN_RMSTOCK_PID
    context.user_data['rmstock_pid'] = pid
    stock = current_stock(pid, product)
    await update.message.reply_text(
        f"✅ *{product['name']}*\n"
        f"📦 Abhi stock: *{stock}*\n\n"
        f"Kitne remove karne hain? Number bhejein (jaise `5`)\n"
        f"Saara stock khatam karne ke liye `all` likhein 👇",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_RMSTOCK_QTY

async def admin_rmstock_apply(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    pid = context.user_data.get('rmstock_pid')
    product = PRODUCTS.get(pid)
    if not pid or not product:
        await update.message.reply_text("❌ Error. /removestock se dobara shuru karein.")
        return ConversationHandler.END
    choice = (update.message.text or "").strip().lower()
    if choice not in ("all", "sab", "clear") and (not choice.isdigit() or int(choice) <= 0):
        await update.message.reply_text(
            "❌ Sahi number bhejein (jaise `5`) ya `all` likhein 👇"
        )
        return ADMIN_RMSTOCK_QTY
    async with INVENTORY_LOCK:
        if choice in ("all", "sab", "clear"):
            removed = clear_credentials(pid)
            remaining = 0
        else:
            removed, remaining = remove_credentials(pid, int(choice))
    context.user_data.pop('rmstock_pid', None)
    await update.message.reply_text(
        f"🗑️ {removed} account(s) remove ho gaye!\n"
        f"📦 *{product['name']}* ka naya stock: *{remaining}*",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

async def admin_rmstock_cancel(update: Update, context):
    context.user_data.pop('rmstock_pid', None)
    await update.message.reply_text("❌ Remove stock cancel.")
    return ConversationHandler.END

# ============== USER FEATURES ==============
async def show_orders(update: Update, context):
    """Show user orders"""
    user_id = str(update.effective_user.id)
    orders = load_json(ORDERS_FILE)
    user_orders = {oid: o for oid, o in orders.items() if str(o.get('user_id')) == user_id}
    
    if not user_orders:
        await update.message.reply_text("🪑 No orders yet!")
        return CHOOSING
    
    text = "🪑 *Your Orders:*\n\n"
    for order_id, order in user_orders.items():
        emoji = "✅" if order['status'] == "delivered" else "⏳" if order['status'] == "pending" else "❌"
        text += f"{emoji} {order['product']}\n   {fmt(order['amount'])} USDT | {order['status'].upper()}\n\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return CHOOSING

async def get_bot_username(context):
    """Return the bot's @username (cached on the Bot object after startup)."""
    if getattr(context.bot, "username", None):
        return context.bot.username
    me = await context.bot.get_me()
    return me.username

async def show_referral(update: Update, context):
    """Show the user's personal referral link (no code) with a Share button."""
    user_id = str(update.effective_user.id)
    async with DATA_LOCK:
        referrals = load_json(REFERRALS_FILE)
        if user_id not in referrals:
            referrals[user_id] = {"code": f"REF{user_id}", "count": 0, "earnings": 0, "referred": []}
            save_json(REFERRALS_FILE, referrals)
        ref = referrals[user_id]
    username = await get_bot_username(context)
    link = f"https://t.me/{username}?start=ref_{user_id}"

    if rewards_active():
        reward_line = (
            f"🎁 *Reward Offer LIVE!* 🔥\n"
            f"5 referrals par ek reward, 10 par dusra reward!\n"
            f"(Har user ke liye max 2 rewards)\n"
            f"⏳ Offer khatam hone mein: {reward_time_left()}\n"
            f"━━━━━━━━━━━━━━━\n"
        )
    else:
        reward_line = ""

    text = (
        f"👥 *Referral Program* 👥\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 *Aapka Referral Link* (tap to copy):\n"
        f"`{link}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Total Referrals: *{ref['count']}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{reward_line}"
        f"📤 Apna link doston ke saath share karein 🚀"
    )
    
    share_text = "🔥 CHEAP AI TOOLS — Premium AI Tools sab se best price par! Abhi join karein 👇"
    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}"
    keyboard = [[InlineKeyboardButton("📤 Share Link", url=share_url)]]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    return CHOOSING

async def show_profile(update: Update, context):
    """Show user's profile: ID, balance, total spent, referral count."""
    user = update.effective_user
    user_id = str(user.id)
    async with DATA_LOCK:
        wallets = load_json(WALLETS_FILE)
        if user_id not in wallets:
            wallets[user_id] = {"balance": 0, "total_spent": 0}
            save_json(WALLETS_FILE, wallets)
        wallet = wallets[user_id]
        referrals = load_json(REFERRALS_FILE)
        ref_count = referrals.get(user_id, {}).get("count", 0)

    text = (
        f"👤 *Your Profile* 👤\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"👋 Name: {escape_markdown(user.first_name or '', version=1)}\n\n"
        f"💰 Wallet Balance: {fmt(wallet['balance'])} USDT\n"
        f"💸 Total Spent: {fmt(wallet['total_spent'])} USDT\n"
        f"👥 Total Referrals: {ref_count}\n\n"
        f"💳 Wallet se instant checkout karein!"
    )
    keyboard = [
        [InlineKeyboardButton("💵 Top Up Wallet", callback_data="tp_open")],
        [InlineKeyboardButton("🛍️ Browse Products", callback_data="back_products")],
    ]
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )
    return CHOOSING

async def show_wallet(update: Update, context):
    """Show wallet"""
    user_id = str(update.effective_user.id)
    async with DATA_LOCK:
        wallets = load_json(WALLETS_FILE)
        if user_id not in wallets:
            wallets[user_id] = {"balance": 0, "total_spent": 0}
            save_json(WALLETS_FILE, wallets)
        wallet = wallets[user_id]
    
    text = (
        f"💰 *Your Wallet* 💰\n\n"
        f"Balance: {fmt(wallet['balance'])} USDT\n"
        f"Total Spent: {fmt(wallet['total_spent'])} USDT\n\n"
        f"💳 Use for instant checkout!"
    )
    keyboard = [[InlineKeyboardButton("💵 Top Up Wallet", callback_data="tp_open")]]
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )
    return CHOOSING

# ============== WALLET TOP-UP ==============
def _topup_provider_keyboard():
    """Inline keyboard listing every configured top-up provider."""
    rows = [
        [InlineKeyboardButton(m["label"], callback_data=f"tpm_{key}")]
        for key, m in TOPUP_METHODS.items()
    ]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="tp_cancel")])
    return InlineKeyboardMarkup(rows)

async def show_topup(update: Update, context):
    """Entry from the reply-keyboard 'Top Up' button: pick a provider."""
    await update.message.reply_text(
        "💵 *Top Up Your Wallet*\n\n"
        "Payment provider select karein 👇",
        reply_markup=_topup_provider_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return TOPUP_METHOD

async def topup_open(update: Update, context):
    """Entry from the inline 'Top Up Wallet' button inside the Wallet view."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "💵 *Top Up Your Wallet*\n\n"
        "Payment provider select karein 👇",
        reply_markup=_topup_provider_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return TOPUP_METHOD

async def topup_cancel(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Top Up cancelled")
    return ConversationHandler.END

async def topup_select(update: Update, context):
    """Provider chosen -> show instructions and wait for the reference/proof."""
    query = update.callback_query
    await query.answer()
    key = query.data.replace("tpm_", "")
    method = TOPUP_METHODS.get(key)
    if not method:
        await query.answer("❌ Invalid provider", show_alert=True)
        return TOPUP_METHOD

    context.user_data['topup_method'] = key
    rate_line = ""
    if key == "nayapay":
        rate = await get_usdt_pkr_rate()
        rate_line = f"💱 Rate: 1 USDT = PKR {rate:,.2f}\n"
    text = (
        f"{method['title']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{method['steps']()}\n"
        f"{rate_line}"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💸 Payment ke baad:\n{method['ref']}\n\n"
        f"📩 Wo *Order ID / Reference* yahan bhejein "
        f"(screenshot bhi bhej sakte hain).\n"
        f"⏳ Admin verify kar ke aapke wallet mein balance add kar dega."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    return TOPUP_PROOF

async def handle_topup_proof(update: Update, context):
    """User sent a top-up reference (text and/or screenshot). Notify admin
    and start the verifying progress bar."""
    msg = update.message
    text = (msg.text or msg.caption or "").strip()

    user = update.effective_user
    key = context.user_data.get('topup_method')
    method = TOPUP_METHODS.get(key)
    if not method:
        await msg.reply_text("❌ Error. /start se dobara shuru karein.")
        return ConversationHandler.END

    photo_id = msg.photo[-1].file_id if msg.photo else None
    if not text and not photo_id:
        await msg.reply_text("❌ Order ID / TXID bhejein (ya screenshot).")
        return TOPUP_PROOF

    topup_id = new_order_id(user.id).replace("ORD-", "TOP-")
    async with DATA_LOCK:
        topups = load_json(TOPUPS_FILE)
        topups[topup_id] = {
            "topup_id": topup_id,
            "user_id": user.id,
            "method": method['label'],
            "reference": text,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }
        save_json(TOPUPS_FILE, topups)

    # Notify admin (forward screenshot if any) with approve/reject buttons
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"tpok_{topup_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"tpno_{topup_id}")]
    ]
    if photo_id:
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID, photo=photo_id,
                caption=f"💵 Top-up proof — {topup_id}"
            )
        except Exception:
            pass
    ref_line = f"Reference: {text}\n" if text else ""
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"💵 New Top-Up Request!\n\n"
            f"ID: {topup_id}\nCustomer: {user.first_name}\n"
            f"Method: {method['label']}\n{ref_line}"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    await start_waiting_bar(context, user.id, topup_id)
    return ConversationHandler.END

async def topup_approve(update: Update, context):
    """Admin approves a top-up -> ask how much USDT to credit."""
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.answer("❌ Unauthorized", show_alert=True)
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    # Don't let admin start a top-up credit while an order delivery is pending
    if context.user_data.get('deliver_order_id'):
        await query.answer(
            "⚠️ Pehle pending order delivery finish karein (message bhejein ya /skip).",
            show_alert=True,
        )
        return ConversationHandler.END

    topup_id = query.data.replace("tpok_", "")
    topups = load_json(TOPUPS_FILE)
    if topup_id not in topups:
        await query.answer("❌ Not found", show_alert=True)
        return ConversationHandler.END

    context.user_data['credit_topup_id'] = topup_id
    t = topups[topup_id]
    await query.edit_message_text(
        f"✅ Approving Top-Up {topup_id}\n"
        f"Method: {t['method']}\n"
        f"Reference: {t.get('reference') or '-'}\n\n"
        f"💵 Kitne *USDT* credit karne hain? Number bhejein (jaise: 10).\n"
        f"Cancel karne ke liye /skip dabayein.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return TOPUP_ADMIN_AMOUNT

async def topup_set_amount(update: Update, context):
    """Admin typed the credit amount -> add to wallet and notify the user."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    topup_id = context.user_data.get('credit_topup_id')
    topups = load_json(TOPUPS_FILE)
    if not topup_id or topup_id not in topups:
        await update.message.reply_text("❌ Top-up nahi mila. Cancelled.")
        context.user_data.pop('credit_topup_id', None)
        return ConversationHandler.END

    raw = (update.message.text or "").strip().replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        amount = -1
    if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000:
        await update.message.reply_text("❌ Valid amount bhejein (jaise: 10). Ya /skip.")
        return TOPUP_ADMIN_AMOUNT

    t = topups[topup_id]
    user_id = str(t['user_id'])
    # Credit + topup status update atomically so a simultaneous purchase by the
    # same user can't overwrite the new balance.
    async with DATA_LOCK:
        wallets = load_json(WALLETS_FILE)
        if user_id not in wallets:
            wallets[user_id] = {"balance": 0, "total_spent": 0}
        wallets[user_id]['balance'] += amount
        save_json(WALLETS_FILE, wallets)
        new_balance = wallets[user_id]['balance']

        topups = load_json(TOPUPS_FILE)
        t = topups.get(topup_id, t)
        t['status'] = 'approved'
        t['amount'] = amount
        topups[topup_id] = t
        save_json(TOPUPS_FILE, topups)
    await complete_waiting_bar(
        context,
        {"order_id": topup_id, "user_id": t['user_id'], "product": "💵 Wallet Top-Up"},
        extra_message=(
            f"💵 {fmt(amount)} USDT aapke wallet mein add ho gaye!\n"
            f"💰 New Balance: {fmt(new_balance)} USDT"
        ),
    )
    await update.message.reply_text(
        f"✅ Top-Up {topup_id} approved. {fmt(amount)} USDT credited."
    )
    context.user_data.pop('credit_topup_id', None)
    return ConversationHandler.END

async def topup_skip(update: Update, context):
    """Admin abandons the credit step -> reject the request so it is resolved
    (no balance added) and the user's progress bar stops."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    topup_id = context.user_data.pop('credit_topup_id', None)
    async with DATA_LOCK:
        topups = load_json(TOPUPS_FILE)
        t = topups.get(topup_id) if topup_id else None
        if t:
            t['status'] = 'rejected'
            topups[topup_id] = t
            save_json(TOPUPS_FILE, topups)
    if t:
        await fail_waiting_bar(
            context,
            {"order_id": topup_id, "user_id": t['user_id']},
            f"❌ Top-Up {topup_id} reject ho gaya.\nKoi transaction confirm nahi hui — admin se rabta karein.",
        )
    await update.message.reply_text("❌ Top-up rejected (koi balance add nahi hua).")
    return ConversationHandler.END

async def topup_reject(update: Update, context):
    """Admin rejects a top-up request -> tell the user, no balance change."""
    if update.effective_user.id != ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()
    topup_id = query.data.replace("tpno_", "")
    async with DATA_LOCK:
        topups = load_json(TOPUPS_FILE)
        t = topups.get(topup_id)
        if t:
            t['status'] = 'rejected'
            topups[topup_id] = t
            save_json(TOPUPS_FILE, topups)
    if not t:
        await query.answer("❌ Not found", show_alert=True)
        return
    await fail_waiting_bar(
        context,
        {"order_id": topup_id, "user_id": t['user_id']},
        f"❌ Top-Up {topup_id} reject ho gaya.\nKoi transaction nahi mili — admin se rabta karein.",
    )
    await query.edit_message_text("❌ Top-Up Rejected")

# ============== ADMIN BALANCE (add / remove credit) ==============
def _parse_balance_args(args):
    """Parse `<user_id> <amount>` -> (user_id_str, amount_float) or (None, None)."""
    if len(args) < 2:
        return None, None
    user_id = args[0].strip()
    if not user_id.isdigit():
        return None, None
    raw = args[1].strip().replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        return user_id, None
    if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000:
        return user_id, None
    return user_id, amount

async def admin_addreward_start(update: Update, context):
    """/addreward — admin referral reward pool mein items add kare (Canva ID, Teams
    invite link, account, code — har line ek alag reward)."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return ConversationHandler.END
    count = len(get_reward_items())
    await update.message.reply_text(
        f"🎁 *Add Referral Rewards*\n\n"
        f"Abhi pool mein *{count}* reward item(s) hain.\n\n"
        f"Ab rewards paste karein — *har reward nayi line par*.\n"
        f"Misaal:\n"
        f"`Canva Team Invite: https://...`\n"
        f"`team-invite@mail.com | pass123`\n"
        f"`*https://shared-link.com/join`\n\n"
        f"Har line = ek reward (ek user ko milega, phir pool se hat jayega).\n\n"
        f"♻️ *REPEAT reward:* line ke shuru mein `*` lagayein "
        f"(jaise `*https://...`). Aise reward baar baar diye jate hain, "
        f"pool se kabhi hatte nahi (jaise ek public/shared link).\n\n"
        f"Ek message mein jitne chahein bhej saktay hain 👇\n"
        f"(band karne ke liye /cancel)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_REWARD_ADD

async def admin_addreward_save(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    items = [ln.strip() for ln in (update.message.text or "").splitlines() if ln.strip()]
    # Drop lines that are only a repeat marker (e.g. "*") — they'd deliver blank.
    items = [it for it in items if clean_reward(it).strip()]
    if not items:
        await update.message.reply_text("❌ Koi reward nahi mila. Har reward nayi line par bhejein 👇")
        return ADMIN_REWARD_ADD
    async with DATA_LOCK:
        data = load_json(REWARDS_FILE)
        if not isinstance(data, dict):
            data = {}
        pool = data.get("items", [])
        if not isinstance(pool, list):
            pool = []
        pool.extend(items)
        data["items"] = pool
        save_json(REWARDS_FILE, data)
        total = len(pool)
    repeat_n = sum(1 for it in items if is_repeat_reward(it))
    repeat_line = f"\n♻️ Inmein {repeat_n} repeat reward (kabhi khatam nahi honge)." if repeat_n else ""
    await update.message.reply_text(
        f"✅ {len(items)} reward(s) add ho gaye!{repeat_line}\n"
        f"🎁 Ab total reward pool: *{total}*\n\n"
        f"Ye un users ko milenge jo *5* aur *10* referrals complete karenge "
        f"(har user ko max 2 reward) — jab reward campaign ON ho.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

async def admin_addreward_cancel(update: Update, context):
    await update.message.reply_text("❌ Reward add cancel ho gaya.")
    return ConversationHandler.END

async def admin_rewards(update: Update, context):
    """/rewards — admin reward pool + campaign status dekhe."""
    if update.effective_user.id != ADMIN_ID:
        return
    if rewards_active():
        status = f"🟢 *Campaign ON* — khatam hone mein: {reward_time_left()}"
    else:
        status = "🔴 *Campaign OFF* — /startrewards <hours> se chalu karein"
    items = get_reward_items()
    if not items:
        await update.message.reply_text(
            f"🎁 *Reward Pool*\n\n{status}\n\n"
            "Abhi pool *khali* hai.\n"
            "Naye rewards add karne ke liye /addreward",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    preview = "\n".join(
        f"{i+1}. {'♻️ ' if is_repeat_reward(it) else ''}{clean_reward(it)[:60]}"
        for i, it in enumerate(items[:20])
    )
    more = f"\n…aur {len(items) - 20} aur" if len(items) > 20 else ""
    repeat_n = sum(1 for it in items if is_repeat_reward(it))
    repeat_note = f"\n♻️ = repeat reward ({repeat_n}) — kabhi khatam nahi hote" if repeat_n else ""
    await update.message.reply_text(
        f"🎁 *Reward Pool*\n\n{status}\n\nTotal items: *{len(items)}*\n\n{preview}{more}{repeat_note}\n\n"
        f"Naye add karne ke liye /addreward",
        parse_mode=ParseMode.MARKDOWN,
    )

async def admin_startrewards(update: Update, context):
    """/startrewards <hours> — referral reward campaign ko X ghante ke liye chalu karein.
    Sirf is dauraan milestone (5/10 referrals) par reward milta hai."""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ Usage: /startrewards <hours>\n"
            "Misaal: /startrewards 24  → reward offer 24 ghante ke liye on\n\n"
            "Band karne ke liye: /endrewards"
        )
        return
    try:
        hours = float(args[0])
    except ValueError:
        await update.message.reply_text("❌ Hours number hona chahiye. Misaal: /startrewards 24")
        return
    if not (0 < hours <= 720):
        await update.message.reply_text("❌ Hours 0 se zyada aur 720 (30 din) se kam hona chahiye.")
        return
    pool = len(get_reward_items())
    until = time.time() + hours * 3600
    async with DATA_LOCK:
        data = load_json(REWARDS_FILE)
        if not isinstance(data, dict):
            data = {}
        data["active_until"] = until
        save_json(REWARDS_FILE, data)
    warn = "" if pool else "\n\n⚠️ Pool *khali* hai! /addreward se rewards daalein warna kisi ko reward nahi milega."
    await update.message.reply_text(
        f"🟢 *Reward Campaign ON!*\n\n"
        f"⏳ {fmt(hours)} ghante ke liye (phir khud band).\n"
        f"🎁 Pool mein abhi {pool} item(s).\n\n"
        f"Is dauraan jo user 5 ya 10 referrals karega, use reward milega."
        + warn,
        parse_mode=ParseMode.MARKDOWN,
    )
    # Sabhi users + channel ko offer ki khabar dein (best-effort) — sirf jab
    # pool mein rewards mojood hon, warna khaali offer announce na ho.
    if pool:
        time_text = reward_time_left()
        sent, failed = await broadcast_rewards(context, time_text)
        await notify_channel(
            context,
            "🎁🎉 *REFERRAL REWARD OFFER ON!* 🎉🎁\n\n"
            "Doston ko refer karein aur MUFT rewards jeetein!\n"
            "🏆 5 referrals = 1 reward  •  🏆 10 referrals = 1 aur\n\n"
            f"⏳ Sirf *{time_text}* ke liye!\n👇 Abhi shuru karein",
        )
        await update.message.reply_text(
            f"📣 Offer notification bhej di gayi — ✅ {sent} users ko pohnchi"
            + (f", ❌ {failed} fail." if failed else ".")
        )

async def admin_endrewards(update: Update, context):
    """/endrewards — referral reward campaign abhi band kar dein."""
    if update.effective_user.id != ADMIN_ID:
        return
    was_active = rewards_active()
    async with DATA_LOCK:
        data = load_json(REWARDS_FILE)
        if not isinstance(data, dict):
            data = {}
        data["active_until"] = 0
        save_json(REWARDS_FILE, data)
    if was_active:
        await update.message.reply_text(
            "🔴 *Reward Campaign band ho gaya.*\n\n"
            "Ab referrals count to honge par koi reward nahi milega.\n"
            "Dobara chalu karne ke liye /startrewards <hours>",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "ℹ️ Reward campaign waise hi off tha.\n"
            "Chalu karne ke liye /startrewards <hours>",
        )

async def admin_setbanner_start(update: Update, context):
    """/setbanner — admin kisi product ki banner image khud change kare."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return ConversationHandler.END
    lines = []
    for pid, p in PRODUCTS.items():
        mark = "🖼️" if (banner_file_id(pid) or product_image_path(pid)) else "—"
        lines.append(f"`{pid}` {mark} {p['name']}")
    await update.message.reply_text(
        "🖼️ *Banner Change*\n\n" + "\n".join(lines) +
        "\n\nKis product ka banner change karna hai? Product number bhejein 👇\n"
        "(🖼️ = abhi banner laga hai)\n(band karne ke liye /cancel)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_BANNER_PID

async def admin_setbanner_pid(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    pid = (update.message.text or "").strip()
    product = PRODUCTS.get(pid)
    if not product:
        await update.message.reply_text("❌ Ye product number nahi mila. Dobara bhejein 👇")
        return ADMIN_BANNER_PID
    context.user_data['banner_pid'] = pid
    await update.message.reply_text(
        f"✅ *{product['name']}*\n\n"
        f"Ab is product ki *nayi banner image bhejein* (photo ke tor par) 👇\n"
        f"(band karne ke liye /cancel)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_BANNER_IMG

async def admin_setbanner_save(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    pid = context.user_data.get('banner_pid')
    product = PRODUCTS.get(pid)
    if not pid or not product:
        await update.message.reply_text("❌ Error. /setbanner se dobara shuru karein.")
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text(
            "❌ Ye photo nahi tha. Image ko *photo* ke tor par bhejein 👇\n"
            "(band karne ke liye /cancel)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ADMIN_BANNER_IMG
    # Largest size = last entry. Store file_id in DB so it survives redeploys.
    file_id = update.message.photo[-1].file_id
    async with DATA_LOCK:
        data = load_json(BANNERS_FILE)
        if not isinstance(data, dict):
            data = {}
        data[str(pid)] = file_id
        save_json(BANNERS_FILE, data)
    context.user_data.pop('banner_pid', None)
    await update.message.reply_text(
        f"✅ *{product['name']}* ka banner update ho gaya!\n\n"
        f"Ab ye image product view aur channel alerts mein dikhega.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

async def admin_setbanner_cancel(update: Update, context):
    context.user_data.pop('banner_pid', None)
    await update.message.reply_text("❌ Banner change cancel.")
    return ConversationHandler.END

async def admin_setprice(update: Update, context):
    """Admin: kisi product ki PERMANENT base price change karein (hamesha ke liye,
    restart/redeploy ke baad bhi rehti hai).
    Usage:
      • /setprice 1 12        → product 1 ki price 12 USDT
      • /setprice 1=12 2=18   → ek saath kai products ('=' ya ':' se)
    """
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        lines = "\n".join(
            f"{pid}. {p['name']} — abhi *{fmt(p['price'])} USDT*"
            for pid, p in PRODUCTS.items()
        )
        await update.message.reply_text(
            "💲 *Set Price* — product ki permanent price change karein\n\n"
            "Format:\n"
            "• `/setprice 1 12`  → product 1 ko 12 USDT\n"
            "• `/setprice 1=12 2=18`  → kai products ek saath\n\n"
            f"📋 *Mojooda prices:*\n{lines}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    pairs = []
    if any(("=" in t or ":" in t) for t in args):
        for t in args:
            t = t.replace(":", "=")
            if "=" not in t:
                continue
            pid, _, val = t.partition("=")
            pairs.append((pid.strip(), val.strip()))
    elif len(args) == 2:
        pairs.append((args[0].strip(), args[1].strip()))
    else:
        await update.message.reply_text(
            "❌ Format galat.\n• `/setprice 1 12`\n• `/setprice 1=12 2=18`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    valid, errors = [], []
    for pid, val in pairs:
        if pid not in PRODUCTS:
            errors.append(f"• Product {pid} nahi mila")
            continue
        try:
            price = float(val)
        except ValueError:
            errors.append(f"• {pid}: '{val}' valid price nahi")
            continue
        if price <= 0:
            errors.append(f"• {pid}: price 0 se zyada honi chahiye")
            continue
        if active_sale(pid):
            errors.append(f"• {pid}: ispar flash sale chal rahi hai — pehle `/endsale {pid}` karein")
            continue
        valid.append((pid, price))

    if not valid:
        await update.message.reply_text("❌ Koi price set nahi hui:\n" + "\n".join(errors))
        return

    async with DATA_LOCK:
        overrides = load_json(PRICES_FILE)
        for pid, price in valid:
            PRODUCTS[pid]["price"] = price
            overrides[pid] = price
        save_json(PRICES_FILE, overrides)

    changed = "\n".join(
        f"🛒 {PRODUCTS[pid]['name']}: ➡️ *{fmt(price)} USDT*" for pid, price in valid
    )
    skipped = ("\n\n⚠️ Skip hue:\n" + "\n".join(errors)) if errors else ""
    await update.message.reply_text(
        f"✅ *Price update ho gayi!* (permanent — restart ke baad bhi rahegi)\n\n{changed}{skipped}",
        parse_mode=ParseMode.MARKDOWN,
    )

# ============== ADMIN: BUTTON COLORS ==============
_COLOR_NAME_TO_STYLE = {
    "blue": "primary", "primary": "primary",
    "green": "success", "success": "success",
    "red": "danger", "danger": "danger",
}

async def admin_setcolor(update: Update, context):
    """Admin: product-list ke buttons ka color set karein (Blue / Green / Red).
    Sirf yeh 3 colors Telegram support karta hai.
    Usage:
      • /setcolor 1 green        → product 1 ka button green
      • /setcolor 1 green 2 red  → kai ek saath
      • /setcolor 1 none         → color hata dein (default)
    """
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args or len(args) % 2 != 0:
        cur = get_button_colors()
        lines = "\n".join(
            f"{pid}. {p['name']} — {BUTTON_COLORS.get(cur.get(pid), '⚪ Default')}"
            for pid, p in PRODUCTS.items()
        )
        await update.message.reply_text(
            "🎨 *Set Button Color* — product list ke buttons ka rang\n\n"
            "Colors: `blue`, `green`, `red`, ya `none` (hata do)\n\n"
            "Format:\n"
            "• `/setcolor 1 green`\n"
            "• `/setcolor 1 green 2 red 3 blue`\n\n"
            f"📋 *Abhi ke colors:*\n{lines}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    changed, errors = [], []
    async with DATA_LOCK:
        colors = get_button_colors()
        it = iter(args)
        for pid, cname in zip(it, it):
            pid = pid.strip()
            cname = cname.strip().lower()
            if pid not in PRODUCTS:
                errors.append(f"• {pid}: aisa product nahi")
            elif cname in ("none", "default", "off", "clear"):
                colors.pop(pid, None)
                changed.append(f"⚪ {PRODUCTS[pid]['name']}: Default")
            elif cname in _COLOR_NAME_TO_STYLE:
                style = _COLOR_NAME_TO_STYLE[cname]
                colors[pid] = style
                changed.append(f"{BUTTON_COLORS[style]} {PRODUCTS[pid]['name']}")
            else:
                errors.append(f"• {pid}: '{cname}' valid nahi (blue/green/red/none)")
        save_json(COLORS_FILE, colors)
    msg = ""
    if changed:
        msg += "✅ *Color set ho gaya!*\n\n" + "\n".join(changed)
    if errors:
        msg += (("\n\n⚠️ Skip:\n" if changed else "❌ Nahi hua:\n") + "\n".join(errors))
    msg += "\n\n💡 Product list dobara kholein to naye colors dikhenge."
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# ============== ADMIN: ADD / REMOVE PRODUCTS ==============
async def admin_seticon(update: Update, context):
    """Admin: product ke naam ke aage icon (emoji) set karein.
    Usage:
      • /seticon 1 🚀
      • /seticon 1 🚀 2 🎨 3 ✨   (kai ek saath)
      • /seticon 1 none            (icon hata dein)
    """
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args or len(args) % 2 != 0:
        cur = get_product_icons()
        lines = "\n".join(
            f"{pid}. {cur.get(pid, '⚪')}  {_strip_leading_emoji(p['name']) or p['name']}"
            for pid, p in PRODUCTS.items()
        )
        await update.message.reply_text(
            "🎯 *Set Icon* — har product ke aage emoji lagayein\n\n"
            "Apni emoji keyboard se koi bhi emoji bhej sakte hain.\n\n"
            "Format:\n"
            "• `/seticon 1 🚀`\n"
            "• `/seticon 1 🚀 2 🎨 3 ✨`\n"
            "• `/seticon 1 none`  → icon hata do\n\n"
            f"📋 *Abhi ke icons:*\n{lines}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    changed, errors = [], []
    async with DATA_LOCK:
        icons = get_product_icons()
        it = iter(args)
        for pid, emoji in zip(it, it):
            pid = pid.strip()
            emoji = emoji.strip()
            if pid not in PRODUCTS:
                errors.append(f"• {pid}: aisa product nahi")
            elif emoji.lower() in ("none", "default", "off", "clear"):
                icons.pop(pid, None)
                changed.append(f"⚪ {_strip_leading_emoji(PRODUCTS[pid]['name'])}: icon hata diya")
            else:
                icons[pid] = emoji
                changed.append(f"{emoji} {_strip_leading_emoji(PRODUCTS[pid]['name'])}")
        save_json(ICONS_FILE, icons)
    msg = ""
    if changed:
        msg += "✅ *Icon set ho gaya!*\n\n" + "\n".join(changed)
    if errors:
        msg += (("\n\n⚠️ Skip:\n" if changed else "❌ Nahi hua:\n") + "\n".join(errors))
    msg += "\n\n💡 Product list dobara kholein to naye icons dikhenge."
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def admin_addproduct_start(update: Update, context):
    """Admin: naya product add karna shuru karein (/addproduct)."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    context.user_data["newprod"] = {}
    await update.message.reply_text(
        "➕ *Naya Product* — Step 1/3\n\n"
        "Product ka *naam* likhein (emoji use kar sakte hain).\n"
        "Misaal: `🚀 ChatGPT Plus - 1 Month`\n\n"
        "❌ Rok dene ke liye /cancel",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_ADDPROD_NAME

async def admin_addproduct_name(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ Naam khali hai. Dobara likhein ya /cancel")
        return ADMIN_ADDPROD_NAME
    context.user_data.setdefault("newprod", {})["name"] = name
    await update.message.reply_text(
        "💲 *Step 2/3* — Price (USDT mein, sirf number).\n"
        "Misaal: `2.5`\n\n/cancel",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_ADDPROD_PRICE

async def admin_addproduct_price(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    raw = (update.message.text or "").strip().replace(",", ".")
    try:
        price = float(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Price sahi number nahi. Misaal: `2.5`\nDobara likhein ya /cancel",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ADMIN_ADDPROD_PRICE
    context.user_data.setdefault("newprod", {})["price"] = price
    await update.message.reply_text(
        "📝 *Step 3/3* — Short description likhein.\n"
        "(Ya `skip` likhein description ke baghair.)\n\n/cancel",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADMIN_ADDPROD_DESC

async def admin_addproduct_desc(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    np = context.user_data.get("newprod", {})
    desc = (update.message.text or "").strip()
    if desc.lower() in ("skip", "-", "none", ""):
        desc = np.get("name", "")
    pid = next_product_id()
    product = {
        "name": np.get("name", f"Product {pid}"),
        "price": np.get("price", 1),
        "stock": 0,
        "description": desc,
        "delivery": "Your access will be shared by admin after payment.",
        "per_seat": False,
    }
    async with DATA_LOCK:
        PRODUCTS[pid] = product
        data = load_json(PRODUCTS_FILE)
        added = data.get("added") or {}
        added[pid] = product
        data["added"] = added
        if data.get("removed"):
            data["removed"] = [x for x in data["removed"] if x != pid]
        save_json(PRODUCTS_FILE, data)
    context.user_data.pop("newprod", None)
    await update.message.reply_text(
        "✅ *Product add ho gaya!*\n\n"
        f"🆔 ID: `{pid}`\n"
        f"🛒 {product['name']}\n"
        f"💲 {fmt(product['price'])} USDT\n"
        "📦 Stock: 0\n\n"
        "Ab yeh karein:\n"
        "➡️ Stock daalein: `/addstock`\n"
        f"🎨 Color dein: `/setcolor {pid} green`\n"
        "🖼 Banner lagayein: `/setbanner`",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

async def admin_addproduct_cancel(update: Update, context):
    context.user_data.pop("newprod", None)
    await update.message.reply_text("❌ Product add cancel ho gaya.")
    return ConversationHandler.END

async def admin_removeproduct(update: Update, context):
    """Admin: ek product delete karein. Usage: /removeproduct <id>"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        lines = "\n".join(f"{pid}. {p['name']}" for pid, p in PRODUCTS.items())
        await update.message.reply_text(
            "🗑 *Remove Product* — product delete karein\n\n"
            "Format: `/removeproduct 3`\n\n"
            f"📋 *Products:*\n{lines}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    pid = args[0].strip()
    if pid not in PRODUCTS:
        await update.message.reply_text(
            f"❌ Product `{pid}` mojood nahi.", parse_mode=ParseMode.MARKDOWN
        )
        return
    if active_sale(pid):
        await update.message.reply_text(
            f"⚠️ Product {pid} par flash sale chal rahi hai. Pehle `/endsale {pid}` karein.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    name = PRODUCTS[pid]["name"]
    async with DATA_LOCK:
        PRODUCTS.pop(pid, None)
        data = load_json(PRODUCTS_FILE)
        added = data.get("added") or {}
        was_custom = pid in added
        added.pop(pid, None)
        data["added"] = added
        if not was_custom:
            removed = data.get("removed") or []
            if pid not in removed:
                removed.append(pid)
            data["removed"] = removed
        save_json(PRODUCTS_FILE, data)
        colors = get_button_colors()
        if pid in colors:
            colors.pop(pid, None)
            save_json(COLORS_FILE, colors)
        icons = get_product_icons()
        if pid in icons:
            icons.pop(pid, None)
            save_json(ICONS_FILE, icons)
    await update.message.reply_text(
        f"✅ *Product delete ho gaya:*\n🗑 {name} (ID {pid})\n\n"
        "Product list se ab yeh hat gaya hai.",
        parse_mode=ParseMode.MARKDOWN,
    )

async def admin_help(update: Update, context):
    """/help — admin ke liye saari commands ki poori list (A-Z) with use."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "ℹ️ Menu kholne ke liye /start dabayein. Madad ke liye *Support/FAQ* button use karein.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    text = (
        "📖 *ADMIN COMMANDS — Poori List (A-Z)*\n\n"
        "💲 *PRICE & SALES*\n"
        "• `/setprice` — Product ki *permanent* price change\n"
        "   `/setprice 1 12`  ya  `/setprice 1=12 2=18`\n"
        "• `/sale` — Timed flash sale (waqt ke baad khud khatam)\n"
        "   `/sale 2 15 3` (id price ghante)  ya  `/sale 1,2 20% 5`\n"
        "• `/multisale` — Alag products, alag sale price, ek hi duration\n"
        "   `/multisale 2=7 5=2 5`\n"
        "• `/endsale` — Sale jaldi band karein\n"
        "   `/endsale 2`  ya  `/endsale 1,2,3`\n"
        "• `/remindsale` — Chalti sale ka reminder dobara bhejein\n"
        "   `/remindsale 2`\n\n"
        "📦 *STOCK*\n"
        "• `/stock` — Saare products ka mojooda stock\n"
        "• `/addstock` — Product mein accounts add karein (step-by-step)\n"
        "• `/viewstock` — Product ke *saved accounts* dekhein\n"
        "   `/viewstock 1`\n"
        "• `/removestock` — Stock kam ya remove karein (step-by-step)\n\n"
        "🖼️ *BANNER*\n"
        "• `/setbanner` — Product ki banner image khud change karein (step-by-step)\n\n"
        "🛒 *PRODUCTS (add / delete / color)*\n"
        "• `/addproduct` — Naya product add karein (naam → price → description)\n"
        "• `/removeproduct` — Product delete karein\n"
        "   `/removeproduct 3`\n"
        "• `/setcolor` — Product button ka color (blue/green/red)\n"
        "   `/setcolor 1 green`  ya  `/setcolor 1 green 2 red`\n"
        "   `/setcolor 1 none` = default\n"
        "• `/seticon` — Product ke aage icon (emoji) lagayein\n"
        "   `/seticon 1 🚀`  ya  `/seticon 1 🚀 2 🎨`\n"
        "   `/seticon 1 none` = hata do\n\n"
        "🎁 *REFERRAL REWARDS*\n"
        "• `/startrewards` — Reward offer chalu karein X ghante ke liye\n"
        "   `/startrewards 24`\n"
        "• `/endrewards` — Reward offer abhi band karein\n"
        "• `/addreward` — Reward pool mein items add (Canva ID, Teams link, code…)\n"
        "   Har line = ek reward; offer ON ho to 5 aur 10 referrals par milta hai\n"
        "   Line ke aage `*` = repeat reward (kabhi khatam nahi hota)\n"
        "• `/rewards` — Reward pool + campaign status dekhein\n\n"
        "💰 *WALLET / USERS*\n"
        "• `/addbalance` — User ke wallet mein USDT add\n"
        "   `/addbalance 123456789 10`\n"
        "• `/removebalance` — User ke wallet se USDT minus\n"
        "   `/removebalance 123456789 10`\n"
        "• `/members` — Saare users ki list / count\n"
        "• `/stats` — Sales, revenue aur orders ke stats\n\n"
        "⚙️ *GENERAL*\n"
        "• `/start` — Bot/menu kholna (sab users)\n"
        "• `/help` — Yehi list dobara dekhein\n"
        "• `/cancel` — Step-by-step flow band karein\n"
        "• `/skip` — Delivery/top-up mein bina extra message approve\n\n"
        "🔔 Channel alerts (sale/stock) aur force-join automatic hain."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_addbalance(update: Update, context):
    """/addbalance <user_id> <amount> — admin user ke wallet mein credit add kare."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    user_id, amount = _parse_balance_args(context.args)
    if not user_id or amount is None:
        await update.message.reply_text(
            "❌ Sahi format:\n`/addbalance <user_id> <amount>`\n"
            "Misaal: `/addbalance 123456789 10`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    async with DATA_LOCK:
        wallets = load_json(WALLETS_FILE)
        if user_id not in wallets:
            wallets[user_id] = {"balance": 0, "total_spent": 0}
        wallets[user_id]['balance'] += amount
        new_balance = wallets[user_id]['balance']
        save_json(WALLETS_FILE, wallets)
    await update.message.reply_text(
        f"✅ User `{user_id}` ke wallet mein *{fmt(amount)} USDT* add ho gaye.\n"
        f"💰 Naya balance: *{fmt(new_balance)} USDT*",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=(
                f"💵 *{fmt(amount)} USDT* aapke wallet mein add ho gaye!\n"
                f"💰 Naya balance: *{fmt(new_balance)} USDT*"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await update.message.reply_text(
            "⚠️ Balance add ho gaya, lekin user ko notify nahi kar saka "
            "(usne bot start nahi kiya ya block kiya hua hai)."
        )

async def admin_removebalance(update: Update, context):
    """/removebalance <user_id> <amount> — admin user ke wallet se credit kaate."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    user_id, amount = _parse_balance_args(context.args)
    if not user_id or amount is None:
        await update.message.reply_text(
            "❌ Sahi format:\n`/removebalance <user_id> <amount>`\n"
            "Misaal: `/removebalance 123456789 10`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    async with DATA_LOCK:
        wallets = load_json(WALLETS_FILE)
        current = wallets.get(user_id, {}).get('balance', 0)
        if user_id not in wallets or current < amount:
            shortfall = True
        else:
            shortfall = False
            wallets[user_id]['balance'] -= amount
            new_balance = wallets[user_id]['balance']
            save_json(WALLETS_FILE, wallets)
    if shortfall:
        await update.message.reply_text(
            f"❌ User `{user_id}` ka balance kam hai (abhi: *{fmt(current)} USDT*). "
            f"Itne ({fmt(amount)} USDT) remove nahi ho sakte.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"✅ User `{user_id}` ke wallet se *{fmt(amount)} USDT* remove ho gaye.\n"
        f"💰 Naya balance: *{fmt(new_balance)} USDT*",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=(
                f"➖ Aapke wallet se *{fmt(amount)} USDT* deduct kiye gaye.\n"
                f"💰 Naya balance: *{fmt(new_balance)} USDT*"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await update.message.reply_text(
            "⚠️ Balance remove ho gaya, lekin user ko notify nahi kar saka."
        )

async def show_support(update: Update, context):
    """Show support"""
    text = (
        f"❓ *Support & FAQ* ❓\n\n"
        f"*Q: How to order?*\n"
        f"A: Browse → Select → Choose payment → Done!\n\n"
        f"*Q: How fast is delivery?*\n"
        f"A: Instant after admin approval (5-10 mins)\n\n"
        f"*Q: Refund policy?*\n"
        f"A: Money-back guarantee!\n\n"
        f"*Q: Payment methods?*\n"
        f"A: NayaPay, Binance Pay (UID), Wallet\n\n"
        f"📧 Contact: `@{SUPPORT_USERNAME}`\n"
        f"💬 Support: 24/7\n\n"
        f"Neeche button par click karke seedha humein message karein 👇"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Contact Support", url=SUPPORT_URL)]]
    )
    await update.message.reply_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
    return CHOOSING

# ============== ADMIN STATS ==============
async def admin_stats(update: Update, context):
    """Admin stats command"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    
    orders = load_json(ORDERS_FILE)
    wallets = load_json(WALLETS_FILE)
    
    delivered = len([o for o in orders.values() if o['status'] == 'delivered'])
    pending = len([o for o in orders.values() if o['status'] == 'pending'])
    total_revenue = sum([o['amount'] for o in orders.values() if o['status'] == 'delivered'])
    
    text = (
        f"📊 *CHEAP AI TOOLS - Stats* 📊\n\n"
        f"✅ Delivered: {delivered}\n"
        f"⏳ Pending: {pending}\n"
        f"💰 Revenue: {fmt(total_revenue)} USDT\n"
        f"👥 Users: {len(wallets)}"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_members(update: Update, context):
    """Admin: how many members the bot has. Usage: /members"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    wallets = load_json(WALLETS_FILE)
    reachable = all_known_user_ids()
    await update.message.reply_text(
        f"👥 *CHEAP AI TOOLS - Members* 👥\n\n"
        f"📲 Bot start karne wale (wallets): *{len(wallets)}*\n"
        f"📣 Broadcast tak pohanchne wale (total): *{len(reachable)}*\n\n"
        f"_Note: Bot sirf un logon ko message bhej sakta hai jinhon ne bot ko_ "
        f"_/start kiya ho. Naye members khud-ba-khud is list mein add hote rahenge._",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cancel(update: Update, context):
    await update.message.reply_text("❌ Cancelled")
    return ConversationHandler.END

# ============== GITHUB INTEGRATION ==============
GITHUB_TOKENS_FILE = "github_tokens.json"

def get_user_github_token(user_id):
    tokens = load_json(GITHUB_TOKENS_FILE)
    if isinstance(tokens, dict):
        u_token = tokens.get(str(user_id))
        if u_token:
            return u_token
    return os.getenv("GITHUB_TOKEN")

def set_user_github_token(user_id, token):
    tokens = load_json(GITHUB_TOKENS_FILE)
    if not isinstance(tokens, dict):
        tokens = {}
    tokens[str(user_id)] = token
    save_json(GITHUB_TOKENS_FILE, tokens)

def delete_user_github_token(user_id):
    tokens = load_json(GITHUB_TOKENS_FILE)
    if isinstance(tokens, dict) and str(user_id) in tokens:
        del tokens[str(user_id)]
        save_json(GITHUB_TOKENS_FILE, tokens)

async def cmd_github(update: Update, context):
    """Show GitHub dashboard menu."""
    user_id = update.effective_user.id
    token = get_user_github_token(user_id)
    
    keyboard = [
        [
            InlineKeyboardButton("👤 My Profile", callback_data="gh_cb_profile"),
            InlineKeyboardButton("📦 Repositories", callback_data="gh_cb_repos")
        ],
        [
            InlineKeyboardButton("📝 My Gists", callback_data="gh_cb_gists"),
            InlineKeyboardButton("🔑 Token Status", callback_data="gh_cb_token")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_str = "✅ Connected" if token else "❌ No Token Configured"
    text = (
        "🐙 *GitHub Dashboard*\n\n"
        f"Status: {status_str}\n\n"
        "Niche buttons se aap apna GitHub Profile, Repos, aur Gists manage kar sakte hain.\n\n"
        "💡 *Commands:*\n"
        "• `/gh_settoken <PAT>` - Personal Access Token set karein\n"
        "• `/gh_deltoken` - Saved token remove karein\n"
        "• `/gh_profile` - Profile overview\n"
        "• `/gh_repos` - Repositories list\n"
        "• `/gh_gists` - Gists list"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def cmd_gh_settoken(update: Update, context):
    """Set GitHub Personal Access Token for the user."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide your GitHub Personal Access Token.\n\n"
            "Example:\n`/gh_settoken ghp_xxxxxx`\n\n"
            "GitHub Settings -> Developer Settings -> Personal Access Tokens se token generate karein.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    token = context.args[0].strip()
    msg = await update.message.reply_text("🔄 Verifying GitHub Token...")
    
    res = await github_service.verify_token(token)
    if res.get("valid"):
        set_user_github_token(user_id, token)
        await msg.edit_text(
            f"✅ *GitHub Access Token Connected Successfully!*\n\n"
            f"👤 *User:* `{res.get('login')}` ({res.get('name')})\n"
            f"📦 *Public Repos:* {res.get('public_repos')}\n"
            f"🔒 *Private Repos:* {res.get('total_private_repos')}\n"
            f"🔗 [View Profile]({res.get('html_url')})\n\n"
            f"Aap ab `/github` command use kar ke apna GitHub account access kar sakte hain.",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    else:
        await msg.edit_text(
            f"❌ *Token Verification Failed*\n\nError: {res.get('error', 'Invalid token')}",
            parse_mode=ParseMode.MARKDOWN
        )

async def cmd_gh_deltoken(update: Update, context):
    """Delete saved GitHub token for user."""
    user_id = update.effective_user.id
    delete_user_github_token(user_id)
    await update.message.reply_text("🗑️ Saved GitHub Token remove kar diya gaya hai.")

async def cmd_gh_profile(update: Update, context):
    """Show user's GitHub profile."""
    user_id = update.effective_user.id
    token = get_user_github_token(user_id)
    
    if update.callback_query:
        await update.callback_query.answer("Fetching profile...")
    
    res = await github_service.get_user_profile(token)
    if not res.get("valid"):
        err_msg = f"❌ *GitHub Error*\n\n{res.get('error', 'No token configured.')}\n\nUse `/gh_settoken <PAT>` to set your token."
        if update.callback_query:
            await update.callback_query.edit_message_text(err_msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(err_msg, parse_mode=ParseMode.MARKDOWN)
        return

    text = (
        f"👤 *GitHub Profile: {res.get('login')}*\n"
        f"─────────────────────\n"
        f"📛 *Name:* {res.get('name')}\n"
        f"📝 *Bio:* {res.get('bio')}\n"
        f"📦 *Public Repos:* {res.get('public_repos')}\n"
        f"🔒 *Private Repos:* {res.get('total_private_repos')}\n"
        f"👥 *Followers:* {res.get('followers')} | *Following:* {res.get('following')}\n"
        f"🔗 [GitHub Link]({res.get('html_url')})"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="gh_cb_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def cmd_gh_repos(update: Update, context):
    """List user's GitHub repos."""
    user_id = update.effective_user.id
    token = get_user_github_token(user_id)

    if update.callback_query:
        await update.callback_query.answer("Fetching repositories...")

    res = await github_service.get_user_repos(token=token, limit=10)
    if not res.get("success"):
        err_msg = f"❌ *GitHub Error*\n\n{res.get('error')}"
        if update.callback_query:
            await update.callback_query.edit_message_text(err_msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(err_msg, parse_mode=ParseMode.MARKDOWN)
        return

    repos = res.get("repos", [])
    if not repos:
        text = "📦 Koi repository nahi mili."
    else:
        text = "📦 *Your GitHub Repositories (Top 10):*\n─────────────────────\n\n"
        for r in repos:
            priv = "🔒 Private" if r["private"] else "🌐 Public"
            desc = r['description'] or "No description"
            text += (
                f"🔹 [{r['name']}]({r['html_url']}) ({priv})\n"
                f"   ⭐ {r['stargazers_count']} | 🍴 {r['forks_count']} | 💻 {r['language']}\n"
                f"   _{desc}_\n\n"
            )

    keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="gh_cb_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def cmd_gh_gists(update: Update, context):
    """List user's GitHub Gists."""
    user_id = update.effective_user.id
    token = get_user_github_token(user_id)

    if update.callback_query:
        await update.callback_query.answer("Fetching gists...")

    res = await github_service.get_user_gists(token=token, limit=10)
    if not res.get("success"):
        err_msg = f"❌ *GitHub Error*\n\n{res.get('error')}"
        if update.callback_query:
            await update.callback_query.edit_message_text(err_msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(err_msg, parse_mode=ParseMode.MARKDOWN)
        return

    gists = res.get("gists", [])
    if not gists:
        text = "📝 Koi Gist nahi mila."
    else:
        text = "📝 *Your GitHub Gists (Top 10):*\n─────────────────────\n\n"
        for g in gists:
            vis = "🌐 Public" if g["public"] else "🔒 Secret"
            files_str = ", ".join(g["files"]) if g["files"] else "No files"
            desc = g['description'] or "No description"
            text += (
                f"🔹 [{desc}]({g['html_url']}) ({vis})\n"
                f"   📁 Files: `{files_str}`\n\n"
            )

    keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="gh_cb_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def github_callback_handler(update: Update, context):
    """Handle inline button queries for GitHub menu."""
    query = update.callback_query
    data = query.data

    if data == "gh_cb_main":
        await cmd_github(update, context)
    elif data == "gh_cb_profile":
        await cmd_gh_profile(update, context)
    elif data == "gh_cb_repos":
        await cmd_gh_repos(update, context)
    elif data == "gh_cb_gists":
        await cmd_gh_gists(update, context)
    elif data == "gh_cb_token":
        user_id = update.effective_user.id
        token = get_user_github_token(user_id)
        if token:
            masked = token[:7] + "..." + token[-4:] if len(token) > 12 else "Configured"
            text = (
                f"🔑 *GitHub Token Status*\n\n"
                f"Status: ✅ Active\n"
                f"Token: `{masked}`\n\n"
                f"Token update karne ke liye: `/gh_settoken <PAT>`\n"
                f"Token remove karne ke liye: `/gh_deltoken`"
            )
        else:
            text = (
                "🔑 *GitHub Token Status*\n\n"
                "Status: ❌ Not Set\n\n"
                "Aap GitHub Personal Access Token connect karne ke liye Command reply karein:\n"
                "`/gh_settoken ghp_xxxxxxxxx`"
            )
        keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="gh_cb_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

# ============== ADVANCED ADMIN CONTROL PANEL ==============
async def cmd_admin_panel(update: Update, context):
    """Main /admin command dashboard."""
    user_id = update.effective_user.id
    if not is_admin(load_json, user_id):
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return

    keyboard = [
        [
            InlineKeyboardButton("📦 Products", callback_data="adm_menu_products"),
            InlineKeyboardButton("📁 Categories", callback_data="adm_menu_categories")
        ],
        [
            InlineKeyboardButton("🧾 Orders", callback_data="adm_menu_orders"),
            InlineKeyboardButton("👥 Users & Wallet", callback_data="adm_menu_users")
        ],
        [
            InlineKeyboardButton("🏷️ Coupons & Promos", callback_data="adm_menu_coupons"),
            InlineKeyboardButton("💳 Payment Gateways", callback_data="adm_menu_payments")
        ],
        [
            InlineKeyboardButton("📢 Mass Broadcast", callback_data="adm_menu_broadcast"),
            InlineKeyboardButton("📊 Analytics & Stats", callback_data="adm_menu_stats")
        ],
        [
            InlineKeyboardButton("⚙️ Shop Settings", callback_data="adm_menu_settings"),
            InlineKeyboardButton("🛡️ Admin Roles", callback_data="adm_menu_roles")
        ],
        [
            InlineKeyboardButton("💾 Backups & Audit Logs", callback_data="adm_menu_backups")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "👑 *ADVANCED ADMIN CONTROL PANEL*\n"
        "───────────────────────────────────\n"
        "Welcome to the master control panel!\n"
        "Select an option below to manage products, categories, orders, users, coupons, broadcasts, settings, and backups interactively."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def admin_panel_callback_handler(update: Update, context):
    """Handle all inline button menu interactions for the admin panel."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    if not is_admin(load_json, user_id):
        await query.answer("❌ Unauthorized", show_alert=True)
        return

    await query.answer()

    if data == "adm_menu_main":
        await cmd_admin_panel(update, context)

    elif data == "adm_menu_products":
        prods = admin_products.get_all_products(load_json, PRODUCTS)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = f"📦 *PRODUCT MANAGEMENT*\n─────────────────────\nTotal Active Products: *{len(prods)}*\n\nChoose an action below:"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_categories":
        cats = admin_products.get_categories(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = f"📁 *CATEGORY MANAGEMENT*\n─────────────────────\nTotal Categories: *{len(cats)}*\n"
        for cid, cinfo in cats.items():
            text += f"• {cinfo.get('emoji', '📁')} *{cinfo.get('name')}* (ID: `{cid}`)\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_orders":
        orders = admin_orders.get_all_orders(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = f"🧾 *ORDER MANAGEMENT*\n─────────────────────\nTotal Recorded Orders: *{len(orders)}*\n\nUse `/search <order_id>` to view or manage specific orders."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_users":
        wallets = load_json(WALLETS_FILE)
        banned = admin_users.get_banned_users(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = (
            f"👥 *USER & WALLET MANAGEMENT*\n─────────────────────\n"
            f"Registered Users: *{len(wallets)}*\n"
            f"Banned Users: *{len(banned)}*\n\n"
            "Use `/addbalance <user_id> <amount>` or `/removebalance <user_id> <amount>` to manage wallets."
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_coupons":
        coupons = admin_coupons.get_coupons(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = f"🏷️ *COUPONS & PROMOS*\n─────────────────────\nActive Coupons: *{len(coupons)}*\n"
        for code, cp in coupons.items():
            text += f"• `{code}` - {cp.get('value')}{'%' if cp.get('type')=='percent' else ' USDT'} off (Uses: {cp.get('used_count')})\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_payments":
        payments = admin_payments.get_payment_methods(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = f"💳 *PAYMENT GATEWAYS*\n─────────────────────\nConfigured Providers: *{len(payments)}*\n"
        for pid, pdata in payments.items():
            text += f"• *{pdata.get('name')}* - Status: {'✅ Enabled' if pdata.get('enabled') else '❌ Disabled'}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_broadcast":
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = "📢 *MASS BROADCAST SYSTEM*\n─────────────────────\nSend announcements to all bot users.\n\nUse `/broadcast <message>` to start a broadcast."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_stats":
        stats = admin_stats.calculate_dashboard_stats(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = (
            f"📊 *ANALYTICS & STATS DASHBOARD*\n─────────────────────\n"
            f"👥 Total Users: *{stats['total_users']}*\n"
            f"💰 Total Wallet Balance: *${stats['total_balance']} USDT*\n"
            f"📦 Total Orders: *{stats['total_orders']}* (Completed: {stats['completed_orders']})\n"
            f"💵 Total Revenue: *${stats['total_revenue']} USDT*\n"
            f"🔥 Top Product: *{stats['top_product']}*\n"
            f"👑 Top Referrer: `{stats['top_referrer']}` ({stats['top_referrer_count']} invites)"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_settings":
        st = admin_settings.get_settings(load_json)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = (
            f"⚙️ *DYNAMIC SHOP SETTINGS*\n─────────────────────\n"
            f"🏪 Shop Name: *{st.get('shop_name')}*\n"
            f"💱 Currency: *{st.get('currency')}*\n"
            f"📩 Support Username: `@{st.get('support_username')}`\n"
            f"📜 Terms Configured: {'Yes' if st.get('terms_text') else 'No'}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_roles":
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = f"🛡️ *MULTI-ADMIN & ROLE MANAGEMENT*\n─────────────────────\nOwner ID: `{ADMIN_ID}`\n\nAdmins have full access to shop controls."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == "adm_menu_backups":
        logs = admin_logs.get_admin_logs(load_json, limit=5)
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_menu_main")]
        ]
        text = "💾 *BACKUPS & AUDIT LOGS*\n─────────────────────\nRecent Admin Actions:\n"
        for l in logs:
            text += f"• `[{l.get('timestamp')}]` Admin `{l.get('admin_id')}`: {l.get('action')} - {l.get('details')}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler so the deployment detects an open port."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - CHEAP AI TOOLS bot is running")

    def log_message(self, *args):
        pass

def start_health_server():
    """Run a tiny HTTP server on PORT in a background thread. The bot uses
    long-polling and never opens a port itself, but VM deployments require an
    open port to pass the health check."""
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"🌐 Health server listening on 0.0.0.0:{port}")

async def error_handler(update, context):
    """Log errors without crashing. Quietly ignore harmless cases:
    - Forbidden: user blocked the bot
    - Conflict: another instance is polling the same token (409)"""
    err = context.error
    name = type(err).__name__
    if name in ("Forbidden", "Conflict"):
        logging.warning("Ignored %s: %s", name, err)
        return
    logging.error("Unhandled exception: %s: %s", name, err)

# ============== MAIN ==============
def main():
    if not BOT_TOKEN or BOT_TOKEN == "your_new_bot_token_here":
        print("❌ BOT_TOKEN not set!")
        return
    
    # Tuned for high concurrency (1000+ users):
    # - concurrent_updates: process many users' updates in parallel, not one-by-one
    # - large connection pool + generous timeouts: many simultaneous Telegram API
    #   calls won't queue up or throw pool-timeout errors under load
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(512)
        .pool_timeout(60.0)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .get_updates_connection_pool_size(16)
    )
    if PROXY_URL:
        print("🔗 Using proxy")
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    app = builder.build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler)
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(product_select, pattern=r"^select_"),
                CallbackQueryHandler(nav_back, pattern=r"^back_"),
                CallbackQueryHandler(topup_open, pattern=r"^tp_open$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler),
            ],
            ASK_QUANTITY: [
                MessageHandler(filters.Text(MENU_BUTTONS), menu_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity),
            ],
            ASK_EMAILS: [
                MessageHandler(filters.Text(MENU_BUTTONS), menu_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emails),
            ],
            CONFIRMING_ORDER: [
                CallbackQueryHandler(quantity_pick, pattern=r"^qty_|^qtyc_"),
                CallbackQueryHandler(nav_back, pattern=r"^back_"),
                CallbackQueryHandler(button_callback, pattern=r"^(buy_|pay_|cancel)"),
                MessageHandler(filters.Text(MENU_BUTTONS), menu_handler),
            ],
            PAYMENT_METHOD: [
                CallbackQueryHandler(nav_back, pattern=r"^back_"),
                CallbackQueryHandler(button_callback, pattern=r"^(buy_|pay_|cancel)"),
                MessageHandler(filters.Text(MENU_BUTTONS), menu_handler),
            ],
            AWAITING_APPROVAL: [
                CallbackQueryHandler(nav_back, pattern=r"^back_"),
                MessageHandler(filters.Text(MENU_BUTTONS), menu_handler),
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), handle_payment_proof),
            ],
            TOPUP_METHOD: [
                CallbackQueryHandler(topup_select, pattern=r"^tpm_"),
                CallbackQueryHandler(topup_cancel, pattern=r"^tp_cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler),
            ],
            TOPUP_PROOF: [
                MessageHandler(filters.Text(MENU_BUTTONS), menu_handler),
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), handle_topup_proof),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Admin delivery flow: Approve -> type login details -> sent to customer
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_approve, pattern=r"^approve_")],
        states={
            ADMIN_DELIVER: [
                CommandHandler("skip", admin_skip_delivery),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_credentials),
            ],
        },
        fallbacks=[CommandHandler("skip", admin_skip_delivery)],
        per_user=True,
        per_chat=True,
    )
    
    # Admin top-up flow: Approve -> type USDT amount -> credited to wallet
    topup_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_approve, pattern=r"^tpok_")],
        states={
            TOPUP_ADMIN_AMOUNT: [
                CommandHandler("skip", topup_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_set_amount),
            ],
        },
        fallbacks=[CommandHandler("skip", topup_skip)],
        per_user=True,
        per_chat=True,
    )
    
    # Admin stock flow: /addstock -> pick product -> paste account credentials
    stock_admin_conv = ConversationHandler(
        entry_points=[CommandHandler("addstock", admin_addstock_start)],
        states={
            ADMIN_STOCK_PID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addstock_pid),
            ],
            ADMIN_STOCK_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addstock_save),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_addstock_cancel)],
        per_user=True,
        per_chat=True,
    )
    
    # Admin remove-stock flow: /removestock -> pick product -> how many (or "all")
    rmstock_admin_conv = ConversationHandler(
        entry_points=[CommandHandler("removestock", admin_rmstock_start)],
        states={
            ADMIN_RMSTOCK_PID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rmstock_pid),
            ],
            ADMIN_RMSTOCK_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rmstock_apply),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_rmstock_cancel)],
        per_user=True,
        per_chat=True,
    )
    
    # Admin reward flow: /addreward -> paste reward items (one per line)
    reward_admin_conv = ConversationHandler(
        entry_points=[CommandHandler("addreward", admin_addreward_start)],
        states={
            ADMIN_REWARD_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addreward_save),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_addreward_cancel)],
        per_user=True,
        per_chat=True,
    )

    banner_admin_conv = ConversationHandler(
        entry_points=[CommandHandler("setbanner", admin_setbanner_start)],
        states={
            ADMIN_BANNER_PID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_setbanner_pid),
            ],
            ADMIN_BANNER_IMG: [
                MessageHandler(filters.PHOTO, admin_setbanner_save),
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, admin_setbanner_save),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_setbanner_cancel)],
        per_user=True,
        per_chat=True,
    )

    # Admin add-product flow: /addproduct -> name -> price -> description
    addproduct_admin_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", admin_addproduct_start)],
        states={
            ADMIN_ADDPROD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addproduct_name),
            ],
            ADMIN_ADDPROD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addproduct_price),
            ],
            ADMIN_ADDPROD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addproduct_desc),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_addproduct_cancel)],
        per_user=True,
        per_chat=True,
    )

    # Force-join gate runs before all other handlers (group -1) so no message or
    # inline-button action slips through without joining the channel.
    app.add_handler(MessageHandler(filters.ALL, global_join_gate), group=-1)
    app.add_handler(CallbackQueryHandler(global_join_gate), group=-1)

    app.add_handler(admin_conv)
    app.add_handler(topup_admin_conv)
    app.add_handler(stock_admin_conv)
    app.add_handler(rmstock_admin_conv)
    app.add_handler(reward_admin_conv)
    app.add_handler(banner_admin_conv)
    app.add_handler(addproduct_admin_conv)
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("members", admin_members))
    app.add_handler(CommandHandler("stock", admin_stock_view))
    app.add_handler(CommandHandler("viewstock", admin_viewstock))
    app.add_handler(CommandHandler("addbalance", admin_addbalance))
    app.add_handler(CommandHandler("removebalance", admin_removebalance))
    app.add_handler(CommandHandler("sale", admin_sale))
    app.add_handler(CommandHandler("multisale", admin_multisale))
    app.add_handler(CommandHandler("endsale", admin_endsale))
    app.add_handler(CommandHandler("remindsale", admin_remindsale))
    app.add_handler(CommandHandler("setprice", admin_setprice))
    app.add_handler(CommandHandler("setcolor", admin_setcolor))
    app.add_handler(CommandHandler("seticon", admin_seticon))
    app.add_handler(CommandHandler("removeproduct", admin_removeproduct))
    app.add_handler(CommandHandler("rewards", admin_rewards))
    app.add_handler(CommandHandler("startrewards", admin_startrewards))
    app.add_handler(CommandHandler("endrewards", admin_endrewards))
    # Admin Panel Handlers
    app.add_handler(CommandHandler("admin", cmd_admin_panel))
    app.add_handler(CallbackQueryHandler(admin_panel_callback_handler, pattern=r"^adm_menu_"))

    # GitHub Integration Handlers
    app.add_handler(CommandHandler(["github", "gh"], cmd_github))
    app.add_handler(CommandHandler("gh_settoken", cmd_gh_settoken))
    app.add_handler(CommandHandler("gh_deltoken", cmd_gh_deltoken))
    app.add_handler(CommandHandler("gh_profile", cmd_gh_profile))
    app.add_handler(CommandHandler("gh_repos", cmd_gh_repos))
    app.add_handler(CommandHandler("gh_gists", cmd_gh_gists))
    app.add_handler(CallbackQueryHandler(github_callback_handler, pattern=r"^gh_cb_"))

    app.add_handler(CallbackQueryHandler(check_join, pattern=r"^check_join$"))
    app.add_handler(CallbackQueryHandler(admin_reject, pattern=r"^reject_"))
    app.add_handler(CallbackQueryHandler(topup_reject, pattern=r"^tpno_"))
    app.add_error_handler(error_handler)
    
    start_health_server()
    seed_db_from_files()
    run_safe_migrations(load_json, save_json, _db_execute)
    apply_price_overrides()
    apply_product_overrides()
    print("🚀 CHEAP AI TOOLS Bot Started!")
    print("Press Ctrl+C to stop")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}")
        raise

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        main()
    finally:
        loop.close()
