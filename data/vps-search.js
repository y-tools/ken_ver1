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
 async function stats(){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),6000);
  try{
   const response=await fetch(base+"/api/v1/stats",{method:"GET",mode:"cors",credentials:"omit",
    cache:"no-store",headers:{"Accept":"application/json"},signal:controller.signal});
   if(!response.ok)throw Error("API response "+response.status);
   const payload=await response.json();
   if(!Number.isFinite(payload?.songCount)||!Number.isFinite(payload?.artistCount))throw Error("Unexpected API schema");
   return payload;
  }finally{clearTimeout(timer);}
 }
 async function adminCall(method,token,body,path=""){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),10000);
  try{
   const response=await fetch(base+"/api/v1/priority-requests"+path,{method,mode:"cors",credentials:"omit",cache:"no-store",
    headers:{"Accept":"application/json","Authorization":"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
    body:body?JSON.stringify(body):undefined,signal:controller.signal});
   let payload=null;try{payload=await response.json();}catch(_){}
   if(!response.ok){
    const d=payload?.detail;
    throw Error(typeof d==="string"?d:"サーバーエラー（"+response.status+"）");
   }
   return payload;
  }finally{clearTimeout(timer);}
 }
 const priorityList=token=>adminCall("GET",token);
 const priorityAdd=(token,data)=>adminCall("POST",token,data);
 const priorityStatus=(token,id,status,extra={})=>adminCall("POST",token,{status,...extra},"/"+encodeURIComponent(id)+"/status");
 const priorityClear=(token,id)=>adminCall("POST",token,{},"/"+encodeURIComponent(id)+"/clear");
 window.KEN_VPS_SEARCH=Object.freeze({search,stats,priorityList,priorityAdd,priorityStatus,priorityClear,apiConfigured:true});
})();
