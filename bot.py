import os
import json
import random
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
TEACHER_CHAT_ID = os.environ.get("TEACHER_CHAT_ID")
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
PORT = int(os.environ.get("PORT", "10000"))
DONE_FILE = "done.json"
CASES_FILE = "cases.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
gemini_client = None
if GEMINI_API_KEY:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
ai_gate = asyncio.Semaphore(2)

ai_usage = {}
AI_DAILY_LIMIT = 3

DEFAULT_CASES = [
    {
        "title": "Smart Ombor va RFID teglar sirlari",
        "text": (
            "Katta kiyim-kechak do'konlari tarmog'i ombor operatsiyalarini tezlashtirish uchun har bir kiyimga "
            "RFID (radiochastotali identifikatsiya) teglarini yopishtirib chiqdi. Endi omborchi har bir qutini "
            "ochib sanab o'tirmaydi, skaner bilan quti yonidan o'tsa, ichidagi 50 ta kiyim soniyasiga tizimga tushadi.\n\n"
            "Lekin qishki kolleksiya kelganda kutilmagan muammo chiqdi: metall tugmali va zanjirli (molniya) qalin "
            "kurtkalar solingan qutilarni skanerlaganda tizim 50 ta kiyim o'rniga 30-35 ta kiyim ko'rsata boshladi. "
            "Ishchilar tizim buzildi deb o'ylab, yana eski usulda qo'lda sanashga majbur bo'lishdi va jo'natish vaqti kechikdi."
        ),
        "questions": [
            "1) Muammoni aniqlang: nima uchun yozgi yengil kiyimlarda yaxshi ishlagan RFID skaneri qishki metall "
            "detallari bor kurtkalarda xato berdi? (fizik va texnologik sabab)",
            "2) Amaliy yechim: ombor jarayonini to'xtatmasdan va qutilarni bittalab ochmasdan, bu muammoni raqamli "
            "yoki operatsion jihatdan qanday hal qilish mumkin?",
        ],
        "crit": [
            "Metall yuzalar radio-to'lqinlarni (RFID signalini) to'sishi yoki aks ettirishi (interference) to'g'ri tushuntirgani",
            "Anti-metal RFID teglari, skanerlash burchagi yoki joylashtirish tartibini o'zgartirish kabi amaliy yechim bergani",
            "Javob aniq va mantiqiy tartibda yozilgani",
        ],
    },
    {
        "title": "Aqlli marshrut (GPS) va yoqilg'i tejamkorligi",
        "text": (
            "Logistika kompaniyasi yuk mashinalari haydovchilariga eng maqbul yo'lni ko'rsatuvchi sun'iy intellektga "
            "asoslangan Aqlli GPS Navigator o'rnatdi. Tizimning maqsadi - masofani qisqartirish va yoqilg'ini tejash.\n\n"
            "Tizim haydovchi Akmalga shahar markazidagi tirband chorrahani aylanib o'tish uchun kichik mahallalar va tor "
            "ko'chalar orqali o'tadigan 3 km qisqaroq yo'lni ko'rsatdi. Biroq Akmal ushbu yo'ldan yurganida mashina "
            "asosiy katta yo'ldagidan ko'ra 20% ko'proq yoqilg'i sarfladi va vaqt jihatidan ham kechikdi."
        ),
        "questions": [
            "1) Mantiqiy tahlil: masofa 3 km ga qisqargan bo'lsa-da, nima uchun yoqilg'i sarfi va vaqt ko'payib ketdi? "
            "AI algoritmi yo'l tanlashda qaysi muhim omillarni e'tiborsiz qoldirgan?",
            "2) Algoritmga tuzatish: navigator algoritmini mukammallashtirish uchun unga masofadan tashqari yana qanday "
            "2 ta ko'rsatkichni (metrikani) qo'shish kerak?",
        ],
        "crit": [
            "Masofa qisqargan bo'lsa-da, tor ko'chalardagi tez-tez to'xtashlar va tezlik cheklovi yoqilg'i sarfini oshirganini mantiqan asoslagani",
            "GPS algoritmiga o'rtacha harakatlanish tezligi va to'xtashlar soni (svetoforlar/mahalla yo'li) kabi 2 ta yangi ko'rsatkich taklif qilgani",
            "Mantiqiy xulosa va aniq bayon",
        ],
    },
]

