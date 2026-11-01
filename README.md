# VietQR Telegram bot (manual confirmation)

This starter bot lets a customer enter a VND amount, creates a VietQR Quick Link
QR for the configured Vietcombank account, stores a pending payment in SQLite,
and lets one configured Telegram admin manually mark it PAID or REJECTED.

## Important
- QR generation does not confirm that money arrived.
- Before `/confirm PAYREFERENCE`, the admin must independently verify the
  actual incoming credit in the Vietcombank business banking app/statement.
- Test with a small amount first. Check the displayed beneficiary and amount
  in the bank app before authorising any transfer.
- Do not share your bot token or online banking credentials.
- This bot does not connect to Vietcombank and does not read bank transactions.

## Setup
1. Install Python 3.10+.
2. Create a Telegram bot via `@BotFather` and copy its token.
3. Find your numeric Telegram user ID (for example, message a trusted ID bot,
   or use Telegram's getUpdates after messaging your bot).
4. Copy `.env.example` to `.env` and fill in the token and numeric admin ID.
5. Install dependencies:
   `python -m pip install -r requirements.txt`
6. Run:
   `python bot.py`

## Customer commands
- `/start`
- `/pay`
- `/cancel`

## Admin commands (only the configured Telegram user ID)
- `/pending`
- `/confirm PAYREFERENCE` — use only after checking the bank account.
- `/reject PAYREFERENCE`

## QR generation
Uses VietQR.io Quick Link image endpoint with Vietcombank BIN 970436.
The amount and unique payment reference are embedded in each QR.
