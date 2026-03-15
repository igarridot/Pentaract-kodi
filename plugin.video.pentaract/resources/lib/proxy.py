import json
import os
import time

import xbmcaddon
import xbmcvfs


ADDON = xbmcaddon.Addon("plugin.video.pentaract")
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
PROXY_SESSIONS_DIR = os.path.join(PROFILE_DIR, "proxy_sessions")
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 57342
PROXY_BASE_URL = "http://%s:%d" % (PROXY_HOST, PROXY_PORT)
PROXY_HEALTH_URL = PROXY_BASE_URL + "/health"
PROXY_START_TIMEOUT_SECONDS = 8.0
SESSION_TTL_SECONDS = 12 * 60 * 60


def proxy_session_path(session_id):
    return os.path.join(PROXY_SESSIONS_DIR, "%s.json" % session_id)


def ensure_proxy_sessions_dir():
    xbmcvfs.mkdirs(PROXY_SESSIONS_DIR)


def cleanup_proxy_sessions():
    if not os.path.isdir(PROXY_SESSIONS_DIR):
        return

    cutoff = time.time() - SESSION_TTL_SECONDS
    for filename in os.listdir(PROXY_SESSIONS_DIR):
        session_path = os.path.join(PROXY_SESSIONS_DIR, filename)
        try:
            if not os.path.isfile(session_path):
                continue
            if os.path.getmtime(session_path) >= cutoff:
                continue
            os.remove(session_path)
        except OSError:
            continue


def save_proxy_session(session_id, session):
    ensure_proxy_sessions_dir()
    with open(proxy_session_path(session_id), "w", encoding="utf-8") as handle:
        json.dump(session, handle)


def load_proxy_session(session_id):
    try:
        with open(proxy_session_path(session_id), "r", encoding="utf-8") as handle:
            session = json.load(handle)
    except (OSError, ValueError):
        return None

    if not isinstance(session, dict):
        return None
    return session
