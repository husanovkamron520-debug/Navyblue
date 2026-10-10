import os
import json
import random
import asyncio
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")  # kerak bo'lsa Renderda almashtiriladi
gemini_client = None
if GEMINI_API_KEY:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
ai_gate = asyncio.Semaphore(2)  # bir vaqtda ko'pi bilan 2 ta baholash (bepul limit uchun)

# ====== KEYSLAR (har biri 10 ball: 4 + 4 + 2, jami 5 x 10 = 50) ======
CASES = [
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
            "Metall yuzalar radio-to'lqinlarni (RFID signalini) to'sishi yoki aks ettirishini (interference) to'g'ri tushuntirgani",
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
    {
        "title": "Tezkor yetkazib berish va sifat muammosi",
        "text": (
            "Internet-do'kon mijozlarni jalb qilish uchun \"Buyurtma berganingizdan keyin 2 soatda yetkazamiz!\" degan "
            "yangi xizmatni yo'lga qo'ydi. Kompaniya bu maqsadga erishish uchun kuryerlarga har bir o'z vaqtida "
            "yetkazilgan buyurtma uchun mukofot puli (bonus) e'lon qildi.\n\n"
            "Natijada yetkazib berish tezligi 98% ga yetdi va kuryerlar juda tez ishlay boshladi. Lekin 1 oydan keyin "
            "mijozlardan tushgan shikoyatlar va tovarlarni qaytarish (Reverse Logistics) 3 barobarga oshib ketdi. "
            "Ko'p mahsulotlar (ayniqsa shisha va mo'rt buyumlar) tirnalgan yoki singan holatda yetib borayotgani ma'lum bo'ldi."
        ),
        "questions": [
            "1) Tizimli xatolik: kompaniya rahbariyati belgilagan KPI (rag'batlantirish tizimi) qanday salbiy oqibatga olib keldi?",
            "2) Muvozanat: yetkazib berish tezligini tushirmagan holda mahsulotlar sifatli yetib borishini ta'minlash "
            "uchun raqamli baholash tizimiga qanday o'zgartirish kiritish kerak?",
        ],
        "crit": [
            "Faqat \"tezlik\" bo'yicha berilgan bonus (KPI) kuryerlarni ehtiyotkorlikni unutishga majbur qilganini aniqlagani",
            "Tizimga tezlik + mijoz reytingi (sifat) ko'rsatkichini birgalikda kiritish yechimini bergani",
            "Fikrni tizimli bayon qilgani",
        ],
    },
    {
        "title": "Dronlar va ob-havo to'siqlari",
        "text": (
            "Tog'li va borish qiyin qishloqlarga dorilarni tez yetkazib berish uchun farmatsevtika kompaniyasi avtonom "
            "dronlar (uchuvchisiz apparatlar) xizmatini ishga tushirdi. Dronlar avtomobilda 2 soat ketadigan yo'lni "
            "20 daqiqada uchib o'tishi kerak edi.\n\n"
            "Lekin kuz va qish oylarida dronlarning 30% dan ortig'i belgilangan manzilga yetib bormay, yo'lda favqulodda "
            "qo'nishni amalga oshirdi yoki orqaga qaytib keldi. Dronlarning dasturiy ta'minoti batareya quvvati va "
            "masofani to'g'ri hisoblagan, lekin real parvoz vaqtidagi shamol tezligini oldindan baholay olmagan edi."
        ),
        "questions": [
            "1) Sabab-oqibat: shamol tezligi va yo'nalishi dronning batareya sarfiga qanday ta'sir qilgan va nima uchun "
            "rejalashtirilgan quvvat yetmay qolgan?",
            "2) Texnologik yechim: dronlarni har bir parvozdan oldin ob-havo o'zgarishlariga moslashtirish uchun qanday "
            "raqamli tizim (masalan, meteo-sensorlar yoki AI) bilan integratsiya qilish kerak?",
        ],
        "crit": [
            "Qarshi va yon shamol dron qarshiligini oshirib, motorlar batareyani kutilganidan tezroq tugatganini tushuntirgani",
            "Dronni Meteo-API (real vaqtdagi ob-havo ma'lumotlari) bilan integratsiya qilish taklifini bergani",
            "Aniq xulosa",
        ],
    },
    {
        "title": "Ishlab chiqarish va zaxira paradoksi",
        "text": (
            "Sharbat ishlab chiqaruvchi zavod savdo ma'lumotlarini tahlil qiluvchi Predictive Analytics (bashoratli "
            "analitika) dasturini o'rnatdi. Dastur o'tgan yilgi issiq iyul oyida apelsin sharbatiga talab juda yuqori "
            "bo'lganini ko'rib, bu yilgi iyul oyi uchun ham omborni to'ldirib apelsin sharbati ishlab chiqarishni rejalashtirdi.\n\n"
            "Biroq bu yilgi iyul oyi kutilmaganda salqin va yomg'irli keldi. Natijada apelsin sharbati sotilmay omborda "
            "qolib ketdi, lekin salqin kunda odamlar ko'proq sotib oladigan issiq choy va kofe mahsulotlariga tanqislik "
            "(shortage) yuzaga keldi. Dastur analitikasi baribir xato qildi."
        ),
        "questions": [
            "1) Analitik xato: sun'iy intellekt/dastur faqat tarixiy sotuv ma'lumotlariga (past data) tayanib qaror "
            "qabul qilganida qanday xavf yuzaga keladi?",
            "2) Moslashuvchanlik: bashorat qilish dasturi aniqroq ishlashi uchun unga o'tgan yilgi sotuvlardan tashqari "
            "yana qanday tashqi real vaqt ma'lumotlarini ulab qo'yish kerak?",
        ],
        "crit": [
            "AI faqat o'tmish ma'lumotlariga (past data) tayanib qaror qabul qilgani xavf tug'dirganini ko'rsatgani",
            "Modelga real vaqtdagi ob-havo prognozi va aholining o'zgaruvchan talabi ma'lumotlarini ulab qo'yish yechimini bergani",
            "Analitika mantiqini to'g'ri ochib bergani",
        ],
    },
]
CRIT_MAX = [4, 4, 2]
CRIT_NAMES = ["tub sabab", "yechim", "struktura"]
pending = {}  # o'qituvchi tasdiqlashini kutayotgan baholar: code -> dict


