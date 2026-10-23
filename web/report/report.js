/* 筛选报告的脚本。数据在 window.REPORT_DATA；文字来自语言包（report／tier／flag／genre 分组）。
   通过照片筛选程序打开时（地址是 /out/<令牌>/report.html）可以改星级和删除；直接双击打开时只读。 */
let D=window.REPORT_DATA||[];const INFO=window.REPORT_INFO||{};
const LC={Green:"var(--g)",Yellow:"var(--y)",Red:"var(--r)"};let f="all",sort="score";const SEL=new Set();
const m=location.pathname.match(/^\/out\/([^/]+)\//);const TOKEN=m?m[1]:null;const EDIT=!!TOKEN;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ext=p=>p.split(".").pop().toUpperCase();
const tier=k=>({candidate:1,alt:1,reject:1,error:1}[k]?T("tier."+k):k);
/* 问题标记：blur、clip_high:0.052、xmp_fail:原因… → 当前语言的说明 */
function flagText(code){const i=code.indexOf(":"),name=i<0?code:code.slice(0,i),val=i<0?"":code.slice(i+1);
 if(name=="clip_high"||name=="clip_low"){const v=parseFloat(val);if(!isNaN(v))return T("flag."+name,{pct:Math.round(v*100)+"%"})}
 if(name=="xmp_fail")return T("flag.xmp_fail",{msg:val});const k="flag."+name;return I18N.dict[k]!==undefined?T(k):code}
function genreText(g){return g&&I18N.dict["genre."+g]!==undefined?T("genre."+g):g}
function api(path,body){return fetch(path,{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body)}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j})}
function toast(t){const e=$("toast");e.textContent=t;e.style.display="block";clearTimeout(toast.t);toast.t=setTimeout(()=>e.style.display="none",2600)}
function stars(n){return n<0?T("report.reject_mark"):n?"★".repeat(n)+"☆".repeat(5-n):"—"}
function score(p){return p.ai?p.ai.overall*10:p.local_score}
const live=()=>D.filter(p=>!p.trashed);
function stats(){const L=live(),c={};L.forEach(p=>c[p.tier]=(c[p.tier]||0)+1);const tr=D.length-L.length;
 $("stats").innerHTML=[["total",L.length],["pairs",L.filter(p=>p.members.length>1).length],["top",L.filter(p=>p.stars>=4).length],["candidate",c.candidate||0],["alt",c.alt||0],["reject",c.reject||0]].concat(tr?[["trashed",tr]]:[])
 .map(([k,v])=>`<div><b>${fmtNum(v)}</b><span class="mut">${T("common.stat."+k)}</span></div>`).join("");
 $("modeNote").textContent=T(EDIT?"report.mode_edit":"report.mode_static")}
function filters(){const opts=[["all",T("report.f.all")],["g4",T("report.f.g4")],["candidate",tier("candidate")],["alt",tier("alt")],["reject",tier("reject")],["pair",T("report.f.pair")],["face",T("report.f.face")]];
 let h=opts.map(([k,v])=>`<button class="${f==k?"on":""}" onclick="f='${k}';render()">${esc(v)}</button>`).join("")+
 `<select onchange="sort=this.value;render()">${["score","time","group"].map(k=>`<option value="${k}"${sort==k?" selected":""}>${T("report.sort."+k)}</option>`).join("")}</select>`;
 if(EDIT){const rj=live().filter(p=>p.tier=="reject"||p.stars<0).length;h+=`<span class="sp"></span><button onclick="SEL.clear();render()" ${SEL.size?"":"disabled"}>${T("report.clear_sel")}</button><button class="danger" onclick="askTrash([...SEL])" ${SEL.size?"":"disabled"}>${T("report.del_sel",{n:SEL.size})}</button><button class="danger" onclick="askTrash(live().filter(p=>p.tier=='reject'||p.stars<0).map(p=>p.path))" ${rj?"":"disabled"}>${T("report.del_rejects",{n:rj})}</button>`}
 $("filters").innerHTML=h}
let CUR=[];
function rateUI(p,i){if(!EDIT)return `<span class="st">${stars(p.stars)}</span>`;
 return `<span class="rate">${[1,2,3,4,5].map(n=>`<button class="${p.stars>=n?"on":""}" title="${T("report.star_n",{n})}" onclick="mark(CUR[${i}].path,${n})">★</button>`).join("")}<button class="x ${p.stars<0?"on":""}" title="${T("report.reject")}" onclick="mark(CUR[${i}].path,-1)">✕</button></span>`}
function openEdit(path){window.open(`/open/edit?t=${encodeURIComponent(TOKEN)}&path=${encodeURIComponent(path)}`,"_blank","noopener")}
function render(){filters();let L=live().filter(p=>f=="all"||(f=="g4"?p.stars>=4:f=="face"?p.faces>0:f=="pair"?p.members.length>1:p.tier==f));
 L.sort(sort=="time"?(a,b)=>a.time-b.time:sort=="group"?(a,b)=>a.group-b.group||score(b)-score(a):(a,b)=>score(b)-score(a));CUR=L;
 const sep=T("report.list_sep");
 $("grid").innerHTML=L.map((p,i)=>{const a=p.ai||{};const exts=p.members.length>1?p.members.map(ext).join("+"):"";
 return `<div class="c${SEL.has(p.path)?" sel":""}">${EDIT?`<input type="checkbox" class="pick" ${SEL.has(p.path)?"checked":""} onchange="pick(CUR[${i}].path,this.checked)" title="${T("report.pick_tip")}"><button class="ed" onclick="openEdit(CUR[${i}].path)" title="${T("report.edit_tip")}">${T("report.edit")}</button>`:""}<img loading="lazy" src="${esc(p.thumb)}" alt="${esc(p.name)}" onclick="z(this.src)">
<div class="b"><div class="row"><span class="n" title="${esc(p.members.join("\n")||p.path)}">${p.label?`<span class="lb" style="background:${LC[p.label]}"></span>`:""}${esc(p.name.replace(/\.[^.]+$/,""))}${exts?`<span class="pair">${exts}</span>`:`<span class="pair">${ext(p.name)}</span>`}</span><span class="tag t-${p.tier}">${esc(tier(p.tier))}</span></div>
<div class="row">${rateUI(p,i)}<span class="mut">${a.overall?esc(a.provider||"AI")+" "+a.overall+"/10 · ":""}${T("report.local",{n:p.local_score})}${p.manual?" · "+T("report.manual"):""}</span></div>
<div class="mut">${esc(p.exposure)}${p.group_size>1?" · "+T("report.burst",{g:p.group,n:p.group_size,best:p.group_best?T("report.burst_best"):""}):""}</div>
${p.flags.length?`<div class="fl">${p.flags.map(x=>esc(flagText(x))).join(sep)}</div>`:""}
${a.comment?`<div class="cm">${esc(a.genre?"["+genreText(a.genre)+"] ":"")}${esc(a.comment)}</div>`:""}
${a.issues&&a.issues.length?`<div class="mut">${esc(T("report.issues",{list:a.issues.join(T("common.sep"))}))}</div>`:""}${p.error?`<div class="fl">${esc(p.error)}</div>`:""}</div></div>`}).join("");stats()}
function z(s){const e=$("zoom");e.querySelector("img").src=s;e.style.display="flex"}
function pick(path,on){on?SEL.add(path):SEL.delete(path);render()}
async function mark(path,n){const p=D.find(x=>x.path==path);const v=(p.stars==n&&n>0)?n-1:n;
 try{const r=await api("/api/mark",{path,stars:v});Object.assign(p,r.photo);render();up(r.summary);
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
