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
  const auth=await C.authenticate();
  if(!auth)return;
  location.replace(openNext() || (C.isAdmin()?"./admin.html":"./index.html"));
 }
 if(mode==="callback"){
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
   await route();
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
  const email=$("#email").value.trim(),password=$("#password").value;
  if(password.length<8){show("パスワードは8文字以上にしてください。");return;}
  const button=form.querySelector("button[type=submit]");button.disabled=true;
  try{
   if(mode==="register"){
    const displayName=$("#displayName").value.trim();
    if(!displayName||displayName.length>40){show("表示名は1〜40文字で入力してください。");return;}
    const {error}=await client.auth.signUp({
     email,password,
     options:{data:{display_name:displayName},emailRedirectTo:link("auth-callback.html")}
    });
    show(error?"登録できませんでした。入力内容を確認してください。":
      "登録を受け付けました。メールの確認リンクを開いてください。");
   }else{
    const {error}=await client.auth.signInWithPassword({email,password});
    if(error){show("メールアドレスまたはパスワードを確認してください。");return;}
    await route();
   }
  }catch(err){show("処理に失敗しました。ネットワークや認証設定を確認してください。");console.error(err);}
  finally{button.disabled=false;}
 });
})();