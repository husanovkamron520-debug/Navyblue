import os
import json
import logging
import random
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from google import genai
from google.genai import types

# --- LOGGING ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- CONFIG & ENV ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

AI_DAILY_LIMIT = 3
AI_MODEL_NAME = "gemini-2.5-flash"

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
ai_gate = asyncio.Semaphore(2)

# --- DATA FILES ---
CASES_FILE = "cases.json"
TEACHERS_FILE = "teachers.json"
STUDENTS_FILE = "students.json"

# --- HELPER FUNCTIONS FOR JSON ---
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error reading {filepath}: {e}")
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error writing {filepath}: {e}")

def get_cases(): return load_json(CASES_FILE, {})
def save_cases(data): save_json(CASES_FILE, data)

def get_teachers(): return load_json(TEACHERS_FILE, {})
def save_teachers(data): save_json(TEACHERS_FILE, data)

def get_students(): return load_json(STUDENTS_FILE, {})
def save_students(data): save_json(STUDENTS_FILE, data)

def get_teacher_code_by_chat_id(chat_id):
    teachers = get_teachers()
    for code, t_info in teachers.items():
        if t_info.get("chat_id") == chat_id:
            return code
    return None

# --- LONG TEXT SENDING ---
async def send_long(bot, chat_id, text, reply_markup=None):
    if len(text) <= 4000:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    else:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            markup = reply_markup if i == len(parts) - 1 else None
            await bot.send_message(chat_id=chat_id, text=part, reply_markup=markup)

