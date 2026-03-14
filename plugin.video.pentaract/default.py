import json
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


ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
PLUGIN_URL = sys.argv[0]
PARAMS = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
DIALOG = xbmcgui.Dialog()
CLIENT = PentaractClient(ADDON)
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
PROXY_SESSIONS_DIR = os.path.join(PROFILE_DIR, "proxy_sessions")
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 57342
PROXY_BASE_URL = "http://%s:%d" % (PROXY_HOST, PROXY_PORT)
PROXY_HEALTH_URL = PROXY_BASE_URL + "/health"
PROXY_START_TIMEOUT_SECONDS = 8.0
SESSION_TTL_SECONDS = 12 * 60 * 60
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
    message = error.message or "Error de comunicacion con Pentaract"
    notify(message, xbmcgui.NOTIFICATION_ERROR)
    log("API error (%s): %s" % (error.status, message), xbmc.LOGERROR)


def prompt_text(heading, current_value="", hidden=False):
    option = xbmcgui.ALPHANUM_HIDE_INPUT if hidden else 0
    return DIALOG.input(
        heading,
        defaultt=current_value,
        type=xbmcgui.INPUT_ALPHANUM,
        option=option,
    ).strip()


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
        return "%s, URL directa al backend" % profile_name
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


def cleanup_stale_proxy_sessions():
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


def register_proxy_session(storage_id, path, title):
    cleanup_stale_proxy_sessions()
    xbmcvfs.mkdirs(PROXY_SESSIONS_DIR)

    _profile, buffer_settings = effective_buffer_settings()
    session_id = str(uuid.uuid4())
    session_path = os.path.join(PROXY_SESSIONS_DIR, "%s.json" % session_id)
    session = {
        "storage_id": storage_id,
        "path": path,
        "title": title or os.path.basename(path or ""),
        "mime_type": mimetypes.guess_type(path)[0] or "video/mp4",
        "prebuffer_bytes": buffer_settings["prebuffer_bytes"],
        "request_timeout_seconds": buffer_settings["request_timeout_seconds"],
        "chunk_size_bytes": buffer_settings["chunk_size_bytes"],
        "created_at": int(time.time()),
    }
    with open(session_path, "w", encoding="utf-8") as handle:
        json.dump(session, handle)
    return session_id, PROXY_BASE_URL + "/stream/" + session_id


def prompt_for_configuration(force_server=False, force_credentials=False):
    base_url = CLIENT.base_url
    username = CLIENT.username
    password = CLIENT.password

    if force_server or not base_url:
        base_url = prompt_text("URL de Pentaract", base_url or "")
        if not base_url:
            return False
        CLIENT.base_url = base_url

    if force_credentials or not username:
        username = prompt_text("Usuario o email", username)
        if not username:
            return False
        CLIENT.username = username

    if force_credentials or not password:
        password = prompt_text("Contrasena", password, hidden=True)
        if not password:
            return False
        CLIENT.password = password

    CLIENT.clear_session()
    return True


def ensure_authenticated(interactive=True):
    attempts = 0
    while attempts < 3:
        try:
            CLIENT.ensure_token()
            return True
        except ConfigurationError:
            if not interactive or not prompt_for_configuration():
                return False
        except PentaractAPIError as error:
            if error.status == 401 and interactive:
                notify("Credenciales invalidas. Actualizalas.", xbmcgui.NOTIFICATION_ERROR)
                if not prompt_for_configuration(force_credentials=True):
                    return False
                attempts += 1
                continue
            if error.status == 0 and interactive:
                notify("No se pudo conectar con Pentaract. Revisa la URL.", xbmcgui.NOTIFICATION_ERROR)
                if not prompt_for_configuration(force_server=True):
                    return False
                attempts += 1
                continue
            show_api_error(error)
            return False
        attempts += 1
    return False


def add_directory_item(label, params, icon="DefaultFolder.png"):
    list_item = xbmcgui.ListItem(label=label)
    list_item.setArt({"icon": icon, "thumb": icon})
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url(params), list_item, True)


def add_action_item(label, params, icon="DefaultAddonProgram.png"):
    list_item = xbmcgui.ListItem(label=label)
    list_item.setArt({"icon": icon, "thumb": icon})
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url(params), list_item, True)


def add_playable_item(storage_id, element, current_path):
    label = "%s  [%s]" % (element["name"], format_size(element.get("size", 0)))
    url = plugin_url(
        {
            "action": "play",
            "storage_id": storage_id,
            "path": element["path"],
            "title": element["name"],
        }
    )
    list_item = xbmcgui.ListItem(label=label)
    mime_type = mimetypes.guess_type(element["path"])[0] or "video/mp4"
    list_item.setMimeType(mime_type)
    list_item.setContentLookup(False)
    list_item.setProperty("IsPlayable", "true")
    list_item.setInfo(
        "video",
        {
            "title": element["name"],
            "size": int(element.get("size", 0)),
        },
    )
    list_item.setArt({"icon": "DefaultVideo.png", "thumb": "DefaultVideo.png"})
    xbmcplugin.addDirectoryItem(HANDLE, url, list_item, False)


