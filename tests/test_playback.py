import unittest

from tests.kodi_test_utils import load_plugin_module


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ScriptedMonitor:
    """Each wait advances the clock by the timeout and runs the next step of
    the script, which plays the part of Kodi between polls."""

    def __init__(self, clock, steps, abort_after=None):
        self.clock = clock
        self.steps = list(steps)
        self.waits = 0
        self.abort_after = abort_after

    def waitForAbort(self, timeout):
        self.clock.now += timeout
        self.waits += 1
        if self.steps:
            self.steps.pop(0)()
        return self.abort_after is not None and self.waits >= self.abort_after


class FakeWatcher:
    def __init__(self):
        self.started = False
        self.finished = False
        self.current = None

    def position(self):
        return self.current


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.module, _addon, _profile = load_plugin_module("pentaract_playback_test", "resources/lib/playback.py")
        self.clock = FakeClock()
        self.watcher = FakeWatcher()
        self.saves = []

    def save(self, position, duration):
        self.saves.append((position, duration))
        return True

    def play_until(self, seconds, then_stop=True):
        """Steps: start, then one poll per second at that position."""
        steps = [lambda: setattr(self.watcher, "started", True)]
        for second in range(1, seconds + 1):
            steps.append(lambda second=second: setattr(self.watcher, "current", (float(second), 100.0)))
        if then_stop:
            steps.append(lambda: setattr(self.watcher, "finished", True))
        return steps

    def test_saves_every_interval_and_once_more_on_stop(self):
        monitor = ScriptedMonitor(self.clock, self.play_until(25))

        self.assertTrue(self.module.follow_playback(self.watcher, monitor, self.save, clock=self.clock))

        positions = [position for position, _duration in self.saves]
        self.assertEqual([10.0, 20.0, 25.0], positions)

    def test_nothing_new_to_save_on_stop_saves_nothing_more(self):
        steps = self.play_until(10, then_stop=False)
        steps.append(lambda: setattr(self.watcher, "current", None))
        steps.append(lambda: setattr(self.watcher, "finished", True))
        monitor = ScriptedMonitor(self.clock, steps)

        self.module.follow_playback(self.watcher, monitor, self.save, clock=self.clock)

        self.assertEqual([(10.0, 100.0)], self.saves)

    def test_gives_up_when_playback_never_starts(self):
        monitor = ScriptedMonitor(self.clock, [])

        self.assertFalse(self.module.follow_playback(self.watcher, monitor, self.save, clock=self.clock))
        self.assertEqual([], self.saves)
        self.assertGreaterEqual(self.clock.now, self.module.START_TIMEOUT_SECONDS)

    def test_playback_error_before_start_stops_waiting(self):
        monitor = ScriptedMonitor(self.clock, [lambda: setattr(self.watcher, "finished", True)])

        self.assertFalse(self.module.follow_playback(self.watcher, monitor, self.save, clock=self.clock))
        self.assertEqual(1, monitor.waits)

    def test_kodi_exiting_still_saves_the_last_position(self):
        monitor = ScriptedMonitor(self.clock, self.play_until(5, then_stop=False), abort_after=7)

        self.module.follow_playback(self.watcher, monitor, self.save, clock=self.clock)

        self.assertEqual([(5.0, 100.0)], self.saves)

    def test_failed_last_save_is_reported(self):
        monitor = ScriptedMonitor(self.clock, self.play_until(3))

        result = self.module.follow_playback(self.watcher, monitor, lambda position, duration: False, clock=self.clock)

        self.assertFalse(result)

    def test_watcher_position_reads_kodi_player(self):
        watcher = self.module.PlaybackWatcher()
        self.assertIsNone(watcher.position())

        watcher.getPlayingFile = lambda: "http://backend/a.mkv"
        watcher.onAVStarted()
        watcher.getTime = lambda: 42.5
        watcher.getTotalTime = lambda: 0
        self.assertIsNone(watcher.position())

        watcher.getTotalTime = lambda: 5400
        self.assertEqual((42.5, 5400.0), watcher.position())

        watcher.onPlayBackEnded()
        self.assertTrue(watcher.started and watcher.finished)

    def test_watcher_ignores_another_video_taking_over(self):
        watcher = self.module.PlaybackWatcher()
        watcher.getPlayingFile = lambda: "http://backend/a.mkv"
        watcher.getTime = lambda: 42.5
        watcher.getTotalTime = lambda: 5400
        watcher.onAVStarted()
        self.assertEqual((42.5, 5400.0), watcher.position())

        # Kodi already plays the next video but has not said so yet.
        watcher.getPlayingFile = lambda: "http://backend/b.mkv"
        self.assertIsNone(watcher.position())
        self.assertFalse(watcher.finished)

        watcher.onAVStarted()
        self.assertTrue(watcher.finished)


if __name__ == "__main__":
    unittest.main()
