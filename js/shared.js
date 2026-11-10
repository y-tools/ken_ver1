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
  let role = "listener";
  let loggedIn = null;
  let channel = null;
  let currentVersion = -1;
  let polling = null;
  let refreshing = null;
  let onSnapshot = null;
  let lastError = null;

  async function authenticate() {
    if (!client) throw Error("Supabaseの設定がありません。config.js を設定してください。");
    const {data:{user},error} = await client.auth.getUser();
    if (error || !user) {
      location.replace("./login.html?next=" + encodeURIComponent(location.pathname + location.search));
      return null;
    }
    const {data:profile,error:profileError} = await client.from("profiles")
      .select("id,display_name,role").eq("id",user.id).single();
    if (profileError || !profile) throw Error("ユーザー情報を取得できませんでした");
    role = profile.role;
    loggedIn = {user,profile};
    return loggedIn;
  }
  async function snapshot() {
    const {data,error} = await client.rpc("denmoku_snapshot");
    if (error) throw error;
    if (!data || !Array.isArray(data.requests)) throw Error("共有データの形式が正しくありません");
    currentVersion = Math.max(currentVersion,Number(data.version || 0));
    return data;
  }
  async function refresh(force=false) {
    if (refreshing) return refreshing;
    refreshing=(async()=>{
      if (!client || !loggedIn) return;
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
    if (!loggedIn) throw Error("ログインが必要です");
    const {error} = await client.rpc("denmoku_action",{p_action:name,p_data:payload});
    if (error) throw error;
    await refresh(true);
  }
  function subscribe(callback) {
    onSnapshot = callback;
    if (channel) client.removeChannel(channel);
    channel=client.channel("denmoku-shared-v2")
      .on("postgres_changes",{
        event:"UPDATE",schema:"public",table:"sync_version",filter:"id=eq.true"
      },()=>{void refresh().catch(()=>{});})
      .subscribe(status=>{ if(status==="SUBSCRIBED") void refresh().catch(()=>{}); });
    // Reconnect, tab suspension and publication misconfiguration recovery.
    if (polling) clearInterval(polling);
    polling=setInterval(()=>{if(!document.hidden)void refresh().catch(()=>{});},12000);
    window.addEventListener("focus",()=>void refresh().catch(()=>{}));
    document.addEventListener("visibilitychange",()=>{if(!document.hidden)void refresh().catch(()=>{});});
    return ()=>{if(channel)client.removeChannel(channel);clearInterval(polling);};
  }
  async function signOut() {
    if (client) await client.auth.signOut();
    location.replace("./login.html");
  }
  window.KEN_SHARED=Object.freeze({
    client,configured,authenticate,snapshot,action,subscribe,refresh,signOut,
    isAdmin:()=>role==="admin"||role==="owner",
    isOwner:()=>role==="owner",
    profile:()=>loggedIn?.profile || null,
    lastError:()=>lastError
  });
})();