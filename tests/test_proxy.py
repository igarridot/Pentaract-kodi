import json
import os
import time
import unittest

from tests.kodi_test_utils import load_plugin_module


class ProxyModuleTests(unittest.TestCase):
    def load_proxy_module(self):
        return load_plugin_module(
            "pentaract_proxy_test",
            "resources/lib/proxy.py",
        )

    def test_save_and_load_proxy_session_roundtrip(self):
        module, _addon, _profile_dir = self.load_proxy_module()
        session = {"storage_id": "s1", "path": "Movies/demo.mp4", "created_at": 10}

        module.save_proxy_session("abc", session)
        loaded = module.load_proxy_session("abc")

        self.assertEqual(session, loaded)
        self.assertTrue(os.path.isfile(module.proxy_session_path("abc")))

    def test_cleanup_proxy_sessions_removes_only_expired_files(self):
        module, _addon, _profile_dir = self.load_proxy_module()
        module.ensure_proxy_sessions_dir()

        expired_path = module.proxy_session_path("expired")
        fresh_path = module.proxy_session_path("fresh")

        with open(expired_path, "w", encoding="utf-8") as handle:
            json.dump({"id": "expired"}, handle)
        with open(fresh_path, "w", encoding="utf-8") as handle:
            json.dump({"id": "fresh"}, handle)

        cutoff = time.time() - module.SESSION_TTL_SECONDS
        os.utime(expired_path, (cutoff - 60, cutoff - 60))
        os.utime(fresh_path, None)

        module.cleanup_proxy_sessions()

        self.assertFalse(os.path.exists(expired_path))
        self.assertTrue(os.path.exists(fresh_path))


if __name__ == "__main__":
    unittest.main()
