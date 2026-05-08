import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# === SOZLAMALAR (tokenlar Render.com da kiritiladi) ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)

conversation_history = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Salom, {user_name}! 👋\n\n"
        "Men Uchiha Bot — sun'iy intellekt yordamchiman!\n"
        "Menga xohlagan savolingizni yuboring!\n\n"
        "📌 Buyruqlar:\n"
        "/start - Botni qayta ishga tushirish\n"
        "/clear - Suhbat tarixini tozalash\n"
        "/help - Yordam"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Uchiha Bot*\n\n"
        "📌 *Buyruqlar:*\n"
        "/start - Botni boshlash\n"
        "/clear - Suhbat tarixini tozalash\n"
        "/help - Yordam\n\n"
        "💬 Shunchaki xabar yuboring!",
        parse_mode="Markdown"
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    await update.message.reply_text("✅ Suhbat tarixi tozalandi!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    await update.message.chat.send_action("typing")

    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {
                "role": "system",
                "content": """Sening isming Uchiha Bot. Seni Erkinov Abrorbek yaratgan.
Agarda sizga ham shunday bot kerak bo'lsa, unga murojaat qilishingiz mumkin: +998 94 337 60 08
O'zbek tilida javob ber, agar foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber."""
            }
        ]

    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    if len(conversation_history[user_id]) > 21:
        system_msg = conversation_history[user_id][0]
        conversation_history[user_id] = [system_msg] + conversation_history[user_id][-20:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation_history[user_id],
            max_tokens=1024
        )

        assistant_reply = response.choices[0].message.content

        conversation_history[user_id].append({
            "role": "assistant",
            "content": assistant_reply
        })

        await update.message.reply_text(assistant_reply)

    except Exception as e:
        logger.error(f"Groq API xatosi: {e}")
        await update.message.reply_text(
            "❌ Xato yuz berdi. Iltimos, keyinroq urinib ko'ring."
        )


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot ishga tushdi! ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
