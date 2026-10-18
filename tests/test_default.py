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

    def test_playable_items_show_server_watch_progress(self):
        module, _addon, _profile_dir = self.load_default_module()
        calls = module.xbmcplugin.calls

        module.add_playable_file_item("storage-1", {
            "path": "Movies/a.mkv", "name": "a.mkv", "size": 10,
            "watch": {"position_seconds": 2530, "duration_seconds": 5400, "watched": True},
        })
        module.add_playable_file_item("storage-1", {
            "path": "Movies/b.mkv", "name": "b.mkv", "size": 10,
            "watch": {"position_seconds": 0, "duration_seconds": 5400, "watched": False},
        })
        module.add_playable_file_item("storage-1", {"path": "Movies/c.mkv", "name": "c.mkv", "size": 10})

        tags = [call[3].getVideoInfoTag() for call in calls if call[0] == "addDirectoryItem"]
        self.assertEqual((1, (2530.0, 5400.0)), (tags[0].playcount, tags[0].resume_point))
        self.assertEqual((0, None), (tags[1].playcount, tags[1].resume_point))
        self.assertEqual((None, None), (tags[2].playcount, tags[2].resume_point))

    def test_report_watch_progress_saves_and_refreshes_listing(self):
        module, _addon, _profile_dir = self.load_default_module()
        saved = []

        class FakeClient:
            def save_watch_progress(self, storage_id, path, position, duration):
                saved.append((storage_id, path, position, duration))

        def fake_follow(watcher, monitor, save):
            return save(600.0, 5400.0)

        module.CLIENT = FakeClient()
        module.follow_playback = fake_follow

        module.report_watch_progress("storage-1", "Movies/a.mkv")

        self.assertEqual([("storage-1", "Movies/a.mkv", 600.0, 5400.0)], saved)
        self.assertIn("Container.Refresh", module.xbmc.builtins)

    def test_report_watch_progress_logs_failures_without_refreshing(self):
        module, _addon, _profile_dir = self.load_default_module()

        class FailingClient:
            def save_watch_progress(self, storage_id, path, position, duration):
                raise module.PentaractAPIError("server down", status=502)

        module.CLIENT = FailingClient()
        module.follow_playback = lambda watcher, monitor, save: save(600.0, 5400.0)

        module.report_watch_progress("storage-1", "Movies/a.mkv")

        self.assertNotIn("Container.Refresh", module.xbmc.builtins)
        self.assertTrue(any("server down" in message for message, _level in module.xbmc.logged))

    def test_playable_items_offer_pentaract_watched_marks(self):
        module, _addon, _profile_dir = self.load_default_module()
        calls = module.xbmcplugin.calls

        for watch in (
            None,
            {"position_seconds": 600, "duration_seconds": 5400, "watched": False},
            {"position_seconds": 0, "duration_seconds": 5400, "watched": True},
        ):
            module.add_playable_file_item("storage-1", {"path": "TV/ep 1.mkv", "name": "ep 1.mkv", "size": 1, "watch": watch})

        menus = [call[3].context_menu for call in calls if call[0] == "addDirectoryItem"]
        labels = [[label for label, _command in menu] for menu in menus]
        autoplay = "Pentaract: turn autoplay on"
        self.assertEqual(["Pentaract: mark as watched", autoplay], labels[0])
        self.assertEqual(["Pentaract: mark as watched", "Pentaract: mark as unwatched", autoplay], labels[1])
        self.assertEqual(["Pentaract: mark as unwatched", autoplay], labels[2])

        command = menus[2][0][1]
        self.assertTrue(command.startswith("RunPlugin(plugin://plugin.video.pentaract?"))
        params = dict(module.urllib.parse.parse_qsl(command[len("RunPlugin(plugin://plugin.video.pentaract?"):-1]))
        self.assertEqual(
            {"action": "set_watched", "storage_id": "storage-1", "path": "TV/ep 1.mkv", "watched": "0"},
            params,
        )

    def finish_video(self, ended=True, autoplay=True, listing=None, player_busy=False, cancel_after_updates=None):
        """Plays TV/ep 1.mkv to its end (or stops it by hand) and returns the
        module, to look at what the plugin did next."""
        module, _addon, _profile_dir = self.load_default_module(settings={"autoplay_next": autoplay})
        listed = []

        class FakeClient:
            def save_watch_progress(self, storage_id, path, position, duration):
                pass

            def list_directory(self, storage_id, path):
                listed.append((storage_id, path))
                if listing is None:
                    raise module.PentaractAPIError("server down", status=502)
                return listing

        def fake_follow(watcher, monitor, save):
            watcher.ended = ended
            return save(5400.0, 5400.0)

        module.CLIENT = FakeClient()
        module.follow_playback = fake_follow
        self.addCleanup(setattr, module.xbmc.Player, "isPlaying", module.xbmc.Player.isPlaying)
        module.xbmc.Player.isPlaying = lambda self: player_busy
        module.xbmcgui.DialogProgress.cancel_after_updates = cancel_after_updates
        self.addCleanup(setattr, module.xbmcgui.DialogProgress, "cancel_after_updates", None)
        module.report_watch_progress("storage-1", "TV/ep 1.mkv")
        module.listed = listed
        return module

    EPISODES = [
        {"path": "TV/ep 2.mkv", "name": "ep 2.mkv", "is_file": True},
        {"path": "TV/cover.jpg", "name": "cover.jpg", "is_file": True},
        {"path": "TV/ep 1.mkv", "name": "ep 1.mkv", "is_file": True},
    ]

    def play_media_params(self, module):
        commands = [command for command in module.xbmc.builtins if command.startswith("PlayMedia(")]
        prefix = "PlayMedia(plugin://plugin.video.pentaract?"
        return [dict(module.urllib.parse.parse_qsl(command[len(prefix):-1])) for command in commands]

    def test_ended_video_plays_the_next_one_in_its_folder(self):
        module = self.finish_video(listing=self.EPISODES)
        self.assertEqual([("storage-1", "TV/")], module.listed)
        self.assertEqual(
            [{"action": "play", "storage_id": "storage-1", "path": "TV/ep 2.mkv", "title": "ep 2.mkv"}],
            self.play_media_params(module),
        )

    def test_no_next_video_when_stopped_by_hand_or_autoplay_off(self):
        for options in ({"ended": False}, {"autoplay": False}):
            module = self.finish_video(listing=self.EPISODES, **options)
            self.assertEqual([], module.listed, options)
            self.assertEqual([], self.play_media_params(module), options)

    def test_no_next_video_after_the_last_one(self):
        module = self.finish_video(listing=self.EPISODES[1:])
        self.assertEqual([], self.play_media_params(module))

    def test_cancelled_countdown_plays_nothing(self):
        module = self.finish_video(listing=self.EPISODES, cancel_after_updates=1)
        self.assertEqual([], self.play_media_params(module))

    def test_no_next_video_when_kodi_already_plays_something(self):
        module = self.finish_video(listing=self.EPISODES, player_busy=True)
        self.assertEqual([], self.play_media_params(module))

    def test_listing_failure_only_logs(self):
        module = self.finish_video(listing=None)
        self.assertEqual([], self.play_media_params(module))
        self.assertTrue(any("server down" in message for message, _level in module.xbmc.logged))

    def test_toggle_autoplay_flips_the_setting_and_refreshes(self):
        module, addon, _profile_dir = self.load_default_module(settings={"autoplay_next": True})
        module.PARAMS = {"action": "toggle_autoplay"}
        module.route()
        self.assertFalse(addon.getSettingBool("autoplay_next"))
        self.assertEqual("Autoplay off", module.DIALOG.notifications[-1][1])
        self.assertIn("Container.Refresh", module.xbmc.builtins)

        module.route()
        self.assertTrue(addon.getSettingBool("autoplay_next"))
        self.assertEqual("Autoplay on", module.DIALOG.notifications[-1][1])

    def test_autoplay_menu_entry_offers_the_opposite_of_the_setting(self):
        module, _addon, _profile_dir = self.load_default_module(settings={"autoplay_next": True})
        label, command = module.autoplay_context_menu_entry()
        self.assertEqual("Pentaract: turn autoplay off", label)
        self.assertEqual("RunPlugin(plugin://plugin.video.pentaract?action=toggle_autoplay)", command)

    def run_set_watched(self, watched, make_client):
        module, _addon, _profile_dir = self.load_default_module()
        module.PARAMS = {"action": "set_watched", "storage_id": "storage-1", "path": "TV/ep 1.mkv", "watched": watched}
        module.CLIENT = make_client(module)
        module.ensure_authenticated = lambda interactive=True: True
        module.route()
        return module

    def test_set_watched_action_marks_on_server_and_refreshes(self):
        marks = []

        class FakeClient:
            def set_watched(self, storage_id, path, watched):
                marks.append((storage_id, path, watched))

        for value, expected in (("1", True), ("0", False)):
            module = self.run_set_watched(value, lambda _module: FakeClient())
            self.assertIn("Container.Refresh", module.xbmc.builtins)
            self.assertEqual(("storage-1", "TV/ep 1.mkv", expected), marks[-1])
        self.assertEqual("Marked as unwatched", module.DIALOG.notifications[-1][1])

    def test_set_watched_action_reports_server_errors(self):
        def failing_client(module):
            class FailingClient:
                def set_watched(self, storage_id, path, watched):
                    raise module.PentaractAPIError("forbidden", status=403)

            return FailingClient()

        module = self.run_set_watched("1", failing_client)
        self.assertNotIn("Container.Refresh", module.xbmc.builtins)
        self.assertEqual("forbidden", module.DIALOG.notifications[-1][1])

    def load_with_untrusted_server(self, answer):
        module, addon, _profile_dir = self.load_default_module()
        module.DIALOG.yesno_answer = answer
        attempts = []

        def ensure_token():
            attempts.append(addon.getSettingString("tls_trusted_sha256"))
            if addon.getSettingString("tls_trusted_sha256") != "AB:CD":
                raise module.UntrustedCertificateError("AB:CD")
            return "tok"

        module.CLIENT.ensure_token = ensure_token
        return module, addon, attempts

    def test_accepting_a_self_signed_certificate_trusts_it_and_connects(self):
        module, addon, attempts = self.load_with_untrusted_server(answer=True)

        self.assertTrue(module.ensure_authenticated(interactive=False))

        self.assertEqual("AB:CD", addon.getSettingString("tls_trusted_sha256"))
        self.assertEqual(["", "AB:CD"], attempts)
        self.assertEqual(1, len(module.DIALOG.yesno_calls))
        self.assertIn("SHA-256: AB:CD", module.DIALOG.yesno_calls[0][1])

    def test_declining_a_self_signed_certificate_does_not_connect(self):
        module, addon, attempts = self.load_with_untrusted_server(answer=False)

        self.assertFalse(module.ensure_authenticated(interactive=True))

        self.assertEqual("", addon.getSettingString("tls_trusted_sha256"))
        self.assertEqual([""], attempts)
        self.assertEqual(0, addon.open_settings_calls, "a declined certificate is not a settings problem")
        self.assertEqual(module.xbmcgui.NOTIFICATION_ERROR, module.DIALOG.notifications[-1][2])


if __name__ == "__main__":
    unittest.main()
