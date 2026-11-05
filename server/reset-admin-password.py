#!/usr/bin/env python3
"""Change Ken music DB administrator password privately over an SSH terminal.

Run as root with /opt/ken-song-api/.venv/bin/python and a real TTY.
The password is never printed, placed in process arguments or sent to GitHub.
"""
from pathlib import Path
from getpass import getpass
import os
import subprocess
import tempfile
from argon2 import PasswordHasher

if os.geteuid()!=0:
    raise SystemExit("Run with sudo")
path=Path("/etc/ken-song-admin.env")
if not path.is_file():
    raise SystemExit("Database editor has not been initialized")
one=getpass("新しい管理者パスワード（16文字以上）: ")
two=getpass("確認のためもう一度: ")
if one!=two or len(one)<16 or len(one)>256 or one.strip()!=one:
    raise SystemExit("パスワードが一致しない、短すぎる、または空白が含まれています")
hash_value=PasswordHasher().hash(one)
original=path.read_text()
lines=original.splitlines()
new=[]
found=0
for line in lines:
    if line.startswith("KEN_ADMIN_PASSWORD_HASH="):
        new.append("KEN_ADMIN_PASSWORD_HASH='"+hash_value+"'")
        found+=1
    else:
        new.append(line)
if found!=1:
    raise SystemExit("Existing configuration has no unique admin password field")
with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,prefix=".ken-admin-",delete=False) as tmp:
    tmp.write("\n".join(new)+"\n")
    tmp_name=tmp.name
os.chmod(tmp_name,0o600)
os.replace(tmp_name,path)
subprocess.run(["systemctl","restart","ken-song-admin"],check=True)
secret_file=Path("/root/ken-song-editor-initial-password.txt")
if secret_file.exists():
    secret_file.unlink()
print("管理者パスワードを更新し、旧セッションを失効させました")
