"""One-time patch: give the Supply Chain AI advisor conversation memory.

Usage: python scripts/apply_ai_memory_patch.py [path/to/supply_chain.py]

Every replacement is asserted to match exactly once, so the script either applies
completely or changes nothing.
"""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "supply_chain.py"
s = open(path, encoding="utf-8").read()

import os
import runpy


def _run_format_patch():
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "apply_ai_format_patch.py"), run_name="__main__")


if "_ai_history_get" in s:
    print("Memory patch already applied.")
    _run_format_patch()
    sys.exit(0)

updated = s


def rep(old, new):
    global updated
    found = updated.count(old)
    if found != 1:
        raise SystemExit(f"Patch anchor matched {found} times (expected 1): {old[:70]!r}")
    updated = updated.replace(old, new)


helpers = '''_AI_HISTORY_KEY = "_sc_ai_history"
_AI_HISTORY_MAX_TURNS = 6
_AI_HISTORY_TTL = 45 * 60


def _ai_history_get(context: Any) -> list[dict[str, Any]]:
    """Return this owner's recent AI turns (expired turns are dropped)."""
    now = datetime.now().timestamp()
    items = [x for x in (context.user_data.get(_AI_HISTORY_KEY) or [])
             if isinstance(x, dict) and now - float(x.get("t", 0)) <= _AI_HISTORY_TTL]
    items = items[-_AI_HISTORY_MAX_TURNS:]
    context.user_data[_AI_HISTORY_KEY] = items
    return items


def _ai_history_add(context: Any, question: str, answer: str) -> None:
    items = _ai_history_get(context)
    items.append({"q": str(question)[:600], "a": str(answer)[:1200], "t": datetime.now().timestamp()})
    context.user_data[_AI_HISTORY_KEY] = items[-_AI_HISTORY_MAX_TURNS:]


def _ai_history_text(context: Any, replied_text: str = "") -> str:
    parts: list[str] = []
    for item in _ai_history_get(context):
        parts.append("Ega: " + str(item.get("q", ""))[:500])
        parts.append("Maslahatchi: " + str(item.get("a", ""))[:900])
    replied = (replied_text or "").strip()
    if replied and "Qaysi masalada yordam kerak" not in replied:
        parts.append("Ega hozirgi savolini shu xabarga javob sifatida yozdi: " + replied[:600])
    return "\\n".join(parts)


def _ai_history_prompt_part(history_text: str) -> str:
    if not history_text:
        return ""
    return (
        "AVVALGI SUHBAT (faqat savolning ma’nosini to‘g‘ri tushunish uchun; fakt manbai emas):\\n"
        f"{history_text}\\n"
        "Agar yangi savol qisqa bo‘lsa yoki oldingi gapga bog‘liq bo‘lsa («shular», «ular», «yana», «nega», «qaysi biri»), "
        "mavzuni AVVALGI SUHBATdan aniqla va savolni shu mavzuda javobla. "
        "Raqam va faktlarni esa faqat quyidagi joriy ma’lumotdan ol; avvalgi javobdagi raqamni tekshirmasdan takrorlama.\\n\\n"
    )


def _ai_keep_mode(context: Any) -> None:
    """Keep the owner in AI-question mode so follow-up messages continue the conversation."""
    context.user_data["_sc_wait"] = {"action": "ai_ask", "started": datetime.now().timestamp(), "parent": "home"}


'''
rep('def _format_ai_customer_answer(answer: str) -> str:', helpers + 'def _format_ai_customer_answer(answer: str) -> str:')

rep('def _ask_gemini_sync(client: Any, model: str, question: str, snapshot: dict[str, Any]) -> str:',
    'def _ask_gemini_sync(client: Any, model: str, question: str, snapshot: dict[str, Any], history_text: str = "") -> str:')
rep('        f"EGANING SAVOLI:\\n{question[:2000]}\\n\\n"\n',
    '        + _ai_history_prompt_part(history_text)\n        + f"EGANING SAVOLI:\\n{question[:2000]}\\n\\n"\n')
rep('def _ask_gemini_quick_sync(client: Any, model: str, question: str, snapshot: dict[str, Any]) -> str:',
    'def _ask_gemini_quick_sync(client: Any, model: str, question: str, snapshot: dict[str, Any], history_text: str = "") -> str:')
rep('        f"SAVOL: {question[:1000]}\\n\\n"\n',
    '        + _ai_history_prompt_part(history_text)\n        + f"SAVOL: {question[:1000]}\\n\\n"\n')

