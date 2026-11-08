(()=>{
"use strict";
const $=s=>document.querySelector(s);
const base=String(window.KEN_CONFIG?.apiBaseUrl||"").replace(/\/+$/,"");
let token="",artist=null,song=null,offset=0,total=0,artistAliases=[],songAliases=[];
const labels={hiragana:"ひらがな",katakana:"カタカナ",romaji:"ローマ字",english:"正式英語表記"};
if(!/^https:\/\/[\w.-]+$/i.test(base)){$("#feedback").textContent="HTTPS APIを設定してください";return;}
function say(v,bad=false){$("#feedback").textContent=v;$("#feedback").classList.toggle("error",bad);}
async function call(path,body){
 const headers={Accept:"application/json"};
 if(body)headers["Content-Type"]="application/json";
 if(token)headers.Authorization="Bearer "+token;
 let res;
 try{res=await fetch(base+path,{method:body?"POST":"GET",headers,body:body?JSON.stringify(body):undefined,credentials:"omit",cache:"no-store"});}
 catch(e){throw Error("VPS APIに接続できません");}
 const data=await res.json().catch(()=>({}));
 if(!res.ok){if(res.status===401&&token){token="";logged(false);}throw Error(typeof data.detail==="string"?data.detail:"APIエラー: "+res.status);}
 return data;
}
const task=fn=>Promise.resolve().then(fn).catch(e=>say(e.message,true));
function logged(v){
 $("#loginPanel").hidden=v;$("#editorPanel").hidden=!v;$("#logout").hidden=!v;
 if(!v){
  $("#artistPanel").hidden=true;$("#songListPanel").hidden=true;$("#songPanel").hidden=true;$("#adminSecret").value="";
  $("#totalArtists").textContent="—";$("#totalSongs").textContent="—";$("#statsNotice").textContent="ログイン後にデータベースから取得します";$("#researchSummary").textContent="ログイン後に調査状況を読み込みます";$("#researchCandidates").replaceChildren();
 }
}
async function refreshStats(){
 $("#statsNotice").textContent="登録件数を取得しています…";
 try{
  const stats=await call("/api/admin/stats");
  if(!Number.isSafeInteger(stats.artists)||stats.artists<0||!Number.isSafeInteger(stats.songs)||stats.songs<0)
   throw Error("データベースの登録件数を取得できませんでした");
  $("#totalArtists").textContent=stats.artists.toLocaleString("ja-JP");
  $("#totalSongs").textContent=stats.songs.toLocaleString("ja-JP");
  $("#statsNotice").textContent="VPSデータベースの現在の登録件数";
 }catch(e){
  $("#totalArtists").textContent="—";$("#totalSongs").textContent="—";
  $("#statsNotice").textContent="件数を取得できませんでした";
  throw e;
 }
}
async function refreshResearch(){
 const lane=$("#researchLane").value;
 const panel=$("#researchCandidates");panel.replaceChildren();
 $("#researchSummary").textContent="調査状況を読み込み中…";
 try{
  const [overview,candidates]=await Promise.all([
   call("/api/admin/research/overview"),
   call("/api/admin/research/candidates?lane="+encodeURIComponent(lane))
  ]);
  const fmt=items=>["candidate","review","verified","registered","rejected"]
   .map(k=>k+":"+(items?.[k]||0)).join(" / ");
  $("#researchSummary").textContent="アーティスト "+fmt(overview.artists)
   +"\n楽曲 "+fmt(overview.songs)
   +"\n直近: "+(overview.recentRuns?.[0]?.status||"実行前");
  const rows=Array.isArray(candidates.items)?candidates.items:[];
  if(!rows.length){panel.textContent="候補はまだありません";return;}
  for(const item of rows){
   const row=document.createElement("div");row.className="research-entry";
   const title=document.createElement("strong");title.textContent=item.title||"(名称未設定)";
   const meta=document.createElement("small");meta.textContent=item.status+
    (item.review_reason?" / "+item.review_reason:"");
   row.append(title,meta);
   if(typeof item.source_url==="string"){
    try{
     const url=new URL(item.source_url);
     if(url.protocol==="https:"&&url.hostname==="musicbrainz.org"){
      const a=document.createElement("a");a.href=url.href;a.textContent="出典";
      a.rel="noopener noreferrer";a.target="_blank";row.append(a);
     }
    }catch{}
   }
   panel.append(row);
  }
 }catch(err){
  $("#researchSummary").textContent="調査状況を取得できませんでした";
  throw err;
 }
}
$("#refreshResearch").addEventListener("click",()=>task(refreshResearch));
$("#researchLane").addEventListener("change",()=>task(refreshResearch));

$("#loginForm").addEventListener("submit",e=>{e.preventDefault();task(async()=>{
 const data=await call("/api/admin/login",{password:$("#adminSecret").value});
 token=data.token;logged(true);$("#adminSecret").value="";say("ログイン成功。アーティストを検索してください");$("#artistSearch").focus();await refreshStats();await refreshResearch().catch(e=>say("調査キューの読み込みに失敗: "+e.message,true));
})});
$("#logout").addEventListener("click",()=>task(async()=>{if(token)await call("/api/admin/logout",{}).catch(()=>{});token="";logged(false);say("ログアウトしました");}));
$("#artistSearchForm").addEventListener("submit",e=>{e.preventDefault();task(searchArtists);});
async function searchArtists(){
 const q=$("#artistSearch").value.trim();if(q.length<2)throw Error("2文字以上入力してください");
 const data=await call("/api/admin/artists?q="+encodeURIComponent(q));
 const target=$("#artistResults");target.replaceChildren();
 if(!data.items.length){target.textContent="該当するアーティストがありません";return;}
 for(const item of data.items){
  const b=document.createElement("button");b.type="button";b.textContent=item.name;
  b.addEventListener("click",()=>task(()=>loadArtist(item.id,0)));
  target.append(b);
 }
}
function makeAliasList(side){
 const list=side==="artist"?artistAliases:songAliases;
 const panel=$(side==="artist"?"#artistAliases":"#songAliases");panel.replaceChildren();
 if(!list.length){panel.textContent="まだ登録されていません";return;}
 const wrapper=document.createElement("div");wrapper.className="aliases";
 for(const v of list){
  const row=document.createElement("div");row.className="alias-entry";
  const left=document.createElement("div");
  const name=document.createElement("strong");name.textContent=(labels[v.kind]||v.kind)+": "+v.value;
  const meta=document.createElement("small");meta.textContent=v.verification==="estimated"?"推定読み":v.verification==="human_confirmed"?"管理者確認":"出典確認";
  left.append(name,meta);
  const edit=document.createElement("button");edit.type="button";edit.className="secondary";edit.textContent="編集";
  edit.addEventListener("click",()=>{
   const form=$(side==="artist"?"#artistAliasForm":"#songAliasForm");
   form.elements.oldId.value=v.id;form.elements.kind.value=v.kind;
   form.elements.value.value=v.value;form.elements.sourceUrl.value=v.sourceUrl||"";
   form.scrollIntoView({behavior:"smooth",block:"nearest"});form.elements.value.focus();
  });
  row.append(left,edit);wrapper.append(row);
 }
 panel.append(wrapper);
}
function showSongList(rows){
 const target=$("#songList");target.replaceChildren();
 if(!rows.length){target.textContent="登録曲がありません";return;}
 for(const item of rows){
  const b=document.createElement("button");b.type="button";
  const name=document.createElement("strong");name.textContent=item.title;
  const date=document.createElement("small");date.textContent=item.releaseYear?[item.releaseYear,item.releaseMonth?String(item.releaseMonth).padStart(2,"0"):null,item.releaseDay?String(item.releaseDay).padStart(2,"0"):null].filter(Boolean).join("-"):"発売日未確認";
  b.append(name,date);b.addEventListener("click",()=>task(()=>loadSong(item.id)));target.append(b);
 }
}
async function loadArtist(id,page=0){
 const data=await call("/api/admin/artists/"+id+"?offset="+page+"&limit=50");
 artist=data.artist;artistAliases=data.aliases;offset=page;total=data.total;
 song=null;$("#songPanel").hidden=true;$("#artistPanel").hidden=false;$("#songListPanel").hidden=false;
 $("#artistName").value=artist.name;$("#artistIdLabel").textContent="ID "+artist.id;
 $("#artistLastResearchedOn").value=artist.lastResearchedOn||"";
 $("#artistLastResearchedOn").max=new Intl.DateTimeFormat("en-CA",
  {timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
 makeAliasList("artist");showSongList(data.songs);
 $("#songsCount").textContent=total.toLocaleString("ja-JP")+"曲";
 $("#prevSongs").disabled=page===0;$("#nextSongs").disabled=page+50>=total;
 $("#pagePosition").textContent=(total?String(page+1)+"〜"+String(Math.min(page+50,total)):"0")+" / "+total;
 say(artist.name+" の登録情報を表示しました");
}
async function loadSong(id){
 const data=await call("/api/admin/songs/"+id);
 song=data.song;songAliases=data.aliases;$("#songPanel").hidden=false;
 $("#songIdLabel").textContent="ID "+song.id;
 const f=$("#songForm").elements;
 for(const key of ["title","releasePrecision","releaseYear","releaseMonth","releaseDay"])f[key].value=song[key]??"";
 f.releaseSourceUrl.value="";updateDateFields();makeAliasList("song");
 $("#songHistory").open=false;$("#songPanel").scrollIntoView({behavior:"smooth",block:"start"});say(song.title+" を編集中");
}
$("#prevSongs").addEventListener("click",()=>{if(artist&&offset>0)task(()=>loadArtist(artist.id,Math.max(0,offset-50)));});
$("#nextSongs").addEventListener("click",()=>{if(artist&&offset+50<total)task(()=>loadArtist(artist.id,offset+50));});
$("#artistForm").addEventListener("submit",e=>{e.preventDefault();task(async()=>{
 if(!artist)return;const value=$("#artistName").value.trim();
 const result=await call("/api/admin/artists/"+artist.id,{name:value,version:artist.version});
 await loadArtist(result.artist.id,offset);say("アーティスト名を更新しました");
})});
$("#artistResearchForm").addEventListener("submit",e=>{e.preventDefault();task(async()=>{
 if(!artist)return;
 const value=$("#artistLastResearchedOn").value||null;
 const result=await call("/api/admin/artists/"+artist.id+"/research",
  {version:artist.version,lastResearchedOn:value});
 await loadArtist(result.artist.id,offset);
 say("最終調査日を保存しました");
})});
function updateDateFields(){
 const f=$("#songForm").elements,kind=f.releasePrecision.value;
 for(const [key,required] of [["releaseYear",kind!=="unknown"],["releaseMonth",kind==="month"||kind==="day"],["releaseDay",kind==="day"]]){
  f[key].disabled=!required;if(!required)f[key].value="";
 }
}
$("#songForm").elements.releasePrecision.addEventListener("change",updateDateFields);
$("#songForm").addEventListener("submit",e=>{e.preventDefault();task(async()=>{
 if(!song)return;
 const f=e.currentTarget.elements,kind=f.releasePrecision.value;
 const number=key=>f[key].value.trim()?Number(f[key].value):null;
 const body={title:f.title.value.trim(),version:song.version,releasePrecision:kind,
  releaseYear:kind==="unknown"?null:number("releaseYear"),
  releaseMonth:kind==="month"||kind==="day"?number("releaseMonth"):null,
  releaseDay:kind==="day"?number("releaseDay"):null,releaseSourceUrl:f.releaseSourceUrl.value.trim()||null};
 const id=song.id;await call("/api/admin/songs/"+id,body);await loadArtist(artist.id,offset);await loadSong(id);
 say("楽曲情報を保存しました");
})});
for(const side of ["artist","song"]){
 const f=$(side==="artist"?"#artistAliasForm":"#songAliasForm");
 f.addEventListener("submit",e=>{e.preventDefault();task(async()=>{
  const target=side==="artist"?artist:song;if(!target)return;
  const el=f.elements;
  await call("/api/admin/aliases",{side,entityId:target.id,kind:el.kind.value,
   value:el.value.value.trim(),sourceUrl:el.sourceUrl.value.trim()||null,
   oldId:el.oldId.value?Number(el.oldId.value):null});
  f.reset();
  if(side==="artist")await loadArtist(artist.id,offset);else await loadSong(song.id);
  say("読み・表記を保存しました");
 })});
}
$("#songHistory").addEventListener("toggle",()=>{if(!$("#songHistory").open||!song)return;task(async()=>{
 const data=await call("/api/admin/audit?entityType=song&entityId="+song.id);
 const target=$("#auditList");target.replaceChildren();
 if(!data.items.length){target.textContent="変更履歴なし";return;}
 for(const row of data.items){
  const p=document.createElement("p");p.textContent=(row.changedAt||"")+" / "+row.action+"\n前: "+JSON.stringify(row.before)+"\n後: "+JSON.stringify(row.after);
  target.append(p);
 }
})});
logged(false);
})();
