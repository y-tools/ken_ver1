import assert from "node:assert/strict";
import { chromium } from "playwright";

const base=process.env.TEST_BASE_URL||"http://127.0.0.1:8765/";
const browser=await chromium.launch({headless:true});
const failures=[];
const page=await browser.newPage({viewport:{width:1440,height:900}});
page.on("pageerror",error=>failures.push(error.message));
const check=async (ok,message)=>{assert.ok(ok,message);console.log("PASS "+message)};
const text=locator=>locator.textContent();
const admin=async()=>{
 await page.locator("#adminTitle").dblclick();
 await page.locator("#adminPasswordInput").fill("kny");
 await page.locator("#adminPasswordForm button[type=submit]").click();
 await page.locator("#adminView").waitFor({state:"visible"});
};
try{
 await page.goto(base,{waitUntil:"domcontentloaded",timeout:60000});
 await page.locator("#listenerView").waitFor({state:"visible"});
 await check((await text(page.locator("#listenerStreamLabel")))==="OFF AIR","Listener starts OFF AIR");
 await page.waitForFunction(
  () => document.querySelector("#catalogStatus")?.textContent?.includes("TK専用カタログ"),
  null,{timeout:30000}
 );
 const tkName="TK from 凛として時雨";
 const tkCatalog=await page.evaluate(async()=>await (await fetch("./catalog.json")).json());
 await check(tkCatalog.length===98 && tkCatalog.every(row=>row[1]===tkName),
   "Static catalog contains exactly 98 TK solo songs, no other artists");
 await page.locator("#searchInput").fill("unravel");
 await page.waitForFunction(()=>window.__searchResults?.some(row=>row.title==="unravel"),null,{timeout:30000});
 await check((await page.locator("#searchResults").textContent()).includes("unravel"),
   "TK title search finds unravel");
 await check(await page.locator("#searchArtistInput").count()===1,
   "Separate artist search input remains available");
 await page.locator("#searchArtistInput").fill(tkName);
 await page.waitForTimeout(700);
 const tkResults=await page.evaluate(()=>window.__searchResults||[]);
 await check(tkResults.some(row=>row.title==="unravel")&&tkResults.every(row=>row.artist===tkName),
   "Title + TK artist query returns TK only");
 await page.locator("#searchArtistInput").fill("B'z");
 await page.waitForTimeout(700);
 await check((await page.evaluate(()=>window.__searchResults||[])).length===0,
   "Non-TK artist cannot appear even when a TK title is entered");
 await page.locator("#searchInput").fill("");
 await page.locator("#searchArtistInput").fill("B'z");
 await page.waitForTimeout(700);
 await check((await page.evaluate(()=>window.__searchResults||[])).length===0,
   "Non-TK artist-only query returns no results");
 await page.locator("#searchArtistInput").fill(tkName);
 await page.waitForTimeout(700);
 await check((await page.evaluate(()=>window.__searchResults||[])).every(row=>row.artist===tkName),
   "TK artist-only search returns only TK");
 await page.locator("#searchInput").fill("unravel");
 await page.locator("#searchArtistInput").fill("");
 await page.waitForTimeout(700);
 await check(await page.locator("#searchResults .karaoke-coverage").count()>0,
   "DAM/JOYSOUND verification remains available for TK songs");
 await check((await page.locator("#searchResults .karaoke-coverage").first().textContent()).includes("収録未確認"),
   "Unverified TK songs do not falsely claim karaoke availability");
 await check(await page.locator("#searchResults .karaoke-coverage").first().locator('a[href*="clubdam.com"]').count()>0,
   "DAM official lookup remains available");
 await check(await page.locator("#searchResults .karaoke-coverage").first().locator('a[href*="joysound.com"]').count()>0,
   "JOYSOUND official lookup remains available");
 await check((await page.locator("#today-history-section").count())===1,"Today sung-history section exists");
 await check((await page.locator("#practice-section .section-no").textContent()).trim()==="04","Practice section is number 04");
 await admin();
 await check((await page.locator("#adminView .admin-columns > section").count())===4,"Admin desktop has four columns");
 await check((await page.locator("#adminOnAir").isHidden()),"Admin OFF AIR badge hidden");
 await check((await page.locator("#split-tools").count())===0 || (await page.locator(".split-tools").count())===1,"Right tool area is split");
 await page.locator("#startStream").click();
 await check(await page.locator("#adminOnAir").isVisible(),"Green ON AIR badge appears");
 await page.locator("#toListener").click();
 await check((await text(page.locator("#listenerStreamLabel")))==="ON AIR","Listener ON AIR updates");
 await page.locator("#openRequestDialog").click();
 await page.locator("#reqTitle").fill("統合テスト曲");
 await page.locator("#reqArtist").fill("テストアーティスト");
 await page.locator("#reqName").fill("試験リスナー");
 await page.locator("#sendRequest").click();
 await admin();
 await check(await page.locator("#adminRequests [data-do=research]").count()===1,"GPT search button visible on request");
 await check(await page.locator("#adminRequests a.lyrics-action").count()===1,"Lyrics URL link visible on request");
 const requestCardHeight=await page.locator("#adminRequests .admin-song-entry").first().evaluate(el=>el.getBoundingClientRect().height);
 await check(requestCardHeight<235,"Request row stays compact ("+Math.round(requestCardHeight)+" px)");
 await page.locator("#adminRequests [data-dest=waiting]").check();
 await page.locator("#adminRequests [data-dest=ready]").check();
 await page.locator("#adminRequests [data-do=classify]").click();
 await check((await page.locator("#adminWaiting .song-title").allTextContents()).includes("統合テスト曲"),"Dual classification: waiting");
 await page.locator(".admin-tools > summary").click();
 await page.locator("#adminSongSearch").fill("統合テスト曲");
 await check((await page.locator("#adminSongList").textContent()).includes("統合テスト曲"),"Dual classification: singable");
 await check((await page.locator("#adminSongList .karaoke-coverage").first().textContent()).includes("収録未確認"),
   "Local karaoke status starts unverified");
 await page.locator("#karaokeTitle").fill("統合テスト曲");
 await page.locator("#karaokeArtist").fill("テストアーティスト");
 await page.locator("#karaokeDamStatus").selectOption("available");
 await page.locator("#karaokeDamUrl").fill("https://www.clubdam.com/karaokesearch/song/sample-test");
 await page.locator("#karaokeDamNumber").fill("1234-56");
 await page.locator("#karaokeJoyStatus").selectOption("searched");
 await page.locator("#karaokeNotes").fill("確認時のテスト用記録");
 page.once("dialog", dialog=>dialog.accept());
 await page.locator('#karaokeCheckForm button[type="submit"]').click();
 const verification=await page.evaluate(()=>window.KEN_KARAOKE.lookup("統合テスト曲","テストアーティスト"));
 await check(verification?.dam?.status==="available"&&verification?.joy?.status==="searched",
   "DAM verified and JOYSOUND not found are stored separately");
 await check(Boolean(verification?.dam?.checkedAt)&&Boolean(verification?.joy?.checkedAt),
   "Verification saves checked dates");
 await check((await page.locator("#adminSongList .karaoke-coverage").first().textContent()).includes("公式で配信確認済み"),
   "Saved coverage appears on managed song list");
 await check(await page.locator("#karaokeExport").isVisible(),"Karaoke CSV export control available");
 await check(await page.locator("#karaokeImport").count()===1,"Karaoke CSV import control available");

 await check(await page.locator("#adminWaiting a.lyrics-action").count()===1,"Lyrics URL link visible on waiting song");
 await check(await page.locator("#adminWaiting [data-do=research]").count()===1,"GPT search button visible on waiting song");
 await page.locator("#adminWaiting [data-do=research]").click();
 await check((await page.locator("#gptResearchPrompt").inputValue()).includes("統合テスト曲"),"Research prompt generated");
 await check((await page.locator("#lyricsSearch").getAttribute("href")).includes("google.com/search"),"Lyrics search link generated");
 await page.locator("#adminWaiting [data-do=singing]").click();
 await check((await page.locator("#adminSinging .song-title").allTextContents()).includes("統合テスト曲"),"Singing state entered");
 await check(await page.locator("#adminSinging a.lyrics-action").count()===1,"Lyrics URL link visible on currently singing song");
 await page.locator("#adminSinging [data-do=done]").click();
 await page.locator("#adminChatInput").fill("テスト用の管理メモ");
 await page.locator("#adminChatForm button[type=submit]").click();
 await check((await page.locator("#adminChatHistory").textContent()).includes("テスト用の管理メモ"),"Chat note is saved");
 await page.locator("#adminSongList [data-song-edit]").first().click();
 await page.locator("#songMemo").fill("テスト用メモ保存");
 await page.locator("#songSaveButton").click();
 await check((await page.locator("#adminSongList").textContent()).includes("テスト用メモ保存"),"Song memo persisted");
 await page.locator("#endStream").click();
 await check(await page.locator("#adminOnAir").isHidden(),"OFF AIR after stream ends");
 await check((await page.locator("#reportHistory").textContent()).includes("統合テスト曲"),"Stream report contains song");
 await page.locator("#toListener").click();
 await check((await page.locator("#todaySingingList").textContent()).includes("統合テスト曲"),"Today history lists completed singing");
 await check((await text(page.locator("#listenerStreamLabel")))==="OFF AIR","Listener shows OFF AIR at the end");
 await check(!failures.length,"No uncaught JS errors: "+failures.join(" | "));
 console.log("ALL UI SMOKE TESTS PASSED");
}catch(error){
 console.error("SMOKE TEST FAILED",error);
 if(failures.length)console.error("PAGE ERRORS",failures.join("\n"));
 await page.screenshot({path:"/tmp/ken-smoke-failure.png",fullPage:true}).catch(()=>{});
 process.exitCode=1;
}finally{
 await browser.close();
}
