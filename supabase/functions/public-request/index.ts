// Public request endpoint for the anonymous listener screen.
// Service role credentials remain inside the hosted Edge Function. Never put them in JS.
const SITE_ORIGIN="https://y-tools.github.io";
const CORS={
 "Access-Control-Allow-Origin":SITE_ORIGIN,
 "Access-Control-Allow-Methods":"POST, OPTIONS",
 "Access-Control-Allow-Headers":"content-type, apikey, authorization, x-client-info",
 "Access-Control-Max-Age":"600",
 "Vary":"Origin",
 "Cache-Control":"no-store",
 "Content-Type":"application/json; charset=utf-8",
};
function json(data:Record<string,unknown>,status=200):Response{
 return new Response(JSON.stringify(data),{status,headers:CORS});
}
function str(value:unknown,maxLength:number):string|null{
 if(typeof value!=="string")return null;
 const trimmed=value.trim();
 return trimmed.length>0&&trimmed.length<=maxLength?trimmed:null;
}
async function ipFingerprint(ip:string,secret:string):Promise<string>{
 const day=new Date().toISOString().slice(0,10);
 const encoder=new TextEncoder();
 const key=await crypto.subtle.importKey("raw",encoder.encode(secret),
   {name:"HMAC",hash:"SHA-256"},false,["sign"]);
 const bytes=new Uint8Array(await crypto.subtle.sign("HMAC",key,
   encoder.encode("ken-denmoku-guest-v2:"+day+":"+ip.toLowerCase())));
 return Array.from(bytes).map(b=>b.toString(16).padStart(2,"0")).join("");
}
Deno.serve(async request=>{
 if(request.method==="OPTIONS"){
   if(request.headers.get("origin")!==SITE_ORIGIN)return json({error:"Origin not allowed"},403);
   return new Response(null,{status:204,headers:CORS});
 }
 if(request.method!=="POST")return json({error:"Method not allowed"},405);
 if(request.headers.get("origin")!==SITE_ORIGIN)return json({error:"Origin not allowed"},403);
 if(!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))
   return json({error:"JSON required"},415);
 const length=Number(request.headers.get("content-length")||0);
 if(length>4096)return json({error:"Request too large"},413);
 const url=Deno.env.get("SUPABASE_URL");
 const serviceKey=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
 if(!url||!serviceKey)return json({error:"Server configuration unavailable"},503);
 // Hosted Supabase traffic reaches the edge through Cloudflare. Do not use
 // user-supplied x-forwarded-for; missing trusted IP means no anonymous writes.
 const ip=request.headers.get("cf-connecting-ip")?.trim();
 if(!ip||!/^[a-fA-F0-9:.]{3,45}$/.test(ip))
   return json({error:"Request security check unavailable"},503);
 let body:Record<string,unknown>;
 try{
   const raw=await request.text();
   if(raw.length>4096)return json({error:"Request too large"},413);
   const parsed:unknown=JSON.parse(raw);
   if(!parsed||typeof parsed!=="object"||Array.isArray(parsed))
     return json({error:"Invalid request"},400);
   body=parsed as Record<string,unknown>;
 }catch{return json({error:"Invalid JSON"},400);}
 if(body.company)return json({error:"Invalid request"},400); // honeypot
 const title=str(body.title,120),artist=str(body.artist,120),
       nickname=str(body.nickname,40);
 const note=typeof body.message==="string"?body.message.trim():null;
 const nonce=typeof body.nonce==="string"?body.nonce:"";
 if(!title||!artist||!nickname||note===null||note.length>200||
   !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(nonce))
   return json({error:"入力内容を確認してください"},400);
 const freeform=body.freeform===true;
 const fingerprint=await ipFingerprint(ip,serviceKey);
 try{
   const r=await fetch(url+"/rest/v1/rpc/"+(freeform?"denmoku_guest_request_freeform":"denmoku_guest_request"),{
     method:"POST",
     headers:{
       "apikey":serviceKey,
       "Authorization":"Bearer "+serviceKey,
       "Content-Type":"application/json",
       "Accept":"application/json",
     },
     body:JSON.stringify({
       p_fingerprint:fingerprint,p_nonce:nonce,
       p_title:title,p_artist:artist,p_nickname:nickname,p_message:note,
     }),
     signal:AbortSignal.timeout(10000),
   });
   if(!r.ok){
     let code="",detail="";
     try{const e=await r.json();code=String(e?.code||"");detail=String(e?.message||"");}catch{}
     if(code==="P0001"||/Too many requests|quota reached/i.test(detail))
       return json({error:"送信が多すぎます。少し時間をおいて再度お試しください"},429);
     if(code==="23514"||/Requests are closed/i.test(detail))
       return json({error:"現在はリクエスト受付時間外です"},409);
     if(code==="22023")
       return json({error:freeform?"曲名とアーティスト名を確認してください":"TKの楽曲カタログから曲を選択してください"},400);
     console.error("Guest request DB failure",r.status,code,detail.slice(0,180));
     return json({error:"サーバーへ保存できませんでした"},502);
   }
   const id:unknown=await r.json();
   if(typeof id!=="string"||!/^[0-9a-f-]{36}$/i.test(id))
     return json({error:"サーバー応答を確認できませんでした"},502);
   return json({ok:true,id},201);
 }catch(e){
   console.error("Guest request network failure",String(e).slice(0,120));
   return json({error:"サーバーとの通信に失敗しました"},503);
 }
});
