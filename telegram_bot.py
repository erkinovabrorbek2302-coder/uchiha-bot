import yt_dlp
import logging
import httpx
import tempfile
import edge_tts
import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

import requests as req
import urllib.parse
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq
from tavily import TavilyClient

ADMIN_ID = 164581954
user_list = set()
message_count = 0

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)

conversation_history = {}
last_image_prompt = {}
user_state = {}
typo_correction = {}


async def _detect_intent(user_message: str) -> str:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Foydalanuvchi xabarining niyatini aniqla. Faqat bitta so'z yoz:
- "rasm" — agar rasm chizish, ko'rsatish, tasvirlash so'ralsa
- "chat" — boshqa barcha holatlarda

Muhim: "kim yaratgan", "sen kim", "nima qila olasan" kabi savollar — chat.
Shaxs, qahramon, anime, kino qahramoni nomi + rasm so'rovi — rasm."""
            },
            {"role": "user", "content": user_message}
        ],
        max_tokens=10
    )
    intent = response.choices[0].message.content.strip().lower()
    if "rasm" in intent:
        return "rasm"
    return "chat"


async def _check_typo(user_message: str) -> str | None:
    """Imlo xatosini tekshiradi, faqat aniq xato bo'lsa to'g'ri variantni qaytaradi"""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Foydalanuvchi xabarida ANIQ va OCHIQ imlo xatosi borligini tekshir.
Qoidalar:
- Faqat haqiqiy yozuv xatolarini to'g'irla (masalan: "narotu" -> "naruto", "privet" -> "salom" emas)
- Agar gap to'g'ri yozilgan bo'lsa — "ok" yoz
- Agar gap ma'nosiz emas, faqat biroz noto'g'ri yozilgan bo'lsa — "ok" yoz  
- Faqat harflar aralashib ketgan, so'z noto'g'ri yozilgan hollarda to'g'rilangan variantni yoz
- "ok" yoki to'g'rilangan matnni yoz, boshqa hech narsa yozma"""
            },
            {"role": "user", "content": user_message}
        ],
        max_tokens=100
    )
    result = response.choices[0].message.content.strip()
    if result.lower() == "ok":
        return None
    # Agar javob original matndan 20% dan kam farq qilsa, xato emas
    if len(result) > 0 and abs(len(result) - len(user_message)) / max(len(user_message), 1) < 0.2:
        if result.lower() == user_message.lower():
            return None
    return result


async def _create_image_prompt(query: str) -> str:
    try:
        search_results = tavily_client.search(query, max_results=5)
        search_info = " ".join([r["content"][:600] for r in search_results["results"]])
    except:
        search_info = query

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Sen dunyodagi eng yaxshi Stable Diffusion prompt yozuvchisan.
Qoidalar:
- FAQAT inglizcha yoz
- Agar taniqli qahramon, anime, kino, serial, o'yin qahramoni bo'lsa — internet ma'lumotidan foydalanib uning AYNAN o'ziga xos: soch rangi va uslubi, ko'z rangi, kiyim, qurol, belgi-alomatlarini BATAFSIL yoz
- Juda batafsil: rang, kiyim, yuz, soch, ko'z, fon, yoritish, atmosfera
- Yuqori sifat uchun: "ultra detailed, 8k uhd, masterpiece, sharp focus, cinematic lighting, vibrant colors, no blur, crystal clear, highly realistic"
- Yuz aniq ko'rinsin: "detailed face, perfect facial features, clear eyes, sharp details"
- Fon ham chiroyli bo'lsin: "beautiful detailed background, cinematic atmosphere"
- FAQAT promptni yoz, hech qanday izoh yozma"""
            },
            {
                "role": "user",
                "content": f"So'rov: {query}\nInternet ma'lumoti: {search_info}"
            }
        ],
        max_tokens=600
    )
    return response.choices[0].message.content.strip()


