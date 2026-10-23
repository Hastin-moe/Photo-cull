/* 照片筛选界面的脚本。界面文字全部来自语言包：T("键")，见 locales/*.json 的 cull 分组。 */
const TOKEN=new URLSearchParams(location.search).get("t")||"";const $=id=>document.getElementById(id);
const api=(p,b)=>fetch(p,{method:b?"POST":"GET",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j});
const F=["folder","recursive","remember_key","ai_alts","xmp","jpeg_embed","xmp_all","dry_run","org","org_dir","org_result","org_format","org_rename","burst_gap","scene_gap","similarity","blur_warn","blur_reject","clip_high","clip_low","workers"];
let S={ai:false,provider:"claude",models:{},keys:{},envKeys:{},P:{},order:[],baseUrl:"",orgMove:false},since=0,timer=null;
const OTHER="__other__";
applyI18n();langMenu($("lang"),v=>api("/api/lang",{lang:v}));if(window.shellNav)shellNav("cull");
$("revealReport").textContent=T("cull.done.reveal_report",{fm:T("common.file_manager")});
document.querySelectorAll(".xlink").forEach(a=>a.href=a.dataset.href+"?t="+encodeURIComponent(TOKEN));

function setAI(v){S.ai=v;document.querySelectorAll(".seg[data-mode] button").forEach(b=>b.classList.toggle("on",(b.dataset.ai=="1")==v));
 $("aiBox").classList.toggle("hidden",!v);$("modeHint").textContent=T(v?"cull.mode.ai_hint":"cull.mode.local_hint")}
function curModel(){return $("modelSel").value==OTHER||!$("modelSel").value?$("model").value.trim():$("modelSel").value}
function stash(){S.models[S.provider]=curModel();S.keys[S.provider]=$("api_key").value.trim();if(S.provider=="custom")S.baseUrl=$("base_url").value.trim()}
function syncModelInput(){const other=$("modelSel").value==OTHER||!$("modelSel").options.length;$("model").classList.toggle("hidden",!other);
 const info=S.P[S.provider]||{},m=(info.models||[]).find(x=>x.id==$("modelSel").value);
 $("modelHint").textContent=other?T(S.provider=="custom"?"cull.ai.model_custom_hint":"cull.ai.model_other_hint"):(m&&m.note?T("cull.model_note."+m.note):"")}
function setProv(p,keep){if(!keep)stash();S.provider=p;const info=S.P[p]||{name:p,models:[],console:"",env:"",key_ph:""};
 document.querySelectorAll("#provSeg button").forEach(b=>b.classList.toggle("on",b.dataset.p==p));
 const want=S.models[p]||info.default||"",ids=(info.models||[]).map(m=>m.id);
 $("modelSel").innerHTML=(info.models||[]).map(m=>`<option value="${m.id}">${m.id}${m.note?" · "+T("cull.model_note."+m.note):""}</option>`).join("")+
  (p=="custom"?"":`<option value="${OTHER}">${T("cull.ai.model_other")}</option>`);
 if(ids.includes(want))$("modelSel").value=want;else{$("modelSel").value=p=="custom"?"":OTHER;$("model").value=want}
 if(p=="custom")$("model").value=want;
 $("baseBox").classList.toggle("hidden",p!="custom");$("base_url").value=S.baseUrl||"";
 $("keyLabel").textContent=T("cull.ai.key_label",{name:info.name});$("api_key").value=S.keys[p]||"";$("api_key").placeholder=info.key_ph||"";
 $("keyHint").textContent=S.envKeys[p]?T("cull.ai.key_env",{env:info.env}):p=="custom"?T("cull.ai.key_custom",{env:info.env}):T("cull.ai.key_console",{console:info.console});
 syncModelInput()}
function setOrgMove(v){S.orgMove=v;document.querySelectorAll("#orgMode button").forEach(b=>b.classList.toggle("on",(b.dataset.m=="1")==v));
 $("orgHint").textContent=T(v?"cull.org.move_hint":"cull.org.copy_hint");syncOrg()}