def add_file_info_item(storage_id, storage_name, element, current_path):
    label = "%s  [%s]" % (element["name"], format_size(element.get("size", 0)))
    list_item = xbmcgui.ListItem(label=label)
    list_item.setInfo("video", {"title": element["name"]})
    list_item.setArt({"icon": "DefaultFile.png", "thumb": "DefaultFile.png"})
    xbmcplugin.addDirectoryItem(
        HANDLE,
        plugin_url(
            {
                "action": "file_info",
                "storage_id": storage_id,
                "storage_name": storage_name,
                "path": element["path"],
                "name": element["name"],
                "size": str(element.get("size", 0)),
                "current_path": current_path,
            }
        ),
        list_item,
        True,
    )


def storage_label(storage):
    return "%s  [%s, %s]" % (
        storage["name"],
        storage.get("files_amount", 0),
        format_size(storage.get("size", 0)),
    )


def render_root(prompt_login=False):
    xbmcplugin.setPluginCategory(HANDLE, "Pentaract")
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)

    add_action_item("[ Configurar conexion ]", {"action": "configure"})
    add_action_item("[ Actualizar credenciales ]", {"action": "login"})
    add_action_item("[ Buffer local: %s ]" % buffer_profile_summary(), {"action": "buffer_settings"})
    add_action_item("[ Borrar credenciales ]", {"action": "clear_credentials"})

    if ensure_authenticated(interactive=prompt_login):
        try:
            storages = CLIENT.list_storages()
        except PentaractAPIError as error:
            show_api_error(error)
            storages = []

        for storage in sorted(storages, key=lambda item: item.get("name", "").lower()):
            add_directory_item(
                storage_label(storage),
                {
                    "action": "browse",
                    "storage_id": storage["id"],
                    "storage_name": storage["name"],
                    "path": "",
                },
            )

        if not storages:
            notify("No hay storages accesibles para este usuario.")

    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def render_directory(storage_id, storage_name, path):
    xbmcplugin.setPluginCategory(HANDLE, storage_name or "Pentaract")
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)

    if not ensure_authenticated(interactive=True):
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
        return

    try:
        elements = CLIENT.list_directory(storage_id, path)
    except PentaractAPIError as error:
        show_api_error(error)
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
        return

    if path:
        add_directory_item(
            "..",
            {
                "action": "browse",
                "storage_id": storage_id,
                "storage_name": storage_name,
                "path": parent_path(path),
            },
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
                add_playable_item(storage_id, element, path)
            elif ADDON.getSettingBool("show_non_video"):
                add_file_info_item(storage_id, storage_name, element, path)
        else:
            add_directory_item(
                element["name"],
                {
                    "action": "browse",
                    "storage_id": storage_id,
                    "storage_name": storage_name,
                    "path": element["path"],
                },
            )

    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def play_video(storage_id, path, title):
    if not ensure_authenticated(interactive=True):
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    try:
        if direct_stream_enabled():
            stream_url = CLIENT.build_stream_url(storage_id, path)
        else:
            if not ensure_local_proxy_service():
                notify("No se pudo iniciar el proxy local de streaming.", xbmcgui.NOTIFICATION_ERROR)
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
                return
            _session_id, stream_url = register_proxy_session(storage_id, path, title)
    except OSError as error:
        log("Failed to register local streaming session: %s" % error, xbmc.LOGERROR)
        notify("No se pudo preparar el stream local.", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    except (ConfigurationError, PentaractAPIError) as error:
        if isinstance(error, PentaractAPIError):
            show_api_error(error)
        else:
            notify(str(error), xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
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
    message = "Ruta: %s\nTamano: %s\n\nKodi solo reproducira ficheros de video compatibles." % (
        PARAMS.get("path", ""),
        format_size(int(PARAMS.get("size", "0"))),
    )
    DIALOG.ok(PARAMS.get("name", "Fichero"), message)
    render_directory(
        PARAMS.get("storage_id", ""),
        PARAMS.get("storage_name", ""),
        PARAMS.get("current_path", ""),
    )


def configure():
    if prompt_for_configuration(force_server=True, force_credentials=True):
        if ensure_authenticated(interactive=True):
            notify("Conexion validada correctamente.")
    render_root(prompt_login=False)


def refresh_login():
    if prompt_for_configuration(force_credentials=True):
        if ensure_authenticated(interactive=True):
            notify("Sesion renovada.")
    render_root(prompt_login=False)


def clear_credentials():
    CLIENT.clear_credentials()
    notify("Credenciales eliminadas.")
    render_root(prompt_login=False)


def open_buffer_settings():
    DIALOG.ok(
        "Pentaract",
        (
            "Los ajustes de buffer de Pentaract son locales al addon.\n\n"
            "No modifican la cache, ni los timeouts, ni ningun ajuste global de Kodi.\n\n"
            "Si eliges 'Directo (sin buffer)', Kodi reproducira desde la URL del backend sin usar el proxy local."
        ),
    )
    ADDON.openSettings()
    render_root(prompt_login=False)


def route():
    action = PARAMS.get("action")
    if action == "browse":
        render_directory(
            PARAMS.get("storage_id", ""),
            PARAMS.get("storage_name", ""),
            PARAMS.get("path", ""),
        )
        return
    if action == "play":
        play_video(
            PARAMS.get("storage_id", ""),
            PARAMS.get("path", ""),
            PARAMS.get("title", ""),
        )
        return
    if action == "configure":
        configure()
        return
    if action == "login":
        refresh_login()
        return
    if action == "clear_credentials":
        clear_credentials()
        return
    if action in ("optimize_streaming", "buffer_settings"):
        open_buffer_settings()
        return
    if action == "file_info":
        show_file_info()
        return
    render_root(prompt_login=True)


if __name__ == "__main__":
    route()
