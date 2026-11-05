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
  () => window.KEN_CATALOG_STATS?.vocadbSourceCount===100000,
  null,{timeout:90000}
 );
 const stats=await page.evaluate(()=>window.KEN_CATALOG_STATS);
 await check(stats.extensionSourceCount===140983,"New catalog extension contains 140983 songs");
 await check(stats.searchableUniqueCount===300000 && stats.targetReached===true,"Exactly 300000 unique songs are searchable");
 await page.locator("#searchInput").fill("流恋情歌");
 await page.waitForFunction(()=>document.querySelector("#searchResults")?.textContent?.includes("流恋情歌"),null,{timeout:30000});
 await check((await page.locator("#searchResults").textContent()).includes("流恋情歌"),"Japanese song catalog search succeeds");
 await check(await page.locator("#searchResults .karaoke-coverage").count()>0,"DAM and JOYSOUND verification panel shown on catalog results");
 await check((await page.locator("#searchResults .karaoke-coverage").first().textContent()).includes("収録未確認"),
  "Unverified titles do not claim karaoke availability");
 await check(await page.locator("#searchResults .karaoke-coverage").first().locator('a[href*="clubdam.com"]').count()>0,
  "DAM official lookup link included for each song");
 await check(await page.locator("#searchResults .karaoke-coverage").first().locator('a[href*="joysound.com"]').count()>0,
  "JOYSOUND official lookup link included for each song");
 await check(await page.locator('[data-search-mode="title"]').getAttribute("aria-pressed")==="true","Title search selected by default");
 const titleResult=await page.locator("#searchResults").textContent();
 await page.locator('[data-search-mode="artist"]').click();
 await check(await page.locator('[data-search-mode="artist"]').getAttribute("aria-pressed")==="true","Artist search switch activates");
 await check((await page.locator("#searchInput").inputValue())==="流恋情歌","Switch retains the existing query");
 await page.waitForTimeout(400);
 await check(!(await page.locator("#searchResults").textContent()).includes("流恋情歌"),"Artist search excludes a title-only match");
 await page.locator('[data-search-mode="title"]').click();
 await check(await page.locator('[data-search-mode="title"]').getAttribute("aria-pressed")==="true","Switch back to title search works");
 await check((await page.locator("#searchResults").textContent()).includes("流恋情歌"),"Title results return on switching back");
 const mbMetadata=await page.evaluate(async()=>{
  const manifest=await window.KEN_MB_SEARCH.ready();
  if(!manifest)return null;
  const indexResponse=await fetch("./data/musicbrainz_700k/bucket_00.json");
  if(!indexResponse.ok)return null;
  const sample=(await indexResponse.json()).find(row=>row[0]&&Array.from(row[0]).length>=2);
  if(!sample)return null;
  const normalized=sample[0].normalize("NFKC").toLowerCase()
   .replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-96))
   .replace(/[\s・ー‐-]/g,"");
  const query=Array.from(normalized).slice(0,2).join("");
  const results=await window.KEN_MB_SEARCH.search(query,30);
  return {manifest,sample,query,results};
 });
 await check(mbMetadata?.manifest?.targetUnique===1000000 && mbMetadata?.manifest?.additionalUnique===700000,
  "One million song manifest is published and verified");
 await check(Array.isArray(mbMetadata.results)&&mbMetadata.results.length>0,
  "On-demand MusicBrainz prefix search returns songs");
 await page.locator("#searchInput").fill(mbMetadata.query);
 await page.waitForFunction(q=>window.__searchResults?.some(row=>row.source==="catalog"&&
  (row.title.toLowerCase().includes(q)||row.artist.toLowerCase().includes(q))),mbMetadata.query,{timeout:30000});
 await check((await page.locator("#searchResults .song-row").count())>0,
  "Additional MusicBrainz song can be searched in the listener UI");
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
