#!/usr/bin/env python3
"""Add only the authenticated admin reverse proxy to the existing Caddy host.

Preserves other site blocks, backs up and validates before reload.
Run as root on the Ken VPS. This does not touch Minecraft or the search API.
"""
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import shutil
import sys

path=Path("/etc/caddy/Caddyfile")
original=path.read_text(encoding="utf-8")
host="kenapi.153-127-64-17.sslip.io {"
if original.count(host)!=1:
    raise SystemExit("Expected exactly one existing Ken API host")
start=original.index(host)
end=original.find("\n}",start)
if end<0:
    raise SystemExit("Could not delimit API host")
block=original[start:end+2]
if "path /api/admin/*" in block:
    print("Admin Caddy route already configured")
    sys.exit(0)
anchor="""    handle @song_api {
        reverse_proxy 127.0.0.1:8787
    }
"""
extra="""    @admin_api {
        path /api/admin/*
        method GET POST OPTIONS
    }
    handle @admin_api {
        reverse_proxy 127.0.0.1:8788
    }

"""
if block.count(anchor)!=1:
    raise SystemExit("Unexpected existing Caddy search route layout")
new_block=block.replace(anchor,extra+anchor)
updated=original[:start]+new_block+original[end+2:]
stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
backup=path.with_name("Caddyfile.backup.ken-editor-"+stamp)
shutil.copy2(path,backup)
path.write_text(updated,encoding="utf-8")

def call(*args):
    return subprocess.run(args,text=True,capture_output=True)

check=call("caddy","validate","--config",str(path))
if check.returncode!=0:
    shutil.copy2(backup,path)
    raise SystemExit("Caddy validation failed; configuration rolled back: "+check.stderr[-1200:])
reload=call("systemctl","reload","caddy")
if reload.returncode!=0:
    shutil.copy2(backup,path)
    call("systemctl","reload","caddy")
    raise SystemExit("Caddy reload failed; restored backup: "+reload.stderr[-1200:])
print("Authenticated editor Caddy route deployed, prior config:",backup)
