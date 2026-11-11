// Owner-only provisioning of admins without a user-supplied email address.
// Supabase Auth stores a synthetic, undeliverable internal address; the admin
// signs in using the ID-to-Auth lookup in the existing login-with-id Edge Function.
// Passwords are passed directly to Supabase Auth, never stored in app tables.
import {createClient} from "https://esm.sh/@supabase/supabase-js@2";

const ORIGIN="https://y-tools.github.io";
const HEADERS={
 "Access-Control-Allow-Origin":ORIGIN,
 "Access-Control-Allow-Headers":"authorization, x-client-info, apikey, content-type",
 "Access-Control-Allow-Methods":"POST, OPTIONS",
 "Cache-Control":"no-store",
 "Vary":"Origin",
 "Content-Type":"application/json; charset=utf-8",
};
function reply(data:Record<string,unknown>,status=200){
 return new Response(JSON.stringify(data),{status,headers:HEADERS});
}
Deno.serve(async request=>{
 if(request.method==="OPTIONS"){
  if(request.headers.get("origin")!==ORIGIN)return reply({error:"Origin not allowed"},403);
  return new Response(null,{status:204,headers:HEADERS});
 }
 if(request.method!=="POST")return reply({error:"Method not allowed"},405);
 if(request.headers.get("origin")!==ORIGIN)return reply({error:"Origin not allowed"},403);
 if(!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))
  return reply({error:"JSON required"},415);

 const url=Deno.env.get("SUPABASE_URL");
 const serviceKey=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
 if(!url||!serviceKey)return reply({error:"認証サーバーの設定を確認してください"},503);

 const authorization=request.headers.get("authorization")||"";
 const token=authorization.replace(/^Bearer\s+/i,"");
 if(!token||token===authorization)return reply({error:"ログインが必要です"},401);

 const admin=createClient(url,serviceKey,{auth:{
  autoRefreshToken:false,persistSession:false,detectSessionInUrl:false
 }});
 const {data:{user},error:authError}=await admin.auth.getUser(token);
 if(authError||!user)return reply({error:"認証セッションが無効です"},401);
 const {data:owner,error:ownerError}=await admin.from("profiles")
  .select("role").eq("id",user.id).single();
 if(ownerError||owner?.role!=="owner")return reply({error:"オーナーだけが管理者を作成できます"},403);

 let body:Record<string,unknown>;
 try{
  const raw=await request.text();
  if(raw.length>2048)return reply({error:"入力が長すぎます"},413);
  const obj:unknown=JSON.parse(raw);
  if(!obj||Array.isArray(obj)||typeof obj!=="object")return reply({error:"入力を確認してください"},400);
  body=obj as Record<string,unknown>;
 }catch{return reply({error:"入力を確認してください"},400);}
 const loginId=typeof body.login_id==="string"?body.login_id.trim().toLowerCase():"";
 const password=typeof body.password==="string"?body.password:"";
 const displayName=typeof body.display_name==="string"?body.display_name.trim():"";
 if(!/^[a-z][a-z0-9._-]{3,23}$/.test(loginId) ||
    !displayName||displayName.length>40||
    password.length<12||password.length>128||!/[a-zA-Z]/.test(password)||!/[0-9]/.test(password))
  return reply({error:"表示名、ログインID、英字と数字を含む12文字以上のパスワードを確認してください"},400);

 // Must not leak role elevation capabilities to regular admins.
 const {data:duplicate,error:duplicateError}=await admin.from("profiles")
  .select("id").eq("login_id",loginId).maybeSingle();
 if(duplicateError)return reply({error:"IDの確認に失敗しました"},503);
 if(duplicate)return reply({error:"そのログインIDは使用されています"},409);
 const {count, error:countError}=await admin.from("profiles")
  .select("id",{head:true,count:"exact"}).eq("role","admin");
 if(countError)return reply({error:"管理者数を確認できませんでした"},503);
 if((count??0)>=50)return reply({error:"管理者の登録上限に達しました"},409);

 // Reserved .invalid TLD: no password-reset or invitation emails can be sent.
 // This opaque address must NEVER be returned to clients or shown in the UI.
 const email="admin-"+crypto.randomUUID()+"@accounts.ken-denmoku.invalid";
 let inviteId:string|null=null;
 let createdId:string|null=null;
 try{
  // Existing signup trigger requires a valid owner invitation before auth.users INSERT.
  const reserved=await admin.from("admin_invites")
   .insert({email,invited_by:user.id,status:"pending"})
   .select("id").single();
  if(reserved.error||!reserved.data?.id)throw Error("invite");
  inviteId=reserved.data.id;

  const created=await admin.auth.admin.createUser({
   email,password,email_confirm:true,
   user_metadata:{login_id:loginId,display_name:displayName},
  });
  if(created.error||!created.data?.user?.id)throw Error("create");
  createdId=created.data.user.id;

  // The signup trigger creates a listener profile; ONLY the verified owner's
  // server-side operation elevates this newly created profile to admin.
  const promoted=await admin.from("profiles")
   .update({role:"admin",updated_at:new Date().toISOString()})
   .eq("id",createdId).eq("role","listener").eq("login_id",loginId)
   .select("id").single();
  if(promoted.error||promoted.data?.id!==createdId)throw Error("promote");

  const accepted=await admin.from("admin_invites")
   .update({status:"accepted"}).eq("id",inviteId).eq("status","pending")
   .select("id").single();
  if(accepted.error||accepted.data?.id!==inviteId)throw Error("invite_accept");

  return reply({success:true,login_id:loginId,display_name:displayName});
 }catch{
  // Best-effort rollback: do not leave a partial login or pending elevation.
  if(createdId)await admin.auth.admin.deleteUser(createdId).catch(()=>{});
  if(inviteId)await admin.from("admin_invites")
   .update({status:"revoked"}).eq("id",inviteId).eq("status","pending");
  return reply({error:"管理者を作成できませんでした。IDや設定を確認してください"},502);
 }
});
