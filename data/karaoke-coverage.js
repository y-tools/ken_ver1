/* Ken Denmoku: manual, source-linked DAM/JOYSOUND verification (no false coverage claims). */
(()=>{
"use strict";
const KEY="ken-denmoku-karaoke-v1";
const $=selector=>document.querySelector(selector);
const escapeHtml=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const normalize=value=>String(value??"").normalize("NFKC").toLowerCase()
 .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
 .replace(/[\s・ー‐-]/g,"");
const songKey=(title,artist)=>normalize(title)+"|"+normalize(artist);
const SOURCES=Object.freeze({
 dam:{title:"DAM",search:"https://www.clubdam.com/karaokesearch/"},
 joy:{title:"JOYSOUND",search:"https://www.joysound.com/web/search"}
});
const all={};
try{
 const stored=JSON.parse(localStorage.getItem(KEY)||"{}");
 if(stored&&typeof stored==="object"&&!Array.isArray(stored)){
  for(const [key,value] of Object.entries(stored)){
   if(value&&typeof value==="object"&&typeof value.title==="string"&&typeof value.artist==="string")
    all[key]=value;
  }
 }
}catch(error){console.warn("Karaoke verification data could not load",error);}
function save(){
 if(window.KEN_SHARED?.configured)return true; // Shared mode writes via authenticated RPC.
 try{localStorage.setItem(KEY,JSON.stringify(all));return true;}
 catch(e){alert("照合情報を保存できませんでした。容量を確認してください。");return false;}
}
function applyShared(records){
 if(!Array.isArray(records))return;
 for(const key of Object.keys(all))delete all[key];
 for(const row of records){
  if(row?.title&&row?.artist)all[songKey(row.title,row.artist)]=row;
 }
 refresh();
}
const lookup=(title,artist)=>all[songKey(title,artist)]||null;
const allowed=(url,provider)=>{
 if(!url)return "";
 try{
  const parsed=new URL(url);
  if(parsed.protocol!=="https:")return "";
  const host=parsed.hostname.toLowerCase();
  const ok=provider==="dam"
   ?(host==="clubdam.com"||host.endsWith(".clubdam.com"))
   :(host==="joysound.com"||host.endsWith(".joysound.com"));
  return ok?parsed.href:"";
 }catch(_){return "";}
};
function siteSearch(title,artist,provider){
 const host=provider==="dam"?"clubdam.com":"joysound.com";
 return "https://www.google.com/search?q="+encodeURIComponent("site:"+host+" "+title+" "+artist+" カラオケ");
}
function statusText(code){
 return code==="available"?"公式で配信確認済み":
  code==="searched"?"公式検索で見つからず":"未確認";
}
function render(song){
 const title=String(song?.title||""),artist=String(song?.artist||"");
 if(!title||!artist)return "";
 const saved=lookup(title,artist);
 const pieces=["dam","joy"].map(provider=>{
  const entry=saved?.[provider]||{};
  const status=entry.status==="available"?"available":entry.status==="searched"?"searched":"unknown";
  const className=status==="available"?"karaoke-status-live":status==="searched"?"karaoke-status-searched":"karaoke-status-unknown";
  const verified=status==="available"&&allowed(entry.url,provider);
  const number=entry.number?" / 曲番号："+escapeHtml(entry.number):"";
  const when=entry.checkedAt?" / 確認日："+escapeHtml(entry.checkedAt.slice(0,10)):"";
  const link=verified?'<a href="'+escapeHtml(allowed(entry.url,provider))+'" target="_blank" rel="noopener noreferrer">確認した公式曲ページ</a>':"";
  return '<div class="karaoke-provider-result"><strong>'+SOURCES[provider].title+'</strong>：'+
   '<span class="'+className+'">'+statusText(status)+'</span>'+number+when+
   '<div class="karaoke-provider-links"><a href="'+SOURCES[provider].search+'" target="_blank" rel="noopener noreferrer">公式曲検索</a>'+
   '<a href="'+escapeHtml(siteSearch(title,artist,provider))+'" target="_blank" rel="noopener noreferrer">曲名で公式サイト内検索</a>'+link+'</div></div>';
 }).join("");
 return '<details class="karaoke-coverage"><summary>DAM / JOYSOUND'+
  (saved?.dam?.status==="available"||saved?.joy?.status==="available"?"（確認記録あり）":"（収録未確認）")+
  '</summary><div class="karaoke-verification-note">機種により配信状況が異なります。収録未確認は未配信を意味しません。</div>'+
  pieces+
  (saved?.notes?'<p class="karaoke-verification-note">'+escapeHtml(saved.notes)+'</p>':"")+
  '<button type="button" class="button subtle" data-karaoke-edit="'+escapeHtml(title)+'" data-karaoke-artist="'+escapeHtml(artist)+'">この曲の確認情報を管理画面で編集</button>'+
  '</details>';
}
function updateLookupLinks(){
 const title=$("#karaokeTitle")?.value.trim()||"";
 const artist=$("#karaokeArtist")?.value.trim()||"";
 for(const p of ["dam","joy"]){
  const a=$("#karaoke"+(p==="dam"?"Dam":"Joy")+"Lookup");
  if(a)a.href=title&&artist?siteSearch(title,artist,p):SOURCES[p].search;
 }
}
function setForm(title,artist){
 $("#karaokeTitle").value=title;
 $("#karaokeArtist").value=artist;
 const row=lookup(title,artist)||{};
 const set=(provider,suffix)=>{
  const p=row[provider]||{};
  $("#karaoke"+suffix+"Status").value=["unknown","available","searched"].includes(p.status)?p.status:"unknown";
  $("#karaoke"+suffix+"Url").value=p.url||"";
  $("#karaoke"+suffix+"Number").value=p.number||"";
 };
 set("dam","Dam");set("joy","Joy");
 $("#karaokeNotes").value=row.notes||"";
 updateLookupLinks();
}
function updateCount(){
 const count=Object.keys(all).length;
 const verified=Object.values(all).filter(row=>row.dam?.status==="available"||row.joy?.status==="available").length;
 if($("#karaokeRecordCount"))
  $("#karaokeRecordCount").textContent="照合記録 "+count+"曲 / 配信確認記録あり "+verified+"曲"+(window.KEN_SHARED?.configured?"（全端末共通）":"（この端末のみ）");
}
function refresh(){
 updateCount();
 document.dispatchEvent(new Event("ken:karaoke-updated"));
}
function validateAndSave({title,artist,dam,joy,notes},{deferSave=false,checkedDates=null}={}){
 if(!title||!artist)throw Error("曲名・アーティストが必要です。");
 if(title.length>190||artist.length>150)throw Error("曲名またはアーティスト名が長すぎます。");
 const validate=(name,row)=>{
  const status=["unknown","available","searched"].includes(row.status)?row.status:"unknown";
  const url=String(row.url||"").trim();
  if(url&&!allowed(url,name))throw Error(SOURCES[name].title+"のURLはその公式サイト内のHTTPS URLを入力してください。");
  if(status==="available"&&!url)throw Error(SOURCES[name].title+"の配信確認には根拠となる公式曲ページURLが必要です。");
  if(status==="available"){
   const parsed=new URL(url);
   if((parsed.pathname==="/"||parsed.pathname==="/web/search"||parsed.pathname==="/karaokesearch/")&&!parsed.search)
    throw Error(SOURCES[name].title+"の配信確認には検索トップではなく曲の個別公式ページURLを指定してください。");
  }
  return {status,url:allowed(url,name),number:String(row.number||"").trim().slice(0,35),checkedAt:status==="unknown"?"":new Date().toISOString()};
 };
 const record={title:title.trim(),artist:artist.trim(),dam:validate("dam",dam),joy:validate("joy",joy),notes:String(notes||"").slice(0,400)};
 if(checkedDates){
  for(const provider of ["dam","joy"]){
   const given=checkedDates[provider]||"";
   if(record[provider].status!=="unknown"&&/^20\d{2}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)?$/.test(given))
    record[provider].checkedAt=given;
  }
 }
 const key=songKey(title,artist);
 if(record.dam.status==="unknown"&&record.joy.status==="unknown"&&!record.notes)
  delete all[key];
 else all[key]=record;
 if(!deferSave){
  if(window.KEN_SHARED?.configured){
   void window.KEN_SHARED.action("karaoke_upsert",{record}).then(()=>refresh())
    .catch(e=>{alert("共有保存に失敗しました: "+e.message);void window.KEN_SHARED.refresh(true);});
   refresh();
  }else{
   if(!save())throw Error("端末に保存できませんでした。");
   refresh();
  }
 }
}
function getFormRecord(){
 const get=suffix=>({
  status:$("#karaoke"+suffix+"Status").value,
  url:$("#karaoke"+suffix+"Url").value,
  number:$("#karaoke"+suffix+"Number").value
 });
 return {title:$("#karaokeTitle").value.trim(),artist:$("#karaokeArtist").value.trim(),
  dam:get("Dam"),joy:get("Joy"),notes:$("#karaokeNotes").value.trim()};
}
function exportCsv(){
 const cols=["title","artist","dam_status","dam_url","dam_number","dam_checked_at","joysound_status","joysound_url","joysound_number","joysound_checked_at","notes"];
 const quote=v=>'"'+String(v??"").replaceAll('"','""')+'"';
 const content=[cols.join(",")];
 for(const row of Object.values(all)){
  const d=row.dam||{},j=row.joy||{};
  content.push([row.title,row.artist,d.status,d.url,d.number,d.checkedAt,j.status,j.url,j.number,j.checkedAt,row.notes].map(quote).join(","));
 }
 const blob=new Blob(["\uFEFF"+content.join("\r\n")],{type:"text/csv;charset=utf-8"});
 const url=URL.createObjectURL(blob);
 const a=document.createElement("a");a.href=url;a.download="ken-karaoke-verification-"+new Date().toISOString().slice(0,10)+".csv";
 document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
}
function parseCsv(content){
 const rows=[];let fields=[],value="",inQuote=false;
 for(let i=0;i<content.length;i++){
  const c=content[i];
  if(inQuote){
   if(c==='"'){if(content[i+1]==='"'){value+='"';i++;}else inQuote=false;}else value+=c;
  }else if(c==='"')inQuote=true;
  else if(c===','||c==='\n'||c==='\r'){
   fields.push(value);value="";
   if(c!==","){
    if(c==='\r'&&content[i+1]==='\n')i++;
    rows.push(fields);fields=[];
   }
  }else value+=c;
 }
 if(value||fields.length){fields.push(value);rows.push(fields);}
 return rows;
}
async function importCsv(file){
 if(!file)return;
 if(file.size>4_000_000)throw Error("CSVは4MB以下にしてください。");
 const rows=parseCsv((await file.text()).replace(/^\uFEFF/,""));
 const header=(rows.shift()||[]).map(x=>x.trim().toLowerCase());
 const must=["title","artist","dam_status","dam_url","joysound_status","joysound_url"];
 for(const item of must)if(!header.includes(item))throw Error("CSVに必要な列がありません："+item);
 let added=0,skipped=0;
 const read=(row,name)=>row[header.indexOf(name)]||"";
 for(const fields of rows){
  if(!fields.some(Boolean))continue;
  const title=read(fields,"title").trim(),artist=read(fields,"artist").trim();
  if(!title||!artist){skipped++;continue;}
  const provider=(prefix)=>({
   status:read(fields,prefix+"_status")||"unknown",
   url:read(fields,prefix+"_url"),
   number:read(fields,prefix+"_number")
  });
  try{
   validateAndSave({title,artist,dam:provider("dam"),joy:provider("joysound"),notes:read(fields,"notes")},{
    deferSave:true,checkedDates:{dam:read(fields,"dam_checked_at"),joy:read(fields,"joysound_checked_at")}
   });
   added++;
  }catch(error){skipped++;console.warn("Skipped karaoke CSV row:",error.message);}
 }
 if(window.KEN_SHARED?.configured){
  const values=Object.values(all);
  for(let i=0;i<values.length;i+=100)
   await window.KEN_SHARED.action("karaoke_import",{records:values.slice(i,i+100)});
 }else if(!save())throw Error("CSVの記録を保存できませんでした。");
 refresh();
 return {added,skipped};
}
function init(){
 const form=$("#karaokeCheckForm");if(!form)return;
 for(const id of ["karaokeTitle","karaokeArtist"])$("#"+id).addEventListener("input",updateLookupLinks);
 form.addEventListener("submit",event=>{
  event.preventDefault();
  try{validateAndSave(getFormRecord());alert(window.KEN_SHARED?.configured?"共有保存を送信しました。反映状態を確認してください。":"公式の確認結果をこの端末に保存しました。");}
  catch(e){alert(e.message);}
 });
 $("#karaokeClear").addEventListener("click",()=>setForm("",""));
 $("#karaokeExport").addEventListener("click",exportCsv);
 $("#karaokeImport").addEventListener("change",async event=>{
  try{
   const out=await importCsv(event.target.files?.[0]);
   if(out)alert("CSVを取り込みました："+out.added+"曲 / スキップ "+out.skipped+"行");
  }catch(e){alert(e.message);}finally{event.target.value="";}
 });
 document.addEventListener("click",event=>{
  const button=event.target.closest("[data-karaoke-edit]");
  if(!button)return;
  const editor=$("#karaokeCheckForm");
  if(!editor)return;
  const details=editor.closest(".admin-tools");
  if(details && $("#adminView")?.hidden===false){
   details.open=true;
   setForm(button.dataset.karaokeEdit||"",button.dataset.karaokeArtist||"");
   editor.scrollIntoView({behavior:"smooth",block:"center"});
  }else{
   setForm(button.dataset.karaokeEdit||"",button.dataset.karaokeArtist||"");
   alert("照合結果の編集は管理画面で行えます。");
  }
 });
 updateCount();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);
else init();
window.KEN_KARAOKE=Object.freeze({render,lookup,siteSearch,official:SOURCES,importCsv,applyShared});
})();