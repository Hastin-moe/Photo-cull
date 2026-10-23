/* 网页端多语言：语言包由服务端注入到 window.I18N = {lang, langs, dict}。
   用法：T("cull.run")、T("cull.done.note_xmp", {n: 3})；HTML 里写 data-i18n="键"（文字）、
   data-i18n-html（含标签的文字）、data-i18n-title、data-i18n-placeholder，调用 applyI18n() 填充。 */
(function(){
  const I=window.I18N||{lang:"zh-CN",langs:{},dict:{}};
  function T(key,vars){let s=I.dict[key];if(s===undefined){console.warn("[i18n] 缺少",key);s=key}
    return vars?String(s).replace(/\{(\w+)\}/g,(m,n)=>vars[n]!==undefined?vars[n]:m):s}
  function applyI18n(root){root=root||document;
    root.querySelectorAll("[data-i18n]").forEach(e=>e.textContent=T(e.dataset.i18n));
    root.querySelectorAll("[data-i18n-html]").forEach(e=>e.innerHTML=T(e.dataset.i18nHtml));
    root.querySelectorAll("[data-i18n-title]").forEach(e=>e.title=T(e.dataset.i18nTitle));
    root.querySelectorAll("[data-i18n-placeholder]").forEach(e=>e.placeholder=T(e.dataset.i18nPlaceholder))}
  /* 语言下拉框：选中后保存到服务端（两个程序共用），再刷新页面 */
  function langMenu(sel,save){if(!sel)return;
    sel.innerHTML=Object.entries(I.langs).map(([k,v])=>`<option value="${k}"${k==I.lang?" selected":""}>${v}</option>`).join("");
    sel.onchange=async()=>{try{await save(sel.value);if(window.SHELL)window.shellPost({pc:"lang"});else location.reload()}catch(e){alert(e.message)}}}
  /* 数字、日期按当前语言格式化 */
  const num=(n,o)=>Number(n).toLocaleString(I.lang,o);
  window.T=T;window.applyI18n=applyI18n;window.langMenu=langMenu;window.fmtNum=num;window.LANG=I.lang;
  document.documentElement.lang=I.lang;
})();
