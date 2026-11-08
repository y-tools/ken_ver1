#!/usr/bin/env python3
"""T008 Phase 0: read-only, secret-free VPS inventory. NO migrations or DML.

Run only with explicit permission and a PostgreSQL read-only account:
  KEN_T008_AUDIT_DSN=... python server/t008_inventory_readonly.py

Outputs schema/route counts and resource statistics, not user rows,
credentials, hostnames, connection URIs, IP addresses or raw query text.
"""
from __future__ import annotations
import argparse,ast,json,os,pathlib,shutil,sys,time
from datetime import datetime,timezone
import psycopg

def safe_route_manifest(root: pathlib.Path) -> dict:
    counts={}
    for relative in ("server/api/main.py","server/admin_api.py"):
        src=root/relative
        if not src.is_file(): continue
        try: tree=ast.parse(src.read_text(encoding="utf-8"))
        except (SyntaxError,UnicodeError,OSError): continue
        methods={}
        for node in ast.walk(tree):
            if not isinstance(node,(ast.AsyncFunctionDef,ast.FunctionDef)): continue
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute):
                    verb=dec.func.attr.lower()
                    if verb in ("get","post","put","patch","delete"):
                        methods[verb.upper()]=methods.get(verb.upper(),0)+1
        counts[relative]=methods
    return counts

def read_os_counters() -> dict:
    result={}
    try:
        result["load_average_1m_5m_15m"]=[round(v,3) for v in os.getloadavg()]
    except OSError: pass
    mem=pathlib.Path("/proc/meminfo")
    if mem.is_file():
        allowed={"MemTotal","MemAvailable","SwapTotal","SwapFree"}
        result["memory_kib"]={}
        for line in mem.read_text().splitlines():
            key,_,value=line.partition(":")
            if key in allowed:
                result["memory_kib"][key]=int(value.strip().split()[0])
    stat=shutil.disk_usage(pathlib.Path.cwd())
    result["filesystem_bytes"]={"total":stat.total,"used":stat.used,"free":stat.free}
    return result

def inventory_db(dsn:str) -> dict:
    with psycopg.connect(dsn,connect_timeout=4,autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            try:
                cur.execute("SET LOCAL statement_timeout='2500ms'")
                cur.execute("SELECT current_setting('transaction_read_only')")
                if cur.fetchone()[0]!="on":
                    raise RuntimeError("read-only session not established")
                cur.execute("SELECT current_setting('server_version_num')::integer")
                version=cur.fetchone()[0]
                cur.execute("""SELECT count(*),coalesce(sum(pg_total_relation_size(c.oid)),0)
                    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE c.relkind IN ('r','p') AND n.nspname NOT IN
                    ('pg_catalog','information_schema')""")
                tables,size=cur.fetchone()
                cur.execute("""SELECT count(*) FROM pg_indexes WHERE schemaname NOT IN
                    ('pg_catalog','information_schema')""")
                indexes=cur.fetchone()[0]
                cur.execute("""SELECT count(*) FILTER(WHERE state='active'),count(*)
                    FROM pg_stat_activity WHERE datname=current_database()""")
                active,connections=cur.fetchone()
                cur.execute("""SELECT count(*) FROM pg_locks WHERE granted=false
                    AND pid IN (SELECT pid FROM pg_stat_activity
                    WHERE datname=current_database())""")
                waiting_locks=cur.fetchone()[0]
                cur.execute("""SELECT count(*) FROM information_schema.table_constraints
                    WHERE constraint_type='FOREIGN KEY'""")
                fk=cur.fetchone()[0]
                cur.execute("""SELECT count(*) FROM pg_roles WHERE rolcanlogin""")
                login_role_count=cur.fetchone()[0]
                # No table data/record content is queried or printed.
                return {"postgresql_version_num":version,
                        "table_count":tables,"table_total_bytes":size,
                        "index_count":indexes,"foreign_key_count":fk,
                        "db_connections":connections,"active_db_connections":active,
                        "waiting_locks":waiting_locks,"login_role_count":login_role_count}
            finally:
                cur.execute("ROLLBACK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo-root",default=".")
    parser.add_argument("--no-db",action="store_true")
    args=parser.parse_args()
    report={"report_version":"T008_inventory_v1",
            "captured_utc":datetime.now(timezone.utc).isoformat(),
            "OS":read_os_counters(),
            "api_route_counts":safe_route_manifest(pathlib.Path(args.repo_root))}
    if not args.no_db:
        dsn=os.environ.get("KEN_T008_AUDIT_DSN")
        if not dsn:
            parser.error("KEN_T008_AUDIT_DSN is required without --no-db")
        try:
            report["database"]=inventory_db(dsn)
        except Exception as exc:
            # Never echo exception text because it can contain a server hostname or DSN.
            report["database"]={"status":"failed","error_type":type(exc).__name__}
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    return 0 if report.get("database",{}).get("status")!="failed" else 2

if __name__=="__main__":
    sys.exit(main())
