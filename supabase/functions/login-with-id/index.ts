// Public login ID + password entrypoint for Supabase Auth.
// The ID -> email lookup and service role key never leave this server.
// Deploy with verify_jwt = false and apply server-side throttling migration first.
import {createClient} from "https://esm.sh/@supabase/supabase-js@2";
const ALLOWED_ORIGIN="https://y-tools.github.io";
const CORS={
  "Access-Control-Allow-Origin":ALLOWED_ORIGIN,
  "Access-Control-Allow-Headers":"authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods":"POST, OPTIONS",
  "Cache-Control":"no-store",
  "Vary":"Origin",
  "Content-Type":"application/json; charset=utf-8"
};
function reply(body:Record<string,unknown>,status=200){
  return new Response(JSON.stringify(body),{status,headers:CORS});
}
const INVALID={error:"ログインIDまたはパスワードが正しくありません"};
Deno.serve(async request=>{
  if(request.method==="OPTIONS")return new Response(null,{status:204,headers:CORS});
  if(request.method!=="POST")return reply({error:"Method not allowed"},405);
  if(request.headers.get("origin")!==ALLOWED_ORIGIN)
    return reply({error:"Origin not allowed"},403);

  const url=Deno.env.get("SUPABASE_URL");
  const serviceKey=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const anonKey=Deno.env.get("SUPABASE_ANON_KEY");
  if(!url||!serviceKey||!anonKey)
    return reply({error:"認証サービスの設定が不足しています"},503);

  let raw:string;
  try {
    raw=await request.text();
    if(raw.length>1024)return reply({error:"Invalid request"},400);
  }catch{
    return reply({error:"Invalid request"},400);
  }
  let parsed:Record<string,unknown>;
  try {parsed=JSON.parse(raw);}catch{return reply({error:"Invalid JSON"},400);}
  const loginId=typeof parsed?.login_id==="string"
    ?parsed.login_id.trim().toLowerCase():"";
  const password=parsed?.password;
  if(!/^[a-z][a-z0-9._-]{3,23}$/.test(loginId) ||
      typeof password!=="string" || password.length<8 || password.length>256)
    return reply(INVALID,401);

  // Trust proxy-normalized client-IP headers only after checking the deployment's
  // forwarding configuration. Use the last forwarded hop, never the first.
  const forwarded=request.headers.get("x-forwarded-for")?.split(",").at(-1)?.trim();
  const ip=(request.headers.get("cf-connecting-ip")||forwarded||"unknown").slice(0,128);
  const admin=createClient(url,serviceKey,{
    auth:{autoRefreshToken:false,persistSession:false,detectSessionInUrl:false}
  });
  // Rate limiting is NOT an in-memory Map: enforce atomically across instances.
  const {data:permitted,error:rateError}=await admin.rpc("reserve_id_login_attempt",{
    p_login_id:loginId,p_ip:ip
  });
  if(rateError)return reply({error:"認証サービスを利用できません"},503);
  if(!permitted)return reply({error:"試行回数が多すぎます。時間をおいてください"},429);

  // No lookup API is exposed to the browser. Avoid differing user-not-found
  // messages or timing-dependent user enumeration where practical.
  const {data:profile,error:profileError}=await admin.from("profiles")
    .select("id").eq("login_id",loginId).maybeSingle();
  if(profileError||!profile)return reply(INVALID,401);

  const {data:record,error:userError}=await admin.auth.admin.getUserById(profile.id);
  const user=record?.user;
  if(userError||!user?.email||!user?.email_confirmed_at)
    return reply(INVALID,401);

  // Password verification is always done by Supabase Auth, NOT our own SQL.
  // Use a separate anon client, so admin credentials never become user session.
  const authClient=createClient(url,anonKey,{
    auth:{autoRefreshToken:false,persistSession:false,detectSessionInUrl:false}
  });
  const {data:login,error:passwordError}=await authClient.auth.signInWithPassword({
    email:user.email,password
  });
  if(passwordError||!login?.session?.access_token||!login?.session?.refresh_token)
    return reply(INVALID,401);

  return reply({
    access_token:login.session.access_token,
    refresh_token:login.session.refresh_token
  },200);
});
