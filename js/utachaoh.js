/*
 * 歌っちゃ王検索（YouTube「カラオケ歌っちゃ王」専用DB）。
 * VPS API: GET /api/v1/utachaoh/search?artist=&title=&limit=
 * 既存の楽曲DB検索とは別系統。1件 = YouTube動画1本。
 */
(() => {
  "use strict";
  const artistInput = document.getElementById("utachaohArtistInput");
  const titleInput = document.getElementById("utachaohTitleInput");
  const helper = document.getElementById("utachaohHelper");
  const results = document.getElementById("utachaohResults");
  if (!artistInput || !titleInput || !helper || !results) return;

  let base = "";
  try {
    const u = new URL(String(window.KEN_CONFIG?.apiBaseUrl || ""));
    const local = ["localhost", "127.0.0.1"].includes(u.hostname);
    if (u.protocol === "https:" || (local && u.protocol === "http:")) base = u.href.replace(/\/+$/, "");
  } catch (_) { /* not configured */ }
  if (!base) {
    helper.textContent = "歌っちゃ王検索は現在利用できません（API未設定）。";
    artistInput.disabled = titleInput.disabled = true;
    return;
  }

  const LIMIT = 50;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (id) => /^[A-Za-z0-9_-]{11}$/.test(id) ? "https://www.youtube.com/watch?v=" + id : "";
  const readings = (o, mainName) => {
    const seen = new Set([String(mainName || "")]);
    return [o?.hiragana, o?.katakana, o?.english].filter((v) => v && !seen.has(v) && seen.add(v)).join(" / ");
  };

  fetch(base + "/api/v1/utachaoh/stats", { mode: "cors", credentials: "omit", cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((s) => {
      if (s && Number.isFinite(s.videoCount) && !artistInput.value && !titleInput.value) {
        helper.textContent = `${s.videoCount.toLocaleString("ja-JP")} 本の動画（${s.artistCount.toLocaleString("ja-JP")} アーティスト）から検索できます。アーティスト名か曲名を入力してください。`;
      }
    })
    .catch(() => {});

  let timer = 0;
  let seq = 0;
  let controller = null;

  function render(items, artist, title) {
    if (!items.length) {
      results.innerHTML = '<div class="empty">見つかりませんでした。表記を変えて（ひらがな・カタカナ・英語など）お試しください。</div>';
      helper.textContent = "0 件";
      return;
    }
    helper.textContent = items.length >= LIMIT ? `${LIMIT} 件以上見つかりました（上位 ${LIMIT} 件を表示）。条件を足すと絞り込めます。` : `${items.length} 件見つかりました。`;
    results.innerHTML = items.map((it) => {
      const url = safeUrl(it.youtubeId);
      const artistName = it.artist?.name || "（アーティスト不明）";
      const songName = it.song?.title || it.videoTitle;
      const aRead = readings(it.artist, it.artist?.name);
      const sRead = readings(it.song, it.song?.title);
      const est = (it.artist?.verification === "estimated" || it.song?.verification === "estimated") ? "（読みは自動推定を含む）" : "";
      return `<div class="song-row utachaoh-row">
  <div class="song-info">
    <div class="song-artist">${esc(artistName)}${aRead ? ` <span class="song-meta" style="display:inline">${esc(aRead)}</span>` : ""}</div>
    <div class="song-title">${esc(songName)}</div>
    ${sRead ? `<div class="song-meta">${esc(sRead)}</div>` : ""}
    <div class="song-meta">${it.videoType ? `［${esc(it.videoType)}］` : ""}${esc(it.videoTitle)} ${esc(est)}</div>
    ${url ? `<div class="song-meta"><a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a></div>` : ""}
  </div>
  <div class="song-actions">${url ? `<a class="button primary" href="${url}" target="_blank" rel="noopener noreferrer">YouTubeで開く</a>` : ""}</div>
</div>`;
    }).join("");
  }

  async function run() {
    const artist = artistInput.value.trim();
    const title = titleInput.value.trim();
    const id = ++seq;
    if (controller) controller.abort();
    if (!artist && !title) {
      results.innerHTML = "";
      helper.textContent = "アーティスト名か曲名を入力してください。";
      return;
    }
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    helper.textContent = "検索中…";
    const url = new URL(base + "/api/v1/utachaoh/search");
    if (artist) url.searchParams.set("artist", artist);
    if (title) url.searchParams.set("title", title);
    url.searchParams.set("limit", String(LIMIT));
    try {
      const res = await fetch(url.toString(), { mode: "cors", credentials: "omit", headers: { Accept: "application/json" }, signal: controller.signal });
      if (res.status === 429) throw Error("busy");
      if (!res.ok) throw Error("HTTP " + res.status);
      const data = await res.json();
      if (id !== seq) return;
      render(Array.isArray(data?.items) ? data.items : [], artist, title);
    } catch (e) {
      if (id !== seq) return;
      results.innerHTML = "";
      helper.textContent = e?.message === "busy" ? "検索が混み合っています。少し待ってからもう一度お試しください。" : "歌っちゃ王検索に接続できませんでした。時間をおいて再度お試しください。";
    } finally {
      clearTimeout(timeout);
    }
  }

  const schedule = () => { clearTimeout(timer); timer = setTimeout(run, 350); };
  artistInput.addEventListener("input", schedule);
  titleInput.addEventListener("input", schedule);
  for (const el of [artistInput, titleInput]) {
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); run(); } });
  }
})();
