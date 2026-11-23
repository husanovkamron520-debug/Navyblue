"""october_tasks.py - istalgan mavzu bo'yicha "Task" (krossvord + so'z qidirish) yaratish.

Nima qiladi:
1. create_task(mavzu, gen_text): Gemini'dan krossvord so'zlari + izohlar va so'z qidirish so'zlarini
   oladi, krossvord to'rini avtomatik joylaydi (kesishuvlar bilan), so'z qidirish matritsasini yasaydi.
2. build_html(task): sinalgan krossvord_ombor.html shabloni asosida tayyor Mini App sahifasini yasaydi
   (shablon ichidagi DATA almashtiriladi, boshqa kod o'zgarmaydi).
3. grade(task, payload): talaba yuborgan natijani SERVERDA, task'ning o'z javob kaliti bilan tekshiradi
   (bot.py'dagi hozirgi ombor-task baholash mantiqi bilan bir xil: krossvord - yordam*5, so'z qidirish - topilgan %).
4. save/load/list_recent: task'larni Supabase'dagi kb_notes jadvalida saqlaydi (qo'shimcha jadval kerak emas).

bot.py bilan ulanish TASK_INTEGRATION.md faylida yozilgan.
"""
import datetime as dt
import json
import os
import random
import re
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(_HERE, "krossvord_ombor.html")

MAX_GRID = 15
INTEGRATED = False  # bot.py ulanishi tugagach True qilinadi (october_tasks.INTEGRATED = True)

_DATA_RE = re.compile(r"var DATA=\{.*?\};\s*\nvar LIM", re.S)


# ---------------------------------------------------------------- so'zlarni tozalash
def clean_word(w: str) -> str:
    """'Taminot', "O'zbek", 'stellaj' -> faqat A-Z, katta harf."""
    w = (w or "").upper()
    w = re.sub(r"[ʻʼ’‘`'´]", "", w)
    return re.sub(r"[^A-Z]", "", w)


# ---------------------------------------------------------------- krossvord joylash
def _fits(cells, dirs, w, r, c, d, max_size):
    """w so'zi (r,c) dan d yo'nalishda joylashadimi; kesishuvlar soni yoki None."""
    dr, dc = (0, 1) if d == "H" else (1, 0)
    pr, pc = dc, dr  # perpendikulyar
    if (r - dr, c - dc) in cells or (r + dr * len(w), c + dc * len(w)) in cells:
        return None
    cross = 0
    for i, ch in enumerate(w):
        p = (r + dr * i, c + dc * i)
        if p in cells:
            if cells[p] != ch or d in dirs[p]:
                return None
            cross += 1
        else:
            if (p[0] + pr, p[1] + pc) in cells or (p[0] - pr, p[1] - pc) in cells:
                return None
    if cross == 0:
        return None
    pts = list(cells) + [(r + dr * i, c + dc * i) for i in range(len(w))]
    rs, cs = [p[0] for p in pts], [p[1] for p in pts]
    if max(rs) - min(rs) + 1 > max_size or max(cs) - min(cs) + 1 > max_size:
        return None
    return cross


