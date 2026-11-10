/* Auth pages. Supabase Auth manages credentials; this code never stores passwords. */
(async()=>{
 "use strict";
 const $=s=>document.querySelector(s);
 const C=window.KEN_SHARED;
 const form=$("#authForm"), feedback=$("#feedback");
 const mode=document.body.dataset.authPage;
 const show=text=>{feedback.textContent=text;};
 if(!C?.configured){show("Supabase未設定です。公開URLとpublishable keyをconfig.jsに設定してください。");return;}
 const client=C.client;
 const link=(name)=>new URL(name,location.href).href;
 const openNext=()=>{
  const next=new URLSearchParams(location.search).get("next");
  if(next && /^\/ken_ver1\/(?!\/)/.test(next) && !next.includes("//") && !next.includes("\\"))
    return next;
  return null;
 };
 async function route(){
  // Admin promotion is allowed only for a currently valid invitation and verified email.
  const {error:acceptError}=await client.rpc("accept_admin_invite");
  if(acceptError)console.warn("Invite acceptance unavailable",acceptError);
  const auth=await C.authenticate();
  if(!auth)return;
  location.replace(openNext() || (C.isAdmin()?"./admin.html":"./index.html"));
 }
 if(mode==="callback"){
  const initialHash=new URLSearchParams(location.hash.replace(/^#/,""));
  const initialQuery=new URLSearchParams(location.search);
  const isInvite=initialHash.get("type")==="invite" || initialQuery.get("type")==="invite";
  show("認証リンクを確認しています…");
  try{
   const query=new URLSearchParams(location.search);
   const token=query.get("token_hash"),type=query.get("type");
   if(token&&type){
    const {error}=await client.auth.verifyOtp({token_hash:token,type});
    if(error)throw error;
   }
   const {data:{session},error}=await client.auth.getSession();
   if(error||!session)throw Error("ログインセッションを確認できません");
   if(isInvite){
    $("#invitePasswordStep").hidden=false;
    show("管理者として使うパスワードを設定してください。");
    $("#invitePasswordStep").addEventListener("submit",async e=>{
     e.preventDefault();
     if($("#invitePassword").value.length<8){show("8文字以上で設定してください。");return;}
     const {error:changeError}=await client.auth.updateUser({password:$("#invitePassword").value});
     if(changeError){show("パスワード設定に失敗しました。再度お試しください。");return;}
     await route();
    });
   }else await route();
  }catch(e){show("認証できませんでした。ログイン画面からやり直してください。");console.error(e);}
  return;
 }
 if(mode==="admin"){
  show("権限を確認しています…");
  try{
   const auth=await C.authenticate();
   if(!auth)return;
   if(!C.isAdmin()){location.replace("./index.html");return;}
   location.replace("./index.html?admin=1");
  }catch(e){show("管理者権限を取得できませんでした。");console.error(e);}
  return;
 }
 if(mode==="account"){
  try{
    const account=await C.authenticate();
    if(!account)return;
    const current=$("#currentLoginId");
    const update=id=>{current.textContent=id||"未設定";};
    update(account.profile.login_id);
    $("#accountIdForm").addEventListener("submit",async e=>{
      e.preventDefault();
      const loginId=$("#newLoginId").value.trim().toLowerCase();
      if(!/^[a-z][a-z0-9._-]{3,23}$/.test(loginId)){
        show("ログインIDの形式を確認してください");return;
      }
      const button=$("#accountIdForm").querySelector("button");
      button.disabled=true;
      const {data,error}=await client.rpc("set_login_id",{p_login_id:loginId});
      button.disabled=false;
      if(error){show(error.code==="23505"?"そのログインIDは利用できません":"ログインIDを保存できませんでした");return;}
      update(data);show("ログインIDを更新しました");
    });
  }catch(err){show("アカウント情報を取得できませんでした");console.error(err);}
  return;
 }
 if(mode==="reset"){
  const {data:{session}}=await client.auth.getSession();
  if(session) {
   $("#emailStep").hidden=true;$("#passwordStep").hidden=false;
  }
  client.auth.onAuthStateChange((event,session)=>{
   if(event==="PASSWORD_RECOVERY"&&session){$("#emailStep").hidden=true;$("#passwordStep").hidden=false;}
  });
  $("#emailStep").addEventListener("submit",async e=>{
   e.preventDefault();show("送信しています…");
   const {error}=await client.auth.resetPasswordForEmail($("#email").value.trim(),
     {redirectTo:link("reset-password.html")});
   show(error?"送信できませんでした。時間を空けてお試しください。":
     "該当するアカウントがある場合は、再設定メールを送信しました。");
  });
  $("#passwordStep").addEventListener("submit",async e=>{
   e.preventDefault();
   if($("#password").value.length<8){show("パスワードは8文字以上にしてください。");return;}
   const {error}=await client.auth.updateUser({password:$("#password").value});
   if(error){show("更新に失敗しました。新しい認証メールを取得してください。");return;}
   show("パスワードを更新しました。");await client.auth.signOut();
   setTimeout(()=>location.replace("./login.html"),1000);
  });
  return;
 }
 if(!form)return;
 form.addEventListener("submit",async e=>{
  e.preventDefault();
  const email=mode==="register"?$("#email").value.trim():"";
   const password=$("#password").value;
  if(password.length<8){show("パスワードは8文字以上にしてください。");return;}
  const button=form.querySelector("button[type=submit]");button.disabled=true;
  try{
   if(mode==="register"){
    const displayName=$("#displayName").value.trim();
    if(!displayName||displayName.length>40){show("表示名は1〜40文字で入力してください。");return;}
    const loginId=$("#loginId").value.trim().toLowerCase();
    if(!/^[a-z][a-z0-9._-]{3,23}$/.test(loginId)){
      show("ログインIDは先頭英字・全4〜24文字の半角英数字と . _ - で指定してください");return;
    }
    const {error}=await client.auth.signUp({
     email,password,
     options:{data:{display_name:displayName,login_id:loginId},emailRedirectTo:link("auth-callback.html")}
    });
    show(error?"登録できませんでした。入力内容を確認してください。":
      "登録を受け付けました。メールの確認リンクを開いてください。");
   }else{
    const identifier=$("#loginIdentifier").value.trim();
    if(!identifier){show("メールアドレスまたはログインIDを入力してください。");return;}
    if(identifier.includes("@")){
      const {error}=await client.auth.signInWithPassword({email:identifier,password});
      if(error){show("ログイン情報を確認してください。");return;}
    }else{
      const loginId=identifier.toLowerCase();
      if(!/^[a-z][a-z0-9._-]{3,23}$/.test(loginId)){
        show("ログイン情報を確認してください。");return;
      }
      // Login ID resolution is only allowed in a server-side function.
      // The browser never obtains the corresponding email address.
      const {data,error}=await client.functions.invoke("login-with-id",{
        body:{login_id:loginId,password}
      });
      if(error||!data?.access_token||!data?.refresh_token){
        show(data?.error==="試行回数が多すぎます。時間をおいてください"?
          data.error:"ログイン情報を確認してください。");
        return;
      }
      const {error:sessionError}=await client.auth.setSession({
        access_token:data.access_token,refresh_token:data.refresh_token
      });
      if(sessionError){show("ログイン情報を確認してください。");return;}
    }
    await route();
   }
  }catch(err){show("処理に失敗しました。ネットワークや認証設定を確認してください。");console.error(err);}
  finally{button.disabled=false;}
 });
})();