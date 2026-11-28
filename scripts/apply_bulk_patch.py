"""One-time patch: bulk archive / permanent delete of inventory products (selected or all).

Backend: POST /sc-api/v1/inventory/bulk (one atomic CAS mutation, tenant-aware, idempotent).
Mini App: row checkboxes, "select all", and two buttons (Arxivlash / O'chirish).
Each file is patched independently and all-or-nothing.
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


# ---------------------------------------------------------------- bot.py
BOT_HELPERS = r'''def _sc_apply_inventory_bulk(snapshot, payload, actor_id):
    """Archive or permanently delete many SKUs in one validated mutation (selected list or all)."""
    if not isinstance(snapshot, dict) or not isinstance(payload, dict):
        raise ValueError("JSON object talab qilinadi.")
    action = payload.get("action")
    if action not in ("archive", "delete"):
        raise ValueError("Amal turi noto'g'ri.")
    products = snapshot.get("products")
    if not isinstance(products, dict):
        raise ValueError("Mahsulotlar ro'yxati noto'g'ri.")
    select_all = payload.get("all") is True
    missing = 0
    if select_all:
        keys = list(products)
    else:
        skus = payload.get("skus")
        if (not isinstance(skus, list) or not 1 <= len(skus) <= 1000
                or not all(isinstance(item, str) and item.strip() and len(item.strip()) <= 128 for item in skus)):
            raise ValueError("SKU ro'yxati noto'g'ri.")
        lookup = {}
        for key in products:
            lookup.setdefault(str(key).casefold(), key)
        keys = []
        seen = set()
        for sku in skus:
            key = lookup.get(sku.strip().casefold())
            if key is None:
                missing += 1
            elif key not in seen:
                seen.add(key)
                keys.append(key)
    archived = snapshot.setdefault("deleted_products", [])
    if not isinstance(archived, list):
        raise ValueError("Arxiv ro'yxati noto'g'ri.")
    if action == "archive":
        if len(archived) + len(keys) > 10000:
            raise ValueError("Arxiv limiti to'lgan; administrator tekshiruvi kerak.")
        stamp = datetime.now(timezone.utc).isoformat()
        for key in keys:
            archived.append({
                "sku": str(key), "product": copy.deepcopy(products[key]),
                "archived_at": stamp, "archived_by": str(actor_id),
            })
            del products[key]
        return {"action": "archive", "processed": len(keys), "missing": missing}
    removed = {str(key).casefold() for key in keys}
    for key in keys:
        del products[key]
    before = len(archived)
    if select_all:
        snapshot["deleted_products"] = []
    else:
        snapshot["deleted_products"] = [
            item for item in archived
            if not (isinstance(item, dict) and str(item.get("sku", "")).casefold() in removed)]
    return {"action": "delete", "processed": len(keys), "missing": missing,
            "archive_removed": before - len(snapshot["deleted_products"])}


def _sc_bulk_inventory_legacy(payload, request_hash):
    """Owner (non-company) dataset: same serialized JSONB-CAS writer as single archive."""
    if not USE_DB:
        raise sc_persistence.PersistenceError("Ommaviy amal uchun Supabase saqlash xizmati kerak.")

    def mutate(snapshot):
        return _sc_apply_inventory_bulk(snapshot, payload, "owner-mini-app")

    with _storage_save_lock:
        result = _get_sc_commit_adapter().commit(
            expected_version=payload["expected_version"], operation_id=payload["operation_id"],
            request_hash=request_hash, mutate=mutate)
        try:
            latest = _sc_storage_load()
        except Exception:
            with _cache_lock:
                _cache.pop(_SC_STORAGE_KEY, None)
        else:
            with _cache_lock:
                _cache[_SC_STORAGE_KEY] = copy.deepcopy(latest)
        return result


'''

BOT_METHOD = r'''        def _sc_inventory_bulk(self):
            if not _SC_STORAGE_READY.is_set():
                self._sc_error("not_ready", "Ma'lumotlar bazasi hali tayyor emas.", 503)
                return
            tenant_context = self._sc_tenant_context("inventory.write")
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
                if length <= 0 or length > 65536 or "application/json" not in self.headers.get("Content-Type", "").lower():
                    self._sc_error("invalid_request", "JSON so'rov hajmi yoki formati noto'g'ri.", 400)
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._sc_error("invalid_request", "So'rov to'liq kelmadi.", 400)
                    return
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object talab qilinadi.")
                action = payload.get("action")
                expected = payload.get("expected_version")
                operation_id = payload.get("operation_id")
                select_all = payload.get("all") is True
                skus = payload.get("skus")
                if action not in ("archive", "delete"):
                    raise ValueError("Amal turi noto'g'ri.")
                if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
                    raise ValueError("Ma'lumot versiyasi noto'g'ri.")
                if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", operation_id):
                    raise ValueError("Amal identifikatori noto'g'ri.")
                if not select_all and (
                        not isinstance(skus, list) or not 1 <= len(skus) <= 1000
                        or not all(isinstance(item, str) and item.strip() for item in skus)):
                    raise ValueError("SKU ro'yxati noto'g'ri.")
                request_hash = hashlib.sha256(json.dumps(
                    {"action": "inventory_bulk_" + action, "all": select_all,
                     "skus": None if select_all else sorted({item.strip().casefold() for item in skus}),
                     "expected_version": expected},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")).hexdigest()
                if is_tenant_request:
                    permission = "inventory.delete" if action == "delete" else "inventory.write"
                    mutation = sc_tenants.TenantStore(_db_request).mutate_snapshot(
                        tenant_context["company_id"], tenant_context["user_id"], permission,
                        lambda snapshot: _sc_apply_inventory_bulk(snapshot, payload, tenant_context["user_id"]),
                        expected_version=expected, operation_id=operation_id, request_hash=request_hash)
                    result = {"data": mutation["result"], "data_version": mutation["version"],
                              "replayed": mutation.get("replayed", False)}
                else:
                    result = {"data": _sc_bulk_inventory_legacy(payload, request_hash)}
                self._sc_json({"data": result, "meta": {"request_id": uuid.uuid4().hex}, "error": None})
            except sc_tenants.TenantOperationConflict as exc:
                self._sc_error("idempotency_conflict", str(exc), 409)
            except sc_tenants.SnapshotVersionConflict:
                self._sc_error("version_conflict", "Ma'lumotlar o'zgargan. Sahifani yangilab qayta urinib ko'ring.", 409)
            except sc_persistence.VersionConflict:
                self._sc_error("version_conflict", "Ma'lumotlar o'zgargan. Sahifani yangilab qayta urinib ko'ring.", 409)
            except (sc_tenants.PermissionDenied, sc_tenants.MembershipRequired):
                self._sc_error("forbidden", "Bu amal uchun ruxsat berilmagan (faqat egasi yoki administrator o'chira oladi).", 403)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._sc_error("invalid_request", str(exc) or "So'rov noto'g'ri.", 400)
            except sc_persistence.CommitOutcomeUnknown:
                self._sc_error("outcome_unknown", "Natija tasdiqlanmadi. Qayta urinishdan oldin omborni yangilang.", 503)
            except sc_persistence.PersistenceError as exc:
                self._sc_error("storage_error", str(exc), 503)
            except Exception:
                logger.exception("Supply Chain inventory bulk endpoint failed")
                self._sc_error("internal_error", "Ichki server xatosi.", 500)

'''


def patch_bot(s):
    if "_sc_apply_inventory_bulk" in s:
        return s
    s = rep(s, "\ndef run_health_server():\n", "\n" + BOT_HELPERS + "def run_health_server():\n")
    s = rep(s, "        def _sc_report_send(self):\n", BOT_METHOD + "        def _sc_report_send(self):\n")
    s = rep(s, '            if parsed.path == "/sc-api/v1/reports/send":\n',
            '            if parsed.path == "/sc-api/v1/inventory/bulk":\n                self._sc_inventory_bulk()\n                return\n'
            '            if parsed.path == "/sc-api/v1/reports/send":\n')
    return s


# ---------------------------------------------------------------- Mini App HTML
CSS_ADD = r'''    .sel{width:20px;height:20px;accent-color:var(--navy);flex:none}
    .bulkbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px}
    .bulkbar .muted{flex:1;min-width:150px;font-size:13px}
    .bulkbar button:disabled{opacity:.45;cursor:not-allowed}
    .danger.hard{background:#a83232;color:#fff;border-color:#a83232}
    .select-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:12px;color:var(--muted)}
'''

BULK_BAR = r'''      <div class="bulkbar" id="bulkbar"><span class="muted" id="bulk-count">Hech narsa tanlanmagan</span><button class="retry" id="bulk-all" type="button">Hammasini tanlash</button><button class="retry" id="bulk-clear" type="button" hidden>Bekor qilish</button><button class="danger" id="bulk-archive" type="button" disabled>Arxivlash</button><button class="danger hard" id="bulk-delete" type="button" disabled>O‘chirish</button></div>
      <div class="muted" id="bulk-status" style="font-size:12px;margin:-4px 0 10px" aria-live="polite"></div>
      <div class="table-wrap"><table class="table"><thead><tr><th><input type="checkbox" id="select-page" class="sel" aria-label="Sahifadagilarni belgilash"></th><th>SKU / Mahsulot</th>'''

BULK_JS = r'''  const selectedSkus=new Set();let selectAllMode=false,inventoryTotal=0,bulkBusy=false;
  function makeSelectBox(sku){
    const box=document.createElement("input");box.type="checkbox";box.className="sel";box.dataset.sku=sku;
    box.checked=selectAllMode||selectedSkus.has(sku);box.disabled=bulkBusy||selectAllMode;
    box.setAttribute("aria-label",sku+" ni tanlash");
    box.addEventListener("click",event=>event.stopPropagation());
    box.addEventListener("change",()=>{
      if(box.checked)selectedSkus.add(sku);else selectedSkus.delete(sku);
      document.querySelectorAll("input.sel[data-sku]").forEach(other=>{if(other.dataset.sku===sku)other.checked=box.checked;});
      updateBulkBar();
    });
    return box;
  }
  function updateBulkBar(){
    const count=selectAllMode?inventoryTotal:selectedSkus.size;
    const canWrite=!tenantMode||["owner","admin","warehouse"].includes(tenantRole);
    const canDelete=!tenantMode||["owner","admin"].includes(tenantRole);
    $("bulk-count").textContent=selectAllMode?("Barcha "+fmt(inventoryTotal)+" ta mahsulot tanlandi"):(selectedSkus.size?fmt(selectedSkus.size)+" ta tanlandi":"Hech narsa tanlanmagan");
    $("bulk-archive").disabled=bulkBusy||count===0||!canWrite;
    $("bulk-delete").disabled=bulkBusy||count===0||!canDelete;
    $("bulk-all").hidden=selectAllMode||inventoryTotal===0;
    $("bulk-all").textContent="Hammasini tanlash ("+fmt(inventoryTotal)+")";
    $("bulk-clear").hidden=count===0;
    const boxes=[...document.querySelectorAll("#inventory-table input.sel")];
    const pageBox=$("select-page");pageBox.disabled=bulkBusy||selectAllMode||boxes.length===0;pageBox.checked=boxes.length>0&&boxes.every(b=>b.checked);
  }
  function clearSelection(){
    selectedSkus.clear();selectAllMode=false;
    document.querySelectorAll("input.sel[data-sku]").forEach(b=>{b.checked=false;b.disabled=bulkBusy;});
    updateBulkBar();
  }
  async function runBulk(action){
    if(bulkBusy)return;
    const all=selectAllMode;const skus=[...selectedSkus];
    const count=all?inventoryTotal:skus.length;if(!count)return;
    const verb=action==="delete"?"BUTUNLAY O‘CHIRILADI":"arxivga o‘tkaziladi";
    const warn=action==="delete"?"\n\nBu amalni qaytarib bo‘lmaydi. Mahsulot arxivdan ham o‘chadi.":"\n\nMahsulotlar o‘chmaydi: arxivda saqlanadi.";
    if(!confirm((all?"Ombordagi BARCHA "+count+" ta mahsulot (filtrdan qat’i nazar) ":count+" ta tanlangan mahsulot ")+verb+"."+warn+"\n\nDavom etamizmi?"))return;
    if(action==="delete"&&all&&!confirm("Oxirgi tasdiq: barcha "+count+" ta mahsulot butunlay o‘chiriladi. Aniqmisiz?"))return;
    bulkBusy=true;updateBulkBar();$("bulk-status").textContent="Bajarilmoqda…";
    try{
      if(!Number.isInteger(inventoryVersion)||inventoryVersion<1)throw new Error("Avval ombor ro‘yxatini yangilang.");
      const operationId=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():("bulk-"+Date.now()+"-"+Math.random().toString(36).slice(2,10));
      const body={action,expected_version:inventoryVersion,operation_id:operationId};
      if(all)body.all=true;else body.skus=skus;
      const result=await api("/sc-api/v1/inventory/bulk",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      const info=(result&&result.data)||result||{};
      const processed=info.processed!==undefined?info.processed:(info.result&&info.result.processed!==undefined?info.result.processed:count);
      selectedSkus.clear();selectAllMode=false;
      $("bulk-status").textContent=(action==="delete"?"O‘chirildi: ":"Arxivlandi: ")+fmt(processed)+" ta mahsulot.";
      page=1;await refreshAll();if(currentView==="inventory")await loadInventory();
    }catch(error){
      $("bulk-status").textContent="Bajarilmadi: "+error.message;
      if(/o.zgargan|version/i.test(error.message)){try{await loadInventory();}catch(_){}}
    }finally{bulkBusy=false;updateBulkBar();}
  }
  async function archiveInventoryProduct(sku,name){'''

BULK_LISTENERS = r'''  $("select-page").addEventListener("change",event=>{
    document.querySelectorAll("#inventory-table input.sel[data-sku]").forEach(box=>{box.checked=event.target.checked;if(event.target.checked)selectedSkus.add(box.dataset.sku);else selectedSkus.delete(box.dataset.sku);});
    document.querySelectorAll("#inventory-mobile input.sel[data-sku]").forEach(box=>{box.checked=selectedSkus.has(box.dataset.sku);});
    updateBulkBar();
  });
  $("bulk-all").addEventListener("click",()=>{selectAllMode=true;document.querySelectorAll("input.sel[data-sku]").forEach(b=>{b.checked=true;b.disabled=true;});updateBulkBar();});
  $("bulk-clear").addEventListener("click",clearSelection);
  $("bulk-archive").addEventListener("click",()=>runBulk("archive"));
  $("bulk-delete").addEventListener("click",()=>runBulk("delete"));
  $("prev").addEventListener("click",()=>{if(page>1){page--;'''


def patch_html(s):
    if "runBulk" in s:
        return s
    s = rep(s, "    #print-area{display:none}\n", CSS_ADD + "    #print-area{display:none}\n")
    s = rep(s, '      <div class="table-wrap"><table class="table"><thead><tr><th>SKU / Mahsulot</th>', BULK_BAR)
    s = rep(s, '      const tr=el("tr","");const status=p.stock_level==="low"?"Kam":',
            '      const tr=el("tr","");const selectCell=el("td","");selectCell.append(makeSelectBox(p.sku));tr.append(selectCell);const status=p.stock_level==="low"?"Kam":')
    s = rep(s, "actions.append(del);c.append(actions);return c;",
            'actions.append(del);c.append(actions);const pick=el("label","select-row");pick.append(makeSelectBox(p.sku),el("span","","Tanlash"));pick.addEventListener("click",event=>event.stopPropagation());c.prepend(pick);return c;')
    s = rep(s, 'tr.classList.add("clickable-row");table.append(tr);mobile.append(makeProductCard(p));\n    });',
            'tr.classList.add("clickable-row");table.append(tr);mobile.append(makeProductCard(p));\n    });\n    updateBulkBar();')
    s = rep(s, 'mobile.append(el("div","notice","Mahsulot topilmadi"));return;}',
            'mobile.append(el("div","notice","Mahsulot topilmadi"));updateBulkBar();return;}')
    s = rep(s, "inventoryVersion=Number(data.data_version||1);\n    totalPages=",
            "inventoryVersion=Number(data.data_version||1);inventoryTotal=Number((data.pagination&&data.pagination.total)||0);\n    totalPages=")
    s = rep(s, "  async function archiveInventoryProduct(sku,name){", BULK_JS)
    s = rep(s, '  $("prev").addEventListener("click",()=>{if(page>1){page--;', BULK_LISTENERS)
    return s


patch_file("bot.py", patch_bot)
patch_file("supply_chain_mini_app.html", patch_html)
print("\n".join(status))
