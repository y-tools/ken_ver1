"""Read-only VPS inventory smoke tests against disposable PostgreSQL, not real VPS."""
import os
from pathlib import Path
import unittest
from server.t008_inventory_readonly import inventory_db,safe_route_manifest,read_os_counters

class InventorySmoke(unittest.TestCase):
    def test_static_api_route_counts(self):
        root=Path(__file__).resolve().parents[2]
        report=safe_route_manifest(root)
        self.assertIsInstance(report,dict)
        self.assertIn("server/api/main.py",report)
        self.assertNotIn("database_password",str(report).lower())

    def test_local_host_counters_without_identifiers(self):
        report=read_os_counters()
        self.assertIn("filesystem_bytes",report)
        self.assertNotIn("hostname",report)
        self.assertNotIn("ip_address",report)

    @unittest.skipUnless(os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES" and
                         os.getenv("KEN_T008_TEST_DATABASE_URL"),
                         "disposable database required")
    def test_readonly_catalog_inventory(self):
        report=inventory_db(os.environ["KEN_T008_TEST_DATABASE_URL"])
        self.assertGreaterEqual(report["table_count"],2)
        self.assertGreaterEqual(report["index_count"],1)
        self.assertEqual(report["postgresql_version_num"]//10000,16)
        self.assertNotIn("credentials",report)
        self.assertNotIn("connection_uri",report)

if __name__=="__main__":
    unittest.main()
