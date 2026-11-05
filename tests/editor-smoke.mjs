import assert from "node:assert/strict";
import { chromium } from "playwright";

const base=process.env.TEST_BASE_URL||"http://127.0.0.1:8765/";
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}});
const pageErrors=[];
page.on("pageerror",error=>pageErrors.push(error.message));
const state={
 artist:{id:101,name:"テスト歌手",version:"2026-11-06T00:00:00+00:00"},
 songs:[{id:202,title:"テスト曲",version:"2026-11-06T00:00:00+00:00",
         releasePrecision:"unknown",releaseYear:null,releaseMonth:null,releaseDay:null}],
 aliases:[],
 songAliases:[],
};
const answer=(route,body,status=200)=>{
 route.fulfill({status,contentType:"application/json",headers:{
  "access-control-allow-origin":"*",
  "access-control-allow-methods":"GET,POST,OPTIONS",
  "access-control-allow-headers":"authorization,content-type,accept",
 },body:JSON.stringify(body)});
};
await page.route("https://kenapi.153-127-64-17.sslip.io/api/admin/**",async route=>{
 const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method();
 if(method==="OPTIONS")return answer(route,{},200);
 if(path==="/api/admin/login")return answer(route,{token:"test-only-bearer-token",expiresIn:1800});
 if(!req.headers().authorization)return answer(route,{detail:"ログインしてください"},401);
 if(path==="/api/admin/artists"&&method==="GET")return answer(route,{items:[state.artist]});
 if(path==="/api/admin/artists/101"&&method==="GET")
   return answer(route,{artist:state.artist,aliases:state.aliases,songs:state.songs,total:1,offset:0,limit:50});
 if(path==="/api/admin/songs/202"&&method==="GET")
   return answer(route,{song:{...state.songs[0],artistId:101},aliases:state.songAliases});
 if(path==="/api/admin/artists/101"&&method==="POST"){
  state.artist={...state.artist,...req.postDataJSON(),version:"2026-11-06T00:01:00+00:00"};
  return answer(route,{artist:state.artist});
 }
 if(path==="/api/admin/songs/202"&&method==="POST"){
  state.songs[0]={...state.songs[0],...req.postDataJSON(),version:"2026-11-06T00:02:00+00:00"};
  return answer(route,{song:state.songs[0]});
 }
 if(path==="/api/admin/aliases"&&method==="POST"){
  const incoming=req.postDataJSON();
  const alias={id:303,kind:incoming.kind,value:incoming.value,
    verification:"human_confirmed",sourceUrl:incoming.sourceUrl,checkedAt:"2026-11-06"};
  if(incoming.side==="artist")state.aliases=[alias];else state.songAliases=[alias];
  return answer(route,{alias});
 }
 if(path==="/api/admin/audit")return answer(route,{items:[]});
 if(path==="/api/admin/logout")return answer(route,{ok:true});
 return answer(route,{detail:"Mock route not found "+method+" "+path},404);
});
try{
 await page.goto(base+"database-editor.html",{waitUntil:"domcontentloaded"});
 await page.locator("#loginPanel").waitFor({state:"visible"});
 assert.equal(await page.locator("#editorPanel").isVisible(),false);
 await page.locator("#adminSecret").fill("test-only-long-password");
 await page.locator("#loginForm button[type=submit]").click();
 await page.locator("#editorPanel").waitFor({state:"visible"});
 console.log("PASS Secure login screen and unlock");
 await page.locator("#artistSearch").fill("テスト");
 await page.locator("#artistSearchForm button[type=submit]").click();
 await page.locator("#artistResults button").first().click();
 await page.locator("#artistPanel").waitFor({state:"visible"});
 assert.equal(await page.locator("#artistName").inputValue(),"テスト歌手");
 console.log("PASS Artist search and selection");
 await page.locator("#songList button").first().click();
 await page.locator("#songPanel").waitFor({state:"visible"});
 await page.locator("#songForm [name=title]").fill("テスト曲・改訂版");
 await page.locator("#songForm [name=releasePrecision]").selectOption("day");
 await page.locator("#songForm [name=releaseYear]").fill("2024");
 await page.locator("#songForm [name=releaseMonth]").fill("11");
 await page.locator("#songForm [name=releaseDay]").fill("6");
 await page.locator("#songForm button[type=submit]").click();
 await page.waitForFunction(()=>document.querySelector("#songForm [name=title]")?.value==="テスト曲・改訂版");
 assert.equal(state.songs[0].releaseYear,2024);
 console.log("PASS Song title and exact release date editing");
 await page.locator("#songAliasForm [name=kind]").selectOption("hiragana");
 await page.locator("#songAliasForm [name=value]").fill("てすときょく");
 await page.locator("#songAliasForm button[type=submit]").click();
 await page.waitForFunction(()=>document.querySelector("#songAliases")?.textContent?.includes("てすときょく"));
 assert.equal(state.songAliases[0].verification,"human_confirmed");
 console.log("PASS Four-way song name editor and saved alias");
 await page.locator("#logout").click();
 await page.locator("#loginPanel").waitFor({state:"visible"});
 assert.equal(await page.locator("#editorPanel").isVisible(),false);
 assert.deepEqual(pageErrors,[]);
 console.log("ALL DATABASE EDITOR BROWSER TESTS PASSED");
}finally{
 await browser.close();
}
