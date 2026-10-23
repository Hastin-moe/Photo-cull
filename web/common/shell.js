/* 在一体窗口（web/shell）里运行时的配合：
   · 页头的「另一个程序 ↗」链接换成 照片筛选｜照片编辑 切换按钮；
   · ⌘1／⌘2（Windows 上 Ctrl）切换；
   · 切换语言时通知外层，两个界面一起刷新。
   单独在浏览器里打开时（地址里没有 shell=1）什么也不做。 */
(function(){
  const IN=new URLSearchParams(location.search).get("shell")=="1"&&window.parent!==window;
  window.SHELL=IN;
  window.shellPost=m=>{if(IN)window.parent.postMessage(m,"*")};
  if(!IN)return;
  document.documentElement.classList.add("in-shell");
  addEventListener("message",e=>{if(e.source!==window.parent)return;const d=e.data||{};if(d.pc=="reload")location.reload()});
  addEventListener("keydown",e=>{if((e.metaKey||e.ctrlKey)&&(e.key=="1"||e.key=="2")){e.preventDefault();shellPost({pc:"switch",to:e.key=="1"?"cull":"edit"})}});
  window.shellNav=function(current){
    const h=document.querySelector("header h1");if(h)h.textContent=T("common.app.suite");
    const a=document.querySelector(".xlink");if(!a)return;
    const seg=document.createElement("div");seg.className="appswitch";seg.setAttribute("role","tablist");
    seg.innerHTML=["cull","edit"].map((k,i)=>`<button role="tab" data-app="${k}" class="${k==current?"on":""}" title="⌘${i+1}">${T("common.app."+k)}</button>`).join("");
    seg.querySelectorAll("button").forEach(b=>b.onclick=()=>{if(b.dataset.app!=current)shellPost({pc:"switch",to:b.dataset.app})});
    a.replaceWith(seg)};
})();
