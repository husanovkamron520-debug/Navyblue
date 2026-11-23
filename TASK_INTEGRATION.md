# Task'ni bot.py bilan ulash (october_tasks.py)

`october_tasks.py` tayyor va sinalgan: istalgan mavzu bo'yicha krossvord + so'z qidirish yaratadi (October'ga
"ombor logistikasi bo'yicha krossvord task yarat" deb yozilsa), `krossvord_ombor.html` shabloni asosida Mini App
sahifasini yasaydi va natijani SERVERDA tekshiradi. Task'lar Supabase `kb_notes` jadvalida saqlanadi.

Hozir u talabaning **Task tugmasida** ko'rinishi uchun bot.py'da 4 ta kichik o'zgarish kerak. Mavjud ombor-task
(`krossvord_ombor.html`, 17 ta qattiq yozilgan so'z) o'zgarishsiz qoladi.

## 0. Import va bayroq
- Fayl boshida `import october_plus` yonida: `import october_tasks`
- `october_plus.setup(...)` va `october_plus.register(app)` dan keyin: `october_tasks.INTEGRATED = True`

## 1. Task tugmasi (`if text == BTN_TASK:` ichida)
Hozirgi bitta tugmali xabar o'rniga, birinchi tugma ombor-task bo'lsin, so'ng oxirgi 8 ta yaratilgan task:

```python
rows = [[InlineKeyboardButton("🧩 Krossvord + 🔎 So'z topish (Ombor)", web_app=WebAppInfo(url=f"{base}/task?t={token}"))]]
try:
    custom = await asyncio.to_thread(october_tasks.list_recent, october_plus._sb, 8)
except Exception:
    custom = []
for item in custom:
    tk = secrets.token_urlsafe(24)
    TASK_TOKENS[tk] = {"chat_id": int(chat_id), "teacher_code": str(student.get("teacher_code")),
                       "created_at": now, "task_id": item["id"]}
    rows.append([InlineKeyboardButton("🧩 " + str(item["title"])[:50], web_app=WebAppInfo(url=f"{base}/task?t={tk}"))])
# reply_markup=InlineKeyboardMarkup(rows)
```

## 2. `do_GET` ichidagi `/task` yo'li
Sessiyada `task_id` bo'lsa, qattiq fayl o'rniga yaratilgan task sahifasi qaytsin:

```python
tid = session.get("task_id")
if tid:
    task = october_tasks.load(october_plus._sb, tid)
    if not task:
        body, ctype, code = "Task topilmadi.".encode("utf-8"), "text/plain; charset=utf-8", 404
    else:
        body, ctype = october_tasks.build_html(task).encode("utf-8"), "text/html; charset=utf-8"
else:
    # mavjud TASK_APP_FILE o'qish kodi o'zgarishsiz
```

## 3. `puzzle_webapp_data` ichidagi `krosstest` bo'limi
Token va talaba/ustoz tekshiruvidan keyin, qattiq `entries = [...]` qismidan OLDIN:

```python
if session.get("task_id"):
    task = await asyncio.to_thread(october_tasks.load, october_plus._sb, session["task_id"])
    if not task:
        await msg.reply_text("⚠️ Task topilmadi. Task'ni qayta oching.")
        return
    try:
        g = october_tasks.grade(task, payload)
    except ValueError as e:
        await msg.reply_text("⚠️ " + str(e))
        return
    TASK_TOKENS.pop(token, None)          # bir martalik
    # shu yerda mavjud kod kabi: teacher_code, teacher, record_id, student_name aniqlanadi,
    # natija PUZZLE_FILE ga yoziladi (kind="custom_task", task_id, g["cw_score"], g["ws_score"], g["score"] ...),
    # ustozga: october_tasks.report_text(task, student_name, g, record_id)
    # talabaga: krossvord / so'z topish / umumiy ballar
    return
```

## Tekshiruv
1. October'ga: "kanban bo'yicha krossvord task yarat" -> task fayli va ID keladi.
2. Talaba akkauntida Task tugmasi -> yangi task ro'yxatda ko'rinadi.
3. Ikkala qismni bajarib yuborsa, talabaga ball, ustozga hisobot boradi; ikkinchi yuborish qabul qilinmaydi.
