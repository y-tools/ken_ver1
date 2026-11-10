-- Production security hardening applied 2026-11-11 to project ken-denmoku-v2.
-- Trigger functions must not be callable through the public PostgREST RPC API.
revoke all on function public.handle_new_user() from public, anon, authenticated;
