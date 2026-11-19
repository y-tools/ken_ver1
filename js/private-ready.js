/* Owner / Ken singable-song browser. Renders only the existing shared ready songs. */
(()=>{
 "use strict";
 const $=selector=>document.querySelector(selector);
 const norm=value=>String(value??"").normalize("NFKC").toLowerCase()
  .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
  .replace(/[\s・ー‐-]/g,"");
 const key=s=>norm(s.title)+"|"+norm(s.artist);
 const kanaRows=["あいうえお","かきくけこ","さしすせそ","たちつてと","なにぬねの",
  "はひふへほ","まみむめも","やゆよ","らりるれろ","わをん"];
 const variant={"が":"か","ぎ":"き","ぐ":"く","げ":"け","ご":"こ",
  "ざ":"さ","じ":"し","ず":"す","ぜ":"せ","ぞ":"そ",
  "だ":"た","ぢ":"ち","づ":"つ","で":"て","ど":"と",
  "ば":"は","び":"ひ","ぶ":"ふ","べ":"へ","ぼ":"ほ",
  "ぱ":"は","ぴ":"ひ","ぷ":"ふ","ぺ":"へ","ぽ":"ほ","ゔ":"う",
  "ぁ":"あ","ぃ":"い","ぅ":"う","ぇ":"え","ぉ":"お",
  "っ":"つ","ゃ":"や","ゅ":"ゆ","ょ":"よ","ゎ":"わ"};
 let rows=[],selectedKana="",initialized=false;
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
  return variant[first]||first;
 };
 const empty=text=>{
  const el=document.createElement("div");el.className="empty";el.setAttribute("role","listitem");el.textContent=text;
  return el;
 };
 function draw(){
  const list=$("#privateReadyList"),count=$("#privateReadyCount");
  if(!list||!count)return;
  const title=norm($("#privateReadyTitleQuery").value);
  const artist=norm($("#privateReadyArtistQuery").value);
  const target=$("#privateReadyKanaTarget").value==="artist"?"artist":"title";
  const results=rows.filter(song=>
   (!title||values(song,"title").some(x=>norm(x).includes(title)))&&
   (!artist||values(song,"artist").some(x=>norm(x).includes(artist)))&&
   (!selectedKana||values(song,target).some(x=>kanaKey(x)===selectedKana))
  );
  count.textContent=rows.length.toLocaleString("ja-JP")+" 曲";
  $("#privateReadyResultCount").textContent="表示 "+results.length.toLocaleString("ja-JP")+
   " / 登録 "+rows.length.toLocaleString("ja-JP")+" 曲";
  const fragment=document.createDocumentFragment();
  if(!results.length)fragment.appendChild(empty(rows.length?
   "条件に一致する歌える曲はありません。":"歌える曲はまだ登録されていません。"));
  for(const song of results){
   const item=document.createElement("div");item.className="private-ready-song";item.setAttribute("role","listitem");
   const titleNode=document.createElement("strong");titleNode.className="private-ready-song-title";
   titleNode.textContent=song.title;
   const artistNode=document.createElement("span");artistNode.className="private-ready-song-artist";
   artistNode.textContent=song.artist;
   item.append(titleNode,artistNode);fragment.appendChild(item);
  }
  list.replaceChildren(fragment);
  for(const b of $("#privateReadyKanaGrid").querySelectorAll("[data-private-kana]")){
   const pressed=b.dataset.privateKana===selectedKana;
   b.classList.toggle("is-active",pressed);
   b.setAttribute("aria-pressed",String(pressed));
  }
 }
 function init(){
  if(initialized||!$("#privateReadyKanaGrid"))return;
  initialized=true;
  const grid=$("#privateReadyKanaGrid"),frag=document.createDocumentFragment();
  for(const char of kanaRows.join("")){
   const b=document.createElement("button");
   b.type="button";b.className="private-ready-kana-button";
   b.dataset.privateKana=char;b.textContent=char;
   b.setAttribute("aria-pressed","false");b.setAttribute("aria-label",char+"で絞り込む");
   frag.appendChild(b);
  }
  grid.replaceChildren(frag);
  grid.addEventListener("click",event=>{
   const b=event.target.closest("[data-private-kana]");if(!b)return;
   selectedKana=selectedKana===b.dataset.privateKana?"":b.dataset.privateKana;
   draw();
  });
  for(const id of ["privateReadyTitleQuery","privateReadyArtistQuery"]){
   $("#"+id).addEventListener("input",draw);
  }
  $("#privateReadyKanaTarget").addEventListener("change",draw);
  $("#privateReadyKanaClear").addEventListener("click",()=>{selectedKana="";draw();});
  $("#privateReadyReset").addEventListener("click",()=>{
   $("#privateReadyTitleQuery").value="";$("#privateReadyArtistQuery").value="";
   $("#privateReadyKanaTarget").value="title";selectedKana="";draw();
  });
 }
 function render(songs){
  init();
  const unique=new Map();
  for(const song of Array.isArray(songs)?songs:[]){
   if(song?.status!=="ready"||!song.title||!song.artist)continue;
   const k=key(song);if(!unique.has(k))unique.set(k,song);
  }
  rows=[...unique.values()].sort((a,b)=>a.title.localeCompare(b.title,"ja")||
   a.artist.localeCompare(b.artist,"ja"));
  draw();
 }
 function clear(){rows=[];}
 window.KEN_READY_BROWSER=Object.freeze({init,render,clear});
})();
