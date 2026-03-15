import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.api import ConfigurationError, PentaractAPIError, PentaractClient
from resources.lib.proxy import (
    PROXY_BASE_URL,
    PROXY_HEALTH_URL,
    PROXY_START_TIMEOUT_SECONDS,
    cleanup_proxy_sessions,
    save_proxy_session,
)


ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
PLUGIN_URL = sys.argv[0]
PARAMS = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
DIALOG = xbmcgui.Dialog()
CLIENT = PentaractClient(ADDON)
DEFAULT_BUFFER_PROFILE = "automatic"
SERVICE_SCRIPT_PATH = xbmcvfs.translatePath(os.path.join(ADDON.getAddonInfo("path"), "service.py"))

BUFFER_PROFILE_PRESETS = {
    "automatic": {
        "prebuffer_bytes": 16 * 1024 * 1024,
        "request_timeout_seconds": 60,
        "chunk_size_bytes": 262144,
    },
    "low_memory": {
        "prebuffer_bytes": 8 * 1024 * 1024,
        "request_timeout_seconds": 45,
        "chunk_size_bytes": 131072,
    },
    "balanced": {
        "prebuffer_bytes": 24 * 1024 * 1024,
        "request_timeout_seconds": 60,
        "chunk_size_bytes": 262144,
    },
    "high_bitrate": {
        "prebuffer_bytes": 64 * 1024 * 1024,
        "request_timeout_seconds": 120,
        "chunk_size_bytes": 524288,
    },
}

BUFFER_PROFILE_LABEL_IDS = {
    "disabled": 30043,
    "automatic": 30014,
    "low_memory": 30015,
    "balanced": 30016,
    "high_bitrate": 30017,
    "custom": 30018,
}

ALLOWED_PREBUFFER_MB = (8, 16, 32, 64, 128)
ALLOWED_TIMEOUT_SECONDS = (30, 60, 120, 240)
ALLOWED_CHUNK_SIZES = (65536, 131072, 262144, 524288)

VIDEO_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogg",
    ".ts",
    ".webm",
    ".wmv",
}


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[plugin.video.pentaract] %s" % message, level)


def plugin_url(params):
    return "%s?%s" % (PLUGIN_URL, urllib.parse.urlencode(params))


