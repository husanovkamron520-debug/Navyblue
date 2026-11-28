"""One-time patch: Mini App reports are sent to the user's Telegram chat, sessions renew themselves,
and the Mini App adapts to wide screens.

Each file is patched independently and all-or-nothing; status lines are printed for the CI log.
"""

status = []


def rep(s, old, new):
    found = s.count(old)
    if found != 1:
        raise SystemExit(f"anchor matched {found} times (expected 1): {old[:70]!r}")
    return s.replace(old, new)


def patch_file(path, fn):
    try:
        s = open(path, encoding="utf-8").read()
        new = fn(s)
        if new == s:
            status.append(f"{path}: already applied")
            return
        open(path, "w", encoding="utf-8").write(new)
        status.append(f"{path}: OK")
    except SystemExit as exc:
        status.append(f"{path}: FAILED - {exc}")
    except Exception as exc:  # noqa: BLE001
        status.append(f"{path}: FAILED - {exc!r}")


# ---------------------------------------------------------------- supply_chain_api.py
def patch_api(s):
    if "INIT_DATA_MAX_AGE_SECONDS = 3600" in s:
        return s
    s = rep(s, "INIT_DATA_MAX_AGE_SECONDS = 600", "INIT_DATA_MAX_AGE_SECONDS = 3600")
    s = rep(s, "    TTL_SECONDS = 600\n", "    TTL_SECONDS = 1800\n")
    return s


# ---------------------------------------------------------------- supply_chain.py
def patch_supply_chain(s):
    if "only: Any = None" in s:
        return s
    s = rep(s,
            'def _xlsx_bytes(data: dict[str, Any]) -> bytes:\n    """Create a minimal standards-compliant XLSX using only Python stdlib."""\n    tables = _report_tables(data)\n',
            'def _xlsx_bytes(data: dict[str, Any], only: Any = None) -> bytes:\n    """Create a minimal standards-compliant XLSX using only Python stdlib."""\n    tables = _report_tables(data)\n    if only:\n        tables = {name: rows for name, rows in tables.items() if name in only}\n')
    s = rep(s,
            'def _pdf_bytes(data: dict[str, Any]) -> bytes:\n    """Create a compact text PDF without adding a runtime dependency."""\n    tables = _report_tables(data)\n',
            'def _pdf_bytes(data: dict[str, Any], only: Any = None) -> bytes:\n    """Create a compact text PDF without adding a runtime dependency."""\n    tables = _report_tables(data)\n    if only:\n        tables = {name: rows for name, rows in tables.items() if name in only}\n')
    return s


# ---------------------------------------------------------------- bot.py
BOT_HELPERS = r'''_SC_REPORT_SHEETS = {"inventory": ["Mahsulotlar"], "orders": ["Buyurtmalar"], "shipments": ["Transport"], "all": None}
_SC_REPORT_TITLES = {"inventory": "Ombor", "orders": "Xarid", "shipments": "Logistika", "all": "To‘liq"}


def _sc_build_report(snapshot, kind, fmt):
    """Build one Supply Chain report file: returns (filename, bytes, caption)."""
    only = _SC_REPORT_SHEETS[kind]
    title = _SC_REPORT_TITLES[kind]
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = f"supply-chain-{kind}-{stamp}"
    if fmt == "xlsx":
        return base + ".xlsx", supply_chain._xlsx_bytes(snapshot, only), f"📊 {title} hisoboti (Excel)"
    if fmt == "pdf":
        return base + ".pdf", supply_chain._pdf_bytes(snapshot, only), f"📄 {title} hisoboti (PDF)"
    import csv
    tables = supply_chain._report_tables(snapshot)
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def safe(value):
        if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
            return "'" + value
        return value

    for name, rows in tables.items():
        if only and name not in only:
            continue
        if not only:
            writer.writerow([f"[{name}]"])
        for row in rows:
            writer.writerow([safe(cell) for cell in row])
        if not only:
            writer.writerow([])
    return base + ".csv", ("\ufeff" + buffer.getvalue()).encode("utf-8"), f"🧾 {title} hisoboti (CSV)"


def _sc_send_document(chat_id, filename, content, caption):
    """Send a file to one Telegram chat through the Bot API (stdlib only, runs in the HTTP thread)."""
    import urllib.request
    boundary = "----scr" + uuid.uuid4().hex
    chunks = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode("utf-8"))
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception:
        raise RuntimeError("Telegram faylni yubora olmadi. Botga /start yozganingizni tekshiring.") from None
    if not result.get("ok"):
        raise RuntimeError("Telegram faylni yubora olmadi. Botga /start yozganingizni tekshiring.")


'''

