import assert from "node:assert/strict";
import { chromium } from "playwright";

// Two isolated browser contexts share ONLY the mocked backend.
// They do not share localStorage, BroadcastChannel, or browser sessions.
const browser=await chromium.launch({headless:true});
const server={
 version:0, name:"Ken", streamLive:false, activeSessionId:null,
 requests:[], songs:[], sessions:[], chatNotes:[], karaoke:[]
};
const errs=[];
async function serverCall(method,args,role){
 if(method==="denmoku_snapshot"){
  return {data:structuredClone({...server,role,userId:role==="admin"?"admin-id":"listener-id",
    chatNotes:role==="listener"?[]:server.chatNotes}),error:null};
 }
 if(method==="version")return {data:{version:server.version},error:null};
 if(method==="denmoku_action"){
  if(role!=="admin"&&role!=="owner")
   return {data:null,error:{message:"Admin permission required"}};
  const action=args?.p_action;
  if(action==="stream_start"){
   if(server.streamLive)return {data:null,error:{message:"Already live"}};
   server.streamLive=true;
   server.activeSessionId="11111111-1111-4111-8111-111111111111";
   server.sessions=[{id:server.activeSessionId,startedAt:Date.now(),endedAt:null,events:[]}];
  }else if(action==="stream_end"){
   if(!server.streamLive)return {data:null,error:{message:"Already offline"}};
   server.streamLive=false;
   server.activeSessionId=null;
   server.sessions[0].endedAt=Date.now();
  }else if(action==="note_add"){
   server.chatNotes.push({id:"note-"+Date.now(),kind:args.p_data.kind||"note",
     text:args.p_data.text,at:Date.now()});
  }else if(action==="song_upsert"){
   const input=args.p_data;
   server.songs.push({id:"song-"+Date.now(),title:input.title,artist:input.artist,
     status:input.status,year:input.year||null,memo:input.memo||""});
  }else return {data:null,error:{message:"Unsupported mock action"}};
  server.version++;
  return {data:server.version,error:null};
 }
 throw Error("Unexpected mocked RPC "+method);
}
const mockSdk=role=>[
 "(()=>{",
 "const role="+JSON.stringify(role)+";",
 "const call=(method,args)=>window.__kenMockServer(method,args,role);",
 "window.supabase={createClient:()=>({",
 "auth:{getUser:async()=>({data:{user:{id:role+'-id',email:role+'@example.com'}},error:null}),signOut:async()=>({error:null})},",
 "from:table=>({select:()=>({eq:()=>({single:async()=>table==='profiles'?{data:{id:role+'-id',role,display_name:role,login_id:null},error:null}:call('version',{})})})}),",
 "rpc:(method,args)=>call(method,args),",
 "channel:()=>({on(){return this;},subscribe(callback){queueMicrotask(()=>callback('SUBSCRIBED'));return this;}}),",
 "removeChannel(){},functions:{invoke:async()=>({data:{success:true},error:null})}",
 "})};",
 "})();"
].join("\n");

async function openPage(role,{hidden=false}={}){
 const ctx=await browser.newContext({viewport:{width:1400,height:900}});
 await ctx.exposeFunction("__kenMockServer",serverCall);
 await ctx.route("**/config.js*",r=>r.fulfill({
  contentType:"application/javascript",
  body:"window.KEN_CONFIG={supabaseUrl:'https://example.supabase.co',supabasePublishableKey:'sb_publishable_testing_only_0123456789012345',apiBaseUrl:''}"
 }));
 await ctx.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/**",r=>r.fulfill({
  contentType:"application/javascript",body:mockSdk(role)
 }));
 const page=await ctx.newPage();
 page.on("pageerror",err=>errs.push(role+": "+err.message));
 if(hidden){
  // Simulate an inactive listener tab that misses all realtime notifications.
  // A timer-based version check must still recover its ON AIR status.
  await page.addInitScript(()=>{
   Object.defineProperty(document,"hidden",{configurable:true,get:()=>true});
  });
 }
 await page.goto("http://127.0.0.1:8765/",{waitUntil:"domcontentloaded",timeout:60000});
 await page.waitForFunction(()=>Boolean(document.querySelector("#signedInUser")?.textContent?.trim()));
 return {ctx,page};
}
try{
 const admin=await openPage("admin");
 const listener=await openPage("listener",{hidden:true});
 assert.equal(await listener.page.locator("#listenerStreamLabel").textContent(),"OFF AIR");

 // Normal listener cannot change stream status even by calling the RPC directly.
 const denied=await listener.page.evaluate(()=>window.KEN_SHARED.client.rpc(
  "denmoku_action",{p_action:"stream_start",p_data:{}}
 ));
 assert.match(denied.error?.message||"",/Admin permission/);

 // The admin's tab writes server state. Listener is in an independent context.
 await admin.page.locator("#adminTitle").dblclick();
 await admin.page.locator("#adminView").waitFor({state:"visible"});
 await admin.page.locator("#startStream").click();
 await admin.page.waitForFunction(()=>document.querySelector("#adminOnAir")?.hidden===false);
 assert.equal(server.streamLive,true);
 await listener.page.waitForFunction(
  ()=>document.querySelector("#listenerStreamLabel")?.textContent==="ON AIR",
  null,{timeout:11500}
 );
 assert.equal(await listener.page.locator("#openRequestDialog").isEnabled(),true);
 console.log("PASS remote listener turns ON AIR without reload, even while hidden");

 // Chat history and managed song list also propagate between independent admins.
 const secondAdmin=await openPage("admin");
 await secondAdmin.page.locator("#adminTitle").dblclick();
 await secondAdmin.page.locator("#adminView").waitFor({state:"visible"});
 await admin.page.locator("#adminChatInput").fill("サーバー共有チャットの同期試験");
 await admin.page.locator("#adminChatForm button[type=submit]").click();
 await secondAdmin.page.waitForFunction(
  ()=>document.querySelector("#adminChatHistory")?.textContent?.includes("サーバー共有チャットの同期試験"),
  null,{timeout:12000}
 );
 assert.equal(
  (await listener.page.locator("#adminChatHistory").textContent()).includes("サーバー共有チャットの同期試験"),
  false,"private admin chat must not be returned to listeners"
 );
 console.log("PASS private admin chat updates in a second browser without reload");

 await secondAdmin.page.locator(".admin-tools > summary").click();
 await secondAdmin.page.locator("#songTitle").fill("unravel");
 await secondAdmin.page.locator("#songArtist").fill("TK from 凛として時雨");
 await secondAdmin.page.locator("#songStatus").selectOption("ready");
 await secondAdmin.page.locator("#songSaveButton").click();
 await admin.page.waitForFunction(
  ()=>document.querySelector("#adminSongList")?.textContent?.includes("unravel"),
  null,{timeout:12000}
 );
 console.log("PASS managed song list updates between independent admins");

 // Stop is also synchronized to the independent, background listener browser.
 await admin.page.locator("#endStream").click();
 await admin.page.waitForFunction(()=>document.querySelector("#adminOnAir")?.hidden===true);
 await listener.page.waitForFunction(
  ()=>document.querySelector("#listenerStreamLabel")?.textContent==="OFF AIR",
  null,{timeout:11500}
 );
 assert.equal(server.streamLive,false);
 assert.equal(await listener.page.locator("#openRequestDialog").isDisabled(),true);
 console.log("PASS remote listener turns OFF AIR without reload");
 assert.deepEqual(errs,[]);
 await secondAdmin.ctx.close();
 await listener.ctx.close();
 await admin.ctx.close();
}finally{
 await browser.close();
}
