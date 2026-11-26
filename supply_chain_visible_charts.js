(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const num = value => {
    const raw = String(value ?? "").replace(/\s/g, "").replace(/[^\d,.-]/g, "");
    if (!raw) return NaN;
    const normalized = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw;
    return Number(normalized);
  };
  function setup() {
    const view = $("analytics-view");
    if (!view || $("visible-chart-style")) return;
    const style = document.createElement("style");
    style.id = "visible-chart-style";
    style.textContent = [
      ".live-chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}",
      ".live-chart-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:15px;min-width:0}",
      ".live-chart-title{font-weight:750;color:var(--navy);margin-bottom:4px}",
      ".live-chart-sub{font-size:11px;color:var(--muted);margin-bottom:15px}",
      ".live-bars{display:grid;gap:12px}",
      ".live-bar-row{display:grid;grid-template-columns:minmax(76px,1fr) minmax(100px,2fr) auto;align-items:center;gap:9px}",
      ".live-bar-name{font-size:11px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".live-bar-track{height:13px;background:#edf1f5;border-radius:20px;overflow:hidden;position:relative}",
      ".live-bar-fill{height:100%;border-radius:20px;background:#3679ad}",
      ".live-bar-fill.low{background:#bd7b18}",
      ".live-bar-value{font-size:10px;color:#526174;white-space:nowrap;font-weight:700}",
      ".live-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:13px;font-size:10px;color:var(--muted)}",
      ".live-legend span{display:flex;align-items:center;gap:5px}",
      ".live-legend i{width:8px;height:8px;border-radius:50%;display:inline-block;background:#3679ad}",
      ".live-forecast{display:flex;align-items:flex-end;gap:8px;height:180px;padding:10px 2px 0;border-bottom:1px solid var(--line);overflow-x:auto}",
      ".live-column{min-width:34px;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:5px}",
      ".live-column-bar{width:min(26px,75%);min-height:2px;border-radius:6px 6px 0 0;background:linear-gradient(180deg,#5b9bd0,#244d78)}",
      ".live-column-value{font-size:9px;color:var(--muted);white-space:nowrap}",
      ".live-column-label{font-size:9px;color:#526174;text-align:center;max-width:58px;overflow:hidden;text-overflow:ellipsis}",
      ".live-empty{font-size:12px;color:var(--muted);padding:18px;text-align:center;background:#f8fafc;border-radius:10px}",
      "@media(max-width:760px){.live-chart-grid{grid-template-columns:1fr}.live-bar-row{grid-template-columns:minmax(76px,1fr) minmax(100px,1.6fr) auto}}"
    ].join("");
    document.head.append(style);
    const grid = document.createElement("div");
    grid.className = "live-chart-grid";
    grid.innerHTML = '<section class="live-chart-card"><div class="live-chart-title">Zaxira va buyurtma chegarasi</div><div class="live-chart-sub">Joriy miqdor reorder nuqtasi bilan taqqoslanadi</div><div id="live-stock-bars" class="live-bars"><div class="live-empty">Ma’lumot yuklanmoqda…</div></div><div class="live-legend"><span><i></i> Joriy zaxira</span><span><i style="background:#bd7b18"></i> Kam zaxira</span></div></section><section class="live-chart-card"><div class="live-chart-title">Keyingi oy talab prognozi</div><div class="live-chart-sub">API hisoblagan prognozlar, mahsulotlar kesimida</div><div id="live-demand-bars" class="live-forecast"><div class="live-empty">Prognoz yuklanmoqda…</div></div></section>';
    const controls = view.querySelector(".analytics-controls");
    if (controls) controls.insertAdjacentElement("afterend", grid);
    const stock = $("stock-chart"), forecast = $("forecast-table");
    const renderStock = () => {
      const target = $("live-stock-bars");
      if (!target || !stock) return;
      const groups = [...stock.querySelectorAll("svg g")];
      const rows = groups.map(g => {
        const texts = [...g.querySelectorAll("text")].map(t => t.textContent.trim());
        const rects = [...g.querySelectorAll("rect")];
        const line = g.querySelector("line");
        if (rects.length < 2 || texts.length < 2) return null;
        const backgroundWidth = Number(rects[0].getAttribute("width")) || 340;
        const currentWidth = Number(rects[1].getAttribute("width")) || 0;
        const reorderX = Number(line?.getAttribute("x1")) || 220;
        const barX = Number(rects[0].getAttribute("x")) || 220;
        const ratio = Math.max(0, Math.min(1.5, (reorderX - barX) / backgroundWidth));
        return {name:texts[0],current:Math.max(0,Math.min(1.5,currentWidth/backgroundWidth)),reorder:ratio,label:texts[texts.length-1]||""};
      }).filter(Boolean);
      target.replaceChildren();
      if (!rows.length) { target.innerHTML='<div class="live-empty">Zaxira grafigi uchun ma’lumot yo‘q.</div>'; return; }
      rows.forEach(row => {
        const line=document.createElement("div");line.className="live-bar-row";
        const name=document.createElement("div");name.className="live-bar-name";name.textContent=row.name;
        const track=document.createElement("div");track.className="live-bar-track";
        const fill=document.createElement("div");fill.className="live-bar-fill";fill.style.width=(row.current/1.5*100)+"%";
        if(row.current<row.reorder)fill.classList.add("low");
        track.append(fill);
        const value=document.createElement("div");value.className="live-bar-value";value.textContent=row.label;
        line.append(name,track,value);target.append(line);
      });
    };
    const renderDemand = () => {
      const target=$("live-demand-bars");
      if(!target || !forecast) return;
      const rows=[...forecast.querySelectorAll("tr")].map(tr=>{
        const cells=[...tr.querySelectorAll("td")].map(td=>td.textContent.trim());
        if(cells.length<3) return null;
        const value=num(cells[2]);
        return Number.isFinite(value)&&value>=0?{name:cells[0].split(" · ")[0],value}:null;
      }).filter(Boolean).slice(0,16);
      target.replaceChildren();
      if(!rows.length){target.innerHTML='<div class="live-empty">Kamida 3 oylik talab tarixi bo‘lgan mahsulotlarda prognoz ko‘rinadi.</div>';return;}
      const max=Math.max(1,...rows.map(r=>r.value));
      rows.forEach(row=>{
        const col=document.createElement("div");col.className="live-column";
        const value=document.createElement("div");value.className="live-column-value";value.textContent=new Intl.NumberFormat("uz-UZ",{maximumFractionDigits:1}).format(row.value);
        const bar=document.createElement("div");bar.className="live-column-bar";bar.style.height=Math.max(2,row.value/max*125)+"px";bar.title=row.name+" · "+row.value;
        const label=document.createElement("div");label.className="live-column-label";label.textContent=row.name;
        col.append(value,bar,label);target.append(col);
      });
    };
    const observe = (node, fn) => {
      if (!node) return;
      new MutationObserver(fn).observe(node,{childList:true,subtree:true,attributes:true});
      fn();
    };
    observe(stock,renderStock);
    observe(forecast,renderDemand);
    $("analytics-refresh")?.addEventListener("click",()=>setTimeout(()=>{renderStock();renderDemand();},500));
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",setup,{once:true});else setup();
})();