def level(total):
    if total >= 45:
        return "🥇 A'lo (Top Analitik)"
    if total >= 35:
        return "🥈 Yaxshi"
    if total >= 25:
        return "🥉 Qoniqarli"
    return "❌ Qoniqarsiz"


async def send_long(bot, chat_id, text, reply_markup=None):
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    for i, ch in enumerate(chunks):
        await bot.send_message(chat_id, ch, reply_markup=reply_markup if i == len(chunks) - 1 else None)


def _grade_sync(items):
    """items: [(case_idx, javob_matni), ...] — barcha keyslar bitta so'rovda baholanadi."""
    parts = []
    for n, (ci, ans) in enumerate(items, 1):
        c = CASES[ci]
        parts.append(
            f"=== KEYS #{n}: {c['title']} ===\nMATN: {c['text']}\nSAVOLLAR: {' '.join(c['questions'])}\n"
            f"MEZONLAR: (a) 0-4 ball: {c['crit'][0]}; (b) 0-4 ball: {c['crit'][1]}; (c) 0-2 ball: {c['crit'][2]}\n"
            f"TALABA JAVOBI:\n{ans}\n"
        )
    prompt = (
        "Sen supply chain management fanidan qattiq, lekin adolatli o'qituvchisan. Talabaning quyidagi keys "
        "javoblarini bahola. Har keys 10 ball: (a) tub sababni aniqlash 0-4, (b) analitik/amaliy yechim 0-4, "
        "(c) javob strukturasi va aniqligi 0-2. Faqat har keysning o'z mezonlariga qarab bahola. "
        "Javob mavzuga mos bo'lmasa yoki bo'sh bo'lsa, past ball qo'y.\n\n"
        + "\n".join(parts)
        + "\nFaqat JSON qaytar, keyslar kiritilgan tartibda, aynan "
        + str(len(items))
        + " ta element: {\"keyslar\":[{\"a\":int,\"b\":int,\"c\":int,\"izoh\":\"o'zbek tilida, 2-3 gap: nega shu ball "
        "va nimani yaxshilash kerak\"}]}"
    )
    resp = gemini_client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(resp.text)["keyslar"]
    if len(data) != len(items):
        raise ValueError("Gemini keyslar soni mos kelmadi")
    results = []
    for d in data:
        sc = [max(0, min(int(d.get(k, 0)), CRIT_MAX[i])) for i, k in enumerate(("a", "b", "c"))]
        results.append((sc, str(d.get("izoh", ""))))
    return results


