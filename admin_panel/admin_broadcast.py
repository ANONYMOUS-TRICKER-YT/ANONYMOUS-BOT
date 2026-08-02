import asyncio
import logging

logger = logging.getLogger(__name__)

WALLETS_FILE = "wallets.json"

async def execute_broadcast(app, load_json_fn, text: str, media_type: str = None, media_file_id: str = None, reply_markup=None) -> dict:
    """Send broadcast message to all users in wallets.json."""
    wallets = load_json_fn(WALLETS_FILE)
    if not isinstance(wallets, dict):
        return {"total": 0, "success": 0, "failed": 0}

    user_ids = list(wallets.keys())
    success = 0
    failed = 0

    for uid in user_ids:
        try:
            target_id = int(uid)
            if media_type == "photo" and media_file_id:
                await app.bot.send_photo(chat_id=target_id, photo=media_file_id, caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            elif media_type == "video" and media_file_id:
                await app.bot.send_video(chat_id=target_id, video=media_file_id, caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            elif media_type == "document" and media_file_id:
                await app.bot.send_document(chat_id=target_id, document=media_file_id, caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                await app.bot.send_message(chat_id=target_id, text=text, parse_mode="Markdown", reply_markup=reply_markup)
            success += 1
            await asyncio.sleep(0.04) # Avoid hit rate limits
        except Exception as e:
            logger.warning(f"Broadcast failed for user {uid}: {e}")
            failed += 1

    return {"total": len(user_ids), "success": success, "failed": failed}
