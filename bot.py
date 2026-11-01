import os
import re
import sqlite3
import secrets
import string
from datetime import datetime, timezone
from urllib.parse import urlencode
from io import BytesIO

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))
BANK_BIN = "970436"  # Vietcombank, verified against VietQR's bank list
ACCOUNT_NO = os.getenv("BANK_ACCOUNT_NO", "23626337777").strip()
ACCOUNT_NAME = os.getenv(
    "BANK_ACCOUNT_NAME", "CONG TY TNHH TMDV THANH NGA 68"
).strip()
DB_PATH = os.getenv("DB_PATH", "payments.sqlite3")

if not BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in your .env file.")
if not ADMIN_ID:
    raise RuntimeError("Set ADMIN_TELEGRAM_ID in your .env file.")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                reference TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

def new_reference():
    alphabet = string.ascii_uppercase + string.digits
    return "PAY" + "".join(secrets.choice(alphabet) for _ in range(8))

def is_admin(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome. Use /pay to create a Vietcombank payment QR.\\n"
        "After paying, please wait for manual confirmation by the recipient."
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_amount"] = True
    await update.message.reply_text(
        "Enter the amount in VND as a whole number (for example: 5000000)."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_amount", None)
    await update.message.reply_text("Cancelled.")

async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_amount"):
        return

    raw = (update.message.text or "").replace(",", "").replace(".", "").strip()
    if not raw.isdigit():
        await update.message.reply_text("Please enter digits only, e.g. 5000000. Or use /cancel.")
        return

    amount = int(raw)
    if amount <= 0 or amount > 9_999_999_999_999:
        await update.message.reply_text("Please enter a valid positive VND amount.")
        return

    context.user_data.pop("awaiting_amount", None)
    reference = new_reference()
    # VietQR Quick Link: amount is embedded in the QR; addInfo carries a unique reference.
    params = {
        "amount": str(amount),
        "addInfo": reference,
        "accountName": ACCOUNT_NAME,
    }
    qr_url = (
        f"https://img.vietqr.io/image/{BANK_BIN}-{ACCOUNT_NO}-compact2.png?"
        + urlencode(params)
    )

    try:
        response = requests.get(qr_url, timeout=20)
        response.raise_for_status()
        if not response.headers.get("content-type", "").lower().startswith("image/"):
            raise ValueError("VietQR did not return an image.")
        photo = BytesIO(response.content)
        photo.name = f"{reference}.png"
    except Exception:
        await update.message.reply_text(
            "I couldn't retrieve the QR image from VietQR. Please try again later."
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO payments
               (reference, user_id, chat_id, amount, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'PENDING', ?, ?)""",
            (reference, update.effective_user.id, update.effective_chat.id,
             amount, now, now)
        )

    caption = (
        f"Payment request {reference}\\n"
        f"Amount: {amount:,} VND\\n"
        f"Beneficiary: {ACCOUNT_NAME}\\n"
        f"Bank: Vietcombank\\n\\n"
        "Scan the QR using your banking app. Check the beneficiary and amount "
        "before confirming the transfer. Your payment will be manually verified."
    )
    await update.message.reply_photo(photo=photo, caption=caption)

    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"New payment request: {reference}\\n"
                f"Amount: {amount:,} VND\\n"
                f"Telegram user ID: {update.effective_user.id}\\n"
                f"After checking the actual bank credit, use /confirm {reference} "
                f"or /reject {reference}."
            )
        )

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Not authorised.")
        return
    with db() as conn:
        rows = conn.execute(
            "SELECT reference, amount, user_id, created_at FROM payments "
            "WHERE status='PENDING' ORDER BY created_at ASC LIMIT 30"
        ).fetchall()
    if not rows:
        await update.message.reply_text("No pending payments.")
        return
    lines = ["Pending payments:"]
    for row in rows:
        lines.append(
            f"{row['reference']} — {row['amount']:,} VND — user {row['user_id']}"
        )
    await update.message.reply_text("\\n".join(lines))

async def set_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE, status: str):
    if not is_admin(update):
        await update.message.reply_text("Not authorised.")
        return
    if len(context.args) != 1:
        await update.message.reply_text(f"Usage: /{status.lower()} PAYREFERENCE")
        return
    reference = context.args[0].upper()
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE reference=?", (reference,)
        ).fetchone()
        if not row:
            await update.message.reply_text("Payment reference not found.")
            return
        if row["status"] != "PENDING":
            await update.message.reply_text(f"This payment is already {row['status']}.")
            return
        conn.execute(
            "UPDATE payments SET status=?, updated_at=? WHERE reference=?",
            (status, now, reference)
        )

    if status == "PAID":
        customer_text = (
            f"Your payment {reference} for {row['amount']:,} VND "
            "has been manually confirmed as received."
        )
    else:
        customer_text = (
            f"Your payment {reference} was not confirmed. "
            "Please contact the administrator."
        )
    await context.bot.send_message(chat_id=row["chat_id"], text=customer_text)
    await update.message.reply_text(f"{reference} marked {status}.")

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_payment_status(update, context, "PAID")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_payment_status(update, context, "REJECTED")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount))
    print("VietQR Telegram bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
