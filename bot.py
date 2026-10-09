import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
TEACHER_CHAT_ID = os.environ.get("TEACHER_CHAT_ID")  # raqam, keyinroq /whoami orqali olinadi
WEBHOOK_URL = os.environ["WEBHOOK_URL"]              # masalan https://navy-bot.onrender.com
PORT = int(os.environ.get("PORT", "10000"))
DONE_FILE = "done.json"

STUDENT_CODES = {
    "obsidian": "Utkir", "terracotta": "Sabina", "khaki": "Mirvosid", "lavender": "Surayyo",
    "celadon": "Abror", "vermilion": "Lobar", "lilac": "Malika", "sepia": "Nodira",
    "auburn": "Nozima", "olive": "Gulsevar", "indigo": "Faxriyor", "pitchgreen": "Hamidulla",
    "slate": "Shoxjahon", "emerald": "Doniyor", "hazel": "Zafar", "charcoal": "Olim",
    "navy": "Kamron", "metallic": "Shuhrat", "ash": "Sardor",
}

QUESTIONS = [
    {"q": "Ta'minot zanjiri odatda qaysi nuqtadan boshlanadi?",
     "opts": ["Ishlab chiqarish quvvatidan", "Mijoz talabi va bozor signallaridan", "Transport tarifidan", "Ombor joylashuvidan"], "correct": 1},
    {"q": "S&OP (Sales & Operations Planning) ning asosiy vazifasi nima?",
     "opts": ["Faqat moliyaviy hisobot tayyorlash", "Talab, supply, capacity, inventory va biznes rejasini bitta umumiy rejaga uyg'unlashtirish", "Transport tarifini belgilash", "Reklama byudjetini taqsimlash"], "correct": 1},
    {"q": "Supplier tanlashda eng past narxga qarash nega yetarli emas?",
     "opts": ["Narx bu yerda umuman ahamiyatsiz", "Quality, delivery, capacity va risk kabi omillar ham umumiy qiymatga ta'sir qiladi", "Supplierlar narxni o'zlari belgilamaydi", "Bu faqat xalqaro yetkazib beruvchilarga tegishli"], "correct": 1},
    {"q": "ABC analysis nimaga xizmat qiladi?",
     "opts": ["Transport marshrutini optimallashtirishga", "Inventoryni qiymat/ahamiyatiga ko'ra guruhlab, prioritet berishga (Pareto tamoyili)", "Bojxona deklaratsiyasini to'ldirishga", "Ishchilar smenasini rejalashtirishga"], "correct": 1},
    {"q": "Talab=50/kun, Buyurtma xarajati=$90, Saqlash xarajati=$0.5/birlik/kun. EOQ taxminan nechaga teng?",
     "opts": ["110", "122", "134", "148"], "correct": 2},
    {"q": "Kunlik talab=30, Lead Time=6 kun, Safety Stock=25. ROP nechaga teng?",
     "opts": ["190", "205", "215", "230"], "correct": 1},
    {"q": "Safety Stockning asosiy maqsadi nima?",
     "opts": ["Omborni imkon qadar to'ldirib turish", "Talab/yetkazishdagi noaniqlik tufayli stockout xavfini kamaytirish", "Transport tezligini oshirish", "Yetkazib beruvchilar sonini kamaytirish"], "correct": 1},
    {"q": "WMS (Warehouse Management System) asosan nimani boshqaradi?",
     "opts": ["Buxgalteriya hisobotlarini", "Ombor operatsiyalari va inventory lokatsiyasini real vaqtda boshqarishni", "Marketing kampaniyalarini", "Ishchilarning ish haqini hisoblashni"], "correct": 1},
    {"q": "OTIF nimani anglatadi?",
     "opts": ["Yetkazish narxini baholash ko'rsatkichi", "On-Time In-Full — buyurtmaning vaqtida VA to'liq yetkazilish foizi", "Ombordagi aylanma mablag' koeffitsienti", "Transport turini tanlash mezoni"], "correct": 1},
    {"q": "Reverse logistics qaysi jarayonni bildiradi?",
     "opts": ["Mahsulotni fabrikadan omborga yuborish jarayonini", "Mahsulotni mijozdan qaytarish, tekshirish, ta'mirlash yoki utilizatsiya qilish oqimini", "Xalqaro eksport hujjatlari jarayonini", "Yangi supplier qidirish jarayonini"], "correct": 1},
    {"q": "Supply chainning uch asosiy oqimi qaysilar?",
     "opts": ["Material, Information, Financial", "Road, Rail, Air", "Demand, Supply, Price", "Plan, Do, Check"], "correct": 0},
    {"q": "Bullwhip effect nima?",
     "opts": ["Yetkazib beruvchining bankrot bo'lishi", "Talabdagi kichik o'zgarishning zanjir bo'ylab yuqoriga ko'tarilgan sari kattalashib ketishi", "Transport narxining mavsumiy oshishi", "Ombordagi avtomatlashtirish darajasi"], "correct": 1},
    {"q": "Qaysi kombinatsiya zamonaviy SCM texnologik stackiga mos keladi?",
     "opts": ["ERP, WMS, TMS va analytics tizimlarining integratsiyasi", "Ijtimoiy tarmoq boshqaruv vositalari", "Faqat buxgalteriya dasturi", "Faqat video konferensiya vositasi"], "correct": 0},
    {"q": "Risk managementda contingency plan nimaga kerak?",
     "opts": ["Muammo kelib chiqmaydi deb faraz qilishga", "Uzilish (disruption) yuz berganda oldindan tayyorlangan muqobil rejani ishga tushirishga", "Faqat sug'urta polisini sotib olishga", "Faqat narxni oshirishga"], "correct": 1},
    {"q": "Sustainable SCM nimani kengaytiradi?",
     "opts": ["Faqat tezlik va narxni optimallashtirishni", "Cost va service bilan birga environmental va social ta'sirni ham hisobga olishni", "Faqat qadoqlash dizaynini o'zgartirishni", "Faqat mahalliy yetkazib beruvchilardan xarid qilishni"], "correct": 1},
    {"q": "SCOR mantig'idagi Plan → Source → Make → Deliver → Return nimani beradi?",
     "opts": ["Faqat moliyaviy audit uchun framework", "Supply chain jarayonlarini yagona umumiy frameworkda ko'rish imkonini", "Faqat IT infratuzilmasini loyihalash usulini", "Faqat HR baholash tizimini"], "correct": 1},
    {"q": "Incoterms nimani belgilaydi?",
     "opts": ["Mahsulotning bozor narxini", "Xalqaro yetkazishda xarajat va risk kimga qachon o'tishini", "Bojxona bojining aniq stavkasini", "Valyuta ayirboshlash kursini"], "correct": 1},
    {"q": "Nega ba'zan havo transporti dengiz transportidan qimmat bo'lsa ham tanlanadi?",
     "opts": ["Chunki havo transporti doim arzonroq bo'ladi", "Yetkazish tezligi muhimroq bo'lgan holatlarda (tez buziluvchi yoki trend mahsulot)", "Chunki dengiz transporti bu yo'nalishda mavjud emas", "Chunki bu bojxona tomonidan talab qilinadi"], "correct": 1},
    {"q": "Demand Forecasting nega hech qachon 100% aniq bo'lmaydi?",
     "opts": ["Chunki statistik usullar umuman ishlamaydi", "Kelajakdagi bozor xatti-harakati noaniqlikni o'z ichiga oladi — prognoz qaror uchun signal, kafolat emas", "Chunki talab har doim bir xil bo'ladi", "Chunki faqat tarixiy ma'lumot kerak emas"], "correct": 1},
    {"q": "Cold Chain logistikasi nima uchun oddiy tashishdan qimmatroq?",
     "opts": ["Faqat uzoqroq masofaga yuborilgani uchun", "Butun yo'l davomida belgilangan harorat rejimini uzluksiz saqlash qo'shimcha texnologiya va nazorat talab qilgani uchun", "Faqat og'irligi ko'proq bo'lgani uchun", "Faqat hujjat ishlari ko'proq bo'lgani uchun"], "correct": 1},
]

