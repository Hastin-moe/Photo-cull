/* 照片编辑界面的脚本。界面文字全部来自语言包：T("键")，见 locales/*.json 的 edit 分组。 */
const Q=new URLSearchParams(location.search),TOKEN=Q.get("t")||"";const $=id=>document.getElementById(id);
document.querySelectorAll(".xlink").forEach(a=>a.href=a.dataset.href+"?t="+encodeURIComponent(TOKEN));
const api=(p,b)=>fetch(p,{method:b?"POST":"GET",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j});
applyI18n();langMenu($("lang"),v=>api("/api/lang",{lang:v}));
["6000","4000","2048"].forEach(v=>document.querySelector(`#size option[value="${v}"]`).textContent=T("edit.export.long_edge",{n:v}));
const BUILTIN_LABEL=T("edit.lib.builtin_label");$("libRoot").placeholder=BUILTIN_LABEL;
const SL=[["temp",-100,100,1],["tint",-100,100,1],["exposure",-5,5,0.05],["contrast",-100,100,1],["highlights",-100,100,1],["shadows",-100,100,1],["whites",-100,100,1],["blacks",-100,100,1],["clarity",-100,100,1],["vibrance",-100,100,1],["saturation",-100,100,1]];
let DEF=null,P=null,cur=null,files=[],lib=null,libRoot="",ch="rgb",wfMode="luma",clip=null,origURL=null,curURL=null,saveT=null;
const clone=o=>JSON.parse(JSON.stringify(o));
const baseName=p=>String(p||"").split(/[\\/]/).pop();   // 兼容 Windows 的反斜杠路径
function pill(key,c){$("pill").textContent=T(key);$("pill").className="pill "+(c||"")}
// ───── 滑块
function buildSliders(){$("sliders").innerHTML=SL.map(([k,a,b,s])=>`<div class="sl"><label title="${T("edit.basic.dbl_reset")}" data-k="${k}">${T("edit.slider."+k)}</label><input type="range" id="s_${k}" min="${a}" max="${b}" step="${s}"><input type="number" id="n_${k}" min="${a}" max="${b}" step="${s}"></div>`).join("");
 SL.forEach(([k])=>{const r=$("s_"+k),n=$("n_"+k);
  r.oninput=()=>{P[k]=+r.value;n.value=r.value;schedule("fast")};r.onchange=()=>{schedule("full");dirty()};
  n.onchange=()=>{P[k]=+n.value;r.value=n.value;schedule("full");dirty()}});
 document.querySelectorAll(".sl label[data-k]").forEach(l=>l.ondblclick=()=>{P[l.dataset.k]=DEF[l.dataset.k];syncUI();schedule("full");dirty()})}
function syncUI(){SL.forEach(([k])=>{$("s_"+k).value=P[k];$("n_"+k).value=P[k]});$("mono").checked=!!P.mono;vigUI();styleUI();drawCurve()}
// ───── 镜头暗角：选镜头 ＋ 弱／中／强（对应约 f/5.6、f/2.8、全开）
let LENSES=[],LEVELS={};
function vigUI(){const v=P&&P.vignette,L=v&&LENSES.find(x=>x.id==v.lens);$("lens").value=L?L.id:"";
 document.querySelectorAll("#vigSeg button").forEach(b=>{b.disabled=!L;b.classList.toggle("on",!!L&&b.dataset.l==v.level);
  b.title=L?T("edit.vig.level_tip",{level:LEVELS[b.dataset.l],stop:L.stops[b.dataset.l],ev:L.ev[b.dataset.l]}):""});
 $("vigNote").textContent=L?T("edit.vig.note",{level:LEVELS[v.level],stop:L.stops[v.level],ev:L.ev[v.level]}):T("edit.vig.none_note")}
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
async function pump(){if(inflight||!want||!cur)return;const q=want;want=null;inflight=true;const s=++seq;pill("edit.pill.rendering","run");
 try{const r=await fetch("/api/edit/render",{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify({params:P,quality:q,seq:s,client:CLIENT,side:sideNeed()})});
  if(r.status==200){const b=await r.blob();if(curURL)URL.revokeObjectURL(curURL);curURL=URL.createObjectURL(b);$("img").src=curURL;$("renderMs").textContent=(r.headers.get("X-Render-Ms")||"?")+" ms";
   const notes=r.headers.get("X-Notes");if(notes){warn(decodeURIComponent(notes))}}
  else if(r.status!=204){const j=await r.json().catch(()=>({}));warn(T("edit.err.render",{err:j.error||r.statusText}))}}
 catch(e){warn(T("edit.err.render",{err:e.message}))}
 finally{inflight=false;pill("edit.pill.ready");if(want)pump()}}
