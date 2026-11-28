/*
 * 歌っちゃ王検索（YouTube「カラオケ歌っちゃ王」専用DB）。
 * 「01 楽曲検索」の「歌っちゃ王のみで検索」にチェックを入れると、
 * 同じアーティスト名・曲名の入力欄で歌っちゃ王の動画を検索し、結果欄にURL付きで表示する。
 * VPS API: GET /api/v1/utachaoh/search?artist=&title=&limit=
 * 既存の楽曲DB検索とは別系統。1件 = YouTube動画1本。
 */
(() => {
  "use strict";
  const toggle = document.getElementById("utachaohOnly");
  const artistInput = document.getElementById("searchArtistInput");
  const titleInput = document.getElementById("searchInput");
  const helper = document.getElementById("searchHelper");
  const results = document.getElementById("searchResults");
  if (!toggle || !artistInput || !titleInput || !helper || !results) return;

  const STORE_KEY = "ken.utachaohOnly";
  let base = "";
  try {
    const u = new URL(String(window.KEN_CONFIG?.apiBaseUrl || ""));
    const local = ["localhost", "127.0.0.1"].includes(u.hostname);
    if (u.protocol === "https:" || (local && u.protocol === "http:")) base = u.href.replace(/\/+$/, "");
  } catch (_) { /* not configured */ }

  const LIMIT = 50;
  let stats = null;
  let timer = 0;
  let seq = 0;
  let controller = null;
  let lastKey = "";

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (id) => /^[A-Za-z0-9_-]{11}$/.test(id) ? "https://www.youtube.com/embed/" + id + "?autoplay=0" : "";
  const readings = (o, mainName) => {
    const seen = new Set([String(mainName || "")]);
    return [o?.hiragana, o?.katakana, o?.english].filter((v) => v && !seen.has(v) && seen.add(v)).join(" / ");
  };
  const idleText = () => stats
    ? `歌っちゃ王の ${stats.videoCount.toLocaleString("ja-JP")} 本の動画（${stats.artistCount.toLocaleString("ja-JP")} アーティスト）から検索します。ふりがな・カタカナ・英語でも探せます。`
    : "歌っちゃ王の動画から検索します。ふりがな・カタカナ・英語でも探せます。";

  function render(items) {
    window.__searchResults = [];
    if (!items.length) {
      results.innerHTML = '<div class="empty">歌っちゃ王の動画が見つかりませんでした。表記を変えて（ひらがな・カタカナ・英語など）お試しください。</div>';
      helper.textContent = "歌っちゃ王：0 件";
      return;
    }
    helper.textContent = items.length >= LIMIT
      ? `歌っちゃ王：${LIMIT} 件以上見つかりました（上位 ${LIMIT} 件を表示）。条件を足すと絞り込めます。`
      : `歌っちゃ王：${items.length} 件見つかりました。`;
    // リクエストボタンは app.js の共通処理（data-select-index → リクエスト画面）を使う
    const live = !document.getElementById("sendRequest")?.disabled;
    const picks = [];
    results.innerHTML = items.map((it) => {
      const url = safeUrl(it.youtubeId);
      const artistName = it.artist?.name || "（アーティスト不明）";
      const songName = it.song?.title || it.videoTitle;
      // リスナー画面では読み・英語表記は表示しない（検索には引き続き使う）
      let requestButton = "";
      if (it.artist?.name && songName) {
        const i = picks.push({ title: songName, artist: it.artist.name, source: "catalog" }) - 1;
        requestButton = `<button class="button primary" data-select-index="${i}" type="button"${live ? "" : ' disabled title="配信中のみリクエスト受付"'}>リクエスト</button>`;
      }
      return `<div class="song-row utachaoh-row">
  <div class="song-info">
    <div class="song-artist">${esc(artistName)}</div>
    <div class="song-title">${esc(songName)}</div>
    <div class="song-meta">${it.videoType ? `［${esc(it.videoType)}］` : ""}${esc(it.videoTitle)}</div>
    ${url ? `<div class="song-meta"><a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a></div>` : ""}
  </div>
  <div class="song-actions">${requestButton}${url ? `<a class="button" href="${url}" target="_blank" rel="noopener noreferrer">YouTubeで開く</a>` : ""}</div>
</div>`;
    }).join("");
    window.__searchResults = picks;
  }

  async function run(force = true) {
    if (!toggle.checked) return;
    const artist = artistInput.value.trim();
    const title = titleInput.value.trim();
    const key = artist + "\u0000" + title;
    // 画面の定期更新（app.js）で同じ条件の再検索が走らないようにする
    if (!force && key === lastKey && results.querySelector(".utachaoh-row, .empty")) return;
    lastKey = key;
    const id = ++seq;
    if (controller) controller.abort();
    window.__searchResults = [];
    if (!base) {
      results.innerHTML = "";
      helper.textContent = "歌っちゃ王検索は現在利用できません（API未設定）。";
      return;
    }
    if (!artist && !title) {
      results.innerHTML = '<div class="empty">曲名またはアーティスト名を入力してください。</div>';
      helper.textContent = idleText();
      return;
    }
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    helper.textContent = "歌っちゃ王を検索中…";
    const url = new URL(base + "/api/v1/utachaoh/search");
    if (artist) url.searchParams.set("artist", artist);
    if (title) url.searchParams.set("title", title);
    url.searchParams.set("limit", String(LIMIT));
    try {
      const res = await fetch(url.toString(), { mode: "cors", credentials: "omit", headers: { Accept: "application/json" }, signal: controller.signal });
      if (res.status === 429) throw Error("busy");
      if (!res.ok) throw Error("HTTP " + res.status);
      const data = await res.json();
      if (id !== seq || !toggle.checked) return;
      render(Array.isArray(data?.items) ? data.items : []);
    } catch (e) {
      if (id !== seq || !toggle.checked) return;
      results.innerHTML = "";
      helper.textContent = e?.message === "busy"
        ? "検索が混み合っています。少し待ってからもう一度お試しください。"
        : "歌っちゃ王検索に接続できませんでした。時間をおいて再度お試しください。";
    } finally {
      clearTimeout(timeout);
    }
  }

  // app.js の renderSearch からも呼ばれる（チェックON時）
  window.__utachaohSearch = () => { clearTimeout(timer); timer = setTimeout(() => run(false), 300); };

  toggle.addEventListener("change", () => {
    try { localStorage.setItem(STORE_KEY, toggle.checked ? "1" : "0"); } catch (_) { /* ignore */ }
    lastKey = "";
    if (toggle.checked) {
      clearTimeout(timer);
      run();
    } else {
      seq++;
      if (controller) controller.abort();
      // 通常の楽曲検索に戻す（app.js の検索を再実行）
      titleInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  for (const el of [artistInput, titleInput]) {
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" && toggle.checked) { clearTimeout(timer); run(); } });
  }

  if (base) {
    fetch(base + "/api/v1/utachaoh/stats", { mode: "cors", credentials: "omit", cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s && Number.isFinite(s.videoCount)) {
          stats = s;
          if (toggle.checked && !artistInput.value.trim() && !titleInput.value.trim()) helper.textContent = idleText();
        }
      })
      .catch(() => {});
  }

  let saved = false;
  try { saved = localStorage.getItem(STORE_KEY) === "1"; } catch (_) { /* ignore */ }
  if (saved) {
    toggle.checked = true;
    run();
  }
})();