function syncOrg(){const on=$("org").checked;$("orgBox").style.opacity=on?1:.5;
 const r=$("org_result").checked,f=$("org_format").checked,n=$("org_rename").checked,d=$("org_dir").value.trim()||T("cull.org.default_dir");
 const base=d.replace(/[\\/]+$/,"").split(/[\\/]/).pop()||d,ex=(st,file)=>[base,r?T(st=="X"?"cull.org.rejected":"cull.org.kept"):"",f?(/\.(jpe?g|heic|png)$/i.test(file)?"JPEG":"RAW"):"",(n?st+"_ILCE-1M2_":"")+file].filter(Boolean).join("/");
 $("orgEx").textContent=T("cull.org.example",{a:ex("4","DSC01234.ARW"),b:ex("X","DSC01235.JPG")})}
function orgOpts(){return{org_dir:$("org_dir").value.trim(),org_result:$("org_result").checked,org_format:$("org_format").checked,org_rename:$("org_rename").checked,org_move:S.orgMove}}
function collect(){stash();const o={ai:S.ai,provider:S.provider,org_move:S.orgMove,base_url_custom:S.baseUrl};F.forEach(k=>{const e=$(k);o[k]=e.type=="checkbox"?e.checked:e.type=="number"?Number(e.value):e.value.trim()});
 S.order.forEach(p=>{o["model_"+p]=S.models[p]||"";o["key_"+p]=S.keys[p]||""});return o}
function fill(s){F.forEach(k=>{const e=$(k);if(e.type=="checkbox")e.checked=!!s[k];else e.value=s[k]??""});
 S.P=s.providers||{};S.order=s.provider_order||Object.keys(S.P);S.envKeys=s.env_keys||{};S.baseUrl=s.base_url_custom||"";
 $("provSeg").innerHTML=S.order.map(p=>`<button data-p="${p}">${S.P[p].name}</button>`).join("");
 $("provSeg").querySelectorAll("button").forEach(b=>b.onclick=()=>setProv(b.dataset.p));
 S.order.forEach(p=>{S.models[p]=s["model_"+p];S.keys[p]=s["key_"+p]||""});
 setAI(!!s.ai);setProv(S.P[s.provider]?s.provider:"claude",true);syncXmp();setOrgMove(!!s.org_move);
 if(!s.lang_saved){const want=(navigator.languages||[navigator.language]).map(x=>String(x).toLowerCase()).map(x=>x.startsWith("zh")?"zh-CN":x.startsWith("ja")?"ja":x.startsWith("en")?"en":"")[0];
  if(want&&want!=LANG)api("/api/lang",{lang:want}).then(()=>location.reload()).catch(()=>{});else if(want)api("/api/lang",{lang:want}).catch(()=>{})}}
function syncXmp(){const on=$("xmp").checked;["jpeg_embed","xmp_all"].forEach(k=>$(k).disabled=!on)}
function pill(key,c){const p=$("pill");p.textContent=T(key);p.className="pill "+(c||"")}
function stageUI(st){const order=["analyze","ai","xmp","done"],cur=order.indexOf(st.stage);
 [["analyze",0],["ai",1],["xmp",2]].forEach(([k,i])=>{const el=$("st-"+k),bar=el.querySelector("i"),lab=el.querySelector(".h span");
  const skip=k=="ai"&&!S.runAI;el.className="stage"+(skip?" skip":cur>i?" done":cur==i?" active":"");
  let pct=cur>i?100:cur==i&&st.total?st.done/st.total*100:0;bar.style.width=(skip?0:pct)+"%";
  lab.textContent=skip?T("cull.stage.off"):cur>i?T("cull.stage.done"):cur==i&&st.total&&k!="xmp"?`${st.done}/${st.total}`:cur==i?T("cull.stage.running"):T("cull.stage.waiting")})}
