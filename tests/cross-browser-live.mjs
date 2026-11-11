import assert from "node:assert/strict";
import { chromium } from "playwright";

// Two isolated browser contexts share ONLY the mocked backend.
// They do not share localStorage, BroadcastChannel, or browser sessions.
const browser=await chromium.launch({headless:true});
const server={
 version:0, name:"Ken", streamLive:false, activeSessionId:null, activeSessionStartedAt:null,
 requests:[], songs:[], sessions:[], chatNotes:[], karaoke:[]
};
const errs=[];
async function serverCall(method,args,role){
 if(method==="denmoku_snapshot"){
  return {data:structuredClone({...server,role,userId:role==="admin"?"admin-id":"listener-id",
    chatNotes:role==="listener"?[]:server.chatNotes}),error:null};
 }
 if(method==="denmoku_public_snapshot"){
  return {data:structuredClone({...server,role:"guest",userId:null,sessions:[],chatNotes:[],
    requests:server.requests.filter(r=>["waiting","singing","done"].includes(r.status))
      .map(r=>({...r,message:"",userId:null}))}),error:null};
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
   server.activeSessionStartedAt=server.sessions.length===0 ? Date.now()-10000 : Date.now();
   server.sessions=[{id:server.activeSessionId,startedAt:Date.now(),endedAt:null,events:[]}];
  }else if(action==="stream_end"){
   if(!server.streamLive)return {data:null,error:{message:"Already offline"}};
   server.streamLive=false;
   server.activeSessionId=null;
   server.activeSessionStartedAt=null;
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
 await ctx.route("https://example.supabase.co/functions/v1/public-request",async route=>{
  const payload=route.request().postDataJSON();
  const valid=server.streamLive && (
    payload.freeform===true
      ? payload.title==="自由曲テスト" && payload.artist==="別のアーティスト" && payload.nickname==="自由入力テスト"
      : payload.artist==="TK from 凛として時雨" && payload.title==="unravel" && payload.nickname==="ゲスト試験"
  );
  if(!valid){
   await route.fulfill({status:400,contentType:"application/json",
     headers:{"Access-Control-Allow-Origin":"*"},body:JSON.stringify({error:"Invalid guest request"})});return;
  }
  server.requests.push({id:"guest-"+Date.now(),title:payload.title,artist:payload.artist,
   nickname:payload.nickname,status:"new",createdAt:Date.now(),message:"",userId:null});
  server.version++;
  await route.fulfill({status:201,contentType:"application/json",
    headers:{"Access-Control-Allow-Origin":"*"},body:JSON.stringify({ok:true,id:crypto.randomUUID()})});
 });
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
 assert.equal(await listener.page.locator("#openRequestDialog").isEnabled(),true,
   "Guest requests are now enabled through a separate server-limited endpoint");
 console.log("PASS remote listener turns ON AIR without reload, even while hidden");
 await listener.page.locator("#openRequestDialog").click();
 await listener.page.locator("#reqTitle").fill("unravel");
 await listener.page.locator("#reqArtist").fill("TK from 凛として時雨");
 await listener.page.locator("#reqName").fill("ゲスト試験");
 await listener.page.locator("#sendRequest").click();
 await admin.page.waitForFunction(
  ()=>document.querySelector("#adminRequests")?.textContent?.includes("ゲスト試験"),
  null,{timeout:12000}
 );
 assert.equal(server.requests.length,1);
 assert.equal(server.requests[0].userId,null);
 console.log("PASS no-login guest request propagates to admin browser");
 assert.equal(await listener.page.locator("#freeformRequestDialog").isVisible(),false);
 await listener.page.locator("#openFreeformRequest").click();
 await listener.page.locator("#freeformRequestDialog").waitFor({state:"visible"});
 assert.equal(await listener.page.locator("#freeRequestTitle").inputValue(),"");
 assert.equal(await listener.page.locator("#freeRequestArtist").inputValue(),"");
 // Closing and reopening must reset unsent song fields, not keep old choices.
 await listener.page.locator("#freeRequestTitle").fill("未送信の曲");
 await listener.page.locator("#freeRequestDialogClose").click();
 await listener.page.locator("#freeformRequestDialog").waitFor({state:"hidden"});
 await listener.page.locator("#openFreeformRequest").click();
 await listener.page.locator("#freeformRequestDialog").waitFor({state:"visible"});
 assert.equal(await listener.page.locator("#freeRequestTitle").inputValue(),"");
 await listener.page.locator("#freeRequestTitle").fill("自由曲テスト");
 await listener.page.locator("#freeRequestArtist").fill("別のアーティスト");
 await listener.page.locator("#freeRequestName").fill("自由入力テスト");
 await listener.page.locator("#freeRequestSubmit").click();
 await admin.page.waitForFunction(
  ()=>document.querySelector("#adminRequests")?.textContent?.includes("自由曲テスト"),
  null,{timeout:12000}
 );
 assert.equal(server.requests.length,2);
 assert.equal(server.requests[1].artist,"別のアーティスト");
 assert.equal(server.requests[1].userId,null);
 await listener.page.locator("#freeformRequestDialog").waitFor({state:"hidden"});
 console.log("PASS freeform popup opens, starts blank, closes and syncs to admin across browsers");

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

 // The active song block must show an actual search link with the new label.
 server.requests[0].status="singing";
 server.version++;
 await listener.page.waitForFunction(
  ()=>document.querySelector("#singingNow .lyrics-action")?.textContent==="歌詞検索",
  null,{timeout:12000}
 );
 assert.match(await listener.page.locator("#singingNow .lyrics-action").getAttribute("href"),/google\.com\/search\?q=/);
 console.log("PASS singing song lyric search is visible and labeled 歌詞検索");

 // A completed request belongs to THIS active stream's visible history.
 server.requests[0].status="done";
 server.requests[0].completedAt=Date.now()-1000;
 server.version++;
 await listener.page.waitForFunction(
  ()=>document.querySelector("#todaySingingCount")?.textContent==="1",
  null,{timeout:11500}
 );
 await admin.page.waitForFunction(()=>document.querySelector("#todaySingingCount")?.textContent==="1");
 console.log("PASS completed song appears in today's history during the stream");

 // Stop is also synchronized to the independent, background listener browser.
 await admin.page.locator("#endStream").click();
 await admin.page.waitForFunction(()=>document.querySelector("#adminOnAir")?.hidden===true);
 await listener.page.waitForFunction(
  ()=>document.querySelector("#listenerStreamLabel")?.textContent==="OFF AIR",
  null,{timeout:11500}
 );
 assert.equal(server.streamLive,false);
 assert.equal(await listener.page.locator("#openRequestDialog").isDisabled(),true);
 await listener.page.waitForFunction(
  ()=>document.querySelector("#todaySingingCount")?.textContent==="0",
  null,{timeout:11500}
 );
 await admin.page.waitForFunction(()=>document.querySelector("#todaySingingCount")?.textContent==="0");
 assert.equal(server.requests[0].status,"done","song request retained for reporting");
 assert.ok(server.sessions[0].endedAt,"stream report still exists");
 console.log("PASS today's history clears on OFF AIR without deleting report data");

 // Even on the same calendar day, a new stream must not resurrect old songs.
 await admin.page.locator("#startStream").click();
 await admin.page.waitForFunction(()=>document.querySelector("#adminOnAir")?.hidden===false);
 await listener.page.waitForFunction(
  ()=>document.querySelector("#listenerStreamLabel")?.textContent==="ON AIR",
  null,{timeout:11500}
 );
 assert.equal(await listener.page.locator("#todaySingingCount").textContent(),"0");
 console.log("PASS previously completed song stays cleared after next stream starts");
 assert.deepEqual(errs,[]);
 await secondAdmin.ctx.close();
 await listener.ctx.close();
 await admin.ctx.close();
}finally{
 await browser.close();
}
