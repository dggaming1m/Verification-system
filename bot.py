import logging
import time
import random
import string
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
from flask import Flask, request
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import requests
import threading
import asyncio
from dotenv import load_dotenv

# === Load environment variables ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
SHORTNER_API = os.getenv("SHORTNER_API")
FLASK_URL = os.getenv("FLASK_URL")
LIKE_API_URL = os.getenv("LIKE_API_URL")
PLAYER_INFO_API = os.getenv("PLAYER_INFO_API")
HOW_TO_VERIFY_URL = os.getenv("HOW_TO_VERIFY_URL")
VIP_ACCESS_URL = os.getenv("VIP_ACCESS_URL")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.isdigit()]

client = MongoClient(MONGO_URI)
db = client['likebot']
users = db['verifications']
profiles = db['users']

# === Flask App ===
flask_app = Flask(__name__)

@flask_app.route("/verify/<code>")
def verify(code):
    user = users.find_one({"code": code})
    if not user:
        return "❌ Link not found or already used."

    if user.get("verified"):
        return "❌ This link has already been used."

    if user.get("expires_at") and datetime.utcnow() > user["expires_at"]:
        return "❌ Link expired. Please generate a new like request."

    users.update_one({"code": code}, {"$set": {"verified": True, "verified_at": datetime.utcnow()}})
    return "✅ Verification successful. Bot will now process your like."

# === Telegram Bot Commands ===