def layout_crossword(items, max_size=MAX_GRID, tries=60, seed=None):
    """items: [(word, clue)] -> (ents, rows, cols). Eng ko'p so'z joylangan variant tanlanadi."""
    rng = random.Random(seed)
    best = None
    for t in range(tries):
        order = list(items)
        rng.shuffle(order)
        order.sort(key=lambda x: -len(x[0]) + (rng.random() * 3 if t else 0))
        cells, dirs, placed = {}, {}, []
        w0, q0 = order[0]
        for i, ch in enumerate(w0):
            cells[(0, i)] = ch
            dirs[(0, i)] = {"H"}
        placed.append({"w": w0, "q": q0, "r": 0, "c": 0, "d": "H"})
        for w, q in order[1:]:
            cand = []
            for (pr_, pc_), ch0 in list(cells.items()):
                for i, ch in enumerate(w):
                    if ch != ch0:
                        continue
                    for d in ("H", "V"):
                        r, c = (pr_, pc_ - i) if d == "H" else (pr_ - i, pc_)
                        x = _fits(cells, dirs, w, r, c, d, max_size)
                        if x:
                            cand.append((x, rng.random(), r, c, d))
            if not cand:
                continue
            cand.sort(reverse=True)
            _, _, r, c, d = cand[0]
            dr, dc = (0, 1) if d == "H" else (1, 0)
            for i, ch in enumerate(w):
                p = (r + dr * i, c + dc * i)
                cells[p] = ch
                dirs.setdefault(p, set()).add(d)
            placed.append({"w": w, "q": q, "r": r, "c": c, "d": d})
        rs, cs = [p[0] for p in cells], [p[1] for p in cells]
        area = (max(rs) - min(rs) + 1) * (max(cs) - min(cs) + 1)
        key = (len(placed), -area)
        if best is None or key > best[0]:
            best = (key, placed, cells)
    _, placed, cells = best
    r0 = min(p[0] for p in cells)
    c0 = min(p[1] for p in cells)
    for e in placed:
        e["r"] -= r0
        e["c"] -= c0
    rows = max(p[0] for p in cells) - r0 + 1
    cols = max(p[1] for p in cells) - c0 + 1
    return placed, rows, cols


# ---------------------------------------------------------------- so'z qidirish matritsasi
_DIRS = [(0, 1), (1, 0), (1, 1), (1, -1), (0, -1), (-1, 0), (-1, -1), (-1, 1)]


def build_wordsearch(words, n=MAX_GRID, seed=None):
    """words: ['BARKOD', ...] -> (grid[str,...], joylangan so'zlar). Sig'masa so'z tashlab ketiladi."""
    rng = random.Random(seed)
    g = [[""] * n for _ in range(n)]
    placed = []
    for w in sorted(words, key=lambda x: -len(x)):
        if len(w) > n:
            continue
        ok = False
        for _ in range(300):
            dr, dc = rng.choice(_DIRS)
            r, c = rng.randrange(n), rng.randrange(n)
            er, ec = r + dr * (len(w) - 1), c + dc * (len(w) - 1)
            if not (0 <= er < n and 0 <= ec < n):
                continue
            cells = [(r + dr * i, c + dc * i) for i in range(len(w))]
            if all(g[a][b] in ("", w[i]) for i, (a, b) in enumerate(cells)):
                for i, (a, b) in enumerate(cells):
                    g[a][b] = w[i]
                ok = True
                break
        if ok:
            placed.append(w)
    pool = "".join(placed) or "ABCDEFGHIJKLMNOPRSTUXYZ"
    for r in range(n):
        for c in range(n):
            if not g[r][c]:
                g[r][c] = rng.choice(pool)
    return ["".join(row) for row in g], placed


# ---------------------------------------------------------------- Gemini orqali task yaratish
_PROMPT = """Sen o'zbek tilidagi o'quv topshiriqlari tuzuvchi o'qituvchisan. Mavzu: "{topic}".
Quyidagi JSON'ni qaytar (FAQAT JSON, izoh yoki ``` belgilarisiz):
{{"title":"qisqa sarlavha","crossword":[{{"word":"STELLAJ","clue":"qisqa aniq izoh"}}],"wordsearch":["Barkod","Forklift"]}}
Qoidalar:
- "crossword": {ncw} ta atama. Har bir "word" bitta so'z, lotin harflarida, 4-11 harf, bo'shliq va chiziqsiz (apostrofsiz yoz: TAMINOT).
  "clue" o'zbekcha, 1 gap, javobning o'zini o'z ichiga olmasin.
- Atamalarda umumiy harflar ko'p bo'lsin (kesishish uchun): A, O, I, E, R, T, L, K, S, N harflari.
- "wordsearch": {nws} ta so'z, mavzuga oid, 4-10 harf, bitta so'z, crossword'dagi so'zlardan farqli.
- Hammasi mavzuga aniq mos va faktik jihatdan to'g'ri bo'lsin."""


def _loose_json(t: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (t or "").strip(), flags=re.I)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        return json.loads(m.group(0)) if m else None


