"""Play queue: once a video plays to its end, the plugin starts the next
video in the same folder, after a short countdown the user can cancel.

"Next" follows the order Kodi shows the listing in: by label, ignoring a
leading "The", with numbers compared by value (episode 2 before episode 10)."""

import re


COUNTDOWN_SECONDS = 5


def listing_sort_key(name):
    lowered = (name or "").lower()
    if lowered.startswith("the "):
        lowered = lowered[4:]
    # re.split with a capture group alternates text and digits, always
    # starting with text, so two keys compare str to str and int to int.
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", lowered)]


def next_video(elements, current_path, is_video):
    """Returns the video listed after current_path in its folder, or None
    when it is the last one or no longer listed."""
    videos = sorted(
        (element for element in elements if element.get("is_file") and is_video(element["path"])),
        key=lambda element: listing_sort_key(element.get("name")),
    )
    paths = [element["path"] for element in videos]
    if current_path not in paths:
        return None
    index = paths.index(current_path) + 1
    return videos[index] if index < len(videos) else None


def countdown(dialog, monitor, heading, message_for, seconds=COUNTDOWN_SECONDS):
    """Shows a progress dialog counting down from seconds. Returns True when
    it ran out, False if the user cancelled it or Kodi is exiting."""
    dialog.create(heading, message_for(seconds))
    try:
        for remaining in range(seconds, 0, -1):
            dialog.update(int(100 * (seconds - remaining) / seconds), message_for(remaining))
            if monitor.waitForAbort(1) or dialog.iscanceled():
                return False
        return True
    finally:
        dialog.close()