function stats(r,reload){const items=[["stat.total",r.total,""],["stat.pairs",r.pairs||0,""],["stat.top",r.top,"g"],["stat.candidate",r.candidate,"g"],["stat.alt",r.alt,"y"],["stat.reject",r.reject,"r"]];
 if(r.error)items.push(["stat.error",r.error,"r"]);if(r.trashed)items.push(["stat.trashed",r.trashed,""]);
 $("stats").style.gridTemplateColumns=`repeat(${Math.min(items.length,8)},1fr)`;
 $("stats").innerHTML=items.map(([k,v,c])=>`<div class="stat ${c}"><b>${fmtNum(v)}</b><span>${T("common."+k)}</span></div>`).join("");
 let note=r.dry_run?T("cull.done.note_dry"):r.xmp?T("cull.done.note_xmp",{n:r.xmp}):T("cull.done.note_none");
 const g=r.organized;$("revealOrg").classList.toggle("hidden",!(g&&!g.dry_run));
 if(g){const verb=T(g.mode=="move"?"cull.org.verb_move":"cull.org.verb_copy");
  note+=" "+(g.dry_run?T("cull.done.org_dry",{verb,n:g.photos,out:g.out}):T("cull.done.org_ok",{verb,n:g.photos,kept:g.kept,rejected:g.rejected,out:g.out})+(g.errors&&g.errors.length?" "+T("cull.done.org_err",{n:g.errors.length}):""))}
 $("doneNote").textContent=note;
 if(reload!==false)$("report").src=`/out/${TOKEN}/report.html?`+Date.now()}
window.addEventListener("message",e=>{if(e.origin===location.origin&&e.data&&e.data.pc=="summary")stats(e.data.s,false)});
const fmTok=n=>n>=1e6?(n/1e6).toFixed(2)+"M":Math.round(n/1e3)+"K";
async function poll(){try{const st=await api("/api/status?since="+since);since=st.next;
 if(st.lines.length){const l=$("log");l.textContent+=st.lines.join("\n")+"\n";l.scrollTop=l.scrollHeight}
 stageUI(st);
 if(st.pending){$("mLine").innerHTML=T("cull.confirm.line",{n:`<span class="big">${st.pending.count}</span>`,model:`<b>${st.pending.model.replace(/[<>&]/g,"")}</b>`});
  $("mTokens").textContent=T("cull.confirm.tokens",{inp:fmTok(st.pending.tokens_in),out:fmTok(st.pending.tokens_out)});$("modal").classList.add("show")}
 else $("modal").classList.remove("show");
 if(!st.running){clearInterval(timer);timer=null;$("run").disabled=false;$("loadPrev").disabled=false;$("cancel").classList.add("hidden");
  if(st.error){$("err").textContent=st.error;$("err").classList.remove("hidden");pill("cull.pill.error","err");$("logBox").open=true}
  if(st.result){stats(st.result);$("done").classList.remove("hidden");pill("cull.pill.done","ok")}
  else if(!st.error)pill("cull.pill.ready")}}catch(e){console.log(e)}}
function showWork(){$("empty").classList.add("hidden");$("work").classList.remove("hidden");$("err").classList.add("hidden")}
function needKey(o){return o.ai&&!o["key_"+o.provider]&&!S.envKeys[o.provider]}
async function run(){const o=collect();if(!o.folder){alert(T("cull.err.no_folder"));return}
 if(o.ai&&o.provider=="custom"&&(!o.base_url_custom||!o.model_custom)){alert(T("cull.err.custom_incomplete"));return}
 if(needKey(o)){alert(T("cull.err.need_key",{name:(S.P[o.provider]||{}).name||""}));$("api_key").focus();return}
 try{await api("/api/run",o)}catch(e){alert(e.message);return}
 S.runAI=o.ai;$("aiStageName").textContent=o.ai?T("cull.stage.ai_named",{name:(S.P[o.provider]||{}).name||"AI"}):T("cull.stage.ai");
 since=0;$("log").textContent="";showWork();$("done").classList.add("hidden");$("run").disabled=true;$("loadPrev").disabled=true;$("cancel").classList.remove("hidden");
 pill("cull.pill.running","run");stageUI({stage:"analyze",done:0,total:0});timer=setInterval(poll,400)}
