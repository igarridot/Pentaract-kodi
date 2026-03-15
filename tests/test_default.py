import unittest

from tests.kodi_test_utils import load_plugin_module


class DefaultModuleTests(unittest.TestCase):
    def load_default_module(self, settings=None):
        return load_plugin_module(
            "pentaract_default_test",
            "default.py",
            addon_settings=settings,
            argv=["plugin://plugin.video.pentaract", "1", ""],
        )

    def test_build_proxy_session_uses_title_fallback_and_mime_type(self):
        module, _addon, _profile_dir = self.load_default_module()

        session = module.build_proxy_session(
            "storage-1",
            "Movies/example.mkv",
            "",
            {
                "prebuffer_bytes": 8 * 1024 * 1024,
                "request_timeout_seconds": 45,
                "chunk_size_bytes": 131072,
            },
            created_at=12345,
        )

        self.assertEqual("storage-1", session["storage_id"])
        self.assertEqual("Movies/example.mkv", session["path"])
        self.assertEqual("example.mkv", session["title"])
        self.assertEqual("video/x-matroska", session["mime_type"])
        self.assertEqual(8 * 1024 * 1024, session["prebuffer_bytes"])
        self.assertEqual(45, session["request_timeout_seconds"])
        self.assertEqual(131072, session["chunk_size_bytes"])
        self.assertEqual(12345, session["created_at"])

    def test_effective_buffer_settings_custom_uses_defaults_for_invalid_values(self):
        module, _addon, _profile_dir = self.load_default_module(
            settings={
                "buffer_profile": "custom",
                "custom_prebuffer_mb": "999",
                "custom_request_timeout_secs": "17",
                "custom_chunk_size_bytes": "123",
            }
        )

        profile, settings = module.effective_buffer_settings()

        self.assertEqual("custom", profile)
        self.assertEqual(32 * 1024 * 1024, settings["prebuffer_bytes"])
        self.assertEqual(60, settings["request_timeout_seconds"])
        self.assertEqual(262144, settings["chunk_size_bytes"])

    def test_register_proxy_session_persists_built_session(self):
        module, _addon, _profile_dir = self.load_default_module()

        saved = {}
        cleanup_calls = []
        module.uuid.uuid4 = lambda: "session-123"
        module.effective_buffer_settings = lambda: (
            "balanced",
            {
                "prebuffer_bytes": 24 * 1024 * 1024,
                "request_timeout_seconds": 60,
                "chunk_size_bytes": 262144,
            },
        )
        module.save_proxy_session = lambda session_id, session: saved.update({"session_id": session_id, "session": session})
        module.cleanup_proxy_sessions = lambda: cleanup_calls.append(True)
        module.time.time = lambda: 99

        session_id, stream_url = module.register_proxy_session("storage-9", "Videos/movie.mp4", "My Movie")

        self.assertEqual("session-123", session_id)
        self.assertEqual(module.PROXY_BASE_URL + "/stream/session-123", stream_url)
        self.assertEqual("session-123", saved["session_id"])
        self.assertEqual("My Movie", saved["session"]["title"])
        self.assertEqual("video/mp4", saved["session"]["mime_type"])
        self.assertEqual(99, saved["session"]["created_at"])
        self.assertEqual([True], cleanup_calls)


if __name__ == "__main__":
    unittest.main()
