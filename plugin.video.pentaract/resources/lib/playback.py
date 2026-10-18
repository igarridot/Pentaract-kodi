"""Reports watch progress for the video the plugin just resolved.

The plugin keeps running after setResolvedUrl and follows the player until
the video stops, saving the position on the server every few seconds and
once more at the end. The server decides what counts as watched."""

import time

import xbmc


SAVE_INTERVAL_SECONDS = 10
POLL_SECONDS = 1
# Telegram can take a while to deliver the first bytes, and the local proxy
# prebuffers before Kodi sees any, so give the player time to start.
START_TIMEOUT_SECONDS = 180


class PlaybackWatcher(xbmc.Player):
    """Tracks the next video Kodi starts: the one the plugin resolved."""

    def __init__(self):
        super().__init__()
        self.started = False
        self.finished = False

    def onAVStarted(self):
        self.started = True

    def onPlayBackStopped(self):
        self.finished = True

    def onPlayBackEnded(self):
        self.finished = True

    def onPlayBackError(self):
        self.finished = True

    def position(self):
        """Returns (position, duration) in seconds, or None if Kodi has
        nothing usable (not playing anymore, or duration still unknown)."""
        try:
            position = float(self.getTime())
            duration = float(self.getTotalTime())
        except (RuntimeError, TypeError, ValueError):
            return None
        if duration <= 0:
            return None
        return position, duration


def follow_playback(watcher, monitor, save, clock=time.time):
    """Saves the watcher's position every SAVE_INTERVAL_SECONDS while the video
    plays, and once more when it stops. save(position, duration) returns
    whether the server stored it. Returns True if the last save succeeded."""
    deadline = clock() + START_TIMEOUT_SECONDS
    while not watcher.started:
        if watcher.finished or clock() > deadline or monitor.waitForAbort(POLL_SECONDS):
            return False

    latest = None
    saved = None
    last_save_at = clock()
    last_save_ok = False
    while not watcher.finished:
        current = watcher.position()
        if current is not None:
            latest = current
        if latest is not None and latest != saved and clock() - last_save_at >= SAVE_INTERVAL_SECONDS:
            last_save_ok = save(*latest)
            saved = latest
            last_save_at = clock()
        if monitor.waitForAbort(POLL_SECONDS):
            break

    if latest is not None and latest != saved:
        last_save_ok = save(*latest)
    return last_save_ok
