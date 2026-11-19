/* Owner / Ken singable-song browser. Database search is read-only until the user chooses Add. */
(()=>{
 "use strict";
 const $=selector=>document.querySelector(selector);
 const norm=value=>String(value??"").normalize("NFKC").toLowerCase()
  .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
  .replace(/[\s・ー‐-]/g,"");
 const key=s=>norm(s.title)+"|"+norm(s.artist);
 const kanaRows=["あいうえお","かきくけこ","さしすせそ","たちつてと","なにぬねの",
  "はひふへほ","まみむめも","やゆよ","らりるれろ","わをん"];
 const variants={"が":"か","ぎ":"き","ぐ":"く","げ":"け","ご":"こ",
  "ざ":"さ","じ":"し","ず":"す","ぜ":"せ","ぞ":"そ",
  "だ":"た","ぢ":"ち","づ":"つ","で":"て","ど":"と",
  "ば":"は","び":"ひ","ぶ":"ふ","べ":"へ","ぼ":"ほ",
  "ぱ":"は","ぴ":"ひ","ぷ":"ふ","ぺ":"へ","ぽ":"ほ","ゔ":"う",
  "ぁ":"あ","ぃ":"い","ぅ":"う","ぇ":"え","ぉ":"お",
  "っ":"つ","ゃ":"や","ゅ":"ゆ","ょ":"よ","ゎ":"わ"};
 const MAX_DB_RESULTS=80;
 let allSongs=[],ready=[],databaseResults=[],selectedKana="",mode="filter";
 let initialized=false,dbSeq=0,dbTimer=null,dbState="start",adding=false;
 function permitted(){
  const shared=window.KEN_SHARED;
  const id=String(shared?.profile?.()?.login_id||"").toLowerCase();
  return Boolean(shared?.isAdmin?.()&&(shared?.isOwner?.()||id==="kenmorley05280602"));
 }
 const values=(song,side)=>{
  const readings=song.readings?.[side]||{};
  const extras=side==="title"?
   [song.titleReading,song.titleKana,song.titleHiragana]:
   [song.artistReading,song.artistKana,song.artistHiragana];
  return [song[side],...extras,readings.hiragana,readings.katakana,readings.romaji,readings.english]
   .filter(value=>typeof value==="string"&&value.trim());
 };
 const kanaKey=value=>{
  const first=norm(value).replace(/^[^ぁ-ゖa-z0-9]+/g,"").charAt(0);
  return variants[first]||first;
 };
 const empty=text=>{
  const el=document.createElement("div");el.className="empty";
  el.setAttribute("role","listitem");el.textContent=text;
  return el;
 };
 function renderFilter(){
  const list=$("#privateReadyList"),count=$("#privateReadyCount");
  if(!list||!count)return;
  const title=norm($("#privateReadyTitleQuery").value);
  const artist=norm($("#privateReadyArtistQuery").value);
  const target=$("#privateReadyKanaTarget").value==="artist"?"artist":"title";
  const results=ready.filter(song=>
   (!title||values(song,"title").some(x=>norm(x).includes(title)))&&
   (!artist||values(song,"artist").some(x=>norm(x).includes(artist)))&&
   (!selectedKana||values(song,target).some(x=>kanaKey(x)===selectedKana)));
  count.textContent=ready.length.toLocaleString("ja-JP")+" 曲";
  $("#privateReadyResultCount").textContent="表示 "+results.length.toLocaleString("ja-JP")+
   " / 登録 "+ready.length.toLocaleString("ja-JP")+" 曲";
  const fragment=document.createDocumentFragment();
  if(!results.length)fragment.appendChild(empty(ready.length?
   "条件に一致する歌える曲はありません。":"歌える曲はまだ登録されていません。"));
  for(const song of results){
   const item=document.createElement("div");item.className="private-ready-song";
   item.setAttribute("role","listitem");
   const titleNode=document.createElement("strong");titleNode.className="private-ready-song-title";
   titleNode.textContent=song.title;
   const artistNode=document.createElement("span");artistNode.className="private-ready-song-artist";
   artistNode.textContent=song.artist;
   item.append(titleNode,artistNode);fragment.appendChild(item);
  }
  list.replaceChildren(fragment);
  for(const b of $("#privateReadyKanaGrid").querySelectorAll("[data-private-kana]")){
   const active=b.dataset.privateKana===selectedKana;
   b.classList.toggle("is-active",active);
   b.setAttribute("aria-pressed",String(active));
  }
 }
 function renderDatabase(){
  if(!$("#privateReadyList"))return;
  const readyKeys=new Set(ready.map(key));
  const list=$("#privateReadyList"),fragment=document.createDocumentFragment();
  $("#privateReadyCount").textContent=ready.length.toLocaleString("ja-JP")+" 曲";
  $("#privateReadyResultCount").textContent=
   dbState==="loading"?"データベースを検索中…":
   dbState==="start"?"曲名かアーティスト名で検索":
   "検索結果 "+databaseResults.length+" 曲";
  if(dbState==="start")fragment.appendChild(empty("曲名かアーティスト名を2文字以上入力してください。"));
  else if(dbState==="loading")fragment.appendChild(empty("データベースを検索しています…"));
  else if(!databaseResults.length)fragment.appendChild(empty("一致する楽曲がありません。検索条件を変えてください。"));
  for(const song of databaseResults){
   const item=document.createElement("div");
   item.className="private-ready-song private-ready-db-song";item.setAttribute("role","listitem");
   const info=document.createElement("div");info.className="private-ready-db-song-info";
   const title=document.createElement("strong");title.className="private-ready-song-title";title.textContent=song.title;
   const artist=document.createElement("span");artist.className="private-ready-song-artist";artist.textContent=song.artist;
   info.append(title,artist);
   const b=document.createElement("button");b.type="button";b.className="button primary private-ready-add-button";
   b.dataset.readyAdd=key(song);
   const exists=readyKeys.has(key(song));
   b.textContent=exists?"登録済み":"歌える曲に追加";
   b.disabled=exists||adding;
   item.append(info,b);fragment.appendChild(item);
  }
  list.replaceChildren(fragment);
 }
 function draw(){if(!permitted())return; if(mode==="add")renderDatabase();else renderFilter();}
 function selectMode(next){
  if(next!=="add"&&next!=="filter")return;
  mode=next;
  const isAdd=mode==="add";
  $("#privateReadyDatabaseControls").hidden=!isAdd;
  $("#privateReadyFilterControls").hidden=isAdd;
  $("#privateReadyModeAdd").classList.toggle("is-active",isAdd);
  $("#privateReadyModeFilter").classList.toggle("is-active",!isAdd);
  $("#privateReadyModeAdd").setAttribute("aria-selected",String(isAdd));
  $("#privateReadyModeFilter").setAttribute("aria-selected",String(!isAdd));
  $("#privateReadySearchHeading").textContent=isAdd?"データベースから曲を追加":"歌える曲を絞り込む";
  $("#privateReadyListHeading").textContent=isAdd?"楽曲データベースの検索結果":"現在の歌える曲";
  $("#privateReadyActionFeedback").textContent="";
  if(isAdd&&dbState==="start"&&($("#privateReadyDbTitleQuery").value||$("#privateReadyDbArtistQuery").value))
   void databaseSearch();
  draw();
 }
 async function databaseSearch(){
  if(!permitted()||!window.KEN_VPS_SEARCH?.search)return;
  const titleQ=$("#privateReadyDbTitleQuery").value.trim();
  const artistQ=$("#privateReadyDbArtistQuery").value.trim();
  const requests=[];
  if(Array.from(titleQ).length>=2)requests.push({q:titleQ,side:"title"});
  if(Array.from(artistQ).length>=2)requests.push({q:artistQ,side:"artist"});
  const seq=++dbSeq;
  if(!requests.length){
   databaseResults=[];dbState="start";
   $("#privateReadyDbStatus").textContent="曲名かアーティスト名を2文字以上入力してください。";
   draw();return;
  }
  dbState="loading";
  $("#privateReadyDbStatus").textContent="検索しています…";draw();
  const responses=await Promise.allSettled(requests.map(async request=>
   window.KEN_VPS_SEARCH.search(request.q,request.side,50)));
  if(seq!==dbSeq||mode!=="add")return;
  const found=new Map(),failed=responses.filter(r=>r.status==="rejected");
  for(const response of responses){
   if(response.status!=="fulfilled")continue;
   for(const song of response.value?.items||[]){
    if(!song?.title||!song?.artist)continue;
    const k=key(song);
    if(!found.has(k))found.set(k,song);
    else if(!found.get(k).readings&&song.readings)found.set(k,song);
   }
  }
  const titleTerm=norm(titleQ),artistTerm=norm(artistQ);
  // The VPS API searches titles and artists separately; both entered fields are AND filters.
  // Do not treat a truncated/failed request as evidence that a song does not exist.
  databaseResults=[...found.values()].filter(song=>
   (!titleTerm||values(song,"title").some(x=>norm(x).includes(titleTerm)))&&
   (!artistTerm||values(song,"artist").some(x=>norm(x).includes(artistTerm))))
   .slice(0,MAX_DB_RESULTS);
  dbState="results";
  $("#privateReadyDbStatus").textContent=failed.length===responses.length?
   "データベースに接続できません。再検索してください。":
   "データベース内の候補 "+databaseResults.length+" 曲"+(failed.length?"（一部の検索に失敗しました）":"")+"。検索は最大50件／項目です。";
  draw();
 }
 function scheduleDatabaseSearch(){
  clearTimeout(dbTimer);
  dbTimer=setTimeout(()=>void databaseSearch(),300);
 }
 async function addReady(event){
  const btn=event.target.closest("[data-ready-add]");if(!btn||adding||mode!=="add"||!permitted())return;
  const song=databaseResults.find(item=>key(item)===btn.dataset.readyAdd);
  if(!song)return;
  const existing=allSongs.find(s=>key(s)===key(song));
  if(existing?.status==="ready"){draw();return;}
  const shared=window.KEN_SHARED;
  if(!shared?.action)return;
  const releaseYear=String(song.releaseDate||"").match(/^\d{4}/)?.[0]||null;
  const payload={id:existing?.id||null,title:song.title,artist:song.artist,status:"ready",
   year:existing?.year??releaseYear,memo:existing?.memo||""};
  adding=true;
  const feedback=$("#privateReadyActionFeedback");feedback.textContent="歌える曲に追加しています…";
  draw();
  try{
   await shared.action("song_upsert",payload);
   feedback.textContent="「"+song.artist+" / "+song.title+"」を歌える曲に追加しました。";
   // Shared action refreshes the snapshot. The subscriber redraws both modes.
  }catch(error){
   feedback.textContent="追加に失敗しました："+String(error.message||error).slice(0,110);
  }finally{adding=false;draw();}
 }
 function init(){
  if(initialized||!$("#privateReadyKanaGrid"))return;
  initialized=true;
  const grid=$("#privateReadyKanaGrid"),frag=document.createDocumentFragment();
  for(const char of kanaRows.join("")){
   const b=document.createElement("button");b.type="button";b.className="private-ready-kana-button";
   b.dataset.privateKana=char;b.textContent=char;
   b.setAttribute("aria-pressed","false");b.setAttribute("aria-label",char+"で絞り込む");
   frag.appendChild(b);
  }
  grid.replaceChildren(frag);
  grid.addEventListener("click",event=>{
   const b=event.target.closest("[data-private-kana]");if(!b)return;
   selectedKana=selectedKana===b.dataset.privateKana?"":b.dataset.privateKana;draw();
  });
  for(const id of ["privateReadyTitleQuery","privateReadyArtistQuery"])
   $("#"+id).addEventListener("input",draw);
  $("#privateReadyKanaTarget").addEventListener("change",draw);
  $("#privateReadyKanaClear").addEventListener("click",()=>{selectedKana="";draw();});
  $("#privateReadyReset").addEventListener("click",()=>{
   $("#privateReadyTitleQuery").value="";$("#privateReadyArtistQuery").value="";
   $("#privateReadyKanaTarget").value="title";selectedKana="";draw();
  });
  $("#privateReadyModeAdd").addEventListener("click",()=>selectMode("add"));
  $("#privateReadyModeFilter").addEventListener("click",()=>selectMode("filter"));
  $("#privateReadyDbTitleQuery").addEventListener("input",scheduleDatabaseSearch);
  $("#privateReadyDbArtistQuery").addEventListener("input",scheduleDatabaseSearch);
  $("#privateReadyDbForm").addEventListener("submit",event=>{
   event.preventDefault();clearTimeout(dbTimer);void databaseSearch();
  });
  $("#privateReadyList").addEventListener("click",event=>void addReady(event));
  selectMode("filter");
 }
 function render(songs){
  init();
  const unique=new Map();
  allSongs=Array.isArray(songs)?songs:[];
  for(const song of allSongs){
   if(song?.status!=="ready"||!song.title||!song.artist)continue;
   const k=key(song);if(!unique.has(k))unique.set(k,song);
  }
  ready=[...unique.values()].sort((a,b)=>a.title.localeCompare(b.title,"ja")||
   a.artist.localeCompare(b.artist,"ja"));
  draw();
 }
 function clear(){allSongs=[];ready=[];databaseResults=[];dbState="start";dbSeq++;clearTimeout(dbTimer);}
 window.KEN_READY_BROWSER=Object.freeze({init,render,clear});
})();
