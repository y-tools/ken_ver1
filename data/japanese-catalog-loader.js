/*
 * Adds the repository's 10,000 curated Japanese songs to the legacy
 * catalog.json search without modifying the application's stored song list.
 * Source metadata: data/japanese_popular_10000.json (Wikidata CC0).
 * JASRAC/NexTone identifiers are not populated without verification.
 */
(()=>{
 "use strict";
 const originalFetch=window.fetch.bind(window);
 const canonical=text=>String(text??"").normalize("NFKC").toLowerCase()
   .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
   .replace(/[\s・ー‐-]/g,"");
 const key=row=>canonical(row[0])+"|"+canonical(row[1]);
 const isCatalog=url=>{
  try{
   const parsed=new URL(typeof url==="string"?url:url.url,location.href);
   return parsed.origin===location.origin && parsed.pathname===new URL("./catalog.json",location.href).pathname;
  }catch(_){return false;}
 };
 let mergedResponse=null;
 async function combinedCatalog(url,options){
  if(!mergedResponse){
   mergedResponse=(async()=>{
    const [japan,world]=await Promise.allSettled([
     originalFetch("./data/japanese_popular_10000.json",{cache:"force-cache"}).then(async r=>{
      if(!r.ok)throw new Error("Japanese catalog HTTP "+r.status);
      return r.json();
     }),
     originalFetch(url,options).then(async r=>{
      if(!r.ok)throw new Error("Global catalog HTTP "+r.status);
      return r.json();
     })
    ]);
    const jRows=japan.status==="fulfilled" && japan.value?.schema==="jp-catalog-v1" && Array.isArray(japan.value.songs)
      ?japan.value.songs:[];
    const wRows=world.status==="fulfilled"&&Array.isArray(world.value)?world.value:[];
    const merged=[],seen=new Set();
    for(const row of [...jRows,...wRows]){
     if(!Array.isArray(row)||typeof row[0]!=="string"||!row[0].trim()||typeof row[1]!=="string"||!row[1].trim())continue;
     const k=key(row);if(seen.has(k))continue;seen.add(k);
     merged.push([row[0],row[1],row[2]||null]);
    }
    if(!merged.length)throw new Error("Both song catalogs are unavailable");
    window.KEN_CATALOG_STATS=Object.freeze({
      japaneseSourceCount:jRows.length,
      worldSourceCount:wRows.length,
      searchableUniqueCount:merged.length
    });
    return JSON.stringify(merged);
   })();
  }
  const body=await mergedResponse;
  return new Response(body,{status:200,headers:{"Content-Type":"application/json; charset=utf-8"}});
 }
 window.fetch=(url,options)=>{
  if(isCatalog(url))return combinedCatalog(url,options);
  return originalFetch(url,options);
 };
})();