async def grade(items):
    async with ai_gate:
        for attempt in range(2):
            try:
                return await asyncio.to_thread(_grade_sync, items)
            except Exception as e:
                logging.warning("Gemini xato (%s): %s", attempt + 1, e)
                await asyncio.sleep(5)
    return None


def format_grade(name, items, results):
    lines = [f"📝 {name} — natija"]
    total = 0
    for (ci, _), (sc, izoh) in zip(items, results):
        sub = sum(sc)
        total += sub
        lines.append(
            f"\n{ci+1}-keys ({CASES[ci]['title']}): {sub}/10\n"
            f"  {CRIT_NAMES[0]} {sc[0]}/4 · {CRIT_NAMES[1]} {sc[1]}/4 · {CRIT_NAMES[2]} {sc[2]}/2\n{izoh}"
        )
    lines.append(f"\nJAMI: {total}/50 — {level(total)}")
    return "\n".join(lines)


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
    text = f"Savol {s['i']+1}/{len(QUESTIONS)}\n\n{q['q']}"
    img = q.get("img")  # ixtiyoriy: "images/rasm1.png" yoki https://... havola
    if img:
        if img.startswith("http"):
            photo = img
        else:
            photo = open(os.path.join(BASE_DIR, img), "rb")
        try:
            await context.bot.send_photo(
                chat_id, photo, caption=text[:1024],
                reply_markup=InlineKeyboardMarkup(kb),
            )
        finally:
            if not isinstance(photo, str):
                photo.close()
    else:
        await context.bot.send_message(
            chat_id, text, reply_markup=InlineKeyboardMarkup(kb),
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in sessions:
        s = sessions[chat_id]
        if s.get("stage") == "case":
            s["answer"].append((update.message.text or "").strip())
            await update.message.reply_text("Qabul qilindi. Davom eting yoki «Javobni yuborish» tugmasini bosing.")
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
    sessions[chat_id] = {"code": text, "name": name, "i": 0, "score": 0, "started": False}
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Testni boshlash", callback_data="start_test")]])
    await update.message.reply_text(
        f"Salom, {name}! Testda {len(QUESTIONS)} ta savol bor.\n"
        f"Tayyor bo'lsangiz, pastdagi tugmani bosing.",
        reply_markup=kb,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id

    # o'qituvchi baholarni tasdiqlaydi
    if query.data.startswith("ap:"):
        if str(chat_id) != str(TEACHER_CHAT_ID):
            await query.answer()
            return
        p = pending.pop(query.data[3:], None)
        if not p:
            await query.answer("Allaqachon yuborilgan yoki ma'lumot yo'q (bot qayta ishga tushgan bo'lishi mumkin)", show_alert=True)
            return
        await send_long(context.bot, p["chat_id"], p["text"])
        await query.answer("Yuborildi ✅")
        await query.edit_message_reply_markup(None)
        return

    if chat_id not in sessions:
        await query.answer()
        return
    s = sessions[chat_id]

    if query.data == "submit_case":
        if s.get("stage") != "case":
            await query.answer()
            return
        answer = "\n".join(s["answer"]).strip()
        if len(answer) < 40:
            await query.answer("Javob juda qisqa. Avval javobingizni yozing.", show_alert=True)
            return
        ci = s["order"][s["k"]]
        s["saved"].append((ci, answer))
        s["answer"] = []
        await query.answer()
        await query.edit_message_reply_markup(None)
        if TEACHER_CHAT_ID:  # zaxira: har javob o'qituvchiga alohida boradi
            try:
                await send_long(context.bot, int(TEACHER_CHAT_ID),
                                f"📄 {s['name']} ({s['code']}) — {ci+1}-keys javobi:\n\n{answer}")
            except Exception as e:
                logging.warning("Teacher notify failed: %s", e)
        s["k"] += 1
        if s["k"] < len(s["order"]):
            await send_case(context, chat_id)
            return
        # oxirgi keys topshirildi
        sessions.pop(chat_id)
        items = s["saved"]
        await context.bot.send_message(chat_id, "✅ Barcha javoblaringiz qabul qilindi. Baho o'qituvchi tekshirgach yuboriladi.")
        if not gemini_client:
            logging.warning("GEMINI_API_KEY yo'q — baholash o'tkazib yuborildi")
            return
        result = await grade(items)
        if not result:
            if TEACHER_CHAT_ID:
                await context.bot.send_message(int(TEACHER_CHAT_ID), f"⚠️ {s['name']} javoblarini AI baholay olmadi.")
            return
        text = format_grade(s["name"], items, result)
        pending[s["code"]] = {"chat_id": chat_id, "text": text}
        if TEACHER_CHAT_ID:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 O'quvchiga yuborish", callback_data=f"ap:{s['code']}")]])
            await send_long(context.bot, int(TEACHER_CHAT_ID), text, reply_markup=kb)
        return

    if s.get("stage") == "case":
        await query.answer()
        return
    if query.data == "start_test":
        if s.get("started"):
            await query.answer()
            return
        s["started"] = True
        await query.answer()
        await query.edit_message_text(f"Salom, {s['name']}! Test boshlandi. Omad! 🍀")
        await send_question(context, chat_id)
        return
    if not s.get("started"):
        await query.answer("Avval «Testni boshlash» tugmasini bosing")
        return
    q = QUESTIONS[s["i"]]
    chosen = int(query.data)
    correct = q["correct"]
    if chosen == correct:
        s["score"] += 1
        await query.answer("✅ To'g'ri!")
    else:
        await query.answer("❌ Noto'g'ri")
    labels = ["A", "B", "C", "D"]
    result = (
        f"{q['q']}\n\nSiz tanladingiz: {labels[chosen]}. {q['opts'][chosen]}\n"
        f"To'g'ri javob: {labels[correct]}. {q['opts'][correct]}"
    )
    if query.message.photo:  # rasmli xabarda matn emas, caption o'zgartiriladi
        await query.edit_message_caption(result[:1024])
    else:
        await query.edit_message_text(result)
    s["i"] += 1
    await send_question(context, chat_id)


async def send_case(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    s = sessions[chat_id]
    k = s["k"]
    c = CASES[s["order"][k]]
    last = k == len(s["order"]) - 1
    label = "✅ Hammasini yuborish" if last else "➡️ Keyingi keysga o'tish"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data="submit_case")]])
    await context.bot.send_message(
        chat_id,
        f"📌 Keys {k+1}/{len(CASES)}: {c['title']}\n\n{c['text']}\n\n" + "\n".join(c["questions"]) +
        "\n\nHar savolga 3-4 jumlali aniq va mantiqiy javob yozing (bir necha xabarda ham bo'ladi). "
        "Tugatgach pastdagi tugmani bosing.",
        reply_markup=kb,
    )


async def finish(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    s = sessions[chat_id]
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
    s["stage"] = "case"
    s["order"] = random.sample(range(len(CASES)), len(CASES))  # har o'quvchida keyslar tartibi tasodifiy
    s["k"] = 0
    s["answer"] = []
    s["saved"] = []
    if TEACHER_CHAT_ID:
        try:
            await context.bot.send_message(
                int(TEACHER_CHAT_ID),
                f"📥 {s['name']} ({s['code']}): {s['score']}/{total} ({pct}%) — {ball90}/90"
            )
        except Exception as e:
            logging.warning("Teacher notify failed: %s", e)
    await context.bot.send_message(
        chat_id,
        f"Endi amaliy qism: {len(CASES)} ta keys. Har biri 10 ball, jami 50 ball.\n\n"
        "Baholash: tub sababni aniqlash - 4 ball, analitik yechim - 4 ball, "
        "javob strukturasi va aniqligi - 2 ball."
    )
    await send_case(context, chat_id)


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
