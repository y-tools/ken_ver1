/*
 * MusicBrainz CC0 extension to one million unique songs.
 * Loads just two small buckets for each query (title/artist 2-char prefix).
 * Never downloads the extra 700,000 rows on initial page load.
 */
(()=>{
 "use strict";
 const base=new URL("./data/musicbrainz_700k/",location.href);
 const norm=v=>String(v??"").normalize("NFKC").toLowerCase()
  .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
  .replace(/[\s・ー‐-]/g,"");
 const bucket=value=>{
  let h=0;
  for(const c of Array.from(norm(value)).slice(0,2))
   h=(h*131+c.codePointAt(0))%256;
  return h.toString(16).padStart(2,"0");
 };
 const cache=new Map();
 let manifestPromise=null;
 async function ready(){
  if(!manifestPromise){
   manifestPromise=(async()=>{
    try{
     const r=await fetch(new URL("manifest.json",base),{cache:"no-cache"});
     if(!r.ok)return null;
     const data=await r.json();
     if(data.schema!=="musicbrainz-on-demand-prefix-v1"||data.targetUnique!==1000000||
        data.baselineUnique!==300000||data.additionalUnique!==700000||
        data.fileCount!==256)return null;
     window.KEN_MB_CATALOG_STATS=Object.freeze({
      targetUnique:1000000,extensionCount:700000,
      baselineUnique:300000,lazySearch:true,ready:true,
     });
     return data;
    }catch(e){
     console.warn("MusicBrainz extension not yet published",e);
     return null;
    }
   })();
  }
  return manifestPromise;
 }
 async function loadBucket(b){
  if(!cache.has(b)){
   const task=(async()=>{
    const response=await fetch(new URL("bucket_"+b+".json",base),{cache:"force-cache"});
    if(!response.ok)throw new Error("MusicBrainz index bucket "+b+" failed");
    const json=await response.json();
    if(!Array.isArray(json))throw new Error("Unexpected MusicBrainz index bucket contents");
    return json;
   })().catch(err=>{cache.delete(b);throw err;});
   cache.set(b,task);
  }
  return cache.get(b);
 }
 async function search(q,limit=30,mode="all"){
  const term=norm(q);
  const fields=mode==="title"?[0]:mode==="artist"?[1]:[0,1];
  if(Array.from(term).length<2||!await ready())return [];
  const buckets=[...new Set([bucket(q)])];
  const lists=await Promise.all(buckets.map(loadBucket));
  const seen=new Set(),results=[];
  for(const list of lists)for(const row of list){
   if(!Array.isArray(row)||!row[0]||!row[1])continue;
   const title=norm(row[0]),artist=norm(row[1]);
   if(!fields.some(index=>norm(row[index]).startsWith(term)))continue;
   const key=title+"|"+artist;
   if(seen.has(key))continue;
   seen.add(key);
   results.push(row);
   if(results.length>=limit)return results;
  }
  return results;
 }
 window.KEN_MB_SEARCH=Object.freeze({ready,search,bucket});
})();