BOT_METHOD = r'''        def _sc_report_send(self):
            if not _SC_STORAGE_READY.is_set():
                self._sc_error("not_ready", "Ma'lumotlar bazasi hali tayyor emas.", 503)
                return
            tenant_context = self._sc_tenant_context("reports.read")
            if tenant_context is False:
                return
            is_tenant_request = tenant_context is not None
            if not is_tenant_request and (
                    not OWNER_CHAT_ID
                    or not _SC_SESSIONS.authenticate(self._sc_bearer(), OWNER_CHAT_ID)):
                self._sc_error("unauthorized", "Sessiya yaroqsiz yoki muddati tugagan.", 401)
                return
            if not _SC_API_LIMITER.allow("write"):
                self._sc_error("rate_limited", "So'rovlar limiti tugadi.", 429)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096 or "application/json" not in self.headers.get("Content-Type", "").lower():
                    self._sc_error("invalid_request", "JSON so'rov formati noto'g'ri.", 400)
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._sc_error("invalid_request", "So'rov to'liq kelmadi.", 400)
                    return
                payload = json.loads(raw.decode("utf-8"))
                kind = payload.get("kind") if isinstance(payload, dict) else None
                fmt = payload.get("format") if isinstance(payload, dict) else None
                if not isinstance(kind, str) or kind not in _SC_REPORT_SHEETS or fmt not in ("xlsx", "csv", "pdf"):
                    self._sc_error("invalid_request", "Hisobot turi yoki formati noto'g'ri.", 400)
                    return
                if is_tenant_request:
                    snapshot = sc_tenants.TenantStore(_db_request).load_snapshot(tenant_context["company_id"])
                    chat_id = tenant_context["user_id"]
                else:
                    snapshot = load_json(supply_chain.DATA_FILE, {})
                    chat_id = OWNER_CHAT_ID
                filename, content, caption = _sc_build_report(snapshot, kind, fmt)
                _sc_send_document(chat_id, filename, content, caption)
                self._sc_json({"data": {"sent": True, "filename": filename},
                               "meta": {"request_id": uuid.uuid4().hex}, "error": None})
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._sc_error("invalid_request", "So'rov formati noto'g'ri.", 400)
            except RuntimeError as exc:
                self._sc_error("send_failed", str(exc), 502)
            except Exception:
                logger.exception("Supply Chain report send failed")
                self._sc_error("internal_error", "Hisobotni tayyorlab bo'lmadi.", 500)

'''


