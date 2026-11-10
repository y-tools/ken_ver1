/* Shared Supabase client and authenticated synchronization.
 * Browser receives only publishable key; RLS + RPC enforce permissions.
 * Existing localStorage is NEVER used as server truth.
 */
(() => {
  "use strict";
  const config = window.KEN_CONFIG || {};
  const url = String(config.supabaseUrl || "").trim();
  const key = String(config.supabasePublishableKey || "").trim();
  const SDK = window.supabase;
  const configured = /^https:\/\/[a-z0-9-]+\.supabase\.co$/i.test(url) &&
    key.length > 20 && SDK && typeof SDK.createClient === "function";
  const client = configured ? SDK.createClient(url, key, {
    auth: {persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}
  }) : null;
  let role = "guest";
  let loggedIn = null;
  let channel = null;
  let currentVersion = -1;
  let polling = null;
  let refreshing = null;
  let onSnapshot = null;
  let lastError = null;
  let stopPresence = null;

  async function authenticate() {
    if (!client) throw Error("Supabaseの設定がありません。config.js を設定してください。");
    const {data:{user},error} = await client.auth.getUser();
    if (error || !user) {
      location.replace("./login.html?next=" + encodeURIComponent(location.pathname + location.search));
      return null;
    }
    const {data:profile,error:profileError} = await client.from("profiles")
      .select("id,display_name,role,login_id").eq("id",user.id).single();
    if (profileError || !profile) throw Error("ユーザー情報を取得できませんでした");
    role = profile.role;
    loggedIn = {user,profile};
    return loggedIn;
  }
  async function enterSite() {
    if (!client) throw Error("Supabaseの設定がありません");
    // The public listener page is available without a login or account.
    const {data:{user},error}=await client.auth.getUser();
    if (!error && user) {
      const {data:profile, error:profileError}=await client.from("profiles")
        .select("id,display_name,role,login_id").eq("id",user.id).single();
      if (!profileError && profile && (profile.role==="owner"||profile.role==="admin")) {
        role=profile.role;
        loggedIn={user,profile};
        return loggedIn;
      }
    }
    role="guest";
    loggedIn=null;
    return null;
  }
  async function snapshot() {
    const {data,error} = await client.rpc(loggedIn ? "denmoku_snapshot" : "denmoku_public_snapshot");
    if (error) throw error;
    if (!data || !Array.isArray(data.requests)) throw Error("共有データの形式が正しくありません");
    currentVersion = Math.max(currentVersion,Number(data.version || 0));
    return data;
  }
  async function refresh(force=false) {
    if (refreshing) return refreshing;
    refreshing=(async()=>{
      if (!client) return;
      if (!force) {
        const {data,error} = await client.from("sync_version").select("version").eq("id",true).single();
        if (error) throw error;
        if (Number(data.version) <= currentVersion) return;
      }
      const data = await snapshot();
      onSnapshot?.(data);
      lastError=null;
    })().catch(error=>{
      lastError=error;
      console.warn("Ken shared refresh error:",error);
      throw error;
    }).finally(()=>{refreshing=null;});
    return refreshing;
  }
  async function action(name,payload={}) {
    if (!loggedIn || !(role==="owner"||role==="admin")) throw Error("管理者ログインが必要です");
    const {error} = await client.rpc("denmoku_action",{p_action:name,p_data:payload});
    if (error) throw error;
    await refresh(true);
  }
  async function requestGuest(payload) {
    if(!client || !configured)throw Error("共有サーバーが設定されていません");
    // This public endpoint is never given a service-role token by the browser.
    const r=await fetch(url+"/functions/v1/public-request",{
      method:"POST",
      headers:{"Content-Type":"application/json","apikey":key},
      body:JSON.stringify(payload),
    });
    let data;
    try{data=await r.json();}catch{throw Error("リクエスト送信の応答が不正です");}
    if(!r.ok || !data?.ok)throw Error(data?.error||"リクエストを送信できませんでした");
    await refresh(true).catch(()=>{});
    return data;
  }
  function subscribe(callback) {
    onSnapshot = callback;
    if (channel) client.removeChannel(channel);
    const check=()=>{void refresh().catch(()=>{});};
    channel=client.channel("denmoku-shared-v2")
      .on("postgres_changes",{
        event:"UPDATE",schema:"public",table:"sync_version",filter:"id=eq.true"
      },check)
      .subscribe(status=>{
        // Immediately verify the server state after connecting/reconnecting.
        if(status==="SUBSCRIBED")check();
        if(status==="CHANNEL_ERROR"||status==="TIMED_OUT"||status==="CLOSED")check();
      });
    // The ON AIR state is authoritative in Supabase, never a browser-local flag.
    // Keep checking even in a background tab/embedded viewer: a missed Realtime
    // notification must not leave a listener indefinitely showing OFF AIR.
    if(polling)clearInterval(polling);
    polling=setInterval(check,4000);
    const onVisible=()=>{if(!document.hidden)check();};
    window.addEventListener("focus",check);
    window.addEventListener("online",check);
    document.addEventListener("visibilitychange",onVisible);
    return ()=>{
      if(channel)client.removeChannel(channel);
      clearInterval(polling);polling=null;
      window.removeEventListener("focus",check);
      window.removeEventListener("online",check);
      document.removeEventListener("visibilitychange",onVisible);
    };
  }
  function startPresence(onUsers=()=>{}) {
    if(!client||!loggedIn)throw Error("Presence requires login");
    // One stable ID for this browser tab, not one user ID provided by the client.
    const storageKey="ken-denmoku-presence-tab-v1";
    let tabId;
    try{tabId=sessionStorage.getItem(storageKey);}catch(_){}
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(tabId||"")){
      tabId=crypto.randomUUID();
      try{sessionStorage.setItem(storageKey,tabId);}catch(_){}
    }
    const adminAccess=role==="admin"||role==="owner";
    let running=true,heartbeatTimer=null,listTimer=null,onlineChannel=null,changeTimer=null;
    let listInFlight=null;
    const heartbeat=async()=>{
      if(!running)return;
      const {error}=await client.rpc("presence_heartbeat",{p_tab_id:tabId});
      if(error)throw error;
    };
    const list=async()=>{
      if(!running||!adminAccess)return;
      if(listInFlight)return listInFlight;
      listInFlight=(async()=>{
        const {data,error}=await client.rpc("presence_admin_list");
        if(error)throw error;
        if(!Array.isArray(data))throw Error("Invalid online user list");
        if(running)onUsers(data,null);
      })().catch(error=>{
        if(running)onUsers(null,error);
      }).finally(()=>{listInFlight=null;});
      return listInFlight;
    };
    // Throttle bursts of realtime heartbeat events; server still enforces identity.
    const queueList=()=>{
      if(!running||!adminAccess||changeTimer)return;
      changeTimer=setTimeout(()=>{changeTimer=null;void list();},250);
    };
    const ping=()=>{void heartbeat().catch(e=>console.warn("Online heartbeat failed",e));};
    const wake=()=>{ping();queueList();};
    const onVisible=()=>{if(!document.hidden)wake();};
    if(adminAccess){
      onlineChannel=client.channel("denmoku-online-v2")
        .on("postgres_changes",{
          event:"*",schema:"public",table:"online_sessions"
        },queueList)
        .subscribe(status=>{
          if(status==="SUBSCRIBED")queueList();
          if(status==="CHANNEL_ERROR"||status==="TIMED_OUT")queueList();
        });
      listTimer=setInterval(queueList,5000); // fallback if Realtime misses an event
    }
    ping();queueList();
    heartbeatTimer=setInterval(ping,15000);
    window.addEventListener("focus",wake);
    window.addEventListener("online",wake);
    document.addEventListener("visibilitychange",onVisible);
    const stop=async()=>{
      if(!running)return;
      running=false;
      clearInterval(heartbeatTimer);
      clearInterval(listTimer);
      clearTimeout(changeTimer);
      if(onlineChannel)await client.removeChannel(onlineChannel);
      window.removeEventListener("focus",wake);
      window.removeEventListener("online",wake);
      document.removeEventListener("visibilitychange",onVisible);
      const {error}=await client.rpc("presence_leave",{p_tab_id:tabId});
      if(error)throw error;
    };
    stopPresence=stop;
    return stop;
  }
  async function signOut() {
    if(stopPresence){
      try{await stopPresence();}catch(error){console.warn("Presence logout failed",error);}
      stopPresence=null;
    }
    if(client)await client.auth.signOut();
    location.replace("./login.html");
  }
  window.KEN_SHARED=Object.freeze({
    client,configured,authenticate,enterSite,snapshot,action,requestGuest,subscribe,refresh,signOut,startPresence,
    isAdmin:()=>role==="admin"||role==="owner",
    isOwner:()=>role==="owner",
    profile:()=>loggedIn?.profile || null,
    lastError:()=>lastError
  });
})();