# --- START & ROLE SELECTION ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    teachers = get_teachers()
    students = get_students()

    # Agar allaqachon o'qituvchi bo'lsa
    if user_id in [str(t["chat_id"]) for t in teachers.values()]:
        teacher_code = get_teacher_code_by_chat_id(update.effective_chat.id)
        kb = [["➕ Yangi keys qo'shish"], ["📊 O'quvchilar ro'yxati"]]
        await update.message.reply_text(
            f"👨‍🏫 Xush kelibsiz, O'qituvchi!\n"
            f"🔑 Sizning kodingiz: `{teacher_code}`\n"
            f"Keys qo'shish uchun pastdagi tugmani bosing yoki /addcase yuboring.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return

    # Agar allaqachon o'qituvchi kodiga biriktirilgan talaba bo'lsa
    if user_id in students and students[user_id].get("teacher_code"):
        kb = [["📌 Case'ni boshlash"]]
        await update.message.reply_text(
            f"Xush kelibsiz, {students[user_id].get('name', 'Talaba')}!\n\n"
            "Case yechishni boshlash uchun quyidagi tugmani bosing:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return

    # Yangi foydalanuvchi: Rolni tanlash uchun inline tugmalar chiqaramiz
    keyboard = [
        [
            InlineKeyboardButton("👨‍🏫 O'qituvchiman", callback_data="role_teacher"),
            InlineKeyboardButton("👨‍🎓 Talabaman", callback_data="role_student")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Assalomu alaykum! SCM Case botiga xush kelibsiz.\n\n"
        "Iltimos, botdan qaysi maqsadda foydalanishigizni tanlang:",
        reply_markup=reply_markup
    )

# --- CALLBACK QUERY (Rolni bosganda ishlaydi) ---

async def role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.message.chat_id)
    chat_id = query.message.chat_id
    teachers = get_teachers()

    if query.data == "role_teacher":
        # Avtomatik o'qituvchi sifatida ro'yxatdan o'tkazish
        existing_code = get_teacher_code_by_chat_id(chat_id)
        if existing_code:
            teacher_code = existing_code
        else:
            teacher_code = f"T_{str(chat_id)[-4:]}"
            teachers[teacher_code] = {
                "chat_id": chat_id,
                "name": query.from_user.full_name
            }
            save_teachers(teachers)

        kb = [["➕ Yangi keys qo'shish"], ["📊 O'quvchilar ro'yxati"]]
        await query.edit_message_text(
            f"✅ Siz O'qituvchi sifatida muvaffaqiyatli ro'yxatdan o'tdingiz!\n\n"
            f"🔑 **Sizning Kodingiz:** `{teacher_code}`\n\n"
            f"Ushbu kodni talabalaringizga yuboring. Keys qo'shish uchun quyidagi menyudan foydalaning.",
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text="Asosiy menyu:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )

    elif query.data == "role_student":
        context.user_data["awaiting_teacher_code"] = True
        await query.edit_message_text(
            "👨‍🎓 Siz Talaba sifatida tanlandingiz.\n\n"
            "Iltimos, o'qituvchingizdan olgan **O'qituvchi kodi**ni (masalan: `T_1234`) yuboring:"
        )

# --- MESSAGE HANDLER ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    students = get_students()
    teachers = get_teachers()

    # 1. O'qituvchi menyudagi tugmani bosganda
    if text == "➕ Yangi keys qo'shish":
        await update.message.reply_text(
            "✍️ Keys qo'shish uchun quyidagi formatda yuboring:\n\n"
            "`/addcase Sarlavha | Keys matni | 1-savol | 2-savol`",
            parse_mode="Markdown"
        )
        return

    # 2. Talaba o'qituvchi kodini yuborganda
    if context.user_data.get("awaiting_teacher_code"):
        if text in teachers:
            students[user_id] = {
                "name": update.effective_user.full_name,
                "teacher_code": text
            }
            save_students(students)
            context.user_data["awaiting_teacher_code"] = False
            kb = [["📌 Case'ni boshlash"]]
            await update.message.reply_text(
                f"✅ Tabriklayman! Siz `{teachers[text]['name']}` o'qituvchining guruhiga qo'shildingiz.\n\n"
                "Case yechishni boshlash uchun pastdagi tugmani bosing:",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
            )
        else:
            await update.message.reply_text("❌ Bunday O'qituvchi kodi topilmadi. Qaytadan to'g'ri kodni kiriting:")
        return

    # 3. Case boshlash tugmasi
    if text == "📌 Case'ni boshlash":
        student = students.get(user_id)
        if not student or not student.get("teacher_code"):
            context.user_data["awaiting_teacher_code"] = True
            await update.message.reply_text("Iltimos, avval o'qituvchingiz bergan kodni kiriting:")
            return

        teacher_code = student["teacher_code"]
        cases_db = get_cases()
        teacher_cases = cases_db.get(teacher_code, [])

        if not teacher_cases:
            await update.message.reply_text("O'qituvchingiz hali bu bazaga birorta ham keys yuklamagan. Biroz kuting.")
            return

        selected_case = random.choice(teacher_cases)
        context.user_data["current_case"] = selected_case
        context.user_data["awaiting_case_answer"] = True

        q_list = "\n".join([f"{i+1}) {q}" for i, q in enumerate(selected_case["questions"])])
        
        msg = (
            f"📋 **Case: {selected_case['title']}**\n\n"
            f"{selected_case['text']}\n\n"
            f"❓ **Savollar:**\n{q_list}\n\n"
            "✍️ *Javoblaringizni bitta xabarda tartib bilan yozib yuboring:*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # 4. Talabaning case javobini qabul qilish va AI baholashi
    if context.user_data.get("awaiting_case_answer"):
        selected_case = context.user_data.get("current_case")
        context.user_data["awaiting_case_answer"] = False

        await update.message.reply_text("⏳ Javobingiz qabul qilindi. AI Professor tahlil qilmoqda, kuting...")

        student = students[user_id]
        teacher_code = student["teacher_code"]
        teacher_info = teachers.get(teacher_code)

        prompt = (
            f"Siz ta'lim tizimidagi ultra-qattiqqo'l va adolatli professorsiz.\n"
            f"Case: {selected_case['title']}\n"
            f"Shart: {selected_case['text']}\n"
            f"Savollar: {selected_case['questions']}\n"
            f"Talabaning javobi: {text}\n\n"
            f"Javobni tahlil qiling. Agar plagiat yoki umumiy so'zlar bo'lsa past baho bering.\n"
            f"Format:\n1. Baho (1-100)\n2. Qisqa tahlil va kamchiliklar."
        )

        try:
            async with ai_gate:
                response = ai_client.models.generate_content(
                    model=AI_MODEL_NAME,
                    contents=prompt
                )
                ai_result = response.text
        except Exception as e:
            ai_result = f"AI baholashda xatolik yuz berdi: {e}"

        await update.message.reply_text(f"📊 **AI Professor Bahosi:**\n\n{ai_result}", parse_mode="Markdown")

        # Natijani FAQAT o'sha o'qituvchiga yuborish
        if teacher_info and teacher_info.get("chat_id"):
            t_msg = (
                f"📥 **Yangi Case Javobi!**\n\n"
                f"👤 **Talaba:** {student['name']}\n"
                f"📋 **Case:** {selected_case['title']}\n\n"
                f"💬 **Talaba Javobi:**\n{text}\n\n"
                f"🤖 **AI Bahosi:**\n{ai_result}"
            )
            await send_long(context.bot, teacher_info["chat_id"], t_msg)

        return

# --- COMMANDS ---

async def add_case_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    teacher_code = get_teacher_code_by_chat_id(chat_id)
    
    if not teacher_code:
        await update.message.reply_text("❌ Siz o'qituvchi emassiz!")
        return

    text = update.message.text.replace("/addcase", "").strip()
    if not text or "|" not in text:
        await update.message.reply_text(
            "Format xato!\nTo'g'ri format:\n"
            "`/addcase Sarlavha | Keys matni | 1-savol | 2-savol`",
            parse_mode="Markdown"
        )
        return

    parts = [p.strip() for p in text.split("|") if p.strip()]
    if len(parts) < 3:
        await update.message.reply_text("Kamida Sarlavha, Keys matni va 1 ta savol bo'lishi kerak!")
        return

    title = parts[0]
    case_text = parts[1]
    questions = parts[2:]

    cases = get_cases()
    if teacher_code not in cases:
        cases[teacher_code] = []

    new_id = len(cases[teacher_code]) + 1
    new_case = {
        "id": new_id,
        "title": title,
        "text": case_text,
        "questions": questions
    }
    cases[teacher_code].append(new_case)
    save_cases(cases)

    await update.message.reply_text(f"✅ Keys bazangizga qo'shildi!\n\n📌 Sarlavha: {title}")

# --- MAIN ---

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN topilmadi!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("addcase", add_case_command))
    app.add_handler(CallbackQueryHandler(role_callback, pattern="^role_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
