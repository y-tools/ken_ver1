import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const content=readFileSync("data/karaoke-coverage.js","utf8");
const memory=new Map();
const context={
 window:{},document:{readyState:"loading",addEventListener(){}},
 localStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)},
 URL,console,Date,alert(){},setTimeout,Blob
};
vm.createContext(context);
vm.runInContext(content,context,{filename:"karaoke-coverage.js"});
const api=context.window.KEN_KARAOKE;
assert.ok(api?.render && api?.lookup && api?.importCsv);
const song={title:"テスト歌&",artist:"試験アーティスト"};
const before=api.render(song);
assert.ok(before.includes("DAM / JOYSOUND"));
assert.ok(before.includes("収録未確認"));
assert.ok(before.includes("clubdam.com/karaokesearch"));
assert.ok(before.includes("joysound.com/web/search"));
assert.ok(before.includes("&amp;"));
assert.equal(api.lookup(song.title,song.artist),null);
const columns=[
"title","artist","dam_status","dam_url","dam_number","dam_checked_at",
"joysound_status","joysound_url","joysound_number","joysound_checked_at","notes"
].join(",");
const valid=[
'"テスト歌&"','"試験アーティスト"','"available"',
'"https://www.clubdam.com/karaokesearch/song/example"','"1001-01"','"2026-11-05"',
'"searched"','""','""','"2026-11-05"','"公式で確認"'
].join(",");
const file={size:500,text:async()=>columns+"\n"+valid+"\n"};
const imported=await api.importCsv(file);
assert.equal(imported.added,1);
assert.equal(imported.skipped,0);
const row=api.lookup(song.title,song.artist);
assert.equal(row.dam.status,"available");
assert.equal(row.joy.status,"searched");
assert.equal(row.dam.checkedAt,"2026-11-05");
assert.equal(row.notes,"公式で確認");
assert.ok(api.render(song).includes("公式で配信確認済み"));
assert.ok(api.render(song).includes("公式検索で見つからず"));
assert.ok(api.render(song).includes("1001-01"));
const invalid=[
'"未登録"','"不正アーティスト"','"available"',
'"https://bad.example.com/song"','""','""',
'"unknown"','""','""','""','""'
].join(",");
const rejected=await api.importCsv({size:500,text:async()=>columns+"\n"+invalid+"\n"});
assert.equal(rejected.added,0);
assert.equal(rejected.skipped,1);
assert.equal(api.lookup("未登録","不正アーティスト"),null);
console.log("KARAOKE STATUS UNIT TESTS PASSED");
