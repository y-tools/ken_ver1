import assert from "node:assert/strict";
import {chromium} from "playwright";
const browser=await chromium.launch({headless:true});
const errors=[];
async function mockPage(path){
 const page=await browser.newPage();
 page.on("pageerror",e=>errors.push(e.message));
 await page.route("**/config.js*",r=>r.fulfill({contentType:"application/javascript",
   body:"window.KEN_CONFIG={supabaseUrl:'https://example.supabase.co',supabasePublishableKey:'sb_publishable_test_12345678901234567890',apiBaseUrl:''}"}));
 await page.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/**",r=>r.fulfill({
   contentType:"application/javascript",body:path==="login.html"
     ?MOCK_SDK.replace(
       "getUser:async()=>({data:{user:{id:'1',email:'test@example.com'}},error:null}),",
       "getUser:async()=>new Promise(()=>{}),")
     :MOCK_SDK
 }));
 await page.goto("http://127.0.0.1:8765/"+path,{waitUntil:"domcontentloaded",timeout:60000});
 return page;
}
const MOCK_SDK=[
 "window.__testCalls=[];",
 "const log=(name,params)=>window.__testCalls.push({name,params});",
 "window.supabase={createClient:()=>({",
 "auth:{",
 "signInWithPassword:async args=>{log('email',args);return {data:{},error:null};},",
 "signUp:async args=>{log('signup',args);return {data:{},error:null};},",
 "setSession:async args=>{log('setSession',args);return {data:{},error:null};},",
 "getUser:async()=>({data:{user:{id:'1',email:'test@example.com'}},error:null}),",
 "getSession:async()=>({data:{session:{}}}),",
 "signOut:async()=>({error:null})",
 "},",
 "rpc:async(name,params)=>{log(name,params);return {data:name==='set_login_id'?params.p_login_id:false,error:null};},",
 "functions:{invoke:async(name,opts)=>{log(name,opts);return {data:{access_token:'test-access',refresh_token:'test-refresh'},error:null};}},",
 "from:()=>({select:()=>({eq:()=>({single:async()=>({data:{id:'1',role:'listener',display_name:'Tester',login_id:'existing_id'},error:null})})})})",
 "})};"
].join("\n");
try{
 const email=await mockPage("login.html");
 await email.locator("#loginIdentifier").fill("test@example.com");
 await email.locator("#password").fill("password1234");
 await email.locator("#authForm button[type=submit]").click();
 await email.waitForFunction(()=>window.__testCalls.some(x=>x.name==="email"));
 assert.equal(await email.evaluate(()=>window.__testCalls.find(x=>x.name==="email").params.email),"test@example.com");
 assert.equal(await email.evaluate(()=>window.__testCalls.some(x=>x.name==="login-with-id")),false);
 await email.close();
 console.log("PASS email + password remains");

 const id=await mockPage("login.html");
 await id.locator("#loginIdentifier").fill("My_Login");
 await id.locator("#password").fill("password1234");
 await id.locator("#authForm button[type=submit]").click();
 await id.waitForFunction(()=>window.__testCalls.some(x=>x.name==="setSession"));
 assert.equal(await id.evaluate(()=>window.__testCalls.find(x=>x.name==="login-with-id").params.body.login_id),"my_login");
 assert.equal(await id.evaluate(()=>window.__testCalls.some(x=>x.name==="email")),false);
 await id.close();
 console.log("PASS ID login with setSession");

 const reg=await mockPage("register.html");
 assert.equal(await reg.locator("#authForm").count(),0,"Self registration is disabled");
 await reg.getByText("管理者アカウントは招待制です").waitFor();
 await reg.close();
 console.log("PASS invitation-only account registration");

 const account=await mockPage("account.html");
 await account.getByText("existing_id").waitFor();
 await account.locator("#newLoginId").fill("New_Login_ID");
 await account.locator("#accountIdForm button").click();
 await account.waitForFunction(()=>window.__testCalls.some(x=>x.name==="set_login_id"));
 assert.equal(await account.evaluate(()=>window.__testCalls.find(x=>x.name==="set_login_id").params.p_login_id),"new_login_id");
 await account.close();
 console.log("PASS account ID change");
 assert.deepEqual(errors,[]);
}finally{await browser.close();}
