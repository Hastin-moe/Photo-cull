"""编辑板块的网页界面（由 gui.py 提供，路径 /edit）。"""

PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>照片编辑</title>
<style>
:root{--bg:#f4f3ef;--panel:#fff;--fg:#1c1c1a;--mut:#74726c;--line:#e2e0da;--soft:#efede8;--acc:#1c1c1a;--acc-fg:#fff;
--g:#2f8a4c;--y:#b8860b;--r:#c0392b;--focus:#3b6fd8;--stage:#e8e6e1}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--panel:#1e1e1c;--fg:#ecebe6;--mut:#9b9992;--line:#33322e;--soft:#272724;--acc:#ecebe6;--acc-fg:#141413;--stage:#0e0e0d}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:13px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue","Microsoft YaHei UI","Microsoft YaHei","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
header{display:flex;align-items:center;justify-content:space-between;padding:10px 18px;border-bottom:1px solid var(--line);gap:12px}
.brand{display:flex;align-items:center;gap:14px}.brand h1{font-size:16px;margin:0}.ver{color:var(--mut);font-size:12px}
.tabs{display:flex;gap:4px;background:var(--soft);padding:3px;border-radius:9px}.tabs a{padding:5px 14px;border-radius:7px;color:var(--mut);text-decoration:none;font-weight:600}
.tabs a.on{background:var(--panel);color:var(--fg);box-shadow:0 1px 2px #0002}
.xlink{font-size:13px;color:var(--mut);text-decoration:none;border:1px solid var(--line);border-radius:7px;padding:4px 10px}.xlink:hover{color:var(--fg);background:var(--soft)}
.vig{margin-top:8px;padding-top:8px;border-top:1px solid var(--line)}.vig select{width:100%}.vig .seg{margin-top:6px;display:grid;grid-template-columns:repeat(3,1fr)}
.vig .seg button:disabled{opacity:.4}#autoMode{max-width:170px;padding:4px 6px}
.pill{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--soft);color:var(--mut)}.pill.run{color:var(--focus)}.pill.err{color:var(--r)}
.app{display:grid;grid-template-columns:var(--lw,280px) minmax(0,1fr) var(--rw,320px);height:calc(100% - 49px)}
.app>.files{grid-column:1}.app>.stage{grid-column:2}.app>.side{grid-column:3}
.app.noL{--lw:0px}.app.noR{--rw:0px}.app.noL .files,.app.noR .side{display:none}
.files{border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.files .top{padding:12px;display:flex;flex-direction:column;gap:8px;border-bottom:1px solid var(--line)}
.row{display:flex;gap:6px;align-items:center}.row input{flex:1;min-width:0}
input[type=text],input[type=number],select{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:6px 8px}
button{font:inherit;cursor:pointer;border-radius:7px;border:1px solid var(--line);background:var(--panel);color:var(--fg);padding:5px 10px;white-space:nowrap}
button:hover{background:var(--soft)}button:disabled{opacity:.45;cursor:default}button.on{background:var(--acc);color:var(--acc-fg);border-color:var(--acc)}
.primary{background:var(--acc);color:var(--acc-fg);border-color:var(--acc);font-weight:600}.primary:hover{background:var(--acc);opacity:.88}
input:focus,select:focus,button:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
.list{overflow:auto;padding:10px;display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:max-content;gap:8px;align-content:start;flex:1;min-height:0}
.fi{border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer;background:var(--panel);position:relative}
.fi.cur{outline:2px solid var(--focus);outline-offset:-1px}
.list.big{grid-template-columns:1fr}
.fi .th{position:relative;width:100%;height:0;padding-top:66.667%;background:var(--soft)}
.fi .th img{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover;display:block}
.fi .nm{font-size:11px;padding:3px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fi .bd{position:absolute;top:4px;left:4px;font-size:9px;font-weight:700;background:#000a;color:#fff;padding:1px 4px;border-radius:3px}
.fi .ed{position:absolute;top:5px;right:5px;width:8px;height:8px;border-radius:50%;background:var(--y)}
.hint{color:var(--mut);font-size:12px}
.stage{display:flex;flex-direction:column;min-width:0;min-height:0}
.bar{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.bar .title{font-weight:600;margin-right:4px;max-width:30ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.bar .sp{flex:1}
.view{flex:1;min-height:0;background:var(--stage);display:flex;align-items:center;justify-content:center;position:relative;padding:8px}
.view img{max-width:100%;max-height:100%;object-fit:contain;box-shadow:0 2px 16px #0003;user-select:none;-webkit-user-drag:none;cursor:zoom-in}
.view.zoom{display:block;overflow:auto;padding:0}.view.zoom img{display:block;max-width:none;max-height:none;margin:0 auto;cursor:zoom-out;box-shadow:none}
.tg{padding:4px 8px;font-size:13px;line-height:1}.tg.off{opacity:.55}
.loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:14px}
.badge{position:absolute;top:12px;left:12px;background:#000b;color:#fff;font-size:12px;padding:3px 9px;border-radius:999px;display:none}
.warn{background:#b8860b22;color:var(--y);border-bottom:1px solid #b8860b55;padding:6px 12px;font-size:12px;display:none}
.empty{color:var(--mut);text-align:center;max-width:420px}.empty h2{color:var(--fg);font-size:18px;margin:0 0 6px}
.side{border-left:1px solid var(--line);overflow:auto;padding:10px 12px 40px;display:flex;flex-direction:column;gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.card>summary,.ct{font-size:11px;font-weight:700;color:var(--mut);letter-spacing:.08em;cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center}
.card>summary::-webkit-details-marker{display:none}.card[open]>summary{margin-bottom:8px}
canvas{display:block;width:100%;border-radius:6px;background:#111}
.scopes{display:flex;flex-direction:column;gap:6px}.seg{display:flex;gap:2px;background:var(--soft);padding:2px;border-radius:7px}
.seg button{border:0;background:transparent;padding:3px 8px;font-size:12px}.seg button.on{background:var(--panel);box-shadow:0 1px 2px #0002;color:var(--fg)}
.clip{display:flex;justify-content:space-between;font-size:11px;color:var(--mut)}
.sl{display:grid;grid-template-columns:62px 1fr 48px;gap:6px;align-items:center;margin:3px 0}
.sl label{font-size:12px;cursor:pointer;user-select:none}.sl input[type=range]{width:100%;accent-color:var(--fg)}
.sl input[type=number]{padding:2px 4px;font-size:12px;text-align:right;width:100%}
.style-cur{display:flex;flex-direction:column;gap:6px}.sty{border:1px solid var(--line);border-radius:8px;padding:7px 9px;display:none}
.sty .nm{font-weight:600;font-size:12px;word-break:break-all}.sty .x{float:right;border:0;padding:0 4px;background:none;color:var(--mut)}
.lib{max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:6px}
.lib details{border-bottom:1px solid var(--line)}.lib summary{padding:6px 8px;cursor:pointer;font-size:12px;font-weight:600;background:var(--soft);position:sticky;top:0}
.lib .it{padding:4px 8px 4px 16px;cursor:pointer;font-size:12px;display:flex;gap:6px;align-items:center}.lib .it:hover{background:var(--soft)}.lib .it .rm{margin-left:auto;border:0;background:none;color:var(--mut);cursor:pointer;visibility:hidden;font-size:12px;padding:0 4px}.lib .it:hover .rm{visibility:visible}.lib .it .rm:hover{color:var(--y)}
.lib .k{font-size:9px;font-weight:700;border:1px solid var(--line);border-radius:3px;padding:0 3px;color:var(--mut)}.lib .k.w{color:var(--y);border-color:var(--y)}
.note{font-size:11px;color:var(--mut);margin-top:4px}.note.w{color:var(--y)}
.prog{height:5px;border-radius:9px;background:var(--soft);overflow:hidden;margin-top:6px}.prog i{display:block;height:100%;width:0;background:var(--focus);transition:width .3s}
.hidden{display:none!important}
@media (max-width:900px){.app>.files,.app>.stage,.app>.side{grid-column:auto}.app{grid-template-columns:1fr;height:auto}.files{border-right:0;max-height:300px}.view{min-height:60vh}.side{border-left:0}}
</style></head><body>
<header><div class="brand"><h1>照片编辑</h1><span class="ver">photo-cull __VER__</span></div><div class="brand"><a class="xlink" data-href="/open/cull" target="_blank" rel="noopener" title="在新标签页打开照片筛选程序（需要先双击「启动筛选」）">照片筛选 ↗</a><span class="pill" id="pill">就绪</span></div></header>
<div class="app">
<aside class="files">
 <div class="top">
  <div class="row"><input type="text" id="folder" placeholder="照片文件夹路径" spellcheck="false"><button id="pick">选择…</button></div>
  <div class="row"><button id="openFolder" style="flex:1">打开文件夹</button><button id="fromCull" class="hidden" title="打开照片筛选程序最近处理的文件夹">筛选结果</button></div>
  <div class="row"><label class="hint" style="flex:1"><input type="checkbox" id="rawOnly"> 只看 RAW</label>
   <span class="seg" id="thSeg"><button data-b="0" class="on">小图</button><button data-b="1">大图</button></span></div>
 </div>
 <div class="list" id="list"><div class="hint" style="grid-column:1/-1">选择一个照片文件夹。支持徕卡／松下 DNG、索尼全部 ARW，以及 JPG／HEIC／TIFF。</div></div>
</aside>
<section class="stage">
 <div class="bar"><button class="tg" id="togL" title="显示／隐藏左侧文件列表（快捷键 [）">◧</button><span class="title" id="title">未打开照片</span><span class="hint" id="exif"></span><span class="sp"></span>
  <span class="hint" id="autoNote"></span>
  <select id="autoMode" title="自动调整用的测光方案"></select><button id="auto" disabled>自动</button><button id="compare" disabled title="按住查看原图">按住对比原图</button>
  <button id="copy" disabled>复制设置</button><button id="paste" disabled>粘贴设置</button><button id="reset" disabled>全部重置</button><button class="tg" id="togR" title="显示／隐藏右侧调整面板（快捷键 ]）">◨</button></div>
 <div class="warn" id="warn"></div>
 <div class="view" id="view"><div class="empty" id="empty"><h2>编辑</h2>从左侧选一张照片。调整会自动保存，原文件不会被修改；完成后在右侧「导出」。</div>
  <img id="img" class="hidden" alt="" title="点击放大到屏幕像素 1:1，再点回到适应窗口"><span class="badge" id="badge">原图</span><div class="loading hidden" id="loading">渲染中…</div></div>
</section>
<aside class="side">
 <div class="card scopes"><div class="ct"><span>监看</span><span class="seg" id="wfSeg"><button data-m="luma" class="on">亮度波形</button><button data-m="parade">RGB 分量</button></span></div>
  <canvas id="hist" width="640" height="200" style="height:100px"></canvas>
  <div class="clip"><span id="clipLo">暗部 0%</span><span id="renderMs"></span><span id="clipHi">高光 0%</span></div>
  <canvas id="wave" width="640" height="300" style="height:140px"></canvas></div>
 <details class="card" open><summary>基本调整<button id="resetBasic" style="font-size:11px;padding:1px 8px">重置</button></summary><div id="sliders"></div>
  <label class="hint"><input type="checkbox" id="mono"> 黑白</label>
  <div class="vig"><div class="hint" style="margin-bottom:4px">镜头暗角（模拟未经机身校正的光学暗角）</div>
   <select id="lens"><option value="">无</option></select>
   <div class="seg" id="vigSeg"><button data-l="weak">弱</button><button data-l="mid">中</button><button data-l="strong">强</button></div>
   <div class="note" id="vigNote"></div></div></details>
 <details class="card" open><summary>曲线<span class="seg" id="chSeg"><button data-c="rgb" class="on">RGB</button><button data-c="r">红</button><button data-c="g">绿</button><button data-c="b">蓝</button></span></summary>
  <canvas id="curve" width="560" height="560" style="aspect-ratio:1;background:var(--soft);touch-action:none;cursor:crosshair"></canvas>
  <div class="row" style="margin-top:6px"><span class="hint" style="flex:1">点击加点、拖动调整、双击删除</span><button id="resetCurve" style="font-size:11px;padding:1px 8px">重置此通道</button></div></details>
 <details class="card" open><summary>风格（LUT）</summary>
  <div class="style-cur">
   <div class="sty" id="lookBox"><button class="x" id="lookX" title="移除">✕</button><div class="hint">外观（来自 XMP 预设）</div><div class="nm" id="lookName"></div>
    <div class="sl"><label>强度</label><input type="range" id="lookAmt" min="0" max="200" step="1"><input type="number" id="lookAmtN" min="0" max="200"></div></div>
   <div class="sty" id="lutBox"><button class="x" id="lutX" title="移除">✕</button><div class="hint">LUT</div><div class="nm" id="lutName"></div>
    <div class="sl"><label>强度</label><input type="range" id="lutAmt" min="0" max="100" step="1"><input type="number" id="lutAmtN" min="0" max="100"></div>
    <div class="row"><span class="hint" style="width:62px">输入空间</span><select id="lutSpace" style="flex:1"></select></div></div>
   <div class="note" id="styleNote"></div>
  </div>
  <div class="row" style="margin-top:8px"><input type="text" id="libRoot" placeholder="（内置）" spellcheck="false" title="留空或「（内置）」＝工具自带的 LUT"><button id="libPick" title="改用别的素材库文件夹">选择…</button><button id="libBuiltin" title="改回工具自带的 LUT">内置</button></div>
  <div class="row" style="margin-top:6px"><button id="lutAdd" title="把自己的 .cube 文件加进「我的 LUT」（可多选）">添加 LUT…</button><input type="file" id="lutFile" accept=".cube" multiple style="display:none"><span class="hint" id="lutAddNote" style="flex:1"></span></div>
  <div class="row" style="margin-top:6px"><input type="text" id="libQ" placeholder="搜索 LUT／预设名称"><button id="libLoad">刷新</button></div>
  <div class="note" id="libScope"></div>
  <div class="lib" id="lib"><div class="hint" style="padding:8px">载入素材库后，点一个 LUT 即可套用。</div></div>
  <div class="note">LUT 按索尼「ST 标准」／徕卡「STD」的 sRGB 画面设计：JPEG 请用 ST／STD 模式拍摄；RAW 以编辑器的标准渲染作为这一画面的近似。</div></details>
 <details class="card" open><summary>导出</summary>
  <div class="row"><select id="fmt" style="flex:1"><option value="jpeg">JPEG</option><option value="tiff">TIFF 16 位</option></select>
   <select id="size" style="flex:1"><option value="0">原尺寸</option><option value="6000">长边 6000</option><option value="4000">长边 4000</option><option value="2048">长边 2048</option></select></div>
  <div class="sl" id="qRow"><label>JPEG 质量</label><input type="range" id="quality" min="60" max="100" value="95"><input type="number" id="qualityN" min="60" max="100" value="95"></div>
  <div class="hint">导出到照片所在文件夹的 photo-cull-export 子文件夹，不覆盖原图。</div>
  <button class="primary" id="export" style="width:100%;margin-top:8px" disabled>导出这张照片</button>
  <div class="prog hidden" id="expProg"><i></i></div><div class="note" id="expNote"></div></details>
</aside></div>
<script>
const Q=new URLSearchParams(location.search),TOKEN=Q.get("t")||"";const $=id=>document.getElementById(id);
document.querySelectorAll(".xlink").forEach(a=>a.href=a.dataset.href+"?t="+encodeURIComponent(TOKEN));
const api=(p,b)=>fetch(p,{method:b?"POST":"GET",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j});
const SL=[["temp","色温",-100,100,1],["tint","色调",-100,100,1],["exposure","曝光",-5,5,0.05],["contrast","对比度",-100,100,1],["highlights","高光",-100,100,1],["shadows","阴影",-100,100,1],["whites","白色",-100,100,1],["blacks","黑色",-100,100,1],["clarity","清晰度",-100,100,1],["vibrance","自然饱和度",-100,100,1],["saturation","饱和度",-100,100,1]];
let DEF=null,P=null,cur=null,files=[],lib=null,libRoot="",ch="rgb",wfMode="luma",clip=null,origURL=null,curURL=null,saveT=null;
const clone=o=>JSON.parse(JSON.stringify(o));
const baseName=p=>String(p||"").split(/[\\/]/).pop();   // 兼容 Windows 的反斜杠路径
function pill(t,c){$("pill").textContent=t;$("pill").className="pill "+(c||"")}
// ───── 滑块
function buildSliders(){$("sliders").innerHTML=SL.map(([k,l,a,b,s])=>`<div class="sl"><label title="双击复位" data-k="${k}">${l}</label><input type="range" id="s_${k}" min="${a}" max="${b}" step="${s}"><input type="number" id="n_${k}" min="${a}" max="${b}" step="${s}"></div>`).join("");
 SL.forEach(([k])=>{const r=$("s_"+k),n=$("n_"+k);
  r.oninput=()=>{P[k]=+r.value;n.value=r.value;schedule("fast")};r.onchange=()=>{schedule("full");dirty()};
  n.onchange=()=>{P[k]=+n.value;r.value=n.value;schedule("full");dirty()}});
 document.querySelectorAll(".sl label[data-k]").forEach(l=>l.ondblclick=()=>{P[l.dataset.k]=DEF[l.dataset.k];syncUI();schedule("full");dirty()})}
function syncUI(){SL.forEach(([k])=>{$("s_"+k).value=P[k];$("n_"+k).value=P[k]});$("mono").checked=!!P.mono;vigUI();styleUI();drawCurve()}
// ───── 镜头暗角：选镜头 ＋ 弱／中／强（对应约 f/5.6、f/2.8、全开）
let LENSES=[],LEVELS={};
function vigUI(){const v=P&&P.vignette,L=v&&LENSES.find(x=>x.id==v.lens);$("lens").value=L?L.id:"";
 document.querySelectorAll("#vigSeg button").forEach(b=>{b.disabled=!L;b.classList.toggle("on",!!L&&b.dataset.l==v.level);
  b.title=L?`${LEVELS[b.dataset.l]}：约 ${L.stops[b.dataset.l]}，四角暗 ${L.ev[b.dataset.l]} 档`:""});
 $("vigNote").textContent=L?`${LEVELS[v.level]}档 ≈ ${L.stops[v.level]} · 四角比中心暗约 ${L.ev[v.level]} 档`:"不加暗角"}
$("lens").onchange=()=>{const id=$("lens").value;P.vignette=id?{lens:id,level:(P.vignette&&P.vignette.level)||"mid"}:null;vigUI();schedule("full");dirty()};
document.querySelectorAll("#vigSeg button").forEach(b=>b.onclick=()=>{if(!P.vignette)return;P.vignette.level=b.dataset.l;vigUI();schedule("full");dirty()});
// ───── 渲染调度：拖动时低清、松手后高清，只保留最新请求
// 预览清晰度：按图片在界面里实际占的像素（含高分屏密度）向服务器要对应的一档，放大查看时要最大一档
let zoomed=false,lastNeed=0;
function sideNeed(){const v=$("view"),im=$("img"),ar=(im.naturalWidth&&im.naturalHeight)?im.naturalWidth/im.naturalHeight:1.5,dpr=window.devicePixelRatio||1;
 if(zoomed)return 4000;const vw=Math.max(200,v.clientWidth-16),vh=Math.max(200,v.clientHeight-16);
 const long=ar>=1?Math.min(vw,vh*ar):Math.min(vh,vw/ar);return Math.round(long*dpr)}
function applyZoom(){const v=$("view"),im=$("img");v.classList.toggle("zoom",zoomed);
 if(zoomed&&im.naturalWidth)im.style.width=(im.naturalWidth/(window.devicePixelRatio||1))+"px";else im.style.width=""}
function toggleZoom(){if(!cur||$("img").classList.contains("hidden"))return;zoomed=!zoomed;applyZoom();lastNeed=sideNeed();schedule("full");
 if(zoomed){const v=$("view");v.scrollLeft=(v.scrollWidth-v.clientWidth)/2;v.scrollTop=(v.scrollHeight-v.clientHeight)/2}}
let rsT=null;new ResizeObserver(()=>{clearTimeout(rsT);rsT=setTimeout(()=>{if(!cur)return;const n=sideNeed();if(Math.abs(n-lastNeed)>lastNeed*0.15){lastNeed=n;schedule("full")}},350)}).observe($("view"));
let inflight=false,want=null,seq=0;const CLIENT=Math.random().toString(36).slice(2);
function schedule(q){if(!cur)return;if(q=="full"||want!="full")want=q;pump()}
async function pump(){if(inflight||!want||!cur)return;const q=want;want=null;inflight=true;const s=++seq;pill("渲染中","run");
 try{const r=await fetch("/api/edit/render",{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify({params:P,quality:q,seq:s,client:CLIENT,side:sideNeed()})});
  if(r.status==200){const b=await r.blob();if(curURL)URL.revokeObjectURL(curURL);curURL=URL.createObjectURL(b);$("img").src=curURL;$("renderMs").textContent=(r.headers.get("X-Render-Ms")||"?")+" ms";
   const notes=r.headers.get("X-Notes");if(notes){warn(decodeURIComponent(notes))}}
  else if(r.status!=204){const j=await r.json().catch(()=>({}));warn("渲染失败："+(j.error||r.statusText))}}
 catch(e){warn("渲染失败："+e.message)}
 finally{inflight=false;pill("就绪");if(want)pump()}}
function warn(t){$("warn").textContent=t;$("warn").style.display=t?"block":"none"}
function dirty(){clearTimeout(saveT);saveT=setTimeout(()=>{if(cur)api("/api/edit/save",{path:cur,params:P}).then(()=>{const f=files.find(x=>x.path==cur);if(f&&!f.edited){f.edited=true;listUI()}}).catch(e=>warn("保存失败："+e.message))},800)}
// ───── 监看：直方图、波形
const scan=document.createElement("canvas");
$("img").onload=()=>{$("img").classList.remove("hidden");$("loading").classList.add("hidden");applyZoom();scopes()};
$("img").onclick=toggleZoom;
// 左右栏折叠（记住选择）
function panels(){const a=document.querySelector(".app");let st={};try{st=JSON.parse(localStorage.getItem("pc_panels")||"{}")}catch(e){}return{a,st}}
function setPanel(k,off){const{a,st}=panels();a.classList.toggle(k=="L"?"noL":"noR",off);$("tog"+k).classList.toggle("off",off);st[k]=off;try{localStorage.setItem("pc_panels",JSON.stringify(st))}catch(e){}}
$("togL").onclick=()=>setPanel("L",!document.querySelector(".app").classList.contains("noL"));
$("togR").onclick=()=>setPanel("R",!document.querySelector(".app").classList.contains("noR"));
document.addEventListener("keydown",e=>{if(/INPUT|TEXTAREA|SELECT/.test((e.target||{}).tagName||""))return;
 if(e.key=="[")$("togL").click();else if(e.key=="]")$("togR").click();else if(e.key=="Escape"&&zoomed)toggleZoom()});
{const{st}=panels();if(st.L)setPanel("L",true);if(st.R)setPanel("R",true)}
function setThumb(big){$("list").classList.toggle("big",big);document.querySelectorAll("#thSeg button").forEach(b=>b.classList.toggle("on",(b.dataset.b=="1")==big));try{localStorage.setItem("pc_thumb",big?"1":"0")}catch(e){}}
document.querySelectorAll("#thSeg button").forEach(b=>b.onclick=()=>setThumb(b.dataset.b=="1"));
try{setThumb(localStorage.getItem("pc_thumb")=="1")}catch(e){}
function scopes(){const im=$("img");if(!im.naturalWidth)return;const w=Math.min(480,im.naturalWidth),h=Math.round(im.naturalHeight*w/im.naturalWidth);
 scan.width=w;scan.height=h;const cx=scan.getContext("2d",{willReadFrequently:true});cx.drawImage(im,0,0,w,h);const d=cx.getImageData(0,0,w,h).data;
 const H=[new Uint32Array(256),new Uint32Array(256),new Uint32Array(256),new Uint32Array(256)];let hi=0,lo=0,n=w*h;
 const WC=$("wave"),WW=WC.width,WH=WC.height,acc=[new Uint32Array(WW*WH),new Uint32Array(WW*WH),new Uint32Array(WW*WH)];const third=Math.floor(WW/3);
 for(let i=0,p=0;i<d.length;i+=4,p++){const r=d[i],g=d[i+1],b=d[i+2],y=(r*54+g*183+b*19)>>8;H[0][r]++;H[1][g]++;H[2][b]++;H[3][y]++;
  if(r>=254||g>=254||b>=254)hi++;if(r<=1&&g<=1&&b<=1)lo++;const x=p%w;
  if(wfMode=="luma"){const col=Math.floor(x*WW/w),row=WH-1-Math.floor(y*(WH-1)/255);acc[0][row*WW+col]++}
  else{const col=Math.floor(x*third/w);[r,g,b].forEach((v,c)=>{const row=WH-1-Math.floor(v*(WH-1)/255);acc[c][row*WW+col+c*third]++})}}
 $("clipHi").textContent="高光溢出 "+(hi/n*100).toFixed(1)+"%";$("clipLo").textContent="暗部死黑 "+(lo/n*100).toFixed(1)+"%";
 $("clipHi").style.color=hi/n>0.01?"var(--r)":"";$("clipLo").style.color=lo/n>0.02?"var(--r)":"";
 clip=H;drawHist(H);drawWave(acc,n);drawCurve()}
function drawHist(H){const c=$("hist"),x=c.getContext("2d"),W=c.width,Hh=c.height;x.clearRect(0,0,W,Hh);x.fillStyle="#111";x.fillRect(0,0,W,Hh);
 let mx=1;for(let k=0;k<3;k++)for(let i=2;i<254;i++)mx=Math.max(mx,H[k][i]);
 const col=["rgba(235,70,60,.55)","rgba(60,200,90,.55)","rgba(70,120,240,.6)"];x.globalCompositeOperation="lighter";
 for(let k=0;k<3;k++){x.fillStyle=col[k];x.beginPath();x.moveTo(0,Hh);for(let i=0;i<256;i++){x.lineTo(i/255*W,Hh-Math.min(1,H[k][i]/mx)*Hh*.95)}x.lineTo(W,Hh);x.fill()}
 x.globalCompositeOperation="source-over";x.strokeStyle="rgba(255,255,255,.75)";x.lineWidth=1.5;x.beginPath();
 for(let i=0;i<256;i++){const y=Hh-Math.min(1,H[3][i]/mx)*Hh*.95;i?x.lineTo(i/255*W,y):x.moveTo(0,y)}x.stroke();
 x.strokeStyle="rgba(255,255,255,.12)";for(let q=1;q<4;q++){x.beginPath();x.moveTo(q*W/4,0);x.lineTo(q*W/4,Hh);x.stroke()}}
function drawWave(acc,n){const c=$("wave"),x=c.getContext("2d"),W=c.width,H=c.height,img=x.createImageData(W,H),D=img.data;
 const norm=Math.max(1,n/W)*0.25;const tint=wfMode=="luma"?[[120,255,140]]:[[255,80,70],[80,255,110],[90,140,255]];
 for(let i=0;i<W*H;i++){let r=0,g=0,b=0;for(let k=0;k<tint.length;k++){const v=acc[k][i];if(v){const a=Math.min(1,Math.sqrt(v/norm));r+=tint[k][0]*a;g+=tint[k][1]*a;b+=tint[k][2]*a}}
  D[i*4]=Math.min(255,17+r);D[i*4+1]=Math.min(255,17+g);D[i*4+2]=Math.min(255,17+b);D[i*4+3]=255}
 x.putImageData(img,0,0);x.strokeStyle="rgba(255,255,255,.18)";x.fillStyle="rgba(255,255,255,.45)";x.font="18px sans-serif";
 [0,25,50,75,100].forEach(v=>{const y=H-1-v/100*(H-1);x.beginPath();x.moveTo(0,y);x.lineTo(W,y);x.stroke();x.fillText(v,4,Math.max(16,y-3))})}
// ───── 曲线（单调三次样条，与后端一致）
function spline(pts,N){const p=[...pts].sort((a,b)=>a[0]-b[0]);const xs=[],ys=[];p.forEach(([a,b])=>{if(xs.length&&a-xs[xs.length-1]<1e-4){ys[ys.length-1]=b}else{xs.push(a);ys.push(b)}});
 const out=new Float32Array(N);if(xs.length<2){for(let i=0;i<N;i++)out[i]=i/(N-1);return out}
 const n=xs.length,h=[],d=[],m=new Array(n).fill(0);for(let k=0;k<n-1;k++){h.push(xs[k+1]-xs[k]);d.push((ys[k+1]-ys[k])/h[k])}
 m[0]=d[0];m[n-1]=d[n-2];for(let k=1;k<n-1;k++)m[k]=d[k-1]*d[k]<=0?0:(d[k-1]+d[k])/2;
 for(let k=0;k<n-1;k++){if(d[k]==0){m[k]=m[k+1]=0}else{const a=m[k]/d[k],b=m[k+1]/d[k],s=a*a+b*b;if(s>9){const t=3/Math.sqrt(s);m[k]=t*a*d[k];m[k+1]=t*b*d[k]}}}
 for(let i=0;i<N;i++){const X=i/(N-1);if(X<=xs[0]){out[i]=ys[0];continue}if(X>=xs[n-1]){out[i]=ys[n-1];continue}
  let k=0;while(k<n-2&&X>xs[k+1])k++;const t=(X-xs[k])/h[k],t2=t*t,t3=t2*t;
  out[i]=Math.min(1,Math.max(0,(2*t3-3*t2+1)*ys[k]+(t3-2*t2+t)*h[k]*m[k]+(-2*t3+3*t2)*ys[k+1]+(t3-t2)*h[k]*m[k+1]))}return out}
const CC={rgb:"#ddd",r:"#e5534b",g:"#3fb950",b:"#4c8dff"};
function drawCurve(){if(!P)return;const c=$("curve"),x=c.getContext("2d"),W=c.width,H=c.height;x.clearRect(0,0,W,H);
 if(clip){const idx={rgb:3,r:0,g:1,b:2}[ch],h=clip[idx];let mx=1;for(let i=2;i<254;i++)mx=Math.max(mx,h[i]);
  x.fillStyle="rgba(128,128,128,.25)";x.beginPath();x.moveTo(0,H);for(let i=0;i<256;i++)x.lineTo(i/255*W,H-Math.min(1,h[i]/mx)*H*.9);x.lineTo(W,H);x.fill()}
 x.strokeStyle="rgba(128,128,128,.35)";x.lineWidth=1;for(let q=1;q<4;q++){x.beginPath();x.moveTo(q*W/4,0);x.lineTo(q*W/4,H);x.moveTo(0,q*H/4);x.lineTo(W,q*H/4);x.stroke()}
 x.beginPath();x.moveTo(0,H);x.lineTo(W,0);x.stroke();
 const pts=P.curve[ch],ys=spline(pts,256);x.strokeStyle=ch=="rgb"?getComputedStyle(document.body).color:CC[ch];x.lineWidth=3;x.beginPath();
 for(let i=0;i<256;i++){const px=i/255*W,py=H-ys[i]*H;i?x.lineTo(px,py):x.moveTo(px,py)}x.stroke();
 pts.forEach(([a,b])=>{x.fillStyle="#fff";x.strokeStyle="#000";x.lineWidth=2;x.beginPath();x.arc(a*W,H-b*H,9,0,7);x.fill();x.stroke()})}
let drag=-1;
function cpos(e){const r=$("curve").getBoundingClientRect();return[Math.min(1,Math.max(0,(e.clientX-r.left)/r.width)),Math.min(1,Math.max(0,1-(e.clientY-r.top)/r.height))]}
$("curve").onpointerdown=e=>{if(!P)return;const [a,b]=cpos(e),pts=P.curve[ch],r=$("curve").getBoundingClientRect();
 drag=pts.findIndex(([px,py])=>Math.hypot((px-a)*r.width,(py-b)*r.height)<12);
 if(drag<0){pts.push([a,b]);pts.sort((p,q)=>p[0]-q[0]);drag=pts.findIndex(p=>p[0]==a&&p[1]==b)}
 $("curve").setPointerCapture(e.pointerId);drawCurve();schedule("fast")};
$("curve").onpointermove=e=>{if(drag<0)return;const pts=P.curve[ch],[a,b]=cpos(e);const lo=drag>0?pts[drag-1][0]+0.01:0,hi=drag<pts.length-1?pts[drag+1][0]-0.01:1;
 pts[drag]=[Math.min(hi,Math.max(lo,a)),b];drawCurve();schedule("fast")};
$("curve").onpointerup=()=>{if(drag>=0){drag=-1;schedule("full");dirty()}};
$("curve").ondblclick=e=>{const [a,b]=cpos(e),pts=P.curve[ch],r=$("curve").getBoundingClientRect();
 const i=pts.findIndex(([px,py])=>Math.hypot((px-a)*r.width,(py-b)*r.height)<12);if(i>0&&i<pts.length-1){pts.splice(i,1);drawCurve();schedule("full");dirty()}};
document.querySelectorAll("#chSeg button").forEach(b=>b.onclick=e=>{e.preventDefault();ch=b.dataset.c;document.querySelectorAll("#chSeg button").forEach(x=>x.classList.toggle("on",x==b));drawCurve()});
$("resetCurve").onclick=e=>{e.preventDefault();P.curve[ch]=[[0,0],[1,1]];drawCurve();schedule("full");dirty()};
document.querySelectorAll("#wfSeg button").forEach(b=>b.onclick=()=>{wfMode=b.dataset.m;document.querySelectorAll("#wfSeg button").forEach(x=>x.classList.toggle("on",x==b));scopes()});
// ───── 风格：LUT／XMP
let SPACES={};
function styleUI(){const lk=P.look,lt=P.lut;$("lookBox").style.display=lk?"block":"none";$("lutBox").style.display=lt?"block":"none";
 if(lk){$("lookName").textContent=lk.name||baseName(lk.path);$("lookAmt").value=Math.round(lk.amount*100);$("lookAmtN").value=Math.round(lk.amount*100)}
 if(lt){$("lutName").textContent=lt.name||baseName(lt.path);$("lutAmt").value=Math.round(lt.amount*100);$("lutAmtN").value=Math.round(lt.amount*100);$("lutSpace").value=lt.space||"srgb"}}
function bindAmt(r,n,key,mx){const set=v=>{P[key].amount=Math.max(0,Math.min(mx,v/100));$(r).value=$(n).value=Math.round(P[key].amount*100)};
 $(r).oninput=()=>{set(+$(r).value);schedule("fast")};$(r).onchange=()=>{schedule("full");dirty()};$(n).onchange=()=>{set(+$(n).value);schedule("full");dirty()}}
bindAmt("lookAmt","lookAmtN","look",2);bindAmt("lutAmt","lutAmtN","lut",1);
$("lutSpace").onchange=()=>{P.lut.space=$("lutSpace").value;schedule("full");dirty()};
$("lookX").onclick=()=>{P.look=null;styleUI();schedule("full");dirty();$("styleNote").textContent=""};
$("lutX").onclick=()=>{P.lut=null;styleUI();schedule("full");dirty();$("styleNote").textContent=""};
async function applyStyle(path){if(!cur){alert("请先打开一张照片");return}
 try{const d=await api("/api/edit/style",{path,root:libRoot});let note=[];
  if(d.kind=="lut"){P.lut={path:d.path,name:d.name,amount:1,space:d.space};note.push(`LUT「${d.name}」（${d.size}³）输入空间：${SPACES[d.space]||d.space}`)}
  else{if(d.kind=="preset"){Object.entries(d.set||{}).forEach(([k,v])=>{P[k]=k=="exposure"?Math.max(-5,Math.min(5,v)):Math.max(-100,Math.min(100,v))});
    if(d.curves&&Object.keys(d.curves).length){["rgb","r","g","b"].forEach(c=>P.curve[c]=d.curves[c]||[[0,0],[1,1]])}P.mono=!!d.mono}
   if(d.look)P.look={path:d.look.path,name:d.look.name,amount:1};
   note.push(`${d.kind=="look"?"外观":"预设"}「${d.name}」${d.has_looktable?"·含 LookTable":""}${d.has_rgbtable?"·含 RGBTable":""}`)}
  if(d.warning)note.push("⚠ "+d.warning);if(d.unsupported&&d.unsupported.length)note.push("未支持的部分（已忽略）："+d.unsupported.join("、"));
  $("styleNote").textContent=note.join("　");$("styleNote").className="note"+(d.warning||(d.unsupported||[]).length?" w":"");
  syncUI();schedule("full");dirty()}catch(e){alert("无法套用："+e.message)}}
function libUI(){if(!lib)return;const q=$("libQ").value.trim().toLowerCase();const groups={};
 lib.items.forEach((it,i)=>{if(q&&!(it.name.toLowerCase().includes(q)||it.group.toLowerCase().includes(q)))return;(groups[it.group]=groups[it.group]||[]).push(i)});
 const keys=Object.keys(groups);
 $("lib").innerHTML=keys.length?keys.map(g=>`<details ${q||keys.length<4?"open":""}><summary>${esc(g||"（根目录）")} · ${groups[g].length}</summary>${groups[g].slice(0,400).map(i=>{const it=lib.items[i];
  return `<div class="it" data-i="${i}" title="${esc(it.path)}"><span class="k ${it.warn?"w":""}">${it.kind=="cube"?(it.space=="srgb"?"LUT":it.space.toUpperCase()):"XMP"}</span>${esc(it.name)}${it.user?`<button class="rm" data-rm="${i}" title="从「我的 LUT」移除">✕</button>`:""}</div>`}).join("")}</details>`).join(""):`<div class="hint" style="padding:8px">没有匹配的文件</div>`;
 $("lib").querySelectorAll(".it").forEach(e=>e.onclick=ev=>{if(ev.target.dataset.rm!==undefined)return;applyStyle(lib.items[+e.dataset.i].path)});
 $("lib").querySelectorAll(".rm").forEach(b=>b.onclick=async ev=>{ev.stopPropagation();const it=lib.items[+b.dataset.rm];if(!confirm(`从「我的 LUT」移除「${it.name}」？`))return;
  try{await api("/api/edit/lut_remove",{path:it.path});if(P.lut&&P.lut.path==it.path){P.lut=null;styleUI();schedule("full");dirty()}$("lutAddNote").textContent=`已移除「${it.name}」`;loadLib()}catch(e){alert(e.message)}})}
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function loadLib(){libRoot=$("libRoot").value.trim();if(!libRoot||libRoot=="（内置）")libRoot="builtin";$("lib").innerHTML=`<div class="hint" style="padding:8px">正在读取…</div>`;
 try{lib=await api("/api/edit/library",{root:libRoot});libRoot=lib.root;$("libRoot").value=lib.builtin?"（内置）":lib.root;libUI();
  const cnt={};lib.items.forEach(it=>cnt[it.group]=(cnt[it.group]||0)+1);
  $("libScope").textContent=lib.builtin?"内置 LUT（工作空间 sRGB）："+Object.entries(cnt).map(([g,n])=>`${g.replace(/ \(sRGB\)$/,"")} ${n} 个`).join("、"):lib.scope&&lib.scope.length?"只列出："+lib.scope.join("、")+`（共 ${lib.items.length} 个）`:"";if(lib.truncated)$("styleNote").textContent="文件太多，只列出了前 8000 个"}catch(e){$("lib").innerHTML=`<div class="hint" style="padding:8px">${esc(e.message)}</div>`}}
$("libLoad").onclick=loadLib;$("libBuiltin").onclick=()=>{$("libRoot").value="（内置）";loadLib()};$("libQ").oninput=()=>{clearTimeout(libUI.t);libUI.t=setTimeout(libUI,150)};
$("lutAdd").onclick=()=>$("lutFile").click();
$("lutFile").onchange=async()=>{const fs=[...$("lutFile").files];$("lutFile").value="";if(!fs.length)return;
 $("lutAddNote").textContent="正在检查…";
 try{const files=await Promise.all(fs.map(async f=>({name:f.name,text:await f.text()})));
  const r=await api("/api/edit/lut_add",{files});let msg=[];
  if(r.added.length)msg.push(`已添加 ${r.added.length} 个到「我的 LUT」`);
  if(r.failed.length)msg.push(`${r.failed.length} 个失败：`+r.failed.map(x=>`${x.name}（${x.error}）`).join("；"));
  $("lutAddNote").textContent=msg.join("。");$("lutAddNote").className="hint"+(r.failed.length?" w":"");
  $("libRoot").value="（内置）";await loadLib();$("libQ").value="";libUI()}catch(e){$("lutAddNote").textContent="添加失败："+e.message}};
$("libPick").onclick=async()=>{try{const r=await api("/api/choose",{start:$("libRoot").value});if(r.folder){$("libRoot").value=r.folder;loadLib()}}catch(e){alert(e.message)}};
// ───── 文件
function listUI(){const L=files.filter(f=>!$("rawOnly").checked||f.raw);
 $("list").innerHTML=L.length?L.map(f=>`<div class="fi ${f.path==cur?"cur":""}" data-p="${esc(f.path)}" title="${esc(f.name)}"><div class="th"><img loading="lazy" src="/api/edit/thumb?t=${encodeURIComponent(TOKEN)}&p=${encodeURIComponent(f.path)}"></div><span class="bd">${f.pair.length?f.pair.join("+"):f.name.split(".").pop().toUpperCase()}</span>${f.edited?'<span class="ed" title="已编辑"></span>':""}<div class="nm">${esc(f.name)}</div></div>`).join(""):`<div class="hint" style="grid-column:1/-1">这个文件夹里没有支持的照片</div>`;
 $("list").querySelectorAll(".fi").forEach(e=>e.onclick=()=>openPhoto(e.dataset.p))}
async function openFolder(folder,then){folder=(folder||$("folder").value).trim();if(!folder)return;$("folder").value=folder;
 try{const r=await api("/api/edit/list",{folder});files=r.items;listUI();if(then)openPhoto(then)}catch(e){alert(e.message)}}
async function openPhoto(path){pill("解码中","run");warn("");try{const info=await api("/api/edit/open",{path});cur=path;P=info.params;origURL&&URL.revokeObjectURL(origURL);origURL=null;
  $("title").textContent=info.name;$("exif").textContent=info.exif||"";
  const mode={raw:"RAW",preview:"内嵌预览",image:"图像"}[info.mode];$("exif").textContent=(info.exif?info.exif+" · ":"")+mode+` · 解码 ${info.decode_ms} ms`;
  warn(info.warning||"");$("empty").classList.add("hidden");$("img").classList.add("hidden");$("loading").classList.remove("hidden");
  $("autoNote").textContent="";["auto","compare","copy","paste","reset","export"].forEach(k=>$(k).disabled=false);if(!window._copied)$("paste").disabled=true;
  listUI();syncUI();schedule("full")}catch(e){pill("出错","err");warn("打开失败："+e.message)}}
$("openFolder").onclick=()=>openFolder();$("folder").onkeydown=e=>{if(e.key=="Enter")openFolder()};$("rawOnly").onchange=listUI;
$("pick").onclick=async()=>{try{const r=await api("/api/choose",{start:$("folder").value});if(r.folder)openFolder(r.folder)}catch(e){alert(e.message)}};
// ───── 工具栏
$("auto").onclick=async()=>{const b=$("auto");b.disabled=true;pill("自动调整中","run");
 try{const r=await api("/api/edit/auto",{params:P,style:$("autoMode").value});Object.entries(r.set).forEach(([k,v])=>P[k]=v);$("autoNote").textContent=r.style+"："+r.note;syncUI();schedule("full");dirty()}
 catch(e){pill("出错","err");alert(e.message)}b.disabled=false};
$("autoMode").onchange=()=>{try{localStorage.setItem("pc_meter",$("autoMode").value)}catch(e){}const m=(window._meters||[]).find(x=>x.id==$("autoMode").value);$("autoMode").title=m?m.desc:""};
$("reset").onclick=()=>{if(!confirm("把这张照片的所有调整恢复默认？"))return;P=clone(DEF);syncUI();schedule("full");dirty();$("styleNote").textContent=""};
$("resetBasic").onclick=e=>{e.preventDefault();SL.forEach(([k])=>P[k]=DEF[k]);P.mono=false;P.vignette=null;syncUI();schedule("full");dirty()};
$("mono").onchange=()=>{P.mono=$("mono").checked;schedule("full");dirty()};
$("copy").onclick=()=>{window._copied=clone(P);$("paste").disabled=false;pill("已复制设置")};
$("paste").onclick=()=>{if(!window._copied)return;P=clone(window._copied);syncUI();schedule("full");dirty();pill("已粘贴设置")};
async function showOrig(on){if(!cur)return;$("badge").style.display=on?"block":"none";if(!on){if(curURL)$("img").src=curURL;return}
 if(!origURL){const r=await fetch("/api/edit/render",{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify({params:DEF,quality:"full",seq:++seq,client:CLIENT,side:sideNeed()})});
  if(r.status==200)origURL=URL.createObjectURL(await r.blob())}if(origURL&&$("badge").style.display=="block")$("img").src=origURL}
$("compare").onpointerdown=()=>showOrig(true);["pointerup","pointerleave"].forEach(ev=>$("compare").addEventListener(ev,()=>{if($("badge").style.display=="block")showOrig(false)}));
// ───── 导出
$("fmt").onchange=()=>$("qRow").classList.toggle("hidden",$("fmt").value!="jpeg");
$("quality").oninput=()=>$("qualityN").value=$("quality").value;$("qualityN").onchange=()=>$("quality").value=$("qualityN").value;
$("export").onclick=async()=>{try{await api("/api/edit/save",{path:cur,params:P});
 await api("/api/edit/export",{path:cur,params:P,fmt:$("fmt").value,quality:+$("quality").value,long_edge:+$("size").value});
 $("export").disabled=true;$("expProg").classList.remove("hidden");$("expNote").textContent="导出中…";pollExp()}catch(e){alert(e.message)}};
async function pollExp(){const s=await api("/api/edit/export_status");$("expProg").querySelector("i").style.width=(s.pct*100)+"%";
 if(s.running){$("expNote").textContent=`${s.name}：${s.msg}`;setTimeout(pollExp,500);return}
 $("export").disabled=false;if(s.error){$("expNote").textContent="导出失败："+s.error;$("expNote").className="note w"}
 else if(s.file){$("expNote").innerHTML=`已导出：${esc(baseName(s.file))} <button id="revealExp" style="font-size:11px;padding:1px 8px">在__FM__中显示</button>`;$("expNote").className="note";
  $("revealExp").onclick=()=>api("/api/edit/reveal",{path:s.file})}}
// ───── 启动
(async()=>{try{const st=await api("/api/edit/state");DEF=st.defaults;SPACES=st.spaces;
 window._meters=st.meters||[];$("autoMode").innerHTML=_meters.map(m=>`<option value="${m.id}" title="${esc(m.desc)}">${esc(m.name)}</option>`).join("");
 let mm=st.default_meter;try{const x=localStorage.getItem("pc_meter");if(_meters.some(m=>m.id==x))mm=x}catch(e){}$("autoMode").value=mm;$("autoMode").onchange();
 LENSES=st.lenses||[];LEVELS=st.levels||{};$("lens").innerHTML='<option value="">无</option>'+LENSES.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join("");
 $("lutSpace").innerHTML=Object.entries(SPACES).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join("");$("lutSpace").disabled=Object.keys(SPACES).length<2;
 buildSliders();P=clone(DEF);libRoot=st.library||"builtin";$("libRoot").value=libRoot=="builtin"?"（内置）":libRoot;
 if(st.cull_folder){$("fromCull").classList.remove("hidden");$("fromCull").onclick=()=>openFolder(st.cull_folder)}
 const want=Q.get("path");const folder=want?want.replace(/[\\/][^\\/]+$/,""):(st.folder||"");
 if(folder)openFolder(folder,want||null);if(libRoot)loadLib()}
 catch(e){document.body.innerHTML="<p style='padding:40px'>链接已失效，请重新运行启动程序。</p>"}})();
</script></body></html>"""
