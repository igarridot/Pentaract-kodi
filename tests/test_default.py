import os
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

    def test_playback_stream_url_direct_mode_uses_download_id(self):
        module, _addon, _profile_dir = self.load_default_module(settings={"buffer_profile": "disabled"})
        build_calls = []

        class FakeClient:
            def build_stream_url(self, storage_id, path, download_id=None):
                build_calls.append(
                    {
                        "storage_id": storage_id,
                        "path": path,
                        "download_id": download_id,
                    }
                )
                return "http://backend/stream"

        module.CLIENT = FakeClient()
        module.uuid.uuid4 = lambda: "stream-123"

        stream_url = module.playback_stream_url("storage-7", "Videos/movie.mkv", "Movie")

        self.assertEqual("http://backend/stream", stream_url)
        self.assertEqual(
            [
                {
                    "storage_id": "storage-7",
                    "path": "Videos/movie.mkv",
                    "download_id": "stream-123",
                }
            ],
            build_calls,
        )

    def test_tune_kodi_timeouts_writes_profile_advancedsettings_and_asks_for_restart(self):
        module, _addon, profile_dir = self.load_default_module()
        target = os.path.join(profile_dir, "advancedsettings.xml")
        module.xbmcvfs.translatePath = lambda path: target if path == module.ADVANCED_SETTINGS_PATH else str(path)

        self.assertTrue(module.tune_kodi_timeouts())

        with open(target, "r", encoding="utf-8") as handle:
            written = handle.read()
        self.assertIn("<curlclienttimeout>120</curlclienttimeout>", written)
        self.assertIn("<curllowspeedtime>120</curllowspeedtime>", written)
        self.assertEqual(1, len(module.DIALOG.ok_calls))
        self.assertIn("Restart Kodi", module.DIALOG.ok_calls[0][1])

    def test_tune_kodi_timeouts_keeps_existing_settings_and_skips_when_already_set(self):
        module, _addon, profile_dir = self.load_default_module()
        target = os.path.join(profile_dir, "advancedsettings.xml")
        module.xbmcvfs.translatePath = lambda path: target if path == module.ADVANCED_SETTINGS_PATH else str(path)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("<advancedsettings><cache><memorysize>1</memorysize></cache></advancedsettings>")

        self.assertTrue(module.tune_kodi_timeouts())
        with open(target, "r", encoding="utf-8") as handle:
            written = handle.read()
        self.assertIn("<memorysize>1</memorysize>", written)
        self.assertIn("<curllowspeedtime>120</curllowspeedtime>", written)

        self.assertFalse(module.tune_kodi_timeouts())
        self.assertEqual(1, len(module.DIALOG.ok_calls))
        self.assertTrue(any("already" in message for _title, message, _icon, _duration in module.DIALOG.notifications))

    def test_render_root_offers_the_timeout_fix(self):
        module, _addon, _profile_dir = self.load_default_module()
        module.ensure_authenticated = lambda interactive=False: False

        module.render_root()

        urls = [call[2] for call in module.xbmcplugin.calls if call[0] == "addDirectoryItem"]
        self.assertTrue(any("action=tune_kodi_timeouts" in url for url in urls), urls)


if __name__ == "__main__":
    unittest.main()
