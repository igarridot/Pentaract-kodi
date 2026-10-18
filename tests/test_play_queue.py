import unittest

from tests.kodi_test_utils import FakeDialogProgress, load_plugin_module


def video(name, folder="TV/"):
    return {"path": folder + name, "name": name, "is_file": True}


def is_video(path):
    return path.endswith((".mkv", ".mp4"))


class CountingMonitor:
    def __init__(self, abort_after=None):
        self.waits = 0
        self.abort_after = abort_after

    def waitForAbort(self, timeout):
        self.waits += 1
        return self.abort_after is not None and self.waits >= self.abort_after


class PlayQueueTests(unittest.TestCase):
    def setUp(self):
        self.module, _addon, _profile = load_plugin_module("pentaract_play_queue_test", "resources/lib/play_queue.py")

    def test_next_video_follows_kodi_listing_order(self):
        elements = [
            video("Episode 10.mkv"),
            {"path": "TV/Extras/", "name": "Extras", "is_file": False},
            video("Episode 2.mkv"),
            video("notes.txt"),
            video("Episode 1.mp4"),
        ]
        self.assertEqual("TV/Episode 2.mkv", self.module.next_video(elements, "TV/Episode 1.mp4", is_video)["path"])
        self.assertEqual("TV/Episode 10.mkv", self.module.next_video(elements, "TV/Episode 2.mkv", is_video)["path"])

    def test_next_video_ignores_a_leading_the(self):
        elements = [video("The Zoo.mkv"), video("Middle.mkv"), video("Apple.mkv")]
        self.assertEqual("TV/The Zoo.mkv", self.module.next_video(elements, "TV/Middle.mkv", is_video)["path"])

    def test_no_next_video_after_the_last_one_or_for_an_unlisted_file(self):
        elements = [video("a.mkv"), video("b.mkv")]
        self.assertIsNone(self.module.next_video(elements, "TV/b.mkv", is_video))
        self.assertIsNone(self.module.next_video(elements, "TV/gone.mkv", is_video))
        self.assertIsNone(self.module.next_video([], "TV/a.mkv", is_video))

    def test_countdown_runs_out(self):
        dialog = FakeDialogProgress()
        monitor = CountingMonitor()
        self.assertTrue(self.module.countdown(dialog, monitor, "Pentaract", lambda s: "in %d" % s, seconds=3))
        self.assertEqual([(0, "in 3"), (33, "in 2"), (66, "in 1")], dialog.updated)
        self.assertEqual(3, monitor.waits)
        self.assertEqual(1, dialog.closed)

    def test_countdown_cancelled_by_the_user(self):
        dialog = FakeDialogProgress()
        dialog.cancel_after_updates = 2
        self.assertFalse(self.module.countdown(dialog, CountingMonitor(), "Pentaract", str, seconds=5))
        self.assertEqual(2, len(dialog.updated))
        self.assertEqual(1, dialog.closed)

    def test_countdown_stops_when_kodi_exits(self):
        dialog = FakeDialogProgress()
        self.assertFalse(self.module.countdown(dialog, CountingMonitor(abort_after=1), "Pentaract", str, seconds=5))
        self.assertEqual(1, dialog.closed)


if __name__ == "__main__":
    unittest.main()