rep('''            context.user_data.pop("_sc_wait", None)
            context.user_data.pop("_sc_ai_draft_candidates", None)
            await _edit(q, "🤖 **AI MASLAHATCHI**\\n\\nQaysi masalada yordam kerak?", _ai_quick_keyboard())''',
'''            _ai_keep_mode(context)
            context.user_data.pop("_sc_ai_draft_candidates", None)
            await _edit(q, "🤖 **AI MASLAHATCHI**\\n\\nQaysi masalada yordam kerak? Tugmani tanlang yoki savolingizni shunchaki yozing.", _ai_quick_keyboard())''')

rep('''            context.user_data["_sc_wait"] = {"action": "ai_ask", "started": datetime.now().timestamp(), "parent": "home"}
            await _edit(q, "Savolingizni shu yerga yozing. Qisqa va aniq javob beraman.", _back_keyboard("ai"))''',
'''            _ai_keep_mode(context)
            await _edit(q, "Savolingizni shu yerga yozing. Qisqa va aniq javob beraman; oldingi gapingizni eslab turaman.", _back_keyboard("ai"))''')

rep('''                    asyncio.to_thread(_ask_gemini_quick_sync, _AI_CLIENT, _AI_MODEL, question, snapshot),
                    timeout=42,
                )
                rows = []''',
'''                    asyncio.to_thread(_ask_gemini_quick_sync, _AI_CLIENT, _AI_MODEL, question, snapshot, _ai_history_text(context)),
                    timeout=42,
                )
                _ai_history_add(context, question, answer)
                _ai_keep_mode(context)
                rows = []''')

rep('''    if datetime.now().timestamp() - float(wait.get("started", 0)) > _WAIT_SECONDS:
        context.user_data.pop("_sc_wait", None)
        await update.message.reply_text("⏱ Vaqt tugadi. /supply orqali qayta boshlang.")
        return True''',
'''    if datetime.now().timestamp() - float(wait.get("started", 0)) > _WAIT_SECONDS:
        context.user_data.pop("_sc_wait", None)
        if wait.get("action") == "ai_ask":
            return False
        await update.message.reply_text("⏱ Vaqt tugadi. /supply orqali qayta boshlang.")
        return True''')

rep('''        context.user_data.pop("_sc_wait", None)
        if _AI_CLIENT is None:
            await update.message.reply_text("Gemini AI ulanmagan.", reply_markup=_home_keyboard())
            return True
        status = await update.message.reply_text("🤖 Tahlil qilinmoqda…")
        try:
            snapshot = _ai_snapshot(_data())
            answer = await asyncio.wait_for(asyncio.to_thread(_ask_gemini_sync, _AI_CLIENT, _AI_MODEL, raw, snapshot), timeout=42)
            full_answer = "🤖 SUPPLY CHAIN AI\\n\\n" + answer + "\\n\\nEslatma: tavsiyalar avtomatik bajarilmaydi."''',
'''        _ai_keep_mode(context)
        if _AI_CLIENT is None:
            await update.message.reply_text("Gemini AI ulanmagan.", reply_markup=_home_keyboard())
            return True
        status = await update.message.reply_text("🤖 Tahlil qilinmoqda…")
        try:
            snapshot = _ai_snapshot(_data())
            reply_to = getattr(update.message, "reply_to_message", None)
            replied_text = ((getattr(reply_to, "text", None) or getattr(reply_to, "caption", None) or "") if reply_to else "")
            history_text = _ai_history_text(context, replied_text)
            answer = await asyncio.wait_for(asyncio.to_thread(_ask_gemini_sync, _AI_CLIENT, _AI_MODEL, raw, snapshot, history_text), timeout=42)
            _ai_history_add(context, raw, answer)
            full_answer = ("🤖 SUPPLY CHAIN AI\\n\\n" + answer +
                           "\\n\\nEslatma: tavsiyalar avtomatik bajarilmaydi.\\nSavolni davom ettirishingiz mumkin: shunchaki yozing.")''')

rep('''                _ask_gemini_quick_sync, _AI_CLIENT, _AI_MODEL, transcript, _ai_snapshot(_data())), timeout=45)
        await status.edit_text(''',
'''                _ask_gemini_quick_sync, _AI_CLIENT, _AI_MODEL, transcript, _ai_snapshot(_data()), _ai_history_text(context)), timeout=45)
        _ai_history_add(context, transcript, answer)
        await status.edit_text(''')

open(path, "w", encoding="utf-8").write(updated)
print("Patch applied.")
_run_format_patch()
