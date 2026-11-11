import assert from "node:assert/strict";
import { chromium } from "playwright";

const origin="http://127.0.0.1:8765";
const browser=await chromium.launch({headless:true});
const errors=[];
function mockSupabase(){
 const role=window.__KEN_TEST_ROLE;
 let data={role,userId:"11111111-1111-4111-8111-111111111111",name:"Ken",
   version:0,streamLive:false,activeSessionId:null,requests:[],songs:[],sessions:[],chatNotes:[],karaoke:[]};
 const client={
  auth:{getUser:async()=>({data:{user:{id:data.userId,email:"test@example.com"}},error:null}),
   signOut:async()=>({error:null})},
  from:(name)=>({select:()=>({eq:()=>({single:async()=>({data:name==="profiles"?
    {id:data.userId,display_name:"テスト利用者",role:data.role}:{version:data.version},error:null})})})}),
  rpc:async(name,params)=>{
   if(name==="denmoku_snapshot")return {data:JSON.parse(JSON.stringify(data)),error:null};
   if(name==="denmoku_public_snapshot")return {data:{
     ...JSON.parse(JSON.stringify(data)),role:"guest",sessions:[],chatNotes:[],
     requests:data.requests.filter(r=>["waiting","singing","done"].includes(r.status))
       .map(r=>({...r,message:"",userId:null}))
   },error:null};
   if(name==="denmoku_action"){
    if(data.role==="listener"&&params.p_action!=="request_add")
      return {data:null,error:{message:"Permission denied"}};
    if(params.p_action==="stream_start"){
      data.streamLive=true;data.activeSessionId=crypto.randomUUID();
      data.sessions.push({id:data.activeSessionId,startedAt:Date.now(),endedAt:null,events:[]});
    }
    if(params.p_action==="stream_end"){
      data.streamLive=false;data.sessions[data.sessions.length-1].endedAt=Date.now();
      data.activeSessionId=null;
    }
    if(params.p_action==="request_add"){
      if(!data.streamLive)return {data:null,error:{message:"OFF AIR"}};
      data.requests.push({id:crypto.randomUUID(),title:params.p_data.title,
        artist:params.p_data.artist,nickname:params.p_data.nickname,
        status:"new",createdAt:Date.now(),message:""});
    }
    data.version++;return {data:data.version,error:null};
   }
   return {data:null,error:null};
  },
  channel:()=>({on(){return this},subscribe(){return this}}),
  removeChannel(){},functions:{invoke:async(name,opts)=>({data:name==="create-admin-id"?{success:true,login_id:opts?.body?.login_id}:{success:true},error:null})}
 };
 window.supabase={createClient:()=>client};
}
async function fixture(role){
 const page=await browser.newPage({viewport:{width:1400,height:900}});
 page.on("pageerror",e=>errors.push(e.message));
 await page.route("**/config.js*",r=>r.fulfill({
  contentType:"application/javascript",
  body:"window.KEN_CONFIG={supabaseUrl:'https://example.supabase.co',supabasePublishableKey:'sb_publishable_testing_only_0123456789012345',apiBaseUrl:''}"
 }));
 await page.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/**",r=>r.fulfill({
  contentType:"application/javascript",
  body:"window.__KEN_TEST_ROLE="+JSON.stringify(role)+";("+mockSupabase.toString()+")();"
 }));
 await page.goto(origin+"/",{waitUntil:"domcontentloaded",timeout:60000});
 await page.locator("#listenerStreamLabel").waitFor({state:"visible",timeout:15000});
 await page.waitForFunction(()=>Boolean(document.querySelector("#signedInUser")?.textContent?.trim()));
 return page;
}
try{
 const admin=await fixture("admin");
 assert.equal(await admin.locator("#listenerStreamLabel").textContent(),"OFF AIR");
 await admin.waitForFunction(()=>document.querySelector("#catalogStatus")?.textContent==="TK専用カタログ");
 const tkCatalog=await admin.evaluate(async()=>await (await fetch("./catalog.json",{cache:"no-store"})).json());
 assert.equal(tkCatalog.length,98,"Static catalog remains exactly 98 songs");
 assert.ok(tkCatalog.every(row=>row[1]==="TK from 凛として時雨"));
 await admin.locator("#searchInput").fill("unravel");
 await admin.waitForFunction(()=>window.__searchResults?.some(row=>row.title==="unravel"));
 await admin.locator("#searchArtistInput").fill("TK from 凛として時雨");
 await admin.waitForFunction(()=>window.__searchResults?.some(row=>row.title==="unravel"&&row.artist==="TK from 凛として時雨"));
 assert.ok((await admin.evaluate(()=>window.__searchResults)).every(row=>row.artist==="TK from 凛として時雨"));
 await admin.locator("#searchArtistInput").fill("B'z");
 await admin.waitForFunction(()=>window.__searchResults?.length===0);
 await admin.locator("#searchInput").fill("");
 await admin.locator("#searchArtistInput").fill("TK from 凛として時雨");
 await admin.waitForFunction(()=>window.__searchResults?.some(row=>row.artist==="TK from 凛として時雨"));
 await admin.locator("#searchArtistInput").fill("");
 console.log("PASS TK-only catalog and two-field AND search under shared mode");

 await admin.locator("#adminTitle").click({clickCount:3});
 await admin.locator("#adminView").waitFor({state:"visible"});
 assert.equal(await admin.locator("#ownerInvite").isVisible(),false);
 await admin.locator("#startStream").click();
 await admin.locator("#adminOnAir").waitFor({state:"visible"});
 await admin.locator("#toListener").click();
 assert.equal(await admin.locator("#listenerStreamLabel").textContent(),"ON AIR");
 await admin.locator("#openRequestDialog").click();
 await admin.locator("#reqTitle").fill("結合テスト曲");
 await admin.locator("#reqArtist").fill("テスト歌手");
 await admin.locator("#reqName").fill("テスト利用者");
 await admin.locator("#sendRequest").click();
 await admin.locator("#adminTitle").click({clickCount:3});
 await admin.locator("#adminRequests").getByText("結合テスト曲").waitFor({state:"visible"});
 await admin.close();
 console.log("PASS admin stream start and shared request UI");

 const owner=await fixture("owner");
 await owner.locator("#adminTitle").click({clickCount:3});
 await owner.locator("#adminView").waitFor({state:"visible"});
 assert.equal(await owner.locator("#ownerInvite").isVisible(),true);
 await owner.locator("#adminCreateId").fill("test_operator");
 await owner.locator("#adminCreatePassword").fill("SecurePass123456");
 await owner.locator("#adminCreatePasswordConfirm").fill("SecurePass123456");
 await owner.locator("#adminCreateSubmit").click();
 await owner.waitForFunction(
   ()=>document.querySelector("#adminCreateFeedback")?.textContent?.includes("test_operator"),
   null,{timeout:8000});
 assert.equal(await owner.locator("#adminCreatePassword").inputValue(),"");
 assert.equal(await owner.locator("#adminCreatePasswordConfirm").inputValue(),"");
 await owner.close();
 console.log("PASS owner-only ID admin UI and password input cleanup");

 const listener=await fixture("listener");
 assert.equal(await listener.locator("#signedInUser").textContent(),"ゲスト閲覧中");
 assert.equal(await listener.locator("#signedInUser").isVisible(),false);
 assert.equal(await listener.locator("#catalogStatus").isVisible(),false);
 assert.equal(await listener.locator("#loginNav").isVisible(),false);
 assert.equal(await listener.locator("#accountNav").isVisible(),false);
 await listener.locator("#adminTitle").click();
 assert.equal(await listener.locator("#loginNav").isVisible(),false);
 await listener.locator("#adminTitle").click();
 assert.equal(await listener.locator("#loginNav").isVisible(),false);
 await listener.locator("#adminTitle").click();
 assert.equal(await listener.locator("#loginNav").isVisible(),true);
 assert.equal(await listener.locator("#adminView").isVisible(),false);
 await listener.close();
 console.log("PASS hidden admin login appears only after 3 title clicks");
 const longPress=await fixture("listener");
 const titleBox=await longPress.locator("#adminTitle").boundingBox();
 assert.ok(titleBox,"title must be available for long press");
 await longPress.mouse.move(titleBox.x+titleBox.width/2,titleBox.y+titleBox.height/2);
 await longPress.mouse.down();
 await longPress.waitForTimeout(820);
 await longPress.mouse.up();
 assert.equal(await longPress.locator("#loginNav").isVisible(),true);
 await longPress.close();
 console.log("PASS 750ms title hold reveals hidden admin login");
 assert.deepEqual(errors,[],"No uncaught JS errors");
}finally{
 await browser.close();
}