def patch_bot(s):
    if "_sc_build_report" in s:
        return s
    s = rep(s, "_SC_SESSION_LIMITER = sc_api.RateLimiter(max_requests=8, window_seconds=60)",
            "_SC_SESSION_LIMITER = sc_api.RateLimiter(max_requests=30, window_seconds=60)")
    s = rep(s, '                if u.path == "/museum" or u.path.startswith("/museum/"):\n                    museum.http_get(self, u)\n                    return\n',
            '                if u.path == "/supply_chain_visible_charts.js":\n'
            '                    js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supply_chain_visible_charts.js")\n'
            '                    with open(js_path, "rb") as js_file:\n'
            '                        body, ctype = js_file.read(), "application/javascript; charset=utf-8"\n'
            '                if u.path == "/museum" or u.path.startswith("/museum/"):\n'
            '                    museum.http_get(self, u)\n'
            '                    return\n')
    s = rep(s, "\ndef run_health_server():\n", "\n" + BOT_HELPERS + "def run_health_server():\n")
    s = rep(s, "        def _sc_api_post(self, parsed):\n", BOT_METHOD + "        def _sc_api_post(self, parsed):\n")
    s = rep(s, '            is_session = parsed.path == "/sc-api/v1/session"\n',
            '            if parsed.path == "/sc-api/v1/reports/send":\n                self._sc_report_send()\n                return\n'
            '            is_session = parsed.path == "/sc-api/v1/session"\n')
    return s


# ---------------------------------------------------------------- Mini App HTML
CSS_ADD = r'''    .top{padding-top:calc(18px + var(--tg-top,0px))}
    #fs-toggle{border:1px solid rgba(255,255,255,.35);background:transparent;color:#fff;border-radius:9px;padding:4px 10px;font-size:12px;font-weight:650;margin-left:10px}
    @media(min-width:1100px){.shell{max-width:1440px}}
    @media(min-width:1500px){.shell{max-width:1680px}}
'''

ALL_CARD = r'''
        <div class="card"><div class="chart-title">To‘liq hisobot</div><div class="chart-sub">Barcha bo‘limlar: ombor, yetkazib beruvchilar, buyurtmalar, transport, risklar, prognoz</div><div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap"><button class="retry" id="export-all" style="flex:1">CSV</button><button class="retry" id="export-all-xlsx" style="flex:1">Excel</button><button class="retry" id="export-all-pdf" style="flex:1">PDF</button></div></div>'''

EXPORT_JS = r'''  async function exportReport(kind,format="csv"){
    const labels={csv:"CSV",xlsx:"Excel",pdf:"PDF"};
    $("report-status").textContent=(labels[format]||format)+" hisoboti tayyorlanmoqda va chatga yuborilmoqda…";
    try{
      const result=await api("/sc-api/v1/reports/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind,format})});
      $("report-status").textContent="Yuborildi: "+result.filename+". Fayl bot bilan suhbatingizda (Telegram chat) turibdi.";
      try{if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("success");}catch(_){}
    }catch(error){
      if(kind==="all"){$("report-status").textContent="Chatga yuborib bo‘lmadi: "+error.message;return;}
      $("report-status").textContent="Chatga yuborib bo‘lmadi: "+error.message+" Brauzer orqali yuklab olishga urinilmoqda…";
      if(format==="pdf")await printReportLocal(kind);else await exportReportLocal(kind,format);
    }
  }
  async function exportReportLocal(kind,format="csv"){'''

PRINT_JS = r'''  async function printReport(kind){return exportReport(kind,"pdf");}
  async function printReportLocal(kind){'''

API_JS = r'''    if(response.status===401&&!options._retried&&token&&tg&&tg.initData){
      try{await reauthenticate();}catch(_){throw new Error("Sessiya muddati tugadi. Mini Appni yopib, botdan qayta oching.");}
      return api(path,{...options,_retried:true});
    }
    if(!response.ok) throw new Error(body.error?.message || ("HTTP "+response.status));
    const data=body.data;'''

