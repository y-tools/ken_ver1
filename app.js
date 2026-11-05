(() => {
"use strict";
const $ = s => document.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = v => String(v ?? "").normalize("NFKC").toLowerCase().replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96)).replace(/[\s・ー‐-]/g,"");
const params = new URLSearchParams(location.search);
const preview = params.get("embed")==="1";
if(preview) document.body.classList.add("embed-mode");
const config = window.KEN_CONFIG || {};
const storageKey = "ken-denmoku-v2";
const initial = {songs:[],requests:[],name:"Ken",streamLive:false};
let state = initial;
try {
 const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
 if(saved && typeof saved==="object") {
  state = {...initial, songs:Array.isArray(saved.songs)?saved.songs:[], requests:Array.isArray(saved.requests)?saved.requests:[], name:typeof saved.name==="string"?saved.name:"Ken",streamLive:saved.streamLive===true};
 }
} catch(_) {}
const catalog = {rows:[],idx:[],ready:false,error:false};

let adminMode=false;
let editingId=null;
let selected=null;
let activeFilter="new";
let isSending=false;
function persist(){
 try{localStorage.setItem(storageKey,JSON.stringify(state));return true;}
 catch(_){ toast("端末の保存容量が不足しています");return false;}
}
function toast(message){
 const el=$("#toast");el.textContent=message;el.hidden=false;
 clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,3400);
}
function readyKey(t,a){return norm(t)+"|"+norm(a);}
function readySet(){return new Set(state.songs.filter(x=>x.status==="ready").map(x=>readyKey(x.title,x.artist)));}
function lookupCatalog(q,limit=60){
 const term=norm(q);if(!term||!catalog.ready)return [];
 const prefix=[],middle=[];
 for(let i=0;i<catalog.rows.length;i++){
  const r=catalog.rows[i],title=norm(r[0]),artist=norm(r[1]);
  if(title.startsWith(term)||artist.startsWith(term)){prefix.push(i);if(prefix.length>=limit)break;}
  else if((title.includes(term)||artist.includes(term))&&middle.length<limit)middle.push(i);
 }
 return prefix.concat(middle).slice(0,limit);
}
function displayRow(s,actions="",status=""){
 const tag=status?'<span class="tag '+(status==="ready"?"ready":"")+'">'+(status==="ready"?"歌える曲":"カタログ")+'</span>':"";
 return '<div class="song-row"><div class="song-info"><div class="song-title">'+esc(s.title)+'</div><div class="song-artist">'+esc(s.artist)+
 (s.year?' · '+esc(s.year):'')+'</div>'+ (tag?'<div class="song-meta">'+tag+'</div>':"")+
 '</div>'+ (actions?'<div class="song-actions">'+actions+'</div>':"")+'</div>';
}
function openRequestDialog(song){
 if(!state.streamLive){toast("現在は配信終了中です。リクエストを送信できません");return;}
 selected=song||null;
 $("#reqTitle").value=song?.title||"";
 $("#reqArtist").value=song?.artist||"";
 $("#chosenSong").hidden=!song;
 $("#chosenSong").textContent=song?"選択中："+song.title+" / "+song.artist:"";
 const dlg=$("#requestDialog");
 if(typeof dlg.showModal==="function")dlg.showModal();else dlg.setAttribute("open","");
 (song?$("#reqName"):$("#reqTitle")).focus();
}
function selectSong(title,artist,source){openRequestDialog({title,artist,source});}
function renderSearch(){
 const q=$("#searchInput").value.trim();
 const ready=state.songs.filter(s=>s.status==="ready");
 const statusLookup=new Map(state.songs.map(s=>[readyKey(s.title,s.artist),s.status]));
 $("#searchHelper").textContent=catalog.ready
  ?"楽曲カタログ "+catalog.rows.length.toLocaleString("ja-JP")+"曲。曲名・アーティスト名をまとめて検索できます。"
  : catalog.error?"カタログを読み込めませんでした。登録済み曲は検索できます。":"楽曲カタログを読み込み中です…";
 const list=[],seen=new Set();
 const add=s=>{const k=readyKey(s.title,s.artist);if(!seen.has(k)){seen.add(k);list.push(s);}};
 for(const s of ready.filter(s=>!q||norm(s.title).includes(norm(q))||norm(s.artist).includes(norm(q))).slice(0,60))add({...s,source:"ready"});
 if(q&&catalog.ready)for(const i of lookupCatalog(q,60)){
  const [title,artist,year]=catalog.rows[i];
  add({title,artist,year,source:statusLookup.get(readyKey(title,artist))||"catalog"});
  if(list.length>=60)break;
 }
 const result=list.slice(0,60);
 $("#searchResults").innerHTML=result.length?result.map((s,i)=>displayRow(s,
  '<button class="button primary" data-select-index="'+i+'" type="button"'+(!state.streamLive?' disabled title="配信中のみリクエスト受付"':'')+'>リクエスト</button>',s.source==="ready"?"ready":"catalog")).join("")
  :'<div class="empty">'+(q?"一致する曲がありません。別の表記でも検索してください。":"歌える曲の登録はまだありません。曲名やアーティスト名で検索してください。")+'</div>';
 window.__searchResults=result;
}
function renderPractice(){
 const list=new Map();
 const add=(title,artist,year)=>{const k=readyKey(title,artist);if(!list.has(k))list.set(k,{title,artist,year,count:0});return list.get(k)};
 for(const s of state.songs.filter(s=>s.status==="practice"))add(s.title,s.artist,s.year);
 for(const r of state.requests.filter(r=>r.status==="practice"))add(r.title,r.artist,null).count++;
 const rows=[...list.values()].sort((a,b)=>a.title.localeCompare(b.title,"ja"));
 $("#practiceCount").textContent=rows.length;
 $("#practiceList").innerHTML=rows.length?rows.map(s=>'<div class="song-row"><div class="song-info"><div class="song-title">'+esc(s.title)+'</div><div class="song-artist">'+esc(s.artist)+'</div><div class="song-meta"><span class="tag wait">練習中</span>'+ (s.count?' リクエスト '+s.count+'件':'')+'</div></div></div>').join("")
  :'<div class="empty">練習中の楽曲はまだありません。</div>';
}
function requestItem(r,controls=""){
 const when=r.createdAt?new Date(r.createdAt).toLocaleString("ja-JP",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"}):"";
 return '<div class="song-row"><div class="song-info"><div class="song-title">'+esc(r.title)+'</div><div class="song-artist">'+esc(r.artist)+'</div><div class="queue-person">リクエスト者：'+esc(r.nickname||"匿名")+'</div>'+
 (r.message?'<div class="song-meta">'+esc(r.message)+'</div>':"")+
 '<div class="song-meta">'+esc(when)+'</div></div>'+(controls?'<div class="song-actions">'+controls+'</div>':"")+'</div>';
}
function waitingRequests(){return state.requests.filter(r=>r.status==="waiting").sort((a,b)=>(a.waitOrder||a.createdAt)-(b.waitOrder||b.createdAt));}
function renderQueue(){
 const waiting=waitingRequests();
 $("#waitingCount").textContent=waiting.length;
 $("#waitingList").innerHTML=waiting.length?waiting.map((r,i)=>'<div class="queue-row"><div class="queue-no">'+(i+1)+'</div><div class="queue-info"><div class="song-title">'+esc(r.title)+'</div><div class="song-artist">'+esc(r.artist)+'</div><div class="queue-person">リクエスト者：'+esc(r.nickname||"匿名")+'</div></div></div>').join("")
  :'<div class="empty">現在の待機曲はありません。</div>';
 $("#adminWaitingCount").textContent=waiting.length;
 $("#adminWaiting").innerHTML=waiting.length?waiting.map(r=>requestItem(r,
  '<button type="button" class="button" data-do="up" data-id="'+esc(r.id)+'">↑</button>'+
  '<button type="button" class="button" data-do="down" data-id="'+esc(r.id)+'">↓</button>'+
  '<button type="button" class="button primary" data-do="done" data-id="'+esc(r.id)+'">歌唱完了</button>'+
  '<button type="button" class="button subtle" data-do="new" data-id="'+esc(r.id)+'">受付へ戻す</button>')).join("")
  :'<div class="empty">待機曲はありません。受付中のリクエストから追加できます。</div>';
}
function renderAdminRequests(){
 const reqs=state.requests.filter(r=>activeFilter==="all"||r.status===activeFilter).sort((a,b)=>b.createdAt-a.createdAt);
 $("#adminRequestCount").textContent=state.requests.filter(r=>r.status==="new").length;
 $("#adminRequests").innerHTML=reqs.length?reqs.map(r=>{
  const key=' data-id="'+esc(r.id)+'"';
  let actions="";
  if(r.status==="new"){
   actions='<button class="button primary" data-do="waiting"'+key+'>待機楽曲に追加</button>'+
    '<button class="button" data-do="practice"'+key+'>練習楽曲に追加</button>';
  }else if(r.status==="waiting"){
   actions='<button class="button" data-do="practice"'+key+'>練習楽曲に追加</button>'+
    '<button class="button subtle" data-do="new"'+key+'>受付へ戻す</button>';
  }else if(r.status==="practice"){
   actions='<button class="button primary" data-do="waiting"'+key+'>待機楽曲に追加</button>'+
    '<button class="button subtle" data-do="new"'+key+'>受付へ戻す</button>';
  }else{
   actions='<button class="button" data-do="new"'+key+'>再受付</button>';
  }
  return requestItem(r,actions+'<button class="button warning" data-do="delete"'+key+'>削除</button>');
 }).join(""):'<div class="empty">該当するリクエストはありません。</div>';
}
function renderStreamStatus(){
 const live=state.streamLive===true;
 $("#streamStatus").textContent=live?"配信中・楽曲リクエスト受付中":"配信終了中・リクエスト受付停止";
 $("#streamStatus").classList.toggle("live",live);
 $("#requestAvailability").textContent=live?"配信中・リクエスト受付中":"配信終了中・リクエスト受付停止";
 $("#requestAvailability").classList.toggle("live",live);
 $("#adminStreamStatus").textContent=live?"配信中・受付中":"配信終了中";
 $("#startStream").disabled=live;
 $("#endStream").disabled=!live;
 $("#openRequestDialog").disabled=!live;
 $("#sendRequest").disabled=!live;
}
function setStreamLive(live){
 if(!adminMode||preview)return;
 if(state.streamLive===live)return;
 state.streamLive=live;
 persist();render();
 toast(live?"配信を開始しました。リクエスト受付中です":"配信を終了しました。リクエスト受付を停止しました");
}
function render(){
 $("#streamerName").textContent=state.name;
 document.title=state.name+"のデンモク";
 renderSearch();renderQueue();renderPractice();renderAdminRequests();renderStreamStatus();
 $("#catalogStatus").textContent=catalog.ready?"楽曲検索利用可":catalog.error?"カタログ読込失敗":"曲カタログ読込中";
 if(!preview){$("#listenerView").hidden=adminMode;$("#adminView").hidden=!adminMode;}
 $("#toListener").hidden=!adminMode || preview;
 document.body.classList.toggle("admin-active",adminMode&&!preview);
}
function changeRequestStatus(id,status){
 const r=state.requests.find(x=>x.id===id);if(!r)return;
 r.status=status;
 if(status==="waiting")r.waitOrder=Math.max(Date.now(),...state.requests.map(x=>x.waitOrder||0))+1;
 if(status==="practice"){
  const existing=state.songs.find(s=>readyKey(s.title,s.artist)===readyKey(r.title,r.artist));
  if(existing){if(existing.status!=="ready")existing.status="practice";}
  else state.songs.push({id:"p-"+Date.now(),title:r.title,artist:r.artist,status:"practice",year:null});
 }
 persist();render();
}
function reorder(id,dir){
 const list=waitingRequests();const a=list.findIndex(x=>x.id===id),b=a+dir;
 if(a<0||b<0||b>=list.length)return;
 const start=Date.now();
 list.forEach((r,i)=>r.waitOrder=start+i);
 const tmp=list[a].waitOrder;list[a].waitOrder=list[b].waitOrder;list[b].waitOrder=tmp;
 persist();render();
}
function requestSubmit(event){
 event.preventDefault();if(isSending)return;
 if(!state.streamLive){toast("配信終了中のため、リクエストを受け付けていません");return;}
 const title=$("#reqTitle").value.trim(),artist=$("#reqArtist").value.trim(),nickname=$("#reqName").value.trim();
 if(!title||!artist||!nickname){toast("曲名・アーティスト・お名前を入力してください");return;}
 if(title.length>120||artist.length>120||nickname.length>40){toast("入力文字数を確認してください");return;}
 isSending=true;
 try{
  const r={id:"r-"+Date.now()+"-"+Math.random().toString(36).slice(2,8),title,artist,nickname,
   message:$("#reqMessage").value.trim().slice(0,200),status:"new",createdAt:Date.now(),songId:null};
  state.requests.push(r);
  if(!persist()){state.requests.pop();return;}
  $("#reqMessage").value="";$("#reqTitle").value="";$("#reqArtist").value="";selected=null;
  $("#chosenSong").hidden=true;
  const dlg=$("#requestDialog");if(typeof dlg.close==="function")dlg.close();else dlg.removeAttribute("open");
  try{localStorage.setItem("ken-nickname",nickname)}catch(_){}
  toast("端末内プレビューに受付登録しました（他の端末には共有されません）");
  render();
 }finally{isSending=false;}
}
function adminAction(event){
 const b=event.target.closest("[data-do]");
 if(!b)return;
 const id=b.dataset.id,act=b.dataset.do;
 if(act==="waiting"||act==="new"||act==="practice"||act==="done"){changeRequestStatus(id,act);return;}
 if(act==="up"||act==="down"){reorder(id,act==="up"?-1:1);return;}
 if(act==="delete"){
  if(!confirm("このリクエストを削除しますか？"))return;
  state.requests=state.requests.filter(r=>r.id!==id);persist();render();
 }
}
async function loadCatalog(){
 try{
  const res=await fetch("./catalog.json",{cache:"force-cache"});
  if(!res.ok)throw Error("HTTP "+res.status);
  const rows=await res.json();if(!Array.isArray(rows))throw Error("Invalid catalog");
  catalog.rows=rows;catalog.ready=true;
 }catch(e){catalog.error=true;console.warn("Catalog unavailable",e);}
 render();
}

/* Hidden manager entrance: press the app title for at least 900ms.
   This is a client-side UI gate only; do not use it for sensitive data. */
const UI_ADMIN_PASSWORD = "kny";
function setupAdminUnlock(){
 const trigger=$("#adminTitle");
 const dialog=$("#adminPasswordDialog");
 const password=$("#adminPasswordInput");
 const error=$("#adminPasswordError");
 const HOLD_MS=750;
 let timer=null;
 let heldAt=0;
 let startX=0,startY=0;
 let pointerId=null;
 let alreadyOpened=false;
 const cancelHold=()=>{
  if(timer!==null){clearTimeout(timer);timer=null;}
  heldAt=0;
 };
 const openPassword=()=>{
  cancelHold();
  if(preview||adminMode||dialog.open)return;
  alreadyOpened=true;
  password.value="";
  error.hidden=true;
  if(typeof dialog.showModal==="function")dialog.showModal();
  else dialog.setAttribute("open","");
  password.focus();
 };
 const beginHold=(x,y,id)=>{
  if(preview||adminMode||dialog.open)return;
  cancelHold();
  alreadyOpened=false;
  startX=x;startY=y;pointerId=id;
  heldAt=Date.now();
  timer=window.setTimeout(()=>openPassword(),HOLD_MS);
 };
 trigger.addEventListener("pointerdown",e=>{
  if(e.button!==0||e.isPrimary===false)return;
  beginHold(e.clientX,e.clientY,e.pointerId);
  // Capture mouse events even if the cursor drifts away from the title.
  if(e.pointerType==="mouse" && typeof trigger.setPointerCapture==="function"){
   try{trigger.setPointerCapture(e.pointerId);}catch(_){}
  }
 });
 trigger.addEventListener("pointermove",e=>{
  if(heldAt && e.pointerId===pointerId && Math.hypot(e.clientX-startX,e.clientY-startY)>55)cancelHold();
 });
 trigger.addEventListener("pointerup",e=>{
  if(pointerId!==e.pointerId)return;
  if(heldAt && !alreadyOpened && Date.now()-heldAt>=HOLD_MS)openPassword();
  cancelHold();
  pointerId=null;
 });
 trigger.addEventListener("pointercancel",cancelHold);
 // PC alternative: double-click title to access the same password gate.
 trigger.addEventListener("dblclick",e=>{e.preventDefault();openPassword();});
 trigger.addEventListener("click",e=>e.preventDefault());
 trigger.addEventListener("contextmenu",e=>{if(heldAt)e.preventDefault();});
 let keyboardStart=0;
 trigger.addEventListener("keydown",e=>{
  if((e.key==="Enter"||e.key===" ")&&!e.repeat){
   e.preventDefault();
   if(!keyboardStart){
    keyboardStart=Date.now();
    beginHold(0,0,"keyboard");
   }
  }
 });
 trigger.addEventListener("keyup",e=>{
  if(e.key==="Enter"||e.key===" "){
   e.preventDefault();
   if(keyboardStart && Date.now()-keyboardStart>=HOLD_MS && !alreadyOpened)openPassword();
   keyboardStart=0;
   cancelHold();
  }
 });
 window.addEventListener("blur",cancelHold);
 document.addEventListener("visibilitychange",()=>{if(document.hidden)cancelHold();});
 $("#adminPasswordCancel").addEventListener("click",()=>{
  if(typeof dialog.close==="function")dialog.close();else dialog.removeAttribute("open");
 });
 $("#adminPasswordForm").addEventListener("submit",e=>{
  e.preventDefault();
  if(password.value!==UI_ADMIN_PASSWORD){
   error.hidden=false;
   password.value="";
   password.focus();
   return;
  }
  if(typeof dialog.close==="function")dialog.close();else dialog.removeAttribute("open");
  adminMode=true;
  render();
  $("#toListener").focus();
 });
 dialog.addEventListener("close",()=>{
  password.value="";
  error.hidden=true;
  alreadyOpened=false;
  cancelHold();
 });
}
function attach(){
 $("#searchInput").addEventListener("input",renderSearch);
 $("#searchResults").addEventListener("click",e=>{
  const btn=e.target.closest("[data-select-index]");if(!btn)return;
  const s=window.__searchResults?.[Number(btn.dataset.selectIndex)];
  if(s)selectSong(s.title,s.artist,s.source);
 });
 $("#requestForm").addEventListener("submit",requestSubmit);
 $("#openRequestDialog").addEventListener("click",()=>openRequestDialog(null));
 $("#requestDialogClose").addEventListener("click",()=>{
  const dlg=$("#requestDialog");if(typeof dlg.close==="function")dlg.close();else dlg.removeAttribute("open");
 });
 $("#startStream").addEventListener("click",()=>setStreamLive(true));
 $("#endStream").addEventListener("click",()=>setStreamLive(false));
 $("#adminView").addEventListener("click",adminAction);
 document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{
  activeFilter=b.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(x=>x.classList.toggle("active",x===b));
  renderAdminRequests();
 }));
 $("#toListener").addEventListener("click",()=>{adminMode=false;render();$("#adminTitle").focus();});
 setupAdminUnlock();
 $("#nameForm").addEventListener("submit",e=>{
  e.preventDefault();state.name=$("#newName").value.trim().slice(0,30)||"Ken";persist();render();toast("この端末の表示名を変更しました");
 });
 $("#songForm").addEventListener("submit",e=>{
  e.preventDefault();
  const title=$("#songTitle").value.trim(),artist=$("#songArtist").value.trim();
  if(!title||!artist)return;
  const old=state.songs.find(s=>readyKey(s.title,s.artist)===readyKey(title,artist));
  if(old){old.status=$("#songStatus").value;old.year=$("#songYear").value||null;}
  else state.songs.push({id:"s-"+Date.now(),title,artist,status:$("#songStatus").value,year:$("#songYear").value||null});
  persist();e.target.reset();render();toast("端末内の歌える曲リストを更新しました");
 });
 $("#songImport").addEventListener("change",async e=>{
  const f=e.target.files[0];if(!f)return;
  const content=await f.text(),lines=content.replace(/^\uFEFF/,"").split(/\r?\n/);
  let count=0;
  for(const line of lines.slice(0,20000)){
   const [title,artist,, ,status,year]=line.split(",").map(x=>x.trim().replace(/^"|"$/g,""));
   if(!title||!artist||/^(曲|title)/i.test(title))continue;
   const k=readyKey(title,artist);
   if(state.songs.some(s=>readyKey(s.title,s.artist)===k))continue;
   state.songs.push({id:"imp-"+Date.now()+"-"+count,title,artist,status:/練習/.test(status)?"practice":"ready",year:year||null});
   count++;
  }
  persist();render();toast(count+"曲を端末内に読み込みました");e.target.value="";
 });
 try{const nick=localStorage.getItem("ken-nickname")||localStorage.getItem("utabox-nick");if(nick)$("#reqName").value=nick;}catch(_){}
 $("#newName").value=state.name;
 window.addEventListener("storage",event=>{
  if(event.key!==storageKey || !event.newValue)return;
  try{
   const updated=JSON.parse(event.newValue);
   if(updated && Array.isArray(updated.requests) && Array.isArray(updated.songs)){
    state={...initial,...updated};
    render();
   }
  }catch(_){}
 });
 if(preview){
  const header=$("#siteHeader");header.hidden=true;
  adminMode=false;$("#adminView").hidden=true;$("#listenerView").hidden=false;
 }
 render();loadCatalog();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",attach);else attach();
})();