def create_task(topic: str, gen_text, ncw: int = 15, nws: int = 18, seed=None) -> dict:
    """gen_text(prompt)->str sinxron funksiya. Muvaffaqiyatsiz bo'lsa ValueError."""
    topic = (topic or "").strip()[:120]
    if not topic:
        raise ValueError("Mavzu ko'rsatilmagan")
    last_err = "noma'lum xato"
    for _ in range(2):
        try:
            raw = gen_text(_PROMPT.format(topic=topic, ncw=ncw, nws=nws))
            data = _loose_json(raw)
            if not isinstance(data, dict):
                raise ValueError("Gemini JSON qaytarmadi")
            items, seen = [], set()
            for it in data.get("crossword", []):
                w = clean_word(str(it.get("word", "")))
                q = str(it.get("clue", "")).strip()[:160]
                if 3 <= len(w) <= 12 and q and w not in seen:
                    seen.add(w)
                    items.append((w, q))
            if len(items) < 6:
                raise ValueError("Krossvord uchun yetarli so'z yo'q (" + str(len(items)) + ")")
            ents, rows, cols = layout_crossword(items, seed=seed)
            if len(ents) < 6:
                raise ValueError("Krossvord to'ri tuzilmadi (faqat " + str(len(ents)) + " so'z sig'di)")
            ws_words, shown = [], {}
            for w in data.get("wordsearch", []):
                k = clean_word(str(w))
                if 3 <= len(k) <= 12 and k not in shown:
                    shown[k] = str(w).strip()[:30].capitalize() or k.capitalize()
                    ws_words.append(k)
            if len(ws_words) < 6:
                raise ValueError("So'z qidirish uchun yetarli so'z yo'q")
            grid, placed = build_wordsearch(ws_words, seed=seed)
            if len(placed) < 6:
                raise ValueError("So'z qidirish matritsasi tuzilmadi")
            return {
                "id": uuid.uuid4().hex[:10],
                "title": str(data.get("title") or topic)[:80],
                "topic": topic,
                "created_at": dt.datetime.utcnow().isoformat(timespec="seconds"),
                "data": {
                    "cw1": {"rows": rows, "cols": cols, "ents": ents},
                    "ws": {"grid": grid, "words": [{"k": w, "show": shown[w]} for w in placed]},
                },
            }
        except Exception as e:  # bir marta qayta urinamiz
            last_err = str(e)
    raise ValueError(last_err)


# ---------------------------------------------------------------- HTML yasash
def build_html(task: dict) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()
    if not _DATA_RE.search(tpl):
        raise ValueError("Shablonda DATA topilmadi")
    data_js = "var DATA=" + json.dumps(task["data"], ensure_ascii=False) + ";\nvar LIM"
    html = _DATA_RE.sub(lambda m: data_js, tpl, count=1)
    title = "🧩 " + str(task["title"]) + " — krossvord va so'z qidirish"
    esc = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(r"<title>.*?</title>", lambda m: "<title>" + esc + "</title>", html, count=1, flags=re.S)
    html = re.sub(r"<h1>.*?</h1>", lambda m: "<h1>" + esc + "</h1>", html, count=1, flags=re.S)
    return html


# ---------------------------------------------------------------- serverda baholash
def answer_cells(task: dict) -> dict:
    out = {}
    for e in task["data"]["cw1"]["ents"]:
        for i, ch in enumerate(e["w"]):
            r = e["r"] + (i if e["d"] == "V" else 0)
            c = e["c"] + (i if e["d"] == "H" else 0)
            out[str(r) + "," + str(c)] = ch
    return out