async def _generate_and_send_image(message, query: str, msg, user_id: int):
    try:
        await msg.edit_text("🎨 AI prompt tayyorlanmoqda...")
        english_prompt = await _create_image_prompt(query)
        last_image_prompt[user_id] = query

        await msg.edit_text("🖌️ Rasm chizilmoqda...")
        encoded = urllib.parse.quote(english_prompt)
        image_url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1024&height=1024&nologo=true&enhance=true&model=flux"
            f"&seed={hash(query) % 9999}"
        )

        async with httpx.AsyncClient(timeout=120) as http_client:
            response = await http_client.get(image_url)

        keyboard = [
            [
                InlineKeyboardButton("🔄 Qayta chizish", callback_data="rasm_qayta"),
                InlineKeyboardButton("✏️ O'zgartirish", callback_data="rasm_ozgartir"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_photo(
            response.content,
            caption=f"🖼️ {query}",
            reply_markup=reply_markup
        )
        await msg.delete()
    except Exception as e:
        logger.error(f"Rasm xatosi: {e}")
        await msg.edit_text("❌ Rasm yaratishda xato yuz berdi.")


async def _analyze_photo(image_base64: str, caption: str = None) -> str:
    if caption:
        prompt_text = f"Bu rasmni ko'r va '{caption}' so'roviga qarab nima qilish kerakligini hal qil. Agar yangi rasm chizish so'ralsa — ultra-detailed inglizcha Stable Diffusion prompt yoz. Agar tahrirlash so'ralsa — tahrirlangan rasm uchun prompt yoz. Agar misol yoki tavsif so'ralsa — o'zbek tilida tushuntir. FAQAT kerakli natijani yoz."
    else:
        prompt_text = "Bu rasmni batafsil tavsifla. Agar taniqli qahramon, anime, kino, serial, o'yin, shaxs bo'lsa — nomini top va batafsil tavsifla. O'zbek tilida yoz."

    result = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt_text}
                ]
            }
        ],
        max_tokens=600
    )
    return result.choices[0].message.content.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    user_list.add(update.effective_user.id)

    keyboard = [
        [
            InlineKeyboardButton("🎨 Rasm chizish", callback_data="menu_rasm"),
            InlineKeyboardButton("🎬 Video yuklash", callback_data="menu_video"),
        ],
        [
            InlineKeyboardButton("🧠 AI chat", callback_data="menu_chat"),
            InlineKeyboardButton("🗑️ Tarixni tozalash", callback_data="menu_clear"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Salom, {user_name}! 👋\n"
        f"👥 {len(user_list)} ta foydalanuvchi\n\n"
        "🤖 *Uchiha Bot imkoniyatlari:*\n\n"
        "🎨 *Rasm chizish* — har qanday rasm, qahramon, shaxs\n"
        "🎬 *Video* — YouTube videolarini yuklab beradi\n"
        "🧠 *AI chat* — har qanday savolga javob beradi\n"
        "🔊 *Ovozli chat* — ovozli xabarga javob qaytaradi\n"
        "📷 *Rasm tahlil* — rasm yuborsang tahlil qiladi\n\n"
        "Shunchaki xabar yozing yoki menyudan tanlang:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "menu_rasm":
        await query.message.reply_text(
            "🎨 Qanday rasm kerak? Yozing!\n\n"
            "Masalan:\n"
            "• *tezkor mashina*\n"
            "• *chiroyli tog' manzarasi*\n"
            "• *Naruto*\n"
            "• *Spider-Man*",
            parse_mode="Markdown"
        )

    elif data == "menu_video":
        await query.message.reply_text(
            "🎬 YouTube linkini yuboring!\n\n"
            "Masalan: `/video https://youtube.com/...`",
            parse_mode="Markdown"
        )

    elif data == "menu_chat":
        await query.message.reply_text(
            "🧠 Savolingizni yozing, javob beraman!\n\n"
            "Masalan:\n"
            "• *Python da for loop nima?*\n"
            "• *Dunyo poytaxti qaysi shahar?*",
            parse_mode="Markdown"
        )

    elif data == "menu_clear":
        conversation_history.pop(user_id, None)
        await query.message.reply_text("✅ Suhbat tarixi tozalandi!")

    elif data == "menu_main":
        keyboard = [
            [
                InlineKeyboardButton("🎨 Rasm chizish", callback_data="menu_rasm"),
                InlineKeyboardButton("🎬 Video yuklash", callback_data="menu_video"),
            ],
            [
                InlineKeyboardButton("🧠 AI chat", callback_data="menu_chat"),
                InlineKeyboardButton("🗑️ Tarixni tozalash", callback_data="menu_clear"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🏠 Asosiy menyu:", reply_markup=reply_markup)

    elif data == "rasm_qayta":
        prompt = last_image_prompt.get(user_id)
        if not prompt:
            await query.message.reply_text("❌ Avvalgi rasm topilmadi.")
            return
        msg = await query.message.reply_text("🎨 Qayta chizilmoqda...")
        await _generate_and_send_image(query.message, prompt, msg, user_id)

    elif data == "rasm_ozgartir":
        user_state[user_id] = "waiting_edit"
        await query.message.reply_text(
            "✏️ *Rasmni qanday o'zgartirmoqchisiz?*\n\n"
            "Masalan:\n"
            "• Qora-oq qilib\n"
            "• Kuchli effektlar bilan\n"
            "• Chiroyli fon bilan\n\n"
            "Yozing 👇",
            parse_mode="Markdown",
            reply_markup=ForceReply(selective=True)
        )

    elif data == "typo_ha":
        corrected = typo_correction.get(user_id)
        if corrected:
            typo_correction.pop(user_id, None)
            msg = await query.message.reply_text("⏳ Javob tayyorlanmoqda...")
            await _process_chat(query.message, corrected, user_id, msg)

    elif data == "typo_yoq":
        typo_correction.pop(user_id, None)
        await query.message.reply_text("Tushunarli, davom eting 👍")


async def _process_chat(message, user_message: str, user_id: int, msg=None):
    try:
        search_results = tavily_client.search(user_message, max_results=3)
        search_context = "\n".join([r["content"][:300] for r in search_results["results"]])
        internet_info = f"\nInternet ma'lumoti:\n{search_context}\n"
    except:
        internet_info = ""

    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {
                "role": "system",
                "content": f"""Sen Uchiha Bot — aqlli, do'stona AI yordamchisan. Seni Erkinov Abrorbek (16 yosh) yaratgan.

Qoidalar:
- Foydalanuvchi qaysi tilda yozsa, o'sha tilda javob ber
- Javoblarni to'liq, aniq va tushunarli yoz — juda qisqa qilma
- O'zingni faqat so'ralganda tanishdir
- Yaratuvchi haqida faqat so'ralganda: Instagram @sung_jinwoo.2010, tel: +998 94 337 60 08
- Emojilarni o'rinli ishlat, ko'p ishlatma
- HTML so'rasa: ```html ... ``` ichida yoz
- Python so'rasa: ```python ... ``` ichida yoz, input() ishlatma
- Savollarga to'liq javob ber, kerakli ma'lumotlarni tushuntir
{internet_info}"""
            }
        ]

    conversation_history[user_id].append({"role": "user", "content": user_message})

    if len(conversation_history[user_id]) > 31:
        sys_msg = conversation_history[user_id][0]
        conversation_history[user_id] = [sys_msg] + conversation_history[user_id][-30:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation_history[user_id],
            max_tokens=4096
        )
        assistant_reply = response.choices[0].message.content
        conversation_history[user_id].append({"role": "assistant", "content": assistant_reply})

        if "```html" in assistant_reply:
            try:
                html_code = assistant_reply.split("```html")[1].split("```")[0].strip()
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                    f.write(html_code)
                    temp_file = f.name
                with open(temp_file, 'rb') as doc:
                    await message.reply_document(doc, filename="index.html", caption="🌐 Veb sayt fayli!")
                os.remove(temp_file)
                if msg:
                    await msg.delete()
                return
            except Exception as e:
                logger.error(f"HTML xatosi: {e}")

        if msg:
            await msg.delete()

        try:
            await message.reply_text(assistant_reply, parse_mode="Markdown")
        except:
            chunks = [assistant_reply[i:i+4000] for i in range(0, len(assistant_reply), 4000)]
            for chunk in chunks:
                try:
                    await message.reply_text(chunk, parse_mode="Markdown")
                except:
                    await message.reply_text(chunk)

    except Exception as e:
        logger.error(f"Groq xatosi: {e}")
        if msg:
            await msg.edit_text("❌ Xato yuz berdi, qaytadan urinib ko'ring.")
        else:
            await message.reply_text("❌ Xato yuz berdi, qaytadan urinib ko'ring.")


async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Tavsif yozing!\nMasalan: /rasm Naruto")
        return
    prompt = " ".join(context.args)
    user_id = update.effective_user.id
    msg = await update.message.reply_text("🎨 Rasm chizilmoqda...")
    await _generate_and_send_image(update.message, prompt, msg, user_id)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(file.file_path)
        image_data = response.content

    image_base64 = base64.b64encode(image_data).decode('utf-8')

    if update.message.caption:
        msg = await update.message.reply_text("🎨 Rasm qayta ishlanmoqda...")
        try:
            result = await _analyze_photo(image_base64, update.message.caption)
            last_image_prompt[user_id] = update.message.caption

            # Agar prompt bo'lsa rasm chiz
            if any(word in update.message.caption.lower() for word in ["chiz", "yarat", "qil", "o'zgartir", "tahrir", "ko'rsat"]):
                encoded = urllib.parse.quote(result)
                image_url = (
                    f"https://image.pollinations.ai/prompt/{encoded}"
                    f"?width=1024&height=1024&nologo=true&enhance=true&model=flux"
                )
                async with httpx.AsyncClient(timeout=120) as http_client:
                    img_response = await http_client.get(image_url)

                keyboard = [[
                    InlineKeyboardButton("🔄 Qayta chizish", callback_data="rasm_qayta"),
                    InlineKeyboardButton("✏️ O'zgartirish", callback_data="rasm_ozgartir"),
                ]]
                await update.message.reply_photo(
                    img_response.content,
                    caption=f"🖼️ {update.message.caption}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                keyboard = [[
                    InlineKeyboardButton("🎨 Rasm chizish", callback_data="rasm_qayta"),
                    InlineKeyboardButton("✏️ O'zgartirish", callback_data="rasm_ozgartir"),
                ]]
                await update.message.reply_text(result, reply_markup=InlineKeyboardMarkup(keyboard))

            await msg.delete()
        except Exception as e:
            logger.error(f"Rasm tahrirlash xatosi: {e}")
            await msg.edit_text("❌ Rasm o'zgartirishda xato.")
    else:
        msg = await update.message.reply_text("🔍 Rasm tahlil qilinmoqda...")
        try:
            analysis = await _analyze_photo(image_base64)
            keyboard = [[
                InlineKeyboardButton("🎨 Shu rasmni chizish", callback_data="rasm_qayta"),
                InlineKeyboardButton("✏️ O'zgartirish", callback_data="rasm_ozgartir"),
            ]]
            await msg.edit_text(analysis, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Rasm tahlil xatosi: {e}")
            await msg.edit_text("❌ Rasm tahlil qilib bo'lmadi.")


async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ YouTube linki yozing!\nMasalan: /video https://youtube.com/shorts/xxx")
        return

    url = context.args[0]
    msg = await update.message.reply_text("⬇️ Video yuklanmoqda, kuting...")

    try:
        ydl_opts = {
            'format': 'best[filesize<50M]/best',
            'outtmpl': f'video_{update.effective_user.id}.%(ext)s',
            'quiet': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        with open(filename, 'rb') as video:
            await update.message.reply_video(video, caption=f"🎬 {info.get('title', 'Video')}")

        os.remove(filename)
        await msg.delete()

    except Exception as e:
        logger.error(f"Video xatosi: {e}")
        await msg.edit_text("❌ Video yuklab bo'lmadi.")


async def analyze_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🎬 Video tahlil qilinmoqda...")
    try:
        video = update.message.video
        if not video.thumbnail:
            await msg.edit_text("❌ Video tahlil qilib bo'lmadi.")
            return

        file = await context.bot.get_file(video.thumbnail.file_id)
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(file.file_path)

        image_base64 = base64.b64encode(response.content).decode('utf-8')
        result = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": "Bu video kadrini tahlil qil. Kino, serial, o'yin bo'lsa nomini top. O'zbek tilida javob ber."}
                ]
            }],
            max_tokens=500
        )
        keyboard = [[InlineKeyboardButton("🎨 Shu janrdagi rasm chizish", callback_data="rasm_qayta")]]
        await msg.edit_text(result.choices[0].message.content, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Video tahlil xatosi: {e}")
        await msg.edit_text("❌ Video tahlil qilib bo'lmadi.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice_file = await context.bot.get_file(update.message.voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await voice_file.download_to_drive(tmp.name)
        voice_path = tmp.name

    with open(voice_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
        )
    user_text = transcription.text
    user_id = update.effective_user.id

    # Qaysi tilda gapirganini aniqlash
    lang_response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "Matnning tilini aniqla. Faqat til kodini yoz: 'uz' o'zbek, 'ru' rus, 'en' ingliz, 'other' boshqa til."
            },
            {"role": "user", "content": user_text}
        ],
        max_tokens=10
    )
    lang = lang_response.choices[0].message.content.strip().lower()

    voice_map = {
        "uz": "uz-UZ-SardorNeural",
        "ru": "ru-RU-DmitryNeural",
        "en": "en-US-GuyNeural",
    }
    voice = voice_map.get(lang, "en-US-GuyNeural")

    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {"role": "system", "content": "Sen Uchiha Bot — aqlli AI yordamchisan. Foydalanuvchi qaysi tilda gapirsa o'sha tilda javob ber."}
        ]

    conversation_history[user_id].append({"role": "user", "content": user_text})
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=conversation_history[user_id],
        max_tokens=1024
    )
    reply_text = response.choices[0].message.content
    conversation_history[user_id].append({"role": "assistant", "content": reply_text})

    communicate = edge_tts.Communicate(reply_text, voice=voice)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out:
        await communicate.save(out.name)
        await update.message.reply_voice(voice=open(out.name, "rb"), caption=f"🎙️ {reply_text[:100]}...")

    os.unlink(voice_path)
    os.unlink(out.name)


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)
    await update.message.reply_text("✅ Suhbat tarixi tozalandi!")


