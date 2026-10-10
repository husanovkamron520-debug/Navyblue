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

AI_MODEL_NAME = "gemini-2.5-flash"

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
ai_gate = asyncio.Semaphore(2)

# --- DATA FILES ---
CASES_FILE = "cases.json"
TEACHERS_FILE = "teachers.json"
STUDENTS_FILE = "students.json"

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

async def send_long(bot, chat_id, text, reply_markup=None):
    if len(text) <= 4000:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    else:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            markup = reply_markup if i == len(parts) - 1 else None
            await bot.send_message(chat_id=chat_id, text=part, reply_markup=markup)

# --- START ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    
    # Har safar /start bosganda foydalanuvchi o'zi xohlagan rolni erkin tanlay olishi uchun inline tugmalar chiqaramiz
    keyboard = [
        [
            InlineKeyboardButton("👨‍🏫 O'qituvchi sifatida kirish", callback_data="role_teacher"),
            InlineKeyboardButton("👨‍🎓 Talaba sifatida kirish", callback_data="role_student")
        ]
    ]
    await update.message.reply_text(
        "👋 Assalomu alaykum! Botga xush kelibsiz.\n\n"
        "Iltimos, bu safar botdan qaysi rejimda foydalanishni xohlashingizni tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = str(chat_id)
    teachers = get_teachers()
    students = get_students()

    if query.data == "role_teacher":
        # Talabalar bazasidan o'chiramiz (agar oldin talaba bo'lgan bo'lsa)
        if user_id in students:
            del students[user_id]
            save_students(students)

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
            f"✅ **O'qituvchi rejimi faollashdi!**\n\n"
            f"🔑 Sizning O'qituvchi kodingiz: `{teacher_code}`\n"
            f"Talabalaringizga shu kodni bering.",
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
            "👨‍🎓 **Talaba rejimi tanlandi.**\n\n"
            "Iltimos, o'qituvchingizdan olgan **O'qituvchi kodi**ni (masalan: `T_1234`) shu yerga yuboring:"
        )

# --- MESSAGE HANDLER ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    students = get_students()
    teachers = get_teachers()
    teacher_code = get_teacher_code_by_chat_id(update.effective_chat.id)

    # 1. O'qituvchi "➕ Yangi keys qo'shish" tugmasini bosganda
    if text == "➕ Yangi keys qo'shish" and teacher_code:
        context.user_data["awaiting_new_case_text"] = True
        await update.message.reply_text(
            "✍️ Ajoyib! Endi shunchaki **keys matnini** yuboring (o'zim sarlavha va savollarga ajratib olaman):"
        )
        return

    # 2. O'qituvchi yuborgan keys matnini qabul qilish va saqlash
    if context.user_data.get("awaiting_new_case_text") and teacher_code:
        context.user_data["awaiting_new_case_text"] = False

        lines = text.split("\n")
        title = lines[0][:40] if lines else "Logistika Case"

        cases = get_cases()
        if teacher_code not in cases:
            cases[teacher_code] = []

        new_id = len(cases[teacher_code]) + 1
        new_case = {
            "id": new_id,
            "title": title,
            "text": text,
            "questions": ["Ushbu case bo'yicha tahlilingizni va yechimingizni yozing."]
        }
        cases[teacher_code].append(new_case)
        save_cases(cases)

        await update.message.reply_text(
            f"✅ **Keys muvaffaqiyatli saqlandi!**\n\n"
            f"📌 Sarlavha: {title}",
            parse_mode="Markdown"
        )
        return

    # 3. Talaba o'qituvchi kodini yuborganda
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
            await update.message.reply_text("❌ Bunday O'qituvchi kodi topilmadi. Qaytadan to'g'ri kiriting:")
        return

    # 4. Talaba "📌 Case'ni boshlash" tugmasini bosganda
    if text == "📌 Case'ni boshlash":
        student = students.get(user_id)
        if not student or not student.get("teacher_code"):
            context.user_data["awaiting_teacher_code"] = True
            await update.message.reply_text("Iltimos, avval o'qituvchingiz bergan kodni kiriting:")
            return

        t_code = student["teacher_code"]
        cases_db = get_cases()
        teacher_cases = cases_db.get(t_code, [])

        if not teacher_cases:
            await update.message.reply_text("O'qituvchingiz hali birorta ham keys yuklamagan.")
            return

        selected_case = random.choice(teacher_cases)
        context.user_data["current_case"] = selected_case
        context.user_data["awaiting_case_answer"] = True

        msg = (
            f"📋 **Case: {selected_case['title']}**\n\n"
            f"{selected_case['text']}\n\n"
            "✍️ *Javobingizni shu yerga yuboring:*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # 5. Talabaning javobini qabul qilish va AI baholashi
    if context.user_data.get("awaiting_case_answer"):
        selected_case = context.user_data.get("current_case")
        context.user_data["awaiting_case_answer"] = False

        await update.message.reply_text("⏳ Javobingiz qabul qilindi. AI Professor tahlil qilmoqda...")

        student = students[user_id]
        t_code = student["teacher_code"]
        teacher_info = teachers.get(t_code)

        prompt = (
            f"Siz ta'lim tizimidagi qattiqqo'l va adolatli professorsiz.\n"
            f"Case: {selected_case['title']}\n"
            f"Matn: {selected_case['text']}\n"
            f"Talabaning javobi: {text}\n\n"
            f"Javobni tahlil qiling va quyidagi formatda yuboring:\n"
            f"1. Baho (1-100)\n2. Qisqa tahlil va kamchiliklar."
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

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN topilmadi!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(role_callback, pattern="^role_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
