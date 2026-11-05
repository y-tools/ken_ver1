#!/usr/bin/env python3
"""Read-only post-deployment verification without printing administrator secret."""
from pathlib import Path
import json
import urllib.request
import urllib.error

password = Path("/root/ken-song-editor-initial-password.txt").read_text(encoding="utf-8").strip()
endpoint="https://kenapi.153-127-64-17.sslip.io"
origin="https://y-tools.github.io"

def call(path, method="GET", payload=None, bearer=None):
    data=json.dumps(payload).encode() if payload is not None else None
    headers={"Origin":origin,"Accept":"application/json"}
    if data is not None:headers["Content-Type"]="application/json"
    if bearer:headers["Authorization"]="Bearer "+bearer
    request=urllib.request.Request(endpoint+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(request,timeout=10) as resp:
            return resp.status,json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code,{}

code,_=call("/api/admin/artists?q=Lemon")
assert code==401,code
print("Unauthorized access correctly denied")
code,login=call("/api/admin/login","POST",{"password":password})
assert code==200,(code, "login failed")
token=login["token"]
print("Administrator login accepted")
code,results=call("/api/admin/artists?q=%E7%B1%B3%E6%B4%A5","GET",bearer=token)
assert code==200,(code,"artist search failed")
print("Artist search returned "+str(len(results.get("items",[])))+" results")
if results["items"]:
    identifier=results["items"][0]["id"]
    code,detail=call("/api/admin/artists/"+str(identifier),"GET",bearer=token)
    assert code==200 and "songs" in detail
    print("Artist songs fetched; count="+str(detail["total"]))
code,_=call("/api/admin/logout","POST",{},bearer=token)
assert code==200
code,_=call("/api/admin/artists?q=Lemon","GET",bearer=token)
assert code==401
print("Logout invalidated session; ALL READ-ONLY ADMIN TESTS PASSED")