function warn(t){$("warn").textContent=t;$("warn").style.display=t?"block":"none"}
function dirty(){clearTimeout(saveT);saveT=setTimeout(()=>{if(cur)api("/api/edit/save",{path:cur,params:P}).then(()=>{const f=files.find(x=>x.path==cur);if(f&&!f.edited){f.edited=true;listUI()}}).catch(e=>warn(T("edit.err.save",{err:e.message})))},800)}
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
 $("clipHi").textContent=T("edit.scope.clip_hi",{pct:(hi/n*100).toFixed(1)+"%"});$("clipLo").textContent=T("edit.scope.clip_lo",{pct:(lo/n*100).toFixed(1)+"%"});
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
async function applyStyle(path){if(!cur){alert(T("edit.err.open_first"));return}
 try{const d=await api("/api/edit/style",{path,root:libRoot});let note=[];
  if(d.kind=="lut"){P.lut={path:d.path,name:d.name,amount:1,space:d.space};note.push(T("edit.style.lut_note",{name:d.name,size:d.size,space:SPACES[d.space]||d.space}))}
  else{if(d.kind=="preset"){Object.entries(d.set||{}).forEach(([k,v])=>{P[k]=k=="exposure"?Math.max(-5,Math.min(5,v)):Math.max(-100,Math.min(100,v))});
    if(d.curves&&Object.keys(d.curves).length){["rgb","r","g","b"].forEach(c=>P.curve[c]=d.curves[c]||[[0,0],[1,1]])}P.mono=!!d.mono}
   if(d.look)P.look={path:d.look.path,name:d.look.name,amount:1};
   note.push(T(d.kind=="look"?"edit.style.look_note":"edit.style.preset_note",{name:d.name})+(d.has_looktable?" · LookTable":"")+(d.has_rgbtable?" · RGBTable":""))}
  if(d.warning)note.push("⚠ "+d.warning);if(d.unsupported&&d.unsupported.length)note.push(T("edit.style.unsupported",{list:d.unsupported.join(T("common.sep"))}));
  $("styleNote").textContent=note.join("　");$("styleNote").className="note"+(d.warning||(d.unsupported||[]).length?" w":"");
  syncUI();schedule("full");dirty()}catch(e){alert(T("edit.err.apply",{err:e.message}))}}