def grade(task: dict, payload: dict) -> dict:
    """Talaba natijasini task'ning javob kaliti bilan tekshiradi. Format xato bo'lsa ValueError."""
    ans = answer_cells(task)
    cw = payload.get("cw") if isinstance(payload.get("cw"), dict) else {}
    raw_cells = cw.get("cells", {})
    if not isinstance(raw_cells, dict) or len(raw_cells) > len(ans) + 5:
        raise ValueError("Krossvord javoblari formati noto'g'ri")
    correct = sum(1 for k, ch in ans.items() if str(raw_cells.get(k, "")).strip().upper() == ch)
    allowed = {w["k"] for w in task["data"]["ws"]["words"]}
    ws = payload.get("ws") if isinstance(payload.get("ws"), dict) else {}
    raw_found = ws.get("found", [])
    if not isinstance(raw_found, list) or len(raw_found) > len(allowed) + 5:
        raise ValueError("So'z qidirish natijasi formati noto'g'ri")
    found = sorted({str(w).upper() for w in raw_found if str(w).upper() in allowed})
    try:
        hints = max(0, min(3, int(cw.get("hints", 0))))
        cw_sec = max(0, min(900, int(cw.get("t", 0))))
        ws_sec = max(0, min(900, int(ws.get("t", 0))))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Vaqt yoki yordam qiymati noto'g'ri")
    cw_score = max(0, min(100, round(correct / len(ans) * 100) - hints * 5))
    ws_score = round(len(found) / len(allowed) * 100)
    return {
        "cw_score": cw_score, "cw_correct": correct, "cw_total": len(ans), "hints": hints,
        "cw_seconds": cw_sec, "ws_score": ws_score, "ws_found": found, "ws_total": len(allowed),
        "ws_seconds": ws_sec, "score": round((cw_score + ws_score) / 2),
    }


def report_text(task: dict, student_name: str, g: dict, record_id: str = "") -> str:
    """Ustozga yuboriladigan hisobot matni (bot.py dagi ombor-task hisoboti shaklida)."""
    cwm, cws = divmod(g["cw_seconds"], 60)
    wsm, wss = divmod(g["ws_seconds"], 60)
    lines = [
        "📝 TASK — YANGI NATIJA: " + str(task["title"]), "",
        "👤 Talaba: " + str(student_name),
        "🏆 Umumiy natija: " + str(g["score"]) + "/100", "",
        "🧩 Krossvord: " + str(g["cw_score"]) + "/100",
        "   To'g'ri kataklar: " + str(g["cw_correct"]) + "/" + str(g["cw_total"]),
        "   Yordam: " + str(g["hints"]) + "/3",
        "   Vaqt: " + str(cwm) + ":" + ("%02d" % cws), "",
        "🔎 So'z topish: " + str(g["ws_score"]) + "/100",
        "   Topilgan: " + str(len(g["ws_found"])) + "/" + str(g["ws_total"]),
        "   So'zlar: " + (", ".join(g["ws_found"]) if g["ws_found"] else "—"),
        "   Vaqt: " + str(wsm) + ":" + ("%02d" % wss),
    ]
    if record_id:
        lines += ["", "🆔 Natija ID: " + record_id]
    return "\n".join(lines)


# ---------------------------------------------------------------- saqlash (Supabase kb_notes)
def save(sb, owner_id: int, task: dict):
    """task'ni kind='task_<id>' qatoriga, ro'yxat uchun esa kind='task_index' qatoriga yozadi."""
    sb.table("kb_notes").insert({"owner": owner_id, "kind": "task_" + task["id"],
                                 "text": json.dumps(task, ensure_ascii=False)}).execute()
    meta = {"id": task["id"], "title": task["title"], "topic": task["topic"], "created_at": task["created_at"]}
    sb.table("kb_notes").insert({"owner": owner_id, "kind": "task_index",
                                 "text": json.dumps(meta, ensure_ascii=False)}).execute()


def load(sb, task_id: str):
    if not re.fullmatch(r"[0-9a-f]{10}", str(task_id or "")):
        return None
    r = sb.table("kb_notes").select("id,text").eq("kind", "task_" + task_id).order("id").execute()
    rows = r.data or []
    if not rows:
        return None
    try:
        return json.loads(rows[-1]["text"])
    except Exception:
        return None


def list_recent(sb, n: int = 8):
    r = sb.table("kb_notes").select("id,text").eq("kind", "task_index").order("id").execute()
    out = []
    for row in (r.data or []):
        try:
            out.append(json.loads(row["text"]))
        except Exception:
            continue
    return out[-n:][::-1]
