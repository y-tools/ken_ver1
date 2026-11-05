/*
 * Ken Denmoku: extension from 1M to 2M unique title/artist pairs.
 * MusicBrainz canonical recording names: CC0.
 * Pronunciation index: pykakasi-generated approximate Japanese readings.
 * Only fetch the necessary 2-character-prefix hash bucket on demand.
 */
(()=>{
 "use strict";
 const prior=window.KEN_MB_SEARCH;
 if(!prior)return;
 const root=new URL("./",location.href);
 const normalize=s=>String(s??"").normalize("NFKC").toLowerCase()
  .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
  .replace(/[\s・ー‐-]/g,"");
 const bucket=prior.bucket;
 const originalSearch=prior.search.bind(prior);
 const cache=new Map();
 const maxCacheEntries=24;
 const manifestCache=new Map();
 const manifestConfig={
  extra:{name:"data/musicbrainz_next_1m/",schema:"musicbrainz-next-million-v1"},
  reading:{name:"data/song_readings/",schema:"ken-phonetic-2m-v1"}
 };
 const getManifest=type=>{
  if(manifestCache.has(type))return manifestCache.get(type);
  const cfg=manifestConfig[type];
  const promise=(async()=>{
   try{
    const response=await fetch(new URL(cfg.name+"manifest.json",root),{cache:"no-cache"});
    if(!response.ok)return null;
    const manifest=await response.json();
    if(manifest.schema!==cfg.schema||manifest.targetUnique&&manifest.targetUnique!==2000000||
       manifest.totalUnique&&manifest.totalUnique!==2000000||
       manifest.bucketCount!==256||!Array.isArray(manifest.files)||manifest.files.length!==256)return null;
    if(type==="extra"&&(manifest.additionalUnique!==1000000||manifest.baselineUnique!==1000000))return null;
    return manifest;
   }catch(error){
    console.warn("Optional "+type+" index is not available",error);
    return null;
   }
  })();
  manifestCache.set(type,promise);
  return promise;
 };
 const loadBucket=async(type,b)=>{
  const key=type+":"+b;
  if(cache.has(key)){
   const p=cache.get(key);
   cache.delete(key);cache.set(key,p);
   return p;
  }
  const folder=manifestConfig[type].name;
  const task=fetch(new URL(folder+"bucket_"+b+".json",root),{cache:"force-cache"})
   .then(r=>{if(!r.ok)throw Error("Cannot fetch "+folder+b);return r.json();})
   .then(rows=>{if(!Array.isArray(rows))throw Error("Malformed index shard");return rows;})
   .catch(e=>{cache.delete(key);throw e;});
  cache.set(key,task);
  while(cache.size>maxCacheEntries)cache.delete(cache.keys().next().value);
  return task;
 };
 const looksLikeMatch=(row,term)=>{
  for(const idx of [0,1,3,4,5,7,8,9]){
   if(row[idx]&&normalize(row[idx]).startsWith(term))return true;
  }
  return false;
 };
 const metaFromReading=row=>({
  type:"automatic",
  title:{hiragana:row[3]||"",katakana:row[4]||"",romaji:row[5]||"",english:row[6]||""},
  artist:{hiragana:row[7]||"",katakana:row[8]||"",romaji:row[9]||"",english:row[10]||""}
 });
 const readResults=async(type,query,limit)=>{
  const manifest=await getManifest(type);
  if(!manifest)return [];
  const key=bucket(query);
  const rows=await loadBucket(type,key);
  const term=normalize(query),output=[];
  for(const row of rows){
   if(!Array.isArray(row)||!row[0]||!row[1])continue;
   if(type==="reading"?!looksLikeMatch(row,term):
    !(normalize(row[0]).startsWith(term)||normalize(row[1]).startsWith(term)))continue;
   if(type==="reading"){
    output.push([row[0],row[1],row[2]||null,null,metaFromReading(row)]);
   }else{
    output.push(row);
   }
   if(output.length>=limit)break;
  }
  return output;
 };
 async function ready(){
  const [extra,readings]=await Promise.all([getManifest("extra"),getManifest("reading")]);
  const ok=Boolean(extra&&readings);
  if(ok){
   window.KEN_2M_STATS=Object.freeze({
    baselineUnique:1000000,
    extensionUnique:1000000,
    targetUnique:2000000,
    ready:true,
    approximateReadingCount:readings.indexedJapaneseUnique||0,
    searchMode:"on-demand prefix",
  });
  }
  return ok?{extra,readings}:null;
 }
 async function search(query,limit=24){
  const term=normalize(query);
  if(Array.from(term).length<2)return originalSearch(query,limit);
  const [phonetic,newSongs,oldSongs]=await Promise.allSettled([
   readResults("reading",query,limit),
   readResults("extra",query,limit),
   originalSearch(query,limit)
  ]);
  const groups=[
   phonetic.status==="fulfilled"?phonetic.value:[],
   newSongs.status==="fulfilled"?newSongs.value:[],
   oldSongs.status==="fulfilled"?oldSongs.value:[]
  ];
  const merged=[],seen=new Set(),readingLookup=new Map();
  for(const row of groups[0]){
   readingLookup.set(normalize(row[0])+"|"+normalize(row[1]),row[4]);
  }
  for(const group of groups)for(const row of group){
   const k=normalize(row[0])+"|"+normalize(row[1]);
   if(seen.has(k))continue;
   seen.add(k);
   const record=[...row];
   if(readingLookup.has(k))record[4]=readingLookup.get(k);
   merged.push(record);
   if(merged.length>=limit)return merged;
  }
  return merged;
 }
 window.KEN_MB_SEARCH=Object.freeze({...prior,search,ready2m:ready});
 window.KEN_READING_FORMAT=Object.freeze({metaFromReading,normalize});
 // Preview and developer diagnostics; page searches also request manifests.
 ready().catch(e=>console.warn("Two-million-song index unavailable",e));
})();