async function loadPrev(){const folder=$("folder").value.trim();if(!folder){alert(T("cull.err.no_folder"));return}
 try{const r=await api("/api/load",{folder});S.runAI=false;showWork();stageUI({stage:"done",done:1,total:1});stats(r.result);$("done").classList.remove("hidden");pill("cull.pill.loaded","ok")}catch(e){alert(e.message)}}
document.querySelectorAll(".seg[data-mode] button").forEach(b=>b.onclick=()=>setAI(b.dataset.ai=="1"));
$("modelSel").onchange=()=>{if($("modelSel").value==OTHER&&!$("model").value)$("model").value="";syncModelInput()};
$("xmp").onchange=syncXmp;$("run").onclick=run;$("loadPrev").onclick=loadPrev;$("cancel").onclick=()=>api("/api/cancel",{});
$("pick").onclick=async()=>{$("pick").disabled=true;try{const r=await api("/api/choose",{start:$("folder").value});if(r.folder)$("folder").value=r.folder}catch(e){alert(e.message)}$("pick").disabled=false};
$("mYes").onclick=()=>{api("/api/confirm",{yes:true});$("modal").classList.remove("show")};
$("mNo").onclick=()=>{api("/api/confirm",{yes:false});$("modal").classList.remove("show")};
$("openReport").onclick=()=>window.SHELL?api("/api/open_report",{}).catch(e=>alert(e.message)):window.open(`/out/${TOKEN}/report.html`,"_blank");
$("revealReport").onclick=()=>api("/api/reveal",{what:"report"});$("revealOrg").onclick=()=>api("/api/reveal",{what:"org"});
["org","org_result","org_format","org_rename"].forEach(k=>$(k).onchange=syncOrg);$("org_dir").oninput=syncOrg;
$("orgMode").querySelectorAll("button").forEach(b=>b.onclick=()=>setOrgMove(b.dataset.m=="1"));
$("pickOrg").onclick=async()=>{$("pickOrg").disabled=true;try{const r=await api("/api/choose",{start:$("org_dir").value||$("folder").value,what:"org"});if(r.folder){$("org_dir").value=r.folder;syncOrg()}}catch(e){alert(e.message)}$("pickOrg").disabled=false};
$("orgNow").onclick=async()=>{const o=orgOpts();
 if(o.org_move&&!confirm(T("cull.org.move_confirm")))return;
 $("orgNow").disabled=true;try{const r=await api("/api/organize",o);stats(r.summary);
  const g=r.organized;if(g&&g.errors&&g.errors.length){const l=$("log");l.textContent+=T("cull.org.failed")+"\n"+g.errors.join("\n")+"\n";$("logBox").open=true}}catch(e){alert(e.message)}$("orgNow").disabled=false};
$("revealPhotos").onclick=()=>api("/api/reveal",{what:"photos"});
/* 页面刷新（例如切换语言）后恢复：正在运行就接着显示进度，已有结果就直接显示结果 */
async function restore(){try{const st=await api("/api/status?since=0");if(!st.running&&!st.result)return;
 S.runAI=!!st.ai;showWork();
 if(st.running){since=0;$("run").disabled=true;$("loadPrev").disabled=true;$("cancel").classList.remove("hidden");pill("cull.pill.running","run");timer=setInterval(poll,400)}
 else{since=st.next;stageUI({stage:"done",done:1,total:1});stats(st.result);$("done").classList.remove("hidden");pill("cull.pill.done","ok")}}catch(e){}}
api("/api/settings").then(s=>{fill(s);restore()}).catch(()=>{document.body.innerHTML=`<p style='padding:40px'>${T("common.link_expired")}</p>`});