async def foydalanuvchilar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Bu buyruq faqat admin uchun!")
        return

    if not user_list:
        await update.message.reply_text("👥 Hali foydalanuvchi yo'q.")
        return

    text = f"👥 Jami: {len(user_list)} ta foydalanuvchi\n\n"
    for user_id in user_list:
        try:
            user = await context.bot.get_chat(user_id)
            name = user.full_name or "—"
            username = f"@{user.username}" if user.username else "—"
            text += f"👤 {name}\n🔗 {username}\n🆔 {user_id}\n\n"
        except:
            text += f"🆔 {user_id}\n\n"

    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_list.add(update.effective_user.id)
    global message_count
    message_count += 1
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_state.get(user_id) == "waiting_edit":
        user_state.pop(user_id)
        prompt = last_image_prompt.get(user_id, "")
        if prompt:
            msg = await update.message.reply_text("🎨 Rasm o'zgartirilmoqda...")
            await _generate_and_send_image(update.message, f"{prompt}, {user_message}", msg, user_id)
        else:
            await update.message.reply_text("❌ Avvalgi rasm topilmadi.")
        return

    await update.message.chat.send_action("typing")

    # Imlo xatosini tekshirish
    corrected = await _check_typo(user_message)
    if corrected and corrected.lower() != user_message.lower():
        typo_correction[user_id] = corrected
        keyboard = [[
            InlineKeyboardButton("✅ Ha", callback_data="typo_ha"),
            InlineKeyboardButton("❌ Yo'q", callback_data="typo_yoq"),
        ]]
        await update.message.reply_text(
            f"Siz shuni demoqchimidingiz:\n*{corrected}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    intent = await _detect_intent(user_message)

    if intent == "rasm":
        msg = await update.message.reply_text("🎨 Rasm tayyorlanmoqda...")
        await _generate_and_send_image(update.message, user_message, msg, user_id)
        return

    msg = await update.message.reply_text("⏳ Javob tayyorlanmoqda...")
    await _process_chat(update.message, user_message, user_id, msg)


# ===================== MAIN =====================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("rasm", generate_image))
    app.add_handler(CommandHandler("video", download_video))
    app.add_handler(CommandHandler("fy", foydalanuvchilar))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.VIDEO, analyze_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    threading.Thread(target=run_health_server, daemon=True).start()
    logger.info("Bot ishga tushdi! ✅")

    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