def load_cases():
    if os.path.exists(CASES_FILE):
        try:
            with open(CASES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data: return data
        except Exception:
            pass
    return DEFAULT_CASES

def save_cases(cases_list):
    with open(CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cases_list, f, ensure_ascii=False, indent=2)

CRIT_MAX = [4, 4, 2]
CRIT_NAMES = ["tub sabab", "yechim", "struktura"]
pending = {}  
case_bag = []

def next_case():
    global case_bag
    cases = load_cases()
    if not case_bag:
        case_bag = list(range(len(cases)))
        random.shuffle(case_bag)
    return case_bag.pop()

def level(total):
    if total >= 45: return "🥇 A'lo (Top Analitik)"
    if total >= 35: return "🥈 Yaxshi"
    if total >= 25: return "🥉 Qoniqarli"
    return "❌ Qoniqarsiz"

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📝 Testni boshlash"), KeyboardButton("📌 Case'ni boshlash")],
        [KeyboardButton("ℹ️ Yordam")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def send_long(bot, chat_id, text, reply_markup=None):
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    for i, ch in enumerate(chunks):
        await bot.send_message(chat_id, ch, reply_markup=reply_markup if i == len(chunks) - 1 else None)

def _grade_sync(items):
    cases = load_cases()
    parts = []
    for n, (ci, ans) in enumerate(items, 1):
        c = cases[ci]
        parts.append(
            f"=== KEYS #{n}: {c['title']} ===\nMATN: {c['text']}\nSAVOLLAR: {' '.join(c['questions'])}\n"
            f"MEZONLAR: (a) 0-4 ball: {c['crit'][0]}; (b) 0-4 ball: {c['crit'][1]}; (c) 0-2 ball: {c['crit'][2]}\n"
            f"TALABA JAVOBI:\n{ans}\n"
        )
    prompt = (
        "Sen supply chain management fanidan dunyodagi eng qattiqqo'l, shubhako'r, talabchan va xato kechirmaydigan professor-o'qituvchisan. "
        "Talabaning quyidagi keys javoblarini tekshirayotganda o'ta shubhali va murosasiz bo'l.\n\n"
        "O'TA QATTIQ TALABLAR:\n"
        "1. Ko'chirma va qolipni aniqlash: Agar talabaning javobida sun'iy intellektga yoki darsliklarga xos bo'lgan o'ta qolip, "
        "rasmiy, sun'iy iboralar (masalan, 'ushbu muammoni hal etish maqsadida', 'xulosa o'rnida', 'ko'rsatkichlarni yaxshilash lozim') "
        "ishlatilgan bo'lsa, uni darhol 'AI generated' yoki internetdan ko'chirma deb hisobla.\n"
        "2. Shaxsiy mantiq talabi: Talaba aynan o'sha vaziyatga nisbatan o'zining shaxsiy, oddiy va real hayotiy mantiqiy "
        "tahlilini yozmagan bo'lsa, garchi javob to'g'ri tuyulsa ham uni ko'chirma deb bahola.\n"
        "3. Jazo: Agar shubhang bo'lsa yoki ko'chirma ekanligi sezilsa, yechim (b) va struktura (c) ballarini shafqatsizlarcha "
        "0 yoki 1 ballga tushirib yubor! Rahm qilma.\n\n"
        "Har keys 10 ball: (a) tub sababni aniqlash 0-4, (b) analitik/amaliy yechim 0-4, "
        "(c) javob strukturasi va aniqligi 0-2.\n\n"
        + "\n".join(parts)
        + "\nFaqat JSON qaytar, keyslar kiritilgan tartibda, aynan "
        + str(len(items))
        + " ta element: {\"keyslar\":[{\"a\":int,\"b\":int,\"c\":int,\"izoh\":\"o'zbek tilida, qattiqqo'llik bilan tanqidiy tahlil qilib, nima uchun past ball qo'yilgani yoki ko'chirmaligi yozilsin\"}]}"
    )
    resp = gemini_client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(resp.text)["keyslar"]
    results = []
    for d in data:
        sc = [max(0, min(int(d.get(k, 0)), CRIT_MAX[i])) for i, k in enumerate(("a", "b", "c"))]
        results.append((sc, str(d.get("izoh", ""))))
    return results

last_error = ""

async def grade(items):
    global last_error
    async with ai_gate:
        for attempt in range(2):
            try:
                return await asyncio.to_thread(_grade_sync, items)
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logging.warning("Gemini xato (%s): %s", attempt + 1, e)
                await asyncio.sleep(5)
    return None

def _is_teacher(update):
    return TEACHER_CHAT_ID and str(update.effective_chat.id) == str(TEACHER_CHAT_ID)

async def aitest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_teacher(update): return
    if not gemini_client:
        await update.message.reply_text("GEMINI_API_KEY topilmadi.")
        return
    try:
        resp = await asyncio.to_thread(
            lambda: gemini_client.models.generate_content(model=GEMINI_MODEL, contents="Faqat 'ok' deb javob ber.")
        )
        await update.message.reply_text(f"✅ Ishlayapti. Model: {GEMINI_MODEL}\nJavob: {resp.text[:100]}")
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {type(e).__name__}: {str(e)[:800]}")

async def modellar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_teacher(update): return
    if not gemini_client:
        await update.message.reply_text("GEMINI_API_KEY topilmadi.")
        return
    def _list():
        out = []
        for m in gemini_client.models.list():
            acts = getattr(m, "supported_actions", None) or []
            if "generateContent" in acts:
                out.append(m.name.replace("models/", ""))
        return out
    try:
        names = await asyncio.to_thread(_list)
        await update.message.reply_text(f"Hozirgi model: {GEMINI_MODEL}\n\nMavjud modellar:\n" + "\n".join(names[:40]))
    except Exception as e:
        await update.message.reply_text(f"❌ Ro'yxat olinmadi: {e}")

async def addcase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_teacher(update): return
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text(
            "❌ Xato format!\n"
            "Ishlatish: `/addcase Sarlavha | Matn | 1-savol | 2-savol`",
            parse_mode="Markdown"
        )
        return
    title = parts[0]
    case_text = parts[1]
    questions = parts[2:]
    
    crit = [
        "Tub sababni to'g'ri va mantiqiy tahlil qilgani",
        "Amaliy va raqamli yechim taklif qilgani",
        "Javob aniq va tuzilmali yozilgani"
    ]
    
    cases = load_cases()
    cases.append({
        "title": title,
        "text": case_text,
        "questions": questions,
        "crit": crit
    })
    save_cases(cases)
    global case_bag
    case_bag = [] 
    await update.message.reply_text(f"✅ Yangi keys qo'shildi!\nJami keyslar soni: {len(cases)}")

def format_grade(name, items, results):
    cases = load_cases()
    lines = [f"📝 {name} — Keys natijasi"]
    total = 0
    for (ci, _), (sc, izoh) in zip(items, results):
        sub = sum(sc)
        total += sub
        lines.append(
            f"\n{ci+1}-keys ({cases[ci]['title']}): {sub}/10\n"
            f"  {CRIT_NAMES[0]} {sc[0]}/4 · {CRIT_NAMES[1]} {sc[1]}/4 · {CRIT_NAMES[2]} {sc[2]}/2\n{izoh}"
        )
    scaled = round(total * 50 / (10 * len(items)))
    lines.append(f"\nKeys bali: {total}/{10*len(items)}")
    lines.append(f"JAMI (50 ballik tizimda): {scaled}/50 — {level(scaled)}")
    return "\n".join(lines)

STUDENT_CODES = {
    "obsidian": "Utkir", "terracotta": "Sabina", "khaki": "Mirvosid", "lavender": "Surayyo",
    "celadon": "Abror", "vermilion": "Lobar", "lilac": "Malika", "sepia": "Nodira",
    "auburn": "Nozima", "olive": "Gulsevar", "indigo": "Faxriyor", "pitchgreen": "Hamidulla",
    "slate": "Shoxjahon", "emerald": "Doniyor", "hazel": "Zafar", "charcoal": "Olim",
    "navy": "Kamron", "metallic": "Shuhrat", "ash": "Sardor",
}

QUESTIONS = [
    {"q": "Ta'minot zanjiri odatda qaysi nuqtadan boshlanadi?", "opts": ["Ishlab chiqarish quvvatidan", "Mijoz talabi va bozor signallaridan", "Transport tarifidan", "Ombor joylashuvidan"], "correct": 1},
    {"q": "S&OP (Sales & Operations Planning) ning asosiy vazifasi nima?", "opts": ["Faqat moliyaviy hisobot tayyorlash", "Talab, supply, capacity, inventory va biznes rejasini bitta umumiy rejaga uyg'unlashtirish", "Transport tarifini belgilash", "Reklama byudjetini taqsimlash"], "correct": 1},
    {"q": "Supplier tanlashda eng past narxga qarash nega yetarli emas?", "opts": ["Narx bu yerda umuman ahamiyatsiz", "Quality, delivery, capacity va risk kabi omillar ham umumiy qiymatga ta'sir qiladi", "Supplierlar narxni o'zlari belgilamaydi", "Bu faqat xalqaro yetkazib beruvchilarga tegishli"], "correct": 1},
    {"q": "ABC analysis nimaga xizmat qiladi?", "opts": ["Transport marshrutini optimallashtirishga", "Inventoryni qiymat/ahamiyatiga ko'ra guruhlab, prioritet berishga (Pareto tamoyili)", "Bojxona deklaratsiyasini to'ldirishga", "Ishchilar smenasini rejalashtirishga"], "correct": 1},
    {"q": "Talab=50/kun, Buyurtma xarajati=$90, Saqlash xarajati=$0.5/birlik/kun. EOQ taxminan nechaga teng?", "opts": ["110", "122", "134", "148"], "correct": 2},
    {"q": "Kunlik talab=30, Lead Time=6 kun, Safety Stock=25. ROP nechaga teng?", "opts": ["190", "205", "215", "230"], "correct": 1},
    {"q": "Safety Stockning asosiy maqsadi nima?", "opts": ["Omborni imkon qadar to'ldirib turish", "Talab/yetkazishdagi noaniqlik tufayli stockout xavfini kamaytirish", "Transport tezligini oshirish", "Yetkazib beruvchilar sonini kamaytirish"], "correct": 1},
    {"q": "WMS (Warehouse Management System) asosan nimani boshqaradi?", "opts": ["Buxgalteriya hisobotlarini", "Ombor operatsiyalari va inventory lokatsiyasini real vaqtda boshqarishni", "Marketing kampaniyalarini", "Ishchilarning ish haqini hisoblashni"], "correct": 1},
    {"q": "OTIF nimani anglatadi?", "opts": ["Yetkazish narxini baholash ko'rsatkichi", "On-Time In-Full — buyurtmaning vaqtida VA to'liq yetkazilish foizi", "Ombordagi aylanma mablag' koeffitsienti", "Transport turini tanlash mezoni"], "correct": 1},
    {"q": "Reverse logistics qaysi jarayonni bildiradi?", "opts": ["Mahsulotni fabrikadan omborga yuborish jarayonini", "Mahsulotni mijozdan qaytarish, tekshirish, ta'mirlash yoki utilizatsiya qilish oqimini", "Xalqaro eksport hujjatlari jarayonini", "Yangi supplier qidirish jarayonini"], "correct": 1},
    {"q": "Supply chainning uch asosiy oqimi qaysilar?", "opts": ["Material, Information, Financial", "Road, Rail, Air", "Demand, Supply, Price", "Plan, Do, Check"], "correct": 0},
    {"q": "Bullwhip effect nima?", "opts": ["Yetkazib beruvchining bankrot bo'lishi", "Talabdagi kichik o'zgarishning zanjir bo'ylab yuqoriga ko'tarilgan sari kattalashib ketishi", "Transport narxining mavsumiy oshishi", "Ombordagi avtomatlashtirish darajasi"], "correct": 1},
    {"q": "Qaysi kombinatsiya zamonaviy SCM texnologik stackiga mos keladi?", "opts": ["ERP, WMS, TMS va analytics tizimlarining integratsiyasi", "Ijtimoiy tarmoq boshqaruv vositalari", "Faqat buxgalteriya dasturi", "Faqat video konferensiya vositasi"], "correct": 0},
    {"q": "Risk managementda contingency plan nimaga kerak?", "opts": ["Muammo kelib chiqmaydi deb faraz qilishga", "Uzilish (disruption) yuz berganda oldindan tayyorlangan muqobil rejani ishga tushirishga", "Faqat sug'urta polisini sotib olishga", "Faqat narxni oshirishga"], "correct": 1},
    {"q": "Sustainable SCM nimani kengaytiradi?", "opts": ["Faqat tezlik va narxni optimallashtirishni", "Cost va service bilan birga environmental va social ta'sirni ham hisobga olishni", "Faqat qadoqlash dizaynini o'zgartirishni", "Faqat mahalliy yetkazib beruvchilardan xarid qilishni"], "correct": 1},
    {"q": "SCOR mantig'idagi Plan → Source → Make → Deliver → Return nimani beradi?", "opts": ["Faqat moliyaviy audit uchun framework", "Supply chain jarayonlarini yagona umumiy frameworkda ko'rish imkonini", "Faqat IT infratuzilmasini loyihalash usulini", "Faqat HR baholash tizimini"], "correct": 1},
    {"q": "Incoterms nimani belgilaydi?", "opts": ["Mahsulotning bozor narxini", "Xalqaro yetkazishda xarajat va risk kimga qachon o'tishini", "Bojxona bojining aniq stavkasini", "Valyuta ayirboshlash kursini"], "correct": 1},
    {"q": "Nega ba'zan havo transporti dengiz transportidan qimmat bo'lsa ham tanlanadi?", "opts": ["Chunki havo transporti doim arzonroq bo'ladi", "Yetkazish tezligi muhimroq bo'lgan holatlarda (tez buziluvchi yoki trend mahsulot)", "Chunki dengiz transporti bu yo'nalishda mavjud emas", "Chunki bu bojxona tomonidan talab qilinadi"], "correct": 1},
    {"q": "Demand Forecasting nega hech qachon 100% aniq bo'lmaydi?", "opts": ["Chunki statistik usullar umuman ishlamaydi", "Kelajakdagi bozor xatti-harakati noaniqlikni o'z ichiga oladi — prognoz qaror uchun signal, kafolat emas", "Chunki talab har doim bir xil bo'ladi", "Chunki faqat tarixiy ma'lumot kerak emas"], "correct": 1},
    {"q": "Cold Chain logistikasi nima uchun oddiy tashishdan qimmatroq?", "opts": ["Faqat uzoqroq masofaga yuborilgani uchun", "Butun yo'l davomida belgilangan harorat rejimini uzluksiz saqlash qo'shimcha texnologiya va nazorat talab qilgani uchun", "Faqat og'irligi ko'proq bo'lgani uchun", "Faqat hujjat ishlari ko'proq bo'lgani uchun"], "correct": 1},
]

sessions = {}      
case_sessions = {} 

def load_json(filename):
    try:
        with open(filename) as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filename, d):
    with open(filename, "w") as f:
        json.dump(d, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xush kelibsiz!\nDavom etish uchun shaxsiy kodingizni yuboring (masalan: navy)",
        reply_markup=get_main_keyboard()
    )

async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning chat_id: {update.effective_chat.id}")

async def send_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    s = sessions[chat_id]
    if s["i"] >= len(QUESTIONS):
        await finish_test(context, chat_id)
        return
    q = QUESTIONS[s["i"]]
    labels = ["A", "B", "C", "D"]
    kb = [[InlineKeyboardButton(f"{labels[oi]}. {opt}", callback_data=str(oi))]
          for oi, opt in enumerate(q["opts"])]
    text = f"Savol {s['i']+1}/{len(QUESTIONS)}\n\n{q['q']}"
    await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))