def format_size(num_bytes):
    size = float(num_bytes or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return "%d %s" % (int(size), unit)
    return "%.1f %s" % (size, unit)


def is_video_path(path):
    return os.path.splitext(path.lower())[1] in VIDEO_EXTENSIONS


def parent_path(path):
    trimmed = (path or "").rstrip("/")
    if not trimmed:
        return ""
    separator = trimmed.rfind("/")
    if separator == -1:
        return ""
    return trimmed[: separator + 1]


def notify(message, icon=xbmcgui.NOTIFICATION_INFO):
    DIALOG.notification("Pentaract", message, icon, 4000)


def localized(string_id, fallback=""):
    value = ADDON.getLocalizedString(string_id)
    return value or fallback


def show_api_error(error):
    message = error.message or "Communication error with Pentaract"
    notify(message, xbmcgui.NOTIFICATION_ERROR)
    log("API error (%s): %s" % (error.status, message), xbmc.LOGERROR)

def addon_setting_string(setting_id, legacy_ids=None):
    value = ADDON.getSettingString(setting_id).strip()
    if value:
        return value

    for legacy_id in legacy_ids or ():
        legacy_value = ADDON.getSettingString(legacy_id).strip()
        if legacy_value:
            return legacy_value

    return ""


def addon_setting_int(setting_id, default, allowed_values=None, legacy_ids=None):
    raw_value = addon_setting_string(setting_id, legacy_ids=legacy_ids)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default

    if allowed_values and value not in allowed_values:
        return default
    return value


def selected_buffer_profile():
    profile = addon_setting_string("buffer_profile", legacy_ids=("cache_profile",))
    if profile in ("disabled", "custom") or profile in BUFFER_PROFILE_PRESETS:
        return profile
    return DEFAULT_BUFFER_PROFILE


def selected_buffer_profile_label():
    profile = selected_buffer_profile()
    return localized(BUFFER_PROFILE_LABEL_IDS.get(profile, 30014), profile)


def effective_buffer_settings():
    profile = selected_buffer_profile()
    if profile == "disabled":
        return profile, {}
    if profile == "custom":
        return profile, {
            "prebuffer_bytes": addon_setting_int(
                "custom_prebuffer_mb",
                32,
                allowed_values=ALLOWED_PREBUFFER_MB,
                legacy_ids=("custom_cache_memorysize_mb",),
            )
            * 1024
            * 1024,
            "request_timeout_seconds": addon_setting_int(
                "custom_request_timeout_secs",
                60,
                allowed_values=ALLOWED_TIMEOUT_SECONDS,
                legacy_ids=("custom_cache_readfactor",),
            ),
            "chunk_size_bytes": addon_setting_int(
                "custom_chunk_size_bytes",
                262144,
                allowed_values=ALLOWED_CHUNK_SIZES,
                legacy_ids=("custom_cache_chunksize",),
            ),
        }

    return profile, dict(BUFFER_PROFILE_PRESETS.get(profile, BUFFER_PROFILE_PRESETS[DEFAULT_BUFFER_PROFILE]))


def buffer_profile_summary():
    profile_name = selected_buffer_profile_label()
    _profile, settings = effective_buffer_settings()
    if _profile == "disabled":
        return "%s, direct backend URL" % profile_name
    return "%s, %s prebuffer, %ds timeout" % (
        profile_name,
        format_size(settings["prebuffer_bytes"]),
        settings["request_timeout_seconds"],
    )


def direct_stream_enabled():
    return selected_buffer_profile() == "disabled"


def local_proxy_is_ready():
    try:
        with urllib.request.urlopen(PROXY_HEALTH_URL, timeout=1) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return False


def ensure_local_proxy_service():
    if local_proxy_is_ready():
        return True

    safe_script_path = SERVICE_SCRIPT_PATH.replace("\\", "\\\\").replace("\"", "\\\"")
    xbmc.executebuiltin("RunScript(\"%s\")" % safe_script_path)
    deadline = time.time() + PROXY_START_TIMEOUT_SECONDS
    while time.time() < deadline:
        if local_proxy_is_ready():
            return True
        xbmc.sleep(200)

    log("Local streaming proxy did not become ready", xbmc.LOGERROR)
    return False


def build_proxy_session(storage_id, path, title, buffer_settings, created_at=None):
    return {
        "storage_id": storage_id,
        "path": path,
        "title": title or os.path.basename(path or ""),
        "mime_type": mimetypes.guess_type(path)[0] or "video/mp4",
        "prebuffer_bytes": buffer_settings["prebuffer_bytes"],
        "request_timeout_seconds": buffer_settings["request_timeout_seconds"],
        "chunk_size_bytes": buffer_settings["chunk_size_bytes"],
        "created_at": int(created_at if created_at is not None else time.time()),
    }


def register_proxy_session(storage_id, path, title):
    session_id = str(uuid.uuid4())
    _profile, buffer_settings = effective_buffer_settings()
    save_proxy_session(session_id, build_proxy_session(storage_id, path, title, buffer_settings))
    cleanup_proxy_sessions()
    return session_id, PROXY_BASE_URL + "/stream/" + session_id


def auth_settings_snapshot():
    return (
        CLIENT.base_url,
        CLIENT.username,
        CLIENT.password,
    )


def open_addon_settings(show_message=True):
    previous_settings = auth_settings_snapshot()
    if show_message:
        DIALOG.ok(
            "Pentaract",
            (
                "Configure the addon URL, credentials, and streaming mode here.\n\n"
                "To clear stored credentials, leave the user and password fields empty and save the changes."
            ),
        )

    ADDON.openSettings()

    current_settings = auth_settings_snapshot()
    if current_settings != previous_settings:
        CLIENT.clear_session()
        notify("Addon settings updated.")
        return True
    return False


def ensure_authenticated(interactive=True):
    attempts = 0
    while attempts < 3:
        try:
            CLIENT.ensure_token()
            return True
        except ConfigurationError:
            if not interactive:
                return False
            notify("Configure the connection from 'Addon settings'.", xbmcgui.NOTIFICATION_ERROR)
            if not open_addon_settings(show_message=False):
                return False
        except PentaractAPIError as error:
            if error.status == 401 and interactive:
                notify("Invalid credentials. Check the addon settings.", xbmcgui.NOTIFICATION_ERROR)
                if not open_addon_settings(show_message=False):
                    return False
                attempts += 1
                continue
            if error.status == 0 and interactive:
                notify("Could not connect to Pentaract. Check the addon settings.", xbmcgui.NOTIFICATION_ERROR)
                if not open_addon_settings(show_message=False):
                    return False
                attempts += 1
                continue
            show_api_error(error)
            return False
        attempts += 1
    return False


def begin_directory(category):
    xbmcplugin.setPluginCategory(HANDLE, category)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)


