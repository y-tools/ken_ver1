// supabase/functions/invite-admin/index.ts
// Deploy with Supabase Edge Functions. Service role key MUST stay server-side.
import {createClient} from "https://esm.sh/@supabase/supabase-js@2";
const ORIGIN="https://y-tools.github.io";
const headers={
 "Access-Control-Allow-Origin":ORIGIN,
 "Access-Control-Allow-Headers":"authorization, x-client-info, apikey, content-type",
 "Access-Control-Allow-Methods":"POST, OPTIONS",
 "Vary":"Origin",
 "Content-Type":"application/json"
};
function respond(body:Record<string,unknown>,status=200){
 return new Response(JSON.stringify(body),{status,headers});
}
Deno.serve(async request=>{
 if(request.method==="OPTIONS")return new Response(null,{status:204,headers});
 if(request.method!=="POST")return respond({error:"Method not allowed"},405);
 const origin=request.headers.get("origin");
 if(origin!==ORIGIN)return respond({error:"Origin not allowed"},403);
 const url=Deno.env.get("SUPABASE_URL");
 const serviceKey=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
 if(!url||!serviceKey)return respond({error:"Server not configured"},500);
 const authorization=request.headers.get("Authorization")||"";
 const token=authorization.replace(/^Bearer\s+/i,"");
 if(!token || token===authorization)return respond({error:"Authentication required"},401);
 const admin=createClient(url,serviceKey,{auth:{autoRefreshToken:false,persistSession:false}});
 const {data:{user},error:userError}=await admin.auth.getUser(token);
 if(userError||!user)return respond({error:"Invalid session"},401);
 const {data:profile,error:profileError}=await admin.from("profiles").select("role")
   .eq("id",user.id).single();
 if(profileError||profile?.role!=="owner")return respond({error:"Owner permission required"},403);
 let body;
 try{body=await request.json();}catch{return respond({error:"Invalid JSON"},400);}
 const email=String(body?.email||"").trim().toLowerCase();
 if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)||email.length>254)
   return respond({error:"Invalid email"},400);
 // Expired pending invitations should not block re-invitations.
 const {error:expiryError}=await admin.from("admin_invites").update({status:"revoked"})
   .eq("email",email).eq("status","pending").lt("expires_at",new Date().toISOString());
 if(expiryError)return respond({error:"Could not expire old invite"},500);
 const {data:existing}=await admin.from("admin_invites").select("id")
   .eq("email",email).eq("status","pending").gt("expires_at",new Date().toISOString()).maybeSingle();
 if(existing)return respond({error:"A pending invitation already exists"},409);

 const {data:record,error:recordError}=await admin.from("admin_invites")
   .insert({email,invited_by:user.id,status:"pending"}).select("id").single();
 if(recordError||!record)return respond({error:"Could not reserve invitation"},409);
 const {data:invitation,error:inviteError}=await admin.auth.admin.inviteUserByEmail(email,{
   redirectTo:"https://y-tools.github.io/ken_ver1/auth-callback.html"
 });
 if(inviteError||!invitation?.user){
   await admin.from("admin_invites").update({status:"revoked"}).eq("id",record.id);
   return respond({error:"Invitation failed. This address may already have an account."},400);
 }
 return respond({success:true,message:"Invitation sent"});
});