async def finish_test(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    s = sessions.pop(chat_id, None)
    if not s: return
    total = len(QUESTIONS)
    pct = round(s["score"] / total * 100)
    ball90 = round(s["score"] / total * 90)
    await context.bot.send_message(
        chat_id,
        f"🎉 Test tugadi!\n{s['score']}/{total} to'g'ri ({pct}%)\n90 ballik tizimda: {ball90} ball",
        reply_markup=get_main_keyboard()
    )
    done = load_json(DONE_FILE)
    done[s["code"]] = {"name": s["name"], "score": s["score"], "total": total, "pct": pct, "ball90": ball90}
    save_json(DONE_FILE, done)
    if TEACHER_CHAT_ID:
        try:
            await context.bot.send_message(
                int(TEACHER_CHAT_ID),
                f"📥 Test natijasi: {s['name']} ({s['code']}): {s['score']}/{total} ({pct}%) — {ball90}/90"
            )
        except Exception as e:
            logging.warning("Teacher notify failed: %s", e)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text_input = (update.message.text or "").strip()
    
    if chat_id in case_sessions:
        s = case_sessions[chat_id]
        s["answer"].append(text_input)
        await update.message.reply_text("Qabul qilindi. Davom eting yoki «Javobni yuborish» tugmasini bosing.")
        return

    if text_input == "📝 Testni boshlash":
        await update.message.reply_text("Testni boshlash uchun shaxsiy kodingizni kiriting (masalan: navy).")
        return
    elif text_input == "📌 Case'ni boshlash":
        await update.message.reply_text("Case ishlash uchun shaxsiy kodingizni kiriting (masalan: navy).")
        return
    elif text_input == "ℹ️ Yordam":
        await update.message.reply_text("Bu bot supply chain management fanidan test va amaliy keyslarni topshirish uchun mo'ljallangan.")
        return

    code_text = text_input.lower()
    name = STUDENT_CODES.get(code_text)
    if not name:
        await update.message.reply_text("Kod topilmadi. Qaytadan urinib ko'ring.")
        return

    sessions[chat_id] = {"code": code_text, "name": name, "i": 0, "score": 0, "started": False}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Testni boshlash", callback_data="start_test")],
        [InlineKeyboardButton("📌 Case'ni boshlash", callback_data="start_case")]
    ])
    await update.message.reply_text(
        f"Salom, {name}! Quyidagilardan birini tanlang:",
        reply_markup=kb,
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id

    if query.data.startswith("ap:"):
        if not _is_teacher(update):
            await query.answer()
            return
        p = pending.pop(query.data[3:], None)
        if not p:
            await query.answer("Ma'lumot topilmadi yoki bot qayta ishga tushgan.", show_alert=True)
            return
        await send_long(context.bot, p["chat_id"], p["text"])
        await query.answer("Yuborildi ✅")
        await query.edit_message_reply_markup(None)
        return

    if query.data == "start_test":
        if chat_id not in sessions:
            await query.answer("Sessiya topilmadi, kodingizni qaytadan yuboring.", show_alert=True)
            return
        s = sessions[chat_id]
        done = load_json(DONE_FILE)
        if s["code"] in done:
            r = done[s["code"]]
            await query.answer("Siz bu testni allaqachon topshirgansiz!", show_alert=True)
            await query.edit_message_text(
                f"Salom, {r['name']}! Siz testni allaqachon topshirgansiz.\n"
                f"Natijangiz: {r['score']}/{r['total']} ({r['pct']}%) — 90 ballik: {r['ball90']}"
            )
            return
        s["started"] = True
        await query.answer()
        await query.edit_message_text(f"Salom, {s['name']}! Test boshlandi. Omad! 🍀")
        await send_question(context, chat_id)
        return

    if query.data == "start_case":
        if chat_id not in sessions:
            await query.answer("Sessiya topilmadi, kodingizni qaytadan yuboring.", show_alert=True)
            return
        s = sessions[chat_id]
        code = s["code"]
        name = s["name"]
        
        today = datetime.now().strftime("%Y-%m-%d")
        usage = ai_usage.get(code, {"date": "", "count": 0})
        if usage["date"] != today:
            usage = {"date": today, "count": 0}
            
        if usage["count"] >= AI_DAILY_LIMIT:
            await query.answer(f"Siz bugungi AI limitidan ({AI_DAILY_LIMIT} ta) foydalanib bo'ldingiz!", show_alert=True)
            return

        ci = next_case()
        case_sessions[chat_id] = {"code": code, "name": name, "ci": ci, "answer": []}
        cases = load_cases()
        c = cases[ci]
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Keys javobini yuborish", callback_data="submit_case")]])
        await query.answer()
        await query.edit_message_text(
            f"📌 Amaliy Keys: {c['title']}\n\n{c['text']}\n\n" + "\n".join(c["questions"]) +
            "\n\nJavobingizni shu chatga matn ko'rinishida yuboring (bir nechta xabar bo'lishi mumkin). "
            "Tugatgach, pastdagi tugmani bosing.",
            reply_markup=kb,
        )
        return

    if query.data == "submit_case":
        if chat_id not in case_sessions:
            await query.answer("Keys sessiyasi topilmadi.", show_alert=True)
            return
        s = case_sessions.pop(chat_id)
        answer = "\n".join(s["answer"]).strip()
        if len(answer) < 30:
            case_sessions[chat_id] = s  
            await query.answer("Javob juda qisqa. Batafsroq yozing.", show_alert=True)
            return
            
        code = s["code"]
        today = datetime.now().strftime("%Y-%m-%d")
        usage = ai_usage.get(code, {"date": today, "count": 0})
        if usage["date"] != today:
            usage = {"date": today, "count": 0}
        usage["count"] += 1
        ai_usage[code] = usage

        await query.answer()
        await query.edit_message_reply_markup(None)
        await context.bot.send_message(chat_id, f"✅ Javobingiz qabul qilindi. AI tahlil qilmoqda (Bugungi urinish: {usage['count']}/{AI_DAILY_LIMIT})...")

        if not gemini_client:
            await context.bot.send_message(chat_id, "⚠️ GEMINI_API_KEY topilmadi, baholanmadi.")
            return

        result = await grade([(s["ci"], answer)])
        if not result:
            await context.bot.send_message(chat_id, "⚠️ AIdan javob olishda xatolik yuz berdi. Keyinroq urinib ko'ring.")
            return

        text = format_grade(s["name"], [(s["ci"], answer)], result)
        pending[code] = {"chat_id": chat_id, "text": text}
        
        if TEACHER_CHAT_ID:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 O'quvchiga yuborish", callback_data=f"ap:{code}")]])
            await send_long(context.bot, int(TEACHER_CHAT_ID), text, reply_markup=kb)
            
        await context.bot.send_message(chat_id, "✅ Javobingiz o'qituvchiga yuborildi. Tez orada natija chiqadi!", reply_markup=get_main_keyboard())
        return

    if chat_id in sessions and sessions[chat_id].get("started"):
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
        result_text = (
            f"{q['q']}\n\nSiz tanladingiz: {labels[chosen]}. {q['opts'][chosen]}\n"
            f"To'g'ri javob: {labels[correct]}. {q['opts'][correct]}"
        )
        try:
            await query.edit_message_text(result_text)
        except Exception:
            pass
        s["i"] += 1
        await send_question(context, chat_id)
        return

    await query.answer()

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("aitest", aitest))
    app.add_handler(CommandHandler("modellar", modellar))
    app.add_handler(CommandHandler("addcase", addcase))
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