sessions = {}  # chat_id -> {"code":..., "name":..., "i":0, "score":0}


def load_done():
    try:
        with open(DONE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_done(d):
    with open(DONE_FILE, "w") as f:
        json.dump(d, f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xush kelibsiz!\nDavom etish uchun shaxsiy kodingizni yuboring (masalan: navy)"
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning chat_id: {update.effective_chat.id}")


async def send_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    s = sessions[chat_id]
    if s["i"] >= len(QUESTIONS):
        await finish(context, chat_id)
        return
    q = QUESTIONS[s["i"]]
    labels = ["A", "B", "C", "D"]
    kb = [[InlineKeyboardButton(f"{labels[oi]}. {opt}", callback_data=str(oi))]
          for oi, opt in enumerate(q["opts"])]
    await context.bot.send_message(
        chat_id,
        f"Savol {s['i']+1}/{len(QUESTIONS)}\n\n{q['q']}",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in sessions:
        return  # test davomida erkin matnni e'tiborsiz qoldiramiz
    text = (update.message.text or "").strip().lower()
    name = STUDENT_CODES.get(text)
    if not name:
        await update.message.reply_text("Kod topilmadi. Qaytadan urinib ko'ring.")
        return
    done = load_done()
    if text in done:
        r = done[text]
        await update.message.reply_text(
            f"Salom, {r['name']}! Siz bu kodni allaqachon topshirgansiz — qayta ishlash o'chirilgan.\n"
            f"Natijangiz: {r['score']}/{r['total']} ({r['pct']}%) — 90 ballik: {r['ball90']}"
        )
        return
    sessions[chat_id] = {"code": text, "name": name, "i": 0, "score": 0}
    await update.message.reply_text(f"Salom, {name}! Test boshlanadi — {len(QUESTIONS)} ta savol.")
    await send_question(context, chat_id)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    if chat_id not in sessions:
        await query.answer()
        return
    s = sessions[chat_id]
    q = QUESTIONS[s["i"]]
    chosen = int(query.data)
    correct = q["correct"]
    if chosen == correct:
        s["score"] += 1
        await query.answer("✅ To'g'ri!")
    else:
        await query.answer("❌ Noto'g'ri")
    labels = ["A", "B", "C", "D"]
    await query.edit_message_text(
        f"{q['q']}\n\nSiz tanladingiz: {labels[chosen]}. {q['opts'][chosen]}\n"
        f"To'g'ri javob: {labels[correct]}. {q['opts'][correct]}"
    )
    s["i"] += 1
    await send_question(context, chat_id)


async def finish(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    s = sessions.pop(chat_id)
    total = len(QUESTIONS)
    pct = round(s["score"] / total * 100)
    ball90 = round(s["score"] / total * 90)
    await context.bot.send_message(
        chat_id,
        f"🎉 Test tugadi!\n{s['score']}/{total} to'g'ri ({pct}%)\n90 ballik tizimda: {ball90} ball"
    )
    done = load_done()
    done[s["code"]] = {"name": s["name"], "score": s["score"], "total": total, "pct": pct, "ball90": ball90}
    save_done(done)
    if TEACHER_CHAT_ID:
        try:
            await context.bot.send_message(
                int(TEACHER_CHAT_ID),
                f"📥 {s['name']} ({s['code']}): {s['score']}/{total} ({pct}%) — {ball90}/90"
            )
        except Exception as e:
            logging.warning("Teacher notify failed: %s", e)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )


if __name__ == "__main__":
    main()
