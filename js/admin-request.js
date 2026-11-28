/*
 * 管理画面の一番下「管理者リクエスト送信」。
 * 楽曲データベース（または歌っちゃ王）から探して、そのままリクエストを送る。
 * リクエスト者は記録上 "__admin__" とし、画面にはリクエスト者・メッセージを出さない（app.js 側で非表示）。
 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const artistInput = $("adminReqArtist"), titleInput = $("adminReqTitle"), toggle = $("adminReqUtachaoh");
  const results = $("adminReqResults"), status = $("adminReqStatus"), direct = $("adminReqDirect");
  if (!artistInput || !titleInput || !toggle || !results || !status || !direct) return;

  const NICK = "__admin__";
  const LIMIT = 50;
  let base = "";
  try {
    const u = new URL(String(window.KEN_CONFIG?.apiBaseUrl || ""));
    const local = ["localhost", "127.0.0.1"].includes(u.hostname);
    if (u.protocol === "https:" || (local && u.protocol === "http:")) base = u.href.replace(/\/+$/, "");
  } catch (_) { /* not configured */ }

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (v) => String(v || "").normalize("NFKC").toLowerCase().replace(/[\s・･·\-‐－ー_.,、。!！?？'"’“”()（）\[\]［］「」『』~〜]/g, "");
  const isLive = () => !$("sendRequest")?.disabled;
  let picks = [];
  let seq = 0, timer = 0, sending = false;

  function draw(items, note) {
    picks = items;
    const live = isLive();
    status.textContent = note;
    results.innerHTML = items.length ? items.map((it, i) => {
      const yt = it.url ? `<a class="button" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">YouTubeで開く</a>` : "";
      return `<div class="song-row"><div class="song-info">
  <div class="song-artist">${esc(it.artist)}</div>
  <div class="song-title">${esc(it.title)}</div>
  ${it.sub ? `<div class="song-meta">${esc(it.sub)}</div>` : ""}
</div><div class="song-actions"><button type="button" class="button primary" data-admin-req="${i}"${live ? "" : ' disabled title="配信中のみリクエスト受付"'}>リクエスト</button>${yt}</div></div>`;
    }).join("") : "";
  }

  async function searchDb(artist, title) {
    const vps = window.KEN_VPS_SEARCH;
    if (!vps) throw Error("楽曲データベースに接続できません");
    const reqs = [];
    if (title) reqs.push(vps.search(title, "title", 50));
    if (artist) reqs.push(vps.search(artist, "artist", 50));
    const res = await Promise.allSettled(reqs);
    if (res.every((r) => r.status === "rejected")) throw Error("楽曲データベースに接続できません");
    const at = norm(artist), tt = norm(title);
    const field = (s, side) => {
      const r = s.readings?.[side] || {};
      return [s[side], r.hiragana, r.katakana, r.romaji, r.english].filter(Boolean).map(norm);
    };
    const found = new Map();
    for (const r of res) {
      if (r.status !== "fulfilled") continue;
      for (const s of r.value?.items || []) {
        if (!s?.title || !s?.artist) continue;
        if (tt && !field(s, "title").some((v) => v.includes(tt))) continue;
        if (at && !field(s, "artist").some((v) => v.includes(at))) continue;
        const k = norm(s.title) + "\u0000" + norm(s.artist);
        if (!found.has(k)) found.set(k, { title: s.title, artist: s.artist, sub: s.releaseDate ? String(s.releaseDate).slice(0, 4) : "" });
      }
    }
    return [...found.values()].slice(0, LIMIT);
  }

  async function searchUtachaoh(artist, title) {
    if (!base) throw Error("歌っちゃ王検索は現在利用できません");
    const url = new URL(base + "/api/v1/utachaoh/search");
    if (artist) url.searchParams.set("artist", artist);
    if (title) url.searchParams.set("title", title);
    url.searchParams.set("limit", String(LIMIT));
    const res = await fetch(url.toString(), { mode: "cors", credentials: "omit", headers: { Accept: "application/json" } });
    if (!res.ok) throw Error(res.status === 429 ? "検索が混み合っています。少し待ってからお試しください" : "歌っちゃ王検索に接続できませんでした");
    const data = await res.json();
    return (Array.isArray(data?.items) ? data.items : []).filter((it) => it.artist?.name && (it.song?.title || it.videoTitle)).map((it) => ({
      title: it.song?.title || it.videoTitle,
      artist: it.artist.name,
      sub: (it.videoType ? `［${it.videoType}］` : "") + (it.videoTitle || ""),
      url: /^[A-Za-z0-9_-]{11}$/.test(it.youtubeId || "") ? "https://www.youtube.com/embed/" + it.youtubeId + "?autoplay=0" : "",
    }));
  }

  async function run() {
    const id = ++seq;
    const artist = artistInput.value.trim(), title = titleInput.value.trim();
    direct.disabled = !(artist && title);
    if (!artist && !title) { draw([], "アーティスト名か曲名を入力すると検索します（1文字から）。"); return; }
    status.textContent = "検索中…";
    try {
      const items = toggle.checked ? await searchUtachaoh(artist, title) : await searchDb(artist, title);
      if (id !== seq) return;
      const where = toggle.checked ? "歌っちゃ王" : "楽曲データベース";
      draw(items, items.length
        ? `${where}：${items.length}${items.length >= LIMIT ? "件以上（上位" + LIMIT + "件を表示）" : "件"}見つかりました。`
        : `${where}で見つかりませんでした。アーティスト名と曲名を入れて「自由入力で送信」で送れます。`);
    } catch (e) {
      if (id !== seq) return;
      draw([], String(e?.message || "検索できませんでした"));
    }
  }
  const schedule = () => { clearTimeout(timer); timer = setTimeout(run, 250); };

  async function send(title, artist) {
    if (sending) return;
    const shared = window.KEN_SHARED;
    if (!shared?.isAdmin?.()) { status.textContent = "管理者としてログインしてください。"; return; }
    if (!isLive()) { status.textContent = "配信終了中はリクエストを送れません。"; return; }
    if (!title || !artist || title.length > 120 || artist.length > 120) { status.textContent = "曲名・アーティスト名を確認してください。"; return; }
    sending = true;
    status.textContent = "送信しています…";
    try {
      await shared.action("request_add", { title, artist, nickname: NICK, message: "", nonce: crypto.randomUUID() });
      status.textContent = `送信しました：${artist} / ${title}（受付リクエストに入りました）`;
    } catch (e) {
      status.textContent = "送信できませんでした：" + String(e?.message || e).slice(0, 100);
    } finally {
      sending = false;
    }
  }

  results.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-admin-req]");
    if (!btn) return;
    const it = picks[Number(btn.dataset.adminReq)];
    if (it) void send(it.title, it.artist);
  });
  direct.addEventListener("click", () => void send(titleInput.value.trim(), artistInput.value.trim()));
  artistInput.addEventListener("input", schedule);
  titleInput.addEventListener("input", schedule);
  toggle.addEventListener("change", () => { clearTimeout(timer); run(); });
  $("adminReqClear")?.addEventListener("click", () => { artistInput.value = ""; titleInput.value = ""; run(); });
  // 配信開始・終了でボタンの押せる/押せないを合わせる
  const sendBtn = $("sendRequest");
  if (sendBtn) new MutationObserver(() => { if (picks.length) draw(picks, status.textContent); }).observe(sendBtn, { attributes: true, attributeFilter: ["disabled"] });
  run();
})();
