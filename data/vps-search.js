/*
 * Optional VPS-backed song lookup. No secrets are stored in GitHub Pages.
 * When not configured (or VPS unavailable), the existing static catalog works.
 */
(()=>{
 "use strict";
 const configured=String(window.KEN_CONFIG?.apiBaseUrl||"").trim();
 if(!configured)return;
 let base;
 try{
  const u=new URL(configured);
  const isLocal=["localhost","127.0.0.1"].includes(u.hostname);
  if(u.protocol!=="https:"&&!(isLocal&&u.protocol==="http:"))throw Error("HTTPS required");
  if(u.username||u.password||u.search||u.hash)throw Error("Invalid API URL");
  base=u.href.replace(/\/+$/,"");
 }catch(error){console.warn("Ken song API configuration is invalid",error);return;}
 const cache=new Map();
 async function search(query,mode="title",limit=30){
  if(query.trim().length<2)return {items:[]};
  const key=mode+"\t"+query.trim().normalize("NFKC");
  if(cache.has(key))return cache.get(key);
  const url=new URL(base+"/api/v1/search");
  url.searchParams.set("q",query);
  url.searchParams.set("mode",mode==="artist"?"artist":"title");
  url.searchParams.set("limit",String(Math.min(50,Math.max(1,limit))));
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),6000);
  const promise=fetch(url.toString(),{
    method:"GET",
    mode:"cors",
    credentials:"omit",
    headers:{"Accept":"application/json"},
    signal:controller.signal
  }).then(async response=>{
    if(!response.ok)throw Error("API response "+response.status);
    const payload=await response.json();
    if(!payload||!Array.isArray(payload.items))throw Error("Unexpected API schema");
    return payload;
  }).finally(()=>clearTimeout(timer)).catch(error=>{
    cache.delete(key);
    throw error;
  });
  cache.set(key,promise);
  if(cache.size>30)cache.delete(cache.keys().next().value);
  return promise;
 }
 window.KEN_VPS_SEARCH=Object.freeze({search,apiConfigured:true});
})();