def end_directory():
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def add_item(label, params, folder, icon, mime_type=None, info=None, properties=None):
    list_item = xbmcgui.ListItem(label=label)
    list_item.setArt({"icon": icon, "thumb": icon})
    if mime_type:
        list_item.setMimeType(mime_type)
        list_item.setContentLookup(False)
    if info:
        list_item.setInfo("video", info)
    for key, value in (properties or {}).items():
        list_item.setProperty(key, value)
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url(params), list_item, folder)


def browse_params(storage_id, storage_name, path):
    return {
        "action": "browse",
        "storage_id": storage_id,
        "storage_name": storage_name,
        "path": path,
    }


def file_info_params(storage_id, storage_name, element, current_path):
    return {
        "action": "file_info",
        "storage_id": storage_id,
        "storage_name": storage_name,
        "path": element["path"],
        "name": element["name"],
        "size": str(element.get("size", 0)),
        "current_path": current_path,
    }


def file_label(element):
    return "%s  [%s]" % (element["name"], format_size(element.get("size", 0)))


def add_storage_item(storage):
    add_item(
        storage_label(storage),
        browse_params(storage["id"], storage["name"], ""),
        True,
        "DefaultFolder.png",
    )


def add_navigation_item(label, params, icon="DefaultFolder.png"):
    add_item(label, params, True, icon)


def add_playable_file_item(storage_id, element):
    add_item(
        file_label(element),
        {
            "action": "play",
            "storage_id": storage_id,
            "path": element["path"],
            "title": element["name"],
        },
        False,
        "DefaultVideo.png",
        mime_type=mimetypes.guess_type(element["path"])[0] or "video/mp4",
        info={"title": element["name"], "size": int(element.get("size", 0))},
        properties={"IsPlayable": "true"},
    )


def add_info_file_item(storage_id, storage_name, element, current_path):
    add_item(
        file_label(element),
        file_info_params(storage_id, storage_name, element, current_path),
        True,
        "DefaultFile.png",
        info={"title": element["name"]},
    )


def storage_label(storage):
    return "%s  [%s, %s]" % (
        storage["name"],
        storage.get("files_amount", 0),
        format_size(storage.get("size", 0)),
    )


def render_root(prompt_login=False):
    begin_directory("Pentaract")
    add_navigation_item(
        "Addon settings",
        {"action": "addon_settings"},
        icon="DefaultAddonProgram.png",
    )

    if ensure_authenticated(interactive=prompt_login):
        try:
            storages = CLIENT.list_storages()
        except PentaractAPIError as error:
            show_api_error(error)
            storages = []

        for storage in sorted(storages, key=lambda item: item.get("name", "").lower()):
            add_storage_item(storage)

        if not storages:
            notify("No storages are available for this user.")

    end_directory()


