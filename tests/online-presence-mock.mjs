import assert from "node:assert/strict";
import {chromium} from "playwright";

const browser=await chromium.launch({headless:true});
const errors=[];
const online=new Map();
const server={version:0,streamLive:false,name:"Ken",activeSessionId:null,
  requests:[],songs:[],sessions:[],chatNotes:[],karaoke:[]};
const identity={
  admin:{userId:"admin-id",displayName:"配信管理者",loginId:"admin_1",role:"admin"},
  listener:{userId:"listener-id",displayName:"試聴リスナー",loginId:"listener_1",role:"listener"}
};
async function rpc(name,args,role){
 const caller=identity[role];
 if(name==="denmoku_snapshot")return {data:{...server,userId:caller.userId,role},error:null};
 if(name==="denmoku_public_snapshot")return {data:{...server,userId:null,role:"guest",sessions:[],chatNotes:[]},error:null};
 if(name==="version")return {data:{version:server.version},error:null};
 if(name==="presence_heartbeat"){
  online.set(caller.userId+"|"+args.p_tab_id,{...caller,tabId:args.p_tab_id,seen:Date.now()});
  return {data:null,error:null};
 }
 if(name==="presence_leave"){
  online.delete(caller.userId+"|"+args.p_tab_id);
  return {data:null,error:null};
 }
 if(name==="presence_admin_list"){
  if(role!=="admin")return {data:null,error:{message:"Admin permission required"}};
  const grouped=new Map();
  for(const row of online.values()){
   if(Date.now()-row.seen>75000)continue;
   const entry=grouped.get(row.userId)||{userId:row.userId,displayName:row.displayName,
     loginId:row.loginId,role:row.role,connections:0,lastSeenAt:row.seen};
   entry.connections++;
   entry.lastSeenAt=Math.max(entry.lastSeenAt,row.seen);
   grouped.set(row.userId,entry);
  }
  return {data:Array.from(grouped.values()),error:null};
 }
 if(name==="denmoku_action")return {data:null,error:{message:"Not used in presence test"}};
 return {data:null,error:{message:"Unknown RPC: "+name}};
}
const sdk=role=>[
 "(()=>{",
 "const role="+JSON.stringify(role)+";",
 "const rpc=(name,args)=>window.__kenTestRpc(name,args,role);",
 "window.supabase={createClient:()=>({",
 "auth:{getUser:async()=>({data:{user:{id:role+'-id',email:role+'@example.com'}},error:null}),",
 "signOut:async()=>({error:null})},",
 "from:table=>({select:()=>({eq:()=>({single:async()=>table==='profiles'?",
 "{data:{id:role+'-id',role,display_name:role==='admin'?'配信管理者':'試聴リスナー',login_id:role+'_1'},error:null}:rpc('version',{})})})}),",
 "rpc,",
 "channel:()=>({on(){return this;},subscribe(cb){queueMicrotask(()=>cb('SUBSCRIBED'));return this;}}),",
 "removeChannel:async()=>{},",
 "functions:{invoke:async()=>({data:{success:true},error:null})}",
 "})};",
 "})();"
].join("\n");
async function open(role){
 const ctx=await browser.newContext({viewport:{width:1400,height:900}});
 await ctx.exposeFunction("__kenTestRpc",rpc);
 await ctx.route("**/config.js*",route=>route.fulfill({
  contentType:"application/javascript",
  body:"window.KEN_CONFIG={supabaseUrl:'https://example.supabase.co',supabasePublishableKey:'sb_publishable_test_12345678901234567890',apiBaseUrl:''}"
 }));
 await ctx.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/**",route=>route.fulfill({
  contentType:"application/javascript",body:sdk(role)
 }));
 const page=await ctx.newPage();
 page.on("pageerror",e=>errors.push(role+": "+e.message));
 await page.goto("http://127.0.0.1:8765/",{waitUntil:"domcontentloaded",timeout:60000});
 await page.waitForFunction(()=>Boolean(document.querySelector("#signedInUser")?.textContent?.trim()));
 return {ctx,page};
}
const opened=[];
try{
 const admin=await open("admin");opened.push(admin);
 await admin.page.locator("#adminTitle").click({clickCount:3});
 await admin.page.locator("#onlineUserCount").getByText("1人").waitFor({timeout:10000});
 assert.equal((await admin.page.locator("#onlineUsersList").textContent()).includes("配信管理者"),true);
 const listener=await open("listener");opened.push(listener);
 assert.equal(await listener.page.locator("#signedInUser").textContent(),"ゲスト閲覧中");
 await admin.page.waitForFunction(
  ()=>document.querySelector("#onlineUserCount")?.textContent==="1人",
  null,{timeout:12000}
 );
 assert.equal(await listener.page.locator("#onlineUsersPanel").isVisible(),false);
 const denied=await listener.page.evaluate(()=>window.KEN_SHARED.client.rpc("presence_admin_list"));
 assert.match(denied.error?.message||"",/Admin permission/);
 console.log("PASS guests do not appear in authenticated online list");

 const second=await open("admin");opened.push(second);
 await admin.page.waitForFunction(
  ()=>document.querySelector("#onlineUsersList")?.textContent?.includes("2接続"),
  null,{timeout:12000}
 );
 assert.equal(await admin.page.locator("#onlineUserCount").textContent(),"1人");
 console.log("PASS two admin tabs count as one unique authenticated user");

 await second.page.locator("#logoutButton").click();
 await admin.page.waitForFunction(
  ()=>!document.querySelector("#onlineUsersList")?.textContent?.includes("2接続"),
  null,{timeout:12000}
 );
 assert.equal(await admin.page.locator("#onlineUserCount").textContent(),"1人");
 console.log("PASS admin logout removes online connection without affecting guest");
 assert.deepEqual(errors,[]);
}finally{
 for(const item of opened)await item.ctx.close().catch(()=>{});
 await browser.close();
}
