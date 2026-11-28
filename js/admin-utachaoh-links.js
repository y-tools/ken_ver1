/*
 * 管理画面の「歌唱中」「歌唱待機楽曲」「リクエスト楽曲」で、
 * 歌っちゃ王（YouTube「カラオケ歌っちゃ王」）に同じアーティスト・曲名の動画があれば
 * 「歌っちゃ王」ボタン（YouTubeのURL）を出す。リクエストのデータには手を加えない。
 */
(() => {
  "use strict";
  let base = "";
  try {
    const u = new URL(String(window.KEN_CONFIG?.apiBaseUrl || ""));
    const local = ["localhost", "127.0.0.1"].includes(u.hostname);
    if (u.protocol === "https:" || (local && u.protocol === "http:")) base = u.href.replace(/\/+$/, "");
  } catch (_) { /* not configured */ }
  if (!base) return;

  const AREAS = ["adminSinging", "adminWaiting", "adminRequests"];
  const norm = (v) => String(v || "").normalize("NFKC").toLowerCase().replace(/[\s・･·\-‐－ー_.,、。!！?？'"’“”()（）\[\]［］「」『』~〜]/g, "");
  const cache = new Map(); // key -> Promise<url|"">

  function lookup(artist, title) {
    const key = norm(artist) + "\u0000" + norm(title);
    if (cache.has(key)) return cache.get(key);
    const url = new URL(base + "/api/v1/utachaoh/search");
    url.searchParams.set("artist", artist);
    url.searchParams.set("title", title);
    url.searchParams.set("limit", "20");
    const p = fetch(url.toString(), { mode: "cors", credentials: "omit", headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(Error("HTTP " + r.status))))
      .then((data) => {
        const items = Array.isArray(data?.items) ? data.items : [];
        const hit = items.find((it) => norm(it.artist?.name) === norm(artist) && norm(it.song?.title) === norm(title));
        return hit && /^[A-Za-z0-9_-]{11}$/.test(hit.youtubeId || "") ? "https://www.youtube.com/watch?v=" + hit.youtubeId : "";
      })
      .catch(() => { cache.delete(key); return ""; });
    cache.set(key, p);
    if (cache.size > 300) cache.delete(cache.keys().next().value);
    return p;
  }

  function decorate(entry) {
    if (entry.dataset.utachaohChecked) return;
    entry.dataset.utachaohChecked = "1";
    const artist = entry.querySelector(".song-artist")?.getAttribute("title") || entry.querySelector(".song-artist")?.textContent || "";
    const title = entry.querySelector(".song-title")?.getAttribute("title") || entry.querySelector(".song-title")?.textContent || "";
    if (!artist.trim() || !title.trim()) return;
    lookup(artist.trim(), title.trim()).then((url) => {
      if (!url || !entry.isConnected || entry.querySelector(".utachaoh-link")) return;
      const boxes = entry.querySelectorAll(".song-actions");
      const box = boxes[boxes.length - 1];
      if (!box) return;
      const a = document.createElement("a");
      a.className = "button utachaoh-link";
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "歌っちゃ王";
      a.title = "歌っちゃ王（YouTube）で開く";
      box.appendChild(a);
    });
  }

  function scan() {
    for (const id of AREAS) {
      const el = document.getElementById(id);
      if (el) el.querySelectorAll(".admin-song-entry").forEach(decorate);
    }
  }

  // app.js は一覧を作り直すので、変化のたびに付け直す
  for (const id of AREAS) {
    const el = document.getElementById(id);
    if (el) new MutationObserver(scan).observe(el, { childList: true, subtree: true });
  }
  scan();
})();