def render_directory(storage_id, storage_name, path):
    begin_directory(storage_name or "Pentaract")

    if not ensure_authenticated(interactive=True):
        end_directory()
        return

    try:
        elements = CLIENT.list_directory(storage_id, path)
    except PentaractAPIError as error:
        show_api_error(error)
        end_directory()
        return

    if path:
        add_navigation_item(
            "..",
            browse_params(storage_id, storage_name, parent_path(path)),
            icon="DefaultFolderBack.png",
        )

    elements = sorted(
        elements,
        key=lambda item: (
            1 if item.get("is_file") else 0,
            item.get("name", "").lower(),
        ),
    )

    for element in elements:
        if element.get("is_file"):
            if is_video_path(element["path"]):
                add_playable_file_item(storage_id, element)
            elif ADDON.getSettingBool("show_non_video"):
                add_info_file_item(storage_id, storage_name, element, path)
        else:
            add_navigation_item(
                element["name"],
                browse_params(storage_id, storage_name, element["path"]),
            )

    end_directory()


def clear_resolved_url():
    xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def playback_stream_url(storage_id, path, title):
    if direct_stream_enabled():
        return CLIENT.build_stream_url(storage_id, path, download_id=str(uuid.uuid4()))
    if not ensure_local_proxy_service():
        raise OSError("Could not start the local streaming proxy.")
    _session_id, stream_url = register_proxy_session(storage_id, path, title)
    return stream_url


def play_video(storage_id, path, title):
    if not ensure_authenticated(interactive=True):
        clear_resolved_url()
        return

    try:
        stream_url = playback_stream_url(storage_id, path, title)
    except OSError as error:
        log("Failed to register local streaming session: %s" % error, xbmc.LOGERROR)
        notify(str(error), xbmcgui.NOTIFICATION_ERROR)
        clear_resolved_url()
        return
    except (ConfigurationError, PentaractAPIError) as error:
        if isinstance(error, PentaractAPIError):
            show_api_error(error)
        else:
            notify(str(error), xbmcgui.NOTIFICATION_ERROR)
        clear_resolved_url()
        return

    list_item = xbmcgui.ListItem(path=stream_url)
    if title:
        list_item.setInfo("video", {"title": title})
    mime_type = mimetypes.guess_type(path)[0]
    if mime_type:
        list_item.setMimeType(mime_type)
    list_item.setContentLookup(False)
    list_item.setProperty("IsPlayable", "true")
    xbmcplugin.setResolvedUrl(HANDLE, True, list_item)


def show_file_info():
    message = "Path: %s\nSize: %s\n\nKodi will only play supported video files." % (
        PARAMS.get("path", ""),
        format_size(int(PARAMS.get("size", "0"))),
    )
    DIALOG.ok(PARAMS.get("name", "File"), message)
    render_directory(
        PARAMS.get("storage_id", ""),
        PARAMS.get("storage_name", ""),
        PARAMS.get("current_path", ""),
    )

def open_settings_from_root():
    open_addon_settings(show_message=True)
    render_root(prompt_login=False)


def browse_from_params():
    render_directory(
        PARAMS.get("storage_id", ""),
        PARAMS.get("storage_name", ""),
        PARAMS.get("path", ""),
    )


def play_from_params():
    play_video(
        PARAMS.get("storage_id", ""),
        PARAMS.get("path", ""),
        PARAMS.get("title", ""),
    )


def route():
    action_handlers = {
        "addon_settings": open_settings_from_root,
        "buffer_settings": open_settings_from_root,
        "browse": browse_from_params,
        "clear_credentials": open_settings_from_root,
        "configure": open_settings_from_root,
        "file_info": show_file_info,
        "login": open_settings_from_root,
        "optimize_streaming": open_settings_from_root,
        "play": play_from_params,
    }
    handler = action_handlers.get(PARAMS.get("action"))
    if handler is None:
        render_root(prompt_login=False)
        return
    handler()


if __name__ == "__main__":
    route()