function libUI(){if(!lib)return;const q=$("libQ").value.trim().toLowerCase();const groups={};
 lib.items.forEach((it,i)=>{if(q&&!(it.name.toLowerCase().includes(q)||it.group.toLowerCase().includes(q)))return;(groups[it.group]=groups[it.group]||[]).push(i)});
 const keys=Object.keys(groups);
 $("lib").innerHTML=keys.length?keys.map(g=>`<details ${q||keys.length<4?"open":""}><summary>${esc(groupLabel(g))} · ${groups[g].length}</summary>${groups[g].slice(0,400).map(i=>{const it=lib.items[i];
  return `<div class="it" data-i="${i}" title="${esc(it.path)}"><span class="k ${it.warn?"w":""}">${it.kind=="cube"?(it.space=="srgb"?"LUT":it.space.toUpperCase()):"XMP"}</span>${esc(it.name)}${it.user?`<button class="rm" data-rm="${i}" title="${esc(T("edit.lib.remove_tip"))}">✕</button>`:""}</div>`}).join("")}</details>`).join(""):`<div class="hint" style="padding:8px">${T("edit.lib.no_match")}</div>`;
 $("lib").querySelectorAll(".it").forEach(e=>e.onclick=ev=>{if(ev.target.dataset.rm!==undefined)return;applyStyle(lib.items[+e.dataset.i].path)});
 $("lib").querySelectorAll(".rm").forEach(b=>b.onclick=async ev=>{ev.stopPropagation();const it=lib.items[+b.dataset.rm];if(!confirm(T("edit.lib.remove_confirm",{name:it.name})))return;
  try{await api("/api/edit/lut_remove",{path:it.path});if(P.lut&&P.lut.path==it.path){P.lut=null;styleUI();schedule("full");dirty()}$("lutAddNote").textContent=T("edit.lib.removed",{name:it.name});loadLib()}catch(e){alert(e.message)}})}
/* 内置素材库的分组名（文件夹名）→ 当前语言的显示名 */
function groupLabel(g){if(!g)return T("edit.lib.root");const it=lib&&lib.items.find(x=>x.group==g);return it&&it.group_label?it.group_label:g}
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function loadLib(){libRoot=$("libRoot").value.trim();if(!libRoot||libRoot==BUILTIN_LABEL)libRoot="builtin";$("lib").innerHTML=`<div class="hint" style="padding:8px">${T("edit.lib.loading")}</div>`;
 try{lib=await api("/api/edit/library",{root:libRoot});libRoot=lib.root;$("libRoot").value=lib.builtin?BUILTIN_LABEL:lib.root;libUI();
  const cnt={};lib.items.forEach(it=>cnt[it.group]=(cnt[it.group]||0)+1);
  $("libScope").textContent=lib.builtin?T("edit.lib.scope_builtin",{list:Object.entries(cnt).map(([g,n])=>T("edit.lib.group_count",{group:groupLabel(g),n})).join(T("common.sep"))}):lib.scope&&lib.scope.length?T("edit.lib.scope_only",{list:lib.scope.join(T("common.sep")),n:lib.items.length}):"";if(lib.truncated)$("styleNote").textContent=T("edit.lib.truncated")}catch(e){$("lib").innerHTML=`<div class="hint" style="padding:8px">${esc(e.message)}</div>`}}
$("libLoad").onclick=loadLib;$("libBuiltin").onclick=()=>{$("libRoot").value=BUILTIN_LABEL;loadLib()};$("libQ").oninput=()=>{clearTimeout(libUI.t);libUI.t=setTimeout(libUI,150)};
$("lutAdd").onclick=()=>$("lutFile").click();
$("lutFile").onchange=async()=>{const fs=[...$("lutFile").files];$("lutFile").value="";if(!fs.length)return;
 $("lutAddNote").textContent=T("edit.lib.checking");
 try{const files=await Promise.all(fs.map(async f=>({name:f.name,text:await f.text()})));
  const r=await api("/api/edit/lut_add",{files});let msg=[];
  if(r.added.length)msg.push(T("edit.lib.added",{n:r.added.length}));
  if(r.failed.length)msg.push(T("edit.lib.add_failed",{n:r.failed.length,list:r.failed.map(x=>`${x.name} (${x.error})`).join(T("common.sep"))}));
  $("lutAddNote").textContent=msg.join(" ");$("lutAddNote").className="hint"+(r.failed.length?" w":"");
  $("libRoot").value=BUILTIN_LABEL;await loadLib();$("libQ").value="";libUI()}catch(e){$("lutAddNote").textContent=T("edit.lib.add_error",{err:e.message})}};