async def like_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    try:
        args = update.message.text.strip().split()
        region = args[1].lower()
        uid = args[2]
    except:
        await update.message.reply_text("❌ Invalid command format. Please use: `/like <region> <uid>`", parse_mode='Markdown')
        return

    user_id = update.message.from_user.id
    user_doc = users.find_one({"user_id": user_id, "uid": uid})

    # ✅ Check if user has completed verification via shortlink
    if not user_doc or not user_doc.get("verified"):
        await update.message.reply_text(
            ("🚫 You have not completed the verification yet!\n\n""🔗 Please use the shortlink provided earlier and complete the quiz/ad step.\n""📩 After that, you will be redirected to the bot and must click `/start <code>`.\n""✅ Once verified, send the same `/like` command again."),
            parse_mode='Markdown'
        )
        return

    # ✅ Proceed to send like via API
    try:
        like_url = LIKE_API_URL.format(uid=uid, region=region)
        api_resp = requests.get(like_url, timeout=10).json()

        try:
            info = requests.get(PLAYER_INFO_API.format(uid=uid, region=region), timeout=5).json()
            player_name = info.get("name", f"Player-{uid[-4:]}")
        except:
            player_name = f"Player-{uid[-4:]}"

        before = api_resp.get("LikesbeforeCommand", 0)
        after = api_resp.get("LikesafterCommand", 0)
        added = api_resp.get("LikesGivenByAPI", 0)

        if added == 0:
            result = (
                "❌ *Like Failed*

"
                "🚫 It seems the like could not be processed.
"
                "💡 Possible Reasons:
"
                "- Daily limit reached
"
                "- Invalid UID or server

"
                "⏳ Try again later or contact support if the issue persists."
            )
        else:
            result = (
                f"✅ *Like Sent Successfully!*

"
                f"👤 *Player:* {player_name}\n"
                f"🆔 *UID:* `{uid}`\n"
                f"👍 *Likes Before:* {before}\n"
                f"✨ *Likes Added:* {added}\n"
                f"🏆 *Total Likes Now:* {after}\n"
                f"🕒 *Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            profiles.update_one({"user_id": user_id}, {"$set": {"last_used": datetime.utcnow()}}, upsert=True)

    except Exception as e:
        result = (
            f"❌ *API Error*

"
            f"📛 An error occurred while trying to send likes.\n"
            f"🧾 UID: `{uid}`\n"
            f"⚠️ Error: `{str(e)}`"
        )

    
    await update.message.reply_text(result, parse_mode='Markdown')

    # ✅ If command was from private chat, also send result to group if known
    if update.message.chat.type == "private":
        if user_doc and user_doc.get("chat_id"):
            try:
                await context.bot.send_message(
                    chat_id=user_doc["chat_id"],
                    text=result,
                    parse_mode='Markdown'
                )
            except:
                pass





async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text.startswith("/start "):
        return

    code = update.message.text.split(" ", 1)[1]
    user = users.find_one({"code": code})
    if not user:
        await update.message.reply_text("❌ Invalid or expired verification link.")
        return

    now = datetime.utcnow()
    verified_at = user.get("verified_at")
    if user.get("verified") and verified_at and (now - verified_at) < timedelta(hours=6):
        await update.message.reply_text("✅ You are already verified within the last 6 hours!")
        return

    users.update_one({"code": code}, {
        "$set": {
            "verified": True,
            "verified_at": now,
            "chat_id": update.effective_chat.id
        }
    })
    await update.message.reply_text("✅ You are verified! Please return to the group and send the /like command again.")

    if not update.message or not update.message.text.startswith("/start "):
        return

    code = update.message.text.split(" ", 1)[1]
    user = users.find_one({"code": code})
    if not user:
        await update.message.reply_text("❌ Invalid or expired verification link.")
        return

    if user.get("verified"):
        await update.message.reply_text("✅ You are already verified!")
    else:
        users.update_one({"code": code}, {
            "$set": {
                "verified": True,
                "verified_at": datetime.utcnow(),
                "chat_id": update.effective_chat.id
            }
        })
        await update.message.reply_text("✅ You are verified! Please return to the group and send the /like command again.")

    if not update.message or not update.message.text.startswith("/start "):
        return

    code = update.message.text.split(" ", 1)[1]
    user = users.find_one({"code": code})
    if not user:
        await update.message.reply_text("❌ Invalid or expired verification link.")
        return

    if user.get("verified"):
        await update.message.reply_text("✅ You are already verified!")
    else:
        users.update_one({"code": code}, {"$set": {"verified": True, "verified_at": datetime.utcnow()}})
        await update.message.reply_text("✅ You are verified! Now please send the /like command again to complete your request.")

    if not update.message or not update.message.text.startswith("/start "):
        return

    code = update.message.text.split(" ", 1)[1]
    user = users.find_one({"code": code})
    if not user:
        await update.message.reply_text("❌ Invalid or expired verification link.")
        return

    if user.get("verified"):
        await update.message.reply_text("✅ You are already verified!")
    else:
        users.update_one({"code": code}, {"$set": {"verified": True, "verified_at": datetime.utcnow()}})
        await update.message.reply_text("✅ You are verified! Likes will be processed shortly.")


async def givevip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    try:
        target_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Use: /givevip <user_id>")
        return

    profiles.update_one({"user_id": target_id}, {"$set": {"is_vip": True}}, upsert=True)
    await update.message.reply_text(f"✅ VIP access granted to user `{target_id}`", parse_mode='Markdown')

# async def process_verified_likes(app: Application): (DISABLED)
    while True:
        pending = users.find({"verified": True, "processed": {"$ne": True}})
        for user in pending:
            uid = user['uid']
            user_id = user['user_id']
            profile = profiles.find_one({"user_id": user_id}) or {}
            is_vip = profile.get("is_vip", False)
            last_used = profile.get("last_used")

            if not is_vip and last_used:
                elapsed = datetime.utcnow() - last_used
                if elapsed < timedelta(hours=24):
                    remaining = timedelta(hours=24) - elapsed
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes = remainder // 60
                    result = (
    f"❌ *Daily Limit Reached*\n\n"\n    f"⏳ Try again after: {hours}h {minutes}m"
)
                    await app.bot.send_message(
                        chat_id=user['chat_id'],
                        reply_to_message_id=user['message_id'],
                        text=result,
                        parse_mode='Markdown'
                    )
                    users.update_one({"_id": user['_id']}, {"$set": {"processed": True}})
                    continue

            try:
                api_resp = requests.get(LIKE_API_URL.format(uid=uid), timeout=10).json()
                player = (
    api_resp.get("PlayerNickname") or
    requests.get(PLAYER_INFO_API.format(uid=uid)).json().get("name") or
    f"Player-{uid[-4:]}"
)
                before = api_resp.get("LikesbeforeCommand", 0)
                after = api_resp.get("LikesafterCommand", 0)
                added = api_resp.get("LikesGivenByAPI", 0)

                if added == 0:
                    result = "❌ Like failed or daily max limit reached."
                else:
                    result = (
    f"✅ *Request Processed Successfully*\n\n"\n    f"👤 *Player:* {player}\n"
    f"🆔 *UID:* `{uid}`\n"\n    f"👍 *Likes Before:* {before}\n"
    f"✨ *Likes Added:* {added}\n"\n    f"🇮🇳 *Total Likes Now:* {after}\n"
    f"⏰ *Processed At:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    profiles.update_one({"user_id": user_id}, {"$set": {"last_used": datetime.utcnow()}}, upsert=True)

            except Exception as e:
                result = (
    f"❌ *API Error: Unable to process like*\n\n"\n    f"🆔 *UID:* `{uid}`\n"
    f"📛 Error: {str(e)}"
)

            await app.bot.send_message(
                chat_id=user['chat_id'],
                reply_to_message_id=user['message_id'],
                text=result,
                parse_mode='Markdown'
            )

            users.update_one({"_id": user['_id']}, {"$set": {"processed": True}})
        await asyncio.sleep(5)

def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("like", like_command))
    app.add_handler(CommandHandler("givevip", givevip_command))

    thread = threading.Thread(target=flask_app.run, kwargs={"host": "0.0.0.0", "port": 5000})
    thread.start()

    app.run_polling()

if __name__ == '__main__':
    run_bot()