WIDE_JS = r'''  let reauthPromise=null;
  function reauthenticate(){
    if(reauthPromise)return reauthPromise;
    reauthPromise=(async()=>{
      if(!tg||!tg.initData)throw new Error("Telegram sessiyasi topilmadi.");
      if(tenantMode&&tenantCompanyId){await activateTenantCompany(tenantCompanyId);return;}
      const response=await fetch("/sc-api/v1/session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:tg.initData}),cache:"no-store"});
      let payload={};try{payload=await response.json();}catch(_){}
      if(!response.ok)throw new Error(payload.error?.message||"Qayta kirish amalga oshmadi");
      token=payload.data.token;
    })().finally(()=>{reauthPromise=null;});
    return reauthPromise;
  }
  function applyInsets(){
    try{
      const top=((tg&&tg.safeAreaInset&&tg.safeAreaInset.top)||0)+((tg&&tg.contentSafeAreaInset&&tg.contentSafeAreaInset.top)||0);
      document.documentElement.style.setProperty("--tg-top",top+"px");
    }catch(_){}
  }
  function setupWideMode(){
    try{
      if(!tg||typeof tg.requestFullscreen!=="function")return;
      if(tg.isVersionAtLeast&&!tg.isVersionAtLeast("8.0"))return;
      const button=$("fs-toggle");
      const sync=()=>{button.textContent=tg.isFullscreen?"⤡ Kichraytirish":"⛶ Katta ekran";applyInsets();};
      button.hidden=false;sync();
      button.addEventListener("click",()=>{try{if(tg.isFullscreen)tg.exitFullscreen();else tg.requestFullscreen();}catch(_){}});
      ["fullscreenChanged","safeAreaChanged","contentSafeAreaChanged"].forEach(name=>{try{tg.onEvent(name,sync);}catch(_){}});
      try{tg.onEvent("fullscreenFailed",()=>{});}catch(_){}
      const desktop=["tdesktop","macos","weba","webk","unigram"].includes(tg.platform);
      if(desktop&&window.innerWidth<900&&!tg.isFullscreen)tg.requestFullscreen();
    }catch(_){}
  }
  async function authenticate() {'''

LISTENERS = r'''  window.addEventListener("afterprint",()=>{$("print-area").hidden=true;});
  $("export-all").addEventListener("click",()=>exportReport("all"));
  $("export-all-xlsx").addEventListener("click",()=>exportReport("all","xlsx"));
  $("export-all-pdf").addEventListener("click",()=>exportReport("all","pdf"));'''


def patch_html(s):
    if "reports/send" in s:
        return s
    s = rep(s, "    #print-area{display:none}\n", CSS_ADD + "    #print-area{display:none}\n")
    s = rep(s, '<span id="connection">Ulanmoqda</span></div></div>',
            '<span id="connection">Ulanmoqda</span><button id="fs-toggle" type="button" hidden>⛶ Katta ekran</button></div></div>')
    s = rep(s, 'id="export-shipments-pdf" style="flex:1">PDF</button></div></div>',
            'id="export-shipments-pdf" style="flex:1">PDF</button></div></div>' + ALL_CARD)
    s = rep(s, "Hisobotlar brauzerda yaratiladi.",
            "Hisobot serverda tayyorlanib, Telegram chatingizga fayl sifatida yuboriladi (yuborilmasa, brauzer orqali yuklab olishga urinadi).")
    s = rep(s, '  async function exportReport(kind,format="csv"){', EXPORT_JS)
    s = rep(s, "  async function printReport(kind){", PRINT_JS)
    s = rep(s, "  async function authenticate() {", WIDE_JS)
    s = rep(s, "    tg.ready();tg.expand();", "    tg.ready();tg.expand();setupWideMode();")
    s = rep(s, '    if(!response.ok) throw new Error(body.error?.message || ("HTTP "+response.status));\n    const data=body.data;', API_JS)
    s = rep(s, '$("retry").hidden=!retry; };',
            '$("retry").hidden=!retry; try{$("notice").scrollIntoView({behavior:"smooth",block:"center"});}catch(_){} };')
    s = rep(s, '  window.addEventListener("afterprint",()=>{$("print-area").hidden=true;});', LISTENERS)
    return s


patch_file("supply_chain_api.py", patch_api)
patch_file("supply_chain.py", patch_supply_chain)
patch_file("bot.py", patch_bot)
patch_file("supply_chain_mini_app.html", patch_html)
print("\n".join(status))
