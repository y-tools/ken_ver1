import assert from "node:assert/strict";
import { chromium } from "playwright";

// Fail-closed smoke: no local fallback can expose a writable admin panel
// when the Supabase project has not been configured.
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage();
 await page.route("https://cdn.jsdelivr.net/**",route=>route.fulfill({
   status:200,contentType:"application/javascript",body:"window.supabase={createClient:()=>({})};"
 }));
 await page.route("**/config.js*",route=>route.fulfill({
   contentType:"application/javascript",
   body:"window.KEN_CONFIG={supabaseUrl:'',supabasePublishableKey:'',apiBaseUrl:''}"
 }));
 const errors=[];
 page.on("pageerror",e=>errors.push(e.message));
 await page.goto("http://127.0.0.1:8765/",{waitUntil:"domcontentloaded"});
 await page.getByText("共有DB未設定です", {exact:false}).waitFor({timeout:10000});
 assert.equal(await page.locator("#adminView").isVisible(),false);
 assert.equal(await page.locator("#requestDialog").isVisible(),false);
 await page.goto("http://127.0.0.1:8765/login.html",{waitUntil:"domcontentloaded"});
 await page.getByText("Supabase未設定です", {exact:false}).waitFor({timeout:10000});
 assert.ok(await page.locator("#authForm").count());
 assert.deepEqual(errors,[],"No page-level JavaScript errors");
 console.log("PASS shared-denmoku fail-closed auth guard");
}finally{await browser.close();}