$("libPick").onclick=async()=>{try{const r=await api("/api/choose",{start:$("libRoot").value});if(r.folder){$("libRoot").value=r.folder;loadLib()}}catch(e){alert(e.message)}};
// ───── 文件
function listUI(){const L=files.filter(f=>!$("rawOnly").checked||f.raw);
 $("list").innerHTML=L.length?L.map(f=>`<div class="fi ${f.path==cur?"cur":""}" data-p="${esc(f.path)}" title="${esc(f.name)}"><div class="th"><img loading="lazy" src="/api/edit/thumb?t=${encodeURIComponent(TOKEN)}&p=${encodeURIComponent(f.path)}"></div><span class="bd">${f.pair.length?f.pair.join("+"):f.name.split(".").pop().toUpperCase()}</span>${f.edited?`<span class="ed" title="${T("edit.files.edited")}"></span>`:""}<div class="nm">${esc(f.name)}</div></div>`).join(""):`<div class="hint" style="grid-column:1/-1">${T("edit.files.none")}</div>`;
 $("list").querySelectorAll(".fi").forEach(e=>e.onclick=()=>openPhoto(e.dataset.p))}
async function openFolder(folder,then){folder=(folder||$("folder").value).trim();if(!folder)return;$("folder").value=folder;
 try{const r=await api("/api/edit/list",{folder});files=r.items;listUI();if(then)openPhoto(then)}catch(e){alert(e.message)}}
async function openPhoto(path){pill("edit.pill.decoding","run");warn("");try{const info=await api("/api/edit/open",{path});cur=path;P=info.params;origURL&&URL.revokeObjectURL(origURL);origURL=null;
  $("title").textContent=info.name;$("exif").textContent=info.exif||"";
  const mode=T("edit.mode."+info.mode);$("exif").textContent=(info.exif?info.exif+" · ":"")+mode+" · "+T("edit.decode_ms",{ms:info.decode_ms});
  warn(info.warning||"");$("empty").classList.add("hidden");$("img").classList.add("hidden");$("loading").classList.remove("hidden");
  $("autoNote").textContent="";["auto","compare","copy","paste","reset","export"].forEach(k=>$(k).disabled=false);if(!window._copied)$("paste").disabled=true;
  listUI();syncUI();schedule("full")}catch(e){pill("edit.pill.error","err");warn(T("edit.err.open",{err:e.message}))}}
$("openFolder").onclick=()=>openFolder();$("folder").onkeydown=e=>{if(e.key=="Enter")openFolder()};$("rawOnly").onchange=listUI;
$("pick").onclick=async()=>{try{const r=await api("/api/choose",{start:$("folder").value});if(r.folder)openFolder(r.folder)}catch(e){alert(e.message)}};
// ───── 工具栏
$("auto").onclick=async()=>{const b=$("auto");b.disabled=true;pill("edit.pill.auto","run");
 try{const r=await api("/api/edit/auto",{params:P,style:$("autoMode").value});Object.entries(r.set).forEach(([k,v])=>P[k]=v);$("autoNote").textContent=T("edit.auto.note",{style:r.style,note:r.note});syncUI();schedule("full");dirty()}
 catch(e){pill("edit.pill.error","err");alert(e.message)}b.disabled=false};
$("autoMode").onchange=()=>{try{localStorage.setItem("pc_meter",$("autoMode").value)}catch(e){}const m=(window._meters||[]).find(x=>x.id==$("autoMode").value);$("autoMode").title=m?m.desc:""};
$("reset").onclick=()=>{if(!confirm(T("edit.bar.reset_confirm")))return;P=clone(DEF);syncUI();schedule("full");dirty();$("styleNote").textContent=""};
$("resetBasic").onclick=e=>{e.preventDefault();SL.forEach(([k])=>P[k]=DEF[k]);P.mono=false;P.vignette=null;syncUI();schedule("full");dirty()};
$("mono").onchange=()=>{P.mono=$("mono").checked;schedule("full");dirty()};
$("copy").onclick=()=>{window._copied=clone(P);$("paste").disabled=false;pill("edit.pill.copied")};
$("paste").onclick=()=>{if(!window._copied)return;P=clone(window._copied);syncUI();schedule("full");dirty();pill("edit.pill.pasted")};
async function showOrig(on){if(!cur)return;$("badge").style.display=on?"block":"none";if(!on){if(curURL)$("img").src=curURL;return}
 if(!origURL){const r=await fetch("/api/edit/render",{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify({params:DEF,quality:"full",seq:++seq,client:CLIENT,side:sideNeed()})});
  if(r.status==200)origURL=URL.createObjectURL(await r.blob())}if(origURL&&$("badge").style.display=="block")$("img").src=origURL}
$("compare").onpointerdown=()=>showOrig(true);["pointerup","pointerleave"].forEach(ev=>$("compare").addEventListener(ev,()=>{if($("badge").style.display=="block")showOrig(false)}));
// ───── 导出
$("fmt").onchange=()=>$("qRow").classList.toggle("hidden",$("fmt").value!="jpeg");
$("quality").oninput=()=>$("qualityN").value=$("quality").value;$("qualityN").onchange=()=>$("quality").value=$("qualityN").value;
$("export").onclick=async()=>{try{await api("/api/edit/save",{path:cur,params:P});
 await api("/api/edit/export",{path:cur,params:P,fmt:$("fmt").value,quality:+$("quality").value,long_edge:+$("size").value});
 $("export").disabled=true;$("expProg").classList.remove("hidden");$("expNote").textContent=T("edit.export.running");pollExp()}catch(e){alert(e.message)}};
async function pollExp(){const s=await api("/api/edit/export_status");$("expProg").querySelector("i").style.width=(s.pct*100)+"%";
 if(s.running){$("expNote").textContent=`${s.name}: ${s.msg}`;setTimeout(pollExp,500);return}
 $("export").disabled=false;if(s.error){$("expNote").textContent=T("edit.export.failed",{err:s.error});$("expNote").className="note w"}
 else if(s.file){$("expNote").innerHTML=`${esc(T("edit.export.done",{name:baseName(s.file)}))} <button id="revealExp" style="font-size:11px;padding:1px 8px">${esc(T("edit.export.reveal",{fm:T("common.file_manager")}))}</button>`;$("expNote").className="note";
  $("revealExp").onclick=()=>api("/api/edit/reveal",{path:s.file})}}
// ───── 启动
(async()=>{try{const st=await api("/api/edit/state");DEF=st.defaults;SPACES=st.spaces;
 window._meters=st.meters||[];$("autoMode").innerHTML=_meters.map(m=>`<option value="${m.id}" title="${esc(m.desc)}">${esc(m.name)}</option>`).join("");
 let mm=st.default_meter;try{const x=localStorage.getItem("pc_meter");if(_meters.some(m=>m.id==x))mm=x}catch(e){}$("autoMode").value=mm;$("autoMode").onchange();
 LENSES=st.lenses||[];LEVELS=st.levels||{};document.querySelectorAll("#vigSeg button").forEach(b=>b.textContent=LEVELS[b.dataset.l]||b.dataset.l);$("lens").innerHTML=`<option value="">${T("edit.vig.none")}</option>`+LENSES.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join("");
 $("lutSpace").innerHTML=Object.entries(SPACES).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join("");$("lutSpace").disabled=Object.keys(SPACES).length<2;
 buildSliders();P=clone(DEF);libRoot=st.library||"builtin";$("libRoot").value=libRoot=="builtin"?BUILTIN_LABEL:libRoot;
 if(st.cull_folder){$("fromCull").classList.remove("hidden");$("fromCull").onclick=()=>openFolder(st.cull_folder)}
 const want=Q.get("path");const folder=want?want.replace(/[\\/][^\\/]+$/,""):(st.folder||"");
 if(folder)openFolder(folder,want||null);if(libRoot)loadLib()}
 catch(e){document.body.innerHTML=`<p style='padding:40px'>${T("common.link_expired")}</p>`}})();
