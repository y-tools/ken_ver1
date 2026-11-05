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
const initial = {songs:[],requests:[],name:"Ken"};
let state = initial;
try {
 const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
 if(saved && typeof saved==="object") {
  state = {...initial, songs:Array.isArray(saved.songs)?saved.songs:[], requests:Array.isArray(saved.requests)?saved.requests:[], name:typeof saved.name==="string"?saved.name:"Ken"};
 }
} catch(_) {}
const catalog = {rows:[],idx:[],ready:false,error:false};
let searchMode="title";
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
function lookupCatalog(q,kind="title",limit=60){
 const normalized=norm(q);
 if(!normalized||!catalog.ready)return [];
 const indexed=[];
 const fallback=[];
 for(let i=0;i<catalog.rows.length;i++){
  const r=catalog.rows[i];
  const name=norm(kind==="artist"?r[1]:r[0]);
  const pos=name.indexOf(normalized);
  if(pos===0){indexed.push(i);if(indexed.length>=limit)break;}
  else if(pos>0 && fallback.length<limit)fallback.push(i);
 }
 return indexed.concat(fallback).slice(0,limit);
}
function displayRow(s,actions="",status=""){
 const tag=status?'<span class="tag '+(status==="ready"?"ready":"")+'">'+(status==="ready"?"歌える曲":"カタログ")+'</span>':"";
 return '<div class="song-row"><div class="song-info"><div class="song-title">'+esc(s.title)+'</div><div class="song-artist">'+esc(s.artist)+
 (s.year?' · '+esc(s.year):'')+'</div>'+ (tag?'<div class="song-meta">'+tag+'</div>':"")+
 '</div>'+ (actions?'<div class="song-actions">'+actions+'</div>':"")+'</div>';
}
function selectSong(title,artist,source){
 selected={title,artist,source};
 $("#reqTitle").value=title;$("#reqArtist").value=artist;
 $("#chosenSong").hidden=false;
 $("#chosenSong").textContent="選択中："+title+" / "+artist;
 document.querySelector("#request-section").scrollIntoView({behavior:"smooth",block:"start"});
 toast("曲を選択しました。お名前を入力して送信してください");
}
function renderSearch(){
 const q=$("#searchInput").value.trim();
 const type=searchMode;
 const readySongs=state.songs.filter(x=>x.status==="ready");
 $("#searchHelper").textContent=catalog.ready
  ? "曲カタログ "+catalog.rows.length.toLocaleString("ja-JP")+"曲。歌える曲は配信者の登録分のみです。"
  : catalog.error?"曲カタログの取得に失敗しました。":"曲カタログを読み込み中です…";
 const readyKeys=readySet();
 let list=[];
 if(type==="ready"){
  list=q?readySongs.filter(x=>norm(x.title+x.artist).includes(norm(q))):readySongs;
  list=list.slice(0,60).map(x=>({...x,source:"ready"}));
 }else if(q){
  list=lookupCatalog(q,type,60).map(i=>{
   const [title,artist,year]=catalog.rows[i];
   return {title,artist,year,source:readyKeys.has(readyKey(title,artist))?"ready":"catalog"};
  });
  const matching=readySongs.filter(x=>norm(type==="title"?x.title:x.artist).includes(norm(q)));
  const seen=new Set(list.map(x=>readyKey(x.title,x.artist)));
  for(const s of matching)if(!seen.has(readyKey(s.title,s.artist)))list.unshift({...s,source:"ready"});
  list=list.slice(0,60);
 }
 $("#searchResults").innerHTML = list.length ? list.map((s,i)=>displayRow(s,
  '<button class="button primary" data-select-index="'+i+'" type="button">リクエストに選ぶ</button>',s.source==="ready"?"ready":"catalog")).join("")
  : '<div class="empty">'+(q||type==="ready"?"検索に一致する曲はありません。曲名とアーティストを直接入力することもできます。":"曲名またはアーティストを入力すると候補を表示します。")+'</div>';
 window.__searchResults=list;
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
  const actions=r.status==="new"?'<button class="button primary" data-do="waiting" data-id="'+esc(r.id)+'">待機曲に追加</button>'
    :r.status==="waiting"?'<button class="button" data-do="new" data-id="'+esc(r.id)+'">受付に戻す</button>'
    :'<button class="button" data-do="new" data-id="'+esc(r.id)+'">再受付</button>';
  return requestItem(r,actions+'<button class="button warning" data-do="delete" data-id="'+esc(r.id)+'">削除</button>');
 }).join(""):'<div class="empty">該当するリクエストはありません。</div>';
}
function render(){
 $("#streamerName").textContent=state.name;
 document.title=state.name+"のデンモク";
 renderSearch();renderQueue();renderAdminRequests();
 $("#catalogStatus").textContent=catalog.ready?"楽曲検索利用可":catalog.error?"カタログ読込失敗":"曲カタログ読込中";
 if(!preview){$("#listenerView").hidden=adminMode;$("#adminView").hidden=!adminMode;}
 $("#toListener").hidden=!adminMode || preview;
 document.body.classList.toggle("admin-active",adminMode&&!preview);
}
function changeRequestStatus(id,status){
 const r=state.requests.find(x=>x.id===id);if(!r)return;
 r.status=status;
 if(status==="waiting"){r.waitOrder=Math.max(Date.now(),...state.requests.map(x=>x.waitOrder||0))+1;}
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
  try{localStorage.setItem("ken-nickname",nickname)}catch(_){}
  toast("端末内プレビューに受付登録しました（他の端末には共有されません）");
  render();
 }finally{isSending=false;}
}
function adminAction(event){
 const b=event.target.closest("[data-do]");
 if(!b)return;
 const id=b.dataset.id,act=b.dataset.do;
 if(act==="waiting"||act==="new"||act==="done"){changeRequestStatus(id,act);return;}
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
 let timer=null;
 let startX=0,startY=0;
 const cancelHold=()=>{if(timer!==null){clearTimeout(timer);timer=null;}};
 const openPassword=()=>{
  cancelHold();
  if(preview||adminMode||dialog.open)return;
  password.value="";
  error.hidden=true;
  dialog.showModal();
  password.focus();
 };
 const startHold=()=>{
  if(preview||adminMode||dialog.open)return;
  cancelHold();
  timer=setTimeout(()=>{timer=null;openPassword();},900);
 };
 trigger.addEventListener("pointerdown",e=>{
  if(e.button!==0)return;
  startX=e.clientX;startY=e.clientY;
  startHold();
 });
 trigger.addEventListener("pointermove",e=>{
  if(Math.hypot(e.clientX-startX,e.clientY-startY)>12)cancelHold();
 });
 ["pointerup","pointercancel","pointerleave","lostpointercapture"].forEach(eventName=>
  trigger.addEventListener(eventName,cancelHold)
 );
 trigger.addEventListener("contextmenu",e=>e.preventDefault());
 trigger.addEventListener("click",e=>e.preventDefault());
 trigger.addEventListener("keydown",e=>{
  if((e.key==="Enter"||e.key===" ")&&!e.repeat){e.preventDefault();startHold();}
 });
 trigger.addEventListener("keyup",e=>{
  if(e.key==="Enter"||e.key===" "){e.preventDefault();cancelHold();}
 });
 window.addEventListener("blur",cancelHold);
 document.addEventListener("visibilitychange",()=>{if(document.hidden)cancelHold();});
 $("#adminPasswordCancel").addEventListener("click",()=>dialog.close());
 $("#adminPasswordForm").addEventListener("submit",e=>{
  e.preventDefault();
  if(password.value!==UI_ADMIN_PASSWORD){
   error.hidden=false;
   password.value="";
   password.focus();
   return;
  }
  dialog.close();
  adminMode=true;
  render();
  $("#toListener").focus();
 });
 dialog.addEventListener("close",()=>{
  password.value="";
  error.hidden=true;
  cancelHold();
 });
}

function attach(){
 document.querySelectorAll("[data-search-mode]").forEach(b=>b.addEventListener("click",()=>{
  searchMode=b.dataset.searchMode;
  document.querySelectorAll("[data-search-mode]").forEach(x=>x.classList.toggle("active",x===b));
  $("#searchInput").placeholder=searchMode==="title"?"曲名で検索":searchMode==="artist"?"アーティスト名で検索":"歌える曲リストを検索";
  renderSearch();
 }));
 $("#searchInput").addEventListener("input",renderSearch);
 $("#searchResults").addEventListener("click",e=>{
  const btn=e.target.closest("[data-select-index]");if(!btn)return;
  const s=window.__searchResults?.[Number(btn.dataset.selectIndex)];
  if(s)selectSong(s.title,s.artist,s.source);
 });
 $("#requestForm").addEventListener("submit",requestSubmit);
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
