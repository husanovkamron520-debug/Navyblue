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
    grid.innerHTML = '<section class="live-chart-card"><div class="live-chart-title">X–Y koordinata grafigi: zaxira holati</div><div class="live-chart-sub">X — qayta buyurtma nuqtasi · Y — joriy zaxira. Har bir nuqta bitta mahsulot.</div><div id="live-xy-scatter"><div class="live-empty">Koordinata grafigi yuklanmoqda…</div></div></section><section class="live-chart-card"><div class="live-chart-title">Zaxira va buyurtma chegarasi</div><div class="live-chart-sub">Joriy miqdor reorder nuqtasi bilan taqqoslanadi</div><div id="live-stock-bars" class="live-bars"><div class="live-empty">Ma’lumot yuklanmoqda…</div></div><div class="live-legend"><span><i></i> Joriy zaxira</span><span><i style="background:#bd7b18"></i> Kam zaxira</span></div></section><section class="live-chart-card" style="grid-column:1/-1"><div class="live-chart-title">Talab dinamikasi · X–Y chiziqli grafik</div><div class="live-chart-sub">X — oylar · Y — real talab miqdori. Mahsulotni tanlab, tarixiy o‘zgarishni ko‘ring.</div><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px"><label for="live-demand-product" style="font-size:12px;font-weight:650">Mahsulot</label><select id="live-demand-product" style="min-width:180px;max-width:100%;padding:9px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--navy)"></select></div><div id="live-demand-line"><div class="live-empty">Talab tarixi yuklanmoqda…</div></div></section><section class="live-chart-card"><div class="live-chart-title">Keyingi oy talab prognozi</div><div class="live-chart-sub">API hisoblagan prognozlar, mahsulotlar kesimida</div><div id="live-demand-bars" class="live-forecast"><div class="live-empty">Prognoz yuklanmoqda…</div></div></section>';
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
        const current=Number(g.getAttribute("data-stock-quantity")); const exactReorder=Number(g.getAttribute("data-reorder-point")); return {name:g.getAttribute("data-product-name")||texts[0],current:Math.max(0,Math.min(1.5,currentWidth/backgroundWidth)),reorder:ratio,stockValue:Number.isFinite(current)?current:NaN,reorderValue:Number.isFinite(exactReorder)?exactReorder:NaN,label:texts[texts.length-1]||""};
      }).filter(Boolean);
      target.replaceChildren();
      const xy=$("live-xy-scatter");
      if (xy) {
        xy.replaceChildren();
        const points=rows.map(row=>({name:row.name,x:Number.isFinite(row.reorderValue)?row.reorderValue:num(row.label.split("/")[1]),y:Number.isFinite(row.stockValue)?row.stockValue:num(row.label.split("/")[0])})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.y>=0);
        if (!points.length) { xy.innerHTML='<div class="live-empty">X–Y grafigi uchun miqdorlar mavjud emas.</div>'; }
        else {
          const ns="http://www.w3.org/2000/svg", W=520,H=310,L=58,R=20,T=18,B=52;
          const maxX=Math.max(1,...points.map(p=>p.x))*1.12,maxY=Math.max(1,...points.map(p=>p.y))*1.12;
          const sx=v=>L+(v/maxX)*(W-L-R),sy=v=>H-B-(v/maxY)*(H-T-B);
          const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 "+W+" "+H);svg.setAttribute("role","img");svg.setAttribute("aria-label","X o‘qida reorder nuqtasi, Y o‘qida joriy zaxira bo‘yicha mahsulotlar scatter grafigi");svg.style.width="100%";svg.style.height="auto";
          for(let i=0;i<=4;i++){
            const x=L+(W-L-R)*i/4,y=H-B-(H-T-B)*i/4;
            const gx=document.createElementNS(ns,"line");gx.setAttribute("x1",L);gx.setAttribute("x2",W-R);gx.setAttribute("y1",y);gx.setAttribute("y2",y);gx.setAttribute("stroke","#e7edf3");svg.append(gx);
            const gy=document.createElementNS(ns,"line");gy.setAttribute("x1",x);gy.setAttribute("x2",x);gy.setAttribute("y1",T);gy.setAttribute("y2",H-B);gy.setAttribute("stroke","#e7edf3");svg.append(gy);
            const yt=document.createElementNS(ns,"text");yt.setAttribute("x",L-9);yt.setAttribute("y",y+4);yt.setAttribute("text-anchor","end");yt.setAttribute("font-size","10");yt.setAttribute("fill","#64748b");yt.textContent=new Intl.NumberFormat("uz-UZ",{maximumFractionDigits:1}).format(maxY*i/4);svg.append(yt);
            const xt=document.createElementNS(ns,"text");xt.setAttribute("x",x);xt.setAttribute("y",H-B+17);xt.setAttribute("text-anchor","middle");xt.setAttribute("font-size","10");xt.setAttribute("fill","#64748b");xt.textContent=new Intl.NumberFormat("uz-UZ",{maximumFractionDigits:1}).format(maxX*i/4);svg.append(xt);
          }
          const axisX=document.createElementNS(ns,"line");axisX.setAttribute("x1",L);axisX.setAttribute("x2",W-R);axisX.setAttribute("y1",H-B);axisX.setAttribute("y2",H-B);axisX.setAttribute("stroke","#526174");axisX.setAttribute("stroke-width","1.5");svg.append(axisX);
          const axisY=document.createElementNS(ns,"line");axisY.setAttribute("x1",L);axisY.setAttribute("x2",L);axisY.setAttribute("y1",T);axisY.setAttribute("y2",H-B);axisY.setAttribute("stroke","#526174");axisY.setAttribute("stroke-width","1.5");svg.append(axisY);
          const xl=document.createElementNS(ns,"text");xl.setAttribute("x",(L+W-R)/2);xl.setAttribute("y",H-8);xl.setAttribute("text-anchor","middle");xl.setAttribute("font-size","11");xl.setAttribute("font-weight","700");xl.setAttribute("fill","#18395e");xl.textContent="X · Reorder nuqtasi";svg.append(xl);
          const yl=document.createElementNS(ns,"text");yl.setAttribute("x",14);yl.setAttribute("y",(T+H-B)/2);yl.setAttribute("transform","rotate(-90 14 "+((T+H-B)/2)+")");yl.setAttribute("text-anchor","middle");yl.setAttribute("font-size","11");yl.setAttribute("font-weight","700");yl.setAttribute("fill","#18395e");yl.textContent="Y · Joriy zaxira";svg.append(yl);
          points.forEach(p=>{const c=document.createElementNS(ns,"circle");c.setAttribute("cx",sx(p.x));c.setAttribute("cy",sy(p.y));c.setAttribute("r","5.5");c.setAttribute("fill",p.y<p.x?"#bd7b18":"#3679ad");c.setAttribute("stroke","#fff");c.setAttribute("stroke-width","1.5");const title=document.createElementNS(ns,"title");title.textContent=p.name+" · Reorder: "+p.x+" · Zaxira: "+p.y;c.append(title);svg.append(c);});
          xy.append(svg);
          const note=document.createElement("div");note.className="live-chart-sub";note.textContent=points.length+" ta mahsulot · nuqtalar ustiga bosib miqdorlarni ko‘ring.";xy.append(note);
        }
      }
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
    let demandPayload=null;
    function renderDemandLine(){
      const target=$("live-demand-line"),select=$("live-demand-product");
      if(!target||!select||!demandPayload)return;
      const items=(demandPayload.items||[]).filter(item=>Array.isArray(item.history)&&item.history.length);
      const previous=select.value;
      select.replaceChildren();
      items.forEach(item=>{const option=document.createElement("option");option.value=item.sku;option.textContent=item.name+" · "+item.sku;select.append(option);});
      if(items.some(item=>item.sku===previous))select.value=previous;
      const chosen=items.find(item=>item.sku===select.value)||items[0];
      target.replaceChildren();
      if(!chosen){target.innerHTML='<div class="live-empty">Talab tarixi hali kiritilmagan. Haqiqiy oylik yozuvlar qo‘shilgach grafik paydo bo‘ladi.</div>';return;}
      const points=chosen.history.filter(p=>Number.isFinite(Number(p.quantity))&&Number(p.quantity)>=0).slice(-6);
      if(!points.length){target.innerHTML='<div class="live-empty">Tanlangan mahsulot uchun chizishga yaroqli tarix yo‘q.</div>';return;}
      const ns="http://www.w3.org/2000/svg",W=560,H=300,L=58,R=22,T=22,B=52;
      const max=Math.max(1,...points.map(p=>Number(p.quantity)))*1.15;
      const sx=i=>points.length===1?(L+W-R)/2:L+i*(W-L-R)/(points.length-1);
      const sy=v=>H-B-(Number(v)/max)*(H-T-B);
      const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 "+W+" "+H);svg.setAttribute("role","img");svg.setAttribute("aria-label",chosen.name+" mahsulotining oylik talab chiziqli grafigi");svg.style.width="100%";svg.style.height="auto";
      for(let i=0;i<=4;i++){const y=H-B-(H-T-B)*i/4;const gridline=document.createElementNS(ns,"line");gridline.setAttribute("x1",L);gridline.setAttribute("x2",W-R);gridline.setAttribute("y1",y);gridline.setAttribute("y2",y);gridline.setAttribute("stroke","#e7edf3");svg.append(gridline);const label=document.createElementNS(ns,"text");label.setAttribute("x",L-9);label.setAttribute("y",y+4);label.setAttribute("text-anchor","end");label.setAttribute("font-size","10");label.setAttribute("fill","#64748b");label.textContent=new Intl.NumberFormat("uz-UZ",{maximumFractionDigits:1}).format(max*i/4);svg.append(label);}
      const axis=document.createElementNS(ns,"line");axis.setAttribute("x1",L);axis.setAttribute("x2",W-R);axis.setAttribute("y1",H-B);axis.setAttribute("y2",H-B);axis.setAttribute("stroke","#526174");svg.append(axis);
      const path=document.createElementNS(ns,"path");path.setAttribute("d",points.map((p,i)=>(i?"L":"M")+sx(i)+" "+sy(p.quantity)).join(" "));path.setAttribute("fill","none");path.setAttribute("stroke","#3679ad");path.setAttribute("stroke-width","3");path.setAttribute("stroke-linecap","round");path.setAttribute("stroke-linejoin","round");svg.append(path);
      points.forEach((p,i)=>{const circle=document.createElementNS(ns,"circle");circle.setAttribute("cx",sx(i));circle.setAttribute("cy",sy(p.quantity));circle.setAttribute("r","5");circle.setAttribute("fill","#244d78");circle.setAttribute("stroke","#fff");circle.setAttribute("stroke-width","2");const title=document.createElementNS(ns,"title");title.textContent=p.month+" · "+p.quantity+" "+(chosen.unit||"");circle.append(title);svg.append(circle);const label=document.createElementNS(ns,"text");label.setAttribute("x",sx(i));label.setAttribute("y",H-B+20);label.setAttribute("text-anchor","middle");label.setAttribute("font-size","10");label.setAttribute("fill","#526174");label.textContent=p.month;svg.append(label);});
      const yLabel=document.createElementNS(ns,"text");yLabel.setAttribute("x",15);yLabel.setAttribute("y",(T+H-B)/2);yLabel.setAttribute("transform","rotate(-90 15 "+((T+H-B)/2)+")");yLabel.setAttribute("text-anchor","middle");yLabel.setAttribute("font-size","11");yLabel.setAttribute("font-weight","700");yLabel.setAttribute("fill","#18395e");yLabel.textContent="Talab ("+(chosen.unit||"miqdor")+")";svg.append(yLabel);
      target.append(svg);const note=document.createElement("div");note.className="live-chart-sub";note.textContent=points.length+" oylik real tarix · keyingi oy prognozi: "+(chosen.forecast_next_month==null?"yetarli tarix yo‘q":new Intl.NumberFormat("uz-UZ",{maximumFractionDigits:2}).format(chosen.forecast_next_month)+" "+(chosen.unit||""));target.append(note);
    }
    window.addEventListener("sc-demand-analytics",event=>{demandPayload=event.detail;renderDemandLine();});
    $("live-demand-product")?.addEventListener("change",renderDemandLine);
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