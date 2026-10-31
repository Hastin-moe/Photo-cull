/* 筛选报告的脚本。数据在 window.REPORT_DATA（results.json 里的照片列表）；文字来自语言包（report／cat／flag／genre 分组）。
   分数是 10 分制、精确到 0.1，界面只显示整数部分；写进 XMP 的星级是 分数÷2 向下取整。
   通过照片筛选程序打开时（地址是 /out/<令牌>/report.html）可以打分和删除；直接双击打开时只读。 */
let D=window.REPORT_DATA||[];const INFO=window.REPORT_INFO||{};
const LC={Green:"var(--g)",Yellow:"var(--y)",Red:"var(--r)"};let f="all",sort="score";const SEL=new Set();
const m=location.pathname.match(/^\/out\/([^/]+)\//);const TOKEN=m?m[1]:null;const EDIT=!!TOKEN;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ext=p=>p.split(".").pop().toUpperCase();
const CATS=["pick","moment","usable","reject","error"];
const cat=k=>CATS.includes(k)?T("cat."+k):k;
const shown=v=>Math.floor(Math.round((v||0)*10)/10+1e-9);          // 只显示整数部分
/* 问题标记：blur、clip_high:0.052、xmp_fail:原因… → 当前语言的说明 */
function flagText(code){const i=code.indexOf(":"),name=i<0?code:code.slice(0,i),val=i<0?"":code.slice(i+1);
 if(name=="clip_high"||name=="clip_low"){const v=parseFloat(val);if(!isNaN(v))return T("flag."+name,{pct:Math.round(v*100)+"%"})}
 if(name=="xmp_fail")return T("flag.xmp_fail",{msg:val});const k="flag."+name;return I18N.dict[k]!==undefined?T(k):code}
function genreText(g){return g&&I18N.dict["genre."+g]!==undefined?T("genre."+g):g}
function api(path,body){return fetch(path,{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body)}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j})}
function toast(t){const e=$("toast");e.textContent=t;e.style.display="block";clearTimeout(toast.t);toast.t=setTimeout(()=>e.style.display="none",2600)}
function scoreText(p){return p.category=="reject"?T("report.reject_mark"):p.category=="error"?"—":T("report.score",{n:shown(p.score)})}
function score(p){return p.category=="reject"?-1:p.score||0}
const live=()=>D.filter(p=>!p.trashed);
function stats(){const L=live(),c={};L.forEach(p=>c[p.category]=(c[p.category]||0)+1);const tr=D.length-L.length;
 const bursts=new Set(L.filter(p=>p.group_size>1&&p.category!="error").map(p=>p.group)).size;
 $("stats").innerHTML=[["total",L.length],["pairs",L.filter(p=>p.members.length>1).length],["bursts",bursts],["pick",c.pick||0],["moment",c.moment||0],["usable",c.usable||0],["reject",c.reject||0]].concat(tr?[["trashed",tr]]:[])
 .map(([k,v])=>`<div><b>${fmtNum(v)}</b><span class="mut">${T("common.stat."+k)}</span></div>`).join("");
 $("modeNote").textContent=T(EDIT?"report.mode_edit":"report.mode_static")}
function filters(){const opts=[["all",T("report.f.all")],["g8",T("report.f.g8")],["pick",cat("pick")],["moment",cat("moment")],["usable",cat("usable")],["reject",cat("reject")],["burst",T("report.f.burst")],["pair",T("report.f.pair")],["face",T("report.f.face")]];
 let h=opts.map(([k,v])=>`<button class="${f==k?"on":""}" onclick="f='${k}';render()">${esc(v)}</button>`).join("")+
 `<select onchange="sort=this.value;render()">${["score","time","group"].map(k=>`<option value="${k}"${sort==k?" selected":""}>${T("report.sort."+k)}</option>`).join("")}</select>`;
 if(EDIT){const rj=live().filter(p=>p.category=="reject").length;h+=`<span class="sp"></span><button onclick="SEL.clear();render()" ${SEL.size?"":"disabled"}>${T("report.clear_sel")}</button><button class="danger" onclick="askTrash([...SEL])" ${SEL.size?"":"disabled"}>${T("report.del_sel",{n:SEL.size})}</button><button class="danger" onclick="askTrash(live().filter(p=>p.category=='reject').map(p=>p.path))" ${rj?"":"disabled"}>${T("report.del_rejects",{n:rj})}</button>`}
 $("filters").innerHTML=h}
let CUR=[];
function rateUI(p,i){const v=p.category=="reject"?-1:shown(p.score);
 if(!EDIT)return `<span class="st">${scoreText(p)}</span>`;
 return `<span class="rate ten">${[1,2,3,4,5,6,7,8,9,10].map(n=>`<button class="${v>=n?"on":""}${n>6?" ai":""}" title="${T("report.score_n",{n,stars:Math.floor(n/2)})}" onclick="mark(CUR[${i}].path,${n})">★</button>`).join("")}<button class="x ${v<0?"on":""}" title="${T("report.reject")}" onclick="mark(CUR[${i}].path,-1)">✕</button><b class="sv">${v<0?"":v||""}</b></span>`}
function openEdit(path){if(window.top!==window&&window.top!==window.parent){window.top.postMessage({pc:"open-edit",path},location.origin);return}   // 在一体窗口里：直接切到照片编辑
 window.open(`/open/edit?t=${encodeURIComponent(TOKEN)}&path=${encodeURIComponent(path)}`,"_blank","noopener")}
function render(){filters();let L=live().filter(p=>f=="all"||(f=="g8"?p.category!="reject"&&shown(p.score)>=8:f=="face"?p.faces>0:f=="pair"?p.members.length>1:f=="burst"?p.group_size>1:p.category==f));
 L.sort(sort=="time"?(a,b)=>a.time-b.time:sort=="group"?(a,b)=>a.group-b.group||score(b)-score(a):(a,b)=>score(b)-score(a));CUR=L;
 const sep=T("report.list_sep");
 $("grid").innerHTML=L.map((p,i)=>{const a=p.ai||{};const exts=p.members.length>1?p.members.map(ext).join("+"):"";
 return `<div class="c${SEL.has(p.path)?" sel":""}">${EDIT?`<input type="checkbox" class="pick" ${SEL.has(p.path)?"checked":""} onchange="pick(CUR[${i}].path,this.checked)" title="${T("report.pick_tip")}"><button class="ed" onclick="openEdit(CUR[${i}].path)" title="${T("report.edit_tip")}">${T("report.edit")}</button>`:""}<img loading="lazy" src="${esc(p.thumb)}" alt="${esc(p.name)}" onclick="z(this.src)">
<div class="b"><div class="row"><span class="n" title="${esc(p.members.join("\n")||p.path)}">${p.label?`<span class="lb" style="background:${LC[p.label]}"></span>`:""}${esc(p.name.replace(/\.[^.]+$/,""))}${exts?`<span class="pair">${exts}</span>`:`<span class="pair">${ext(p.name)}</span>`}</span><span class="tag t-${p.category}">${esc(cat(p.category))}</span></div>
<div class="row">${rateUI(p,i)}<span class="mut">${a.overall?esc(a.provider||"AI")+" "+shown(a.overall)+"/10 · ":""}${T("report.local",{n:shown(p.local_score)})}${p.manual?" · "+T("report.manual"):""}</span></div>
<div class="mut">${esc(p.exposure)}${p.group_size>1?" · "+T("report.burst",{g:p.group,n:p.group_size,best:p.group_best?T("report.burst_best"):""}):""}</div>
${p.flags.length?`<div class="fl">${p.flags.map(x=>esc(flagText(x))).join(sep)}</div>`:""}
${a.comment?`<div class="cm">${esc(a.genre?"["+genreText(a.genre)+"] ":"")}${esc(a.comment)}</div>`:""}
${a.issues&&a.issues.length?`<div class="mut">${esc(T("report.issues",{list:a.issues.join(T("common.sep"))}))}</div>`:""}${p.error?`<div class="fl">${esc(p.error)}</div>`:""}</div></div>`}).join("");stats()}
function z(s){const e=$("zoom");e.querySelector("img").src=s;e.style.display="flex"}
function pick(path,on){on?SEL.add(path):SEL.delete(path);render()}
async function mark(path,n){const p=D.find(x=>x.path==path);const cur=p.category=="reject"?-1:shown(p.score);
 const v=(cur==n&&n>0)?n-1:(cur==-1&&n==-1)?0:n;          // 再点一次同一颗星：减一分；再点一次 ✕：取消淘汰
 try{const r=await api("/api/mark",{path,score:v});Object.assign(p,r.photo);render();up(r.summary);
  toast(T("report.toast_written",{files:r.written.join(T("common.sep"))||T("report.toast_nochange")})+(r.organized?T("report.toast_org"):""))}catch(e){toast(T("report.toast_write_fail",{err:e.message}))}}
function up(s){if(window.parent!==window)window.parent.postMessage({pc:"summary",s},location.origin)}
function closeM(){$("modal").classList.remove("show")}
function askTrash(paths){if(!paths.length)return;const ps=D.filter(p=>paths.includes(p.path));const files=ps.reduce((n,p)=>n+Math.max(1,p.members.length),0);
 const trash=T("common.trash");$("mT").textContent=T("report.trash_title",{n:ps.length});
 $("mB").innerHTML=T("report.trash_body",{files,trash:esc(trash)});$("mGo").textContent=T("report.trash_go",{trash});
 $("mGo").onclick=async()=>{closeM();try{const r=await api("/api/trash",{paths});r.trashed.forEach(x=>{const p=D.find(y=>y.path==x);if(p)p.trashed=true;SEL.delete(x)});render();up(r.summary);toast(T("report.toast_trashed",{where:r.where,n:r.files}))}catch(e){toast(T("report.toast_trash_fail",{err:e.message}))}};
 $("modal").classList.add("show")}
applyI18n();$("metaLine").textContent=T("report.meta",{src:INFO.src||"",when:INFO.when||"",ver:INFO.ver||""});document.title=T("report.title");
render();
