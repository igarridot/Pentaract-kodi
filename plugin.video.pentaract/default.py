import mimetypes
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET

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
KODI_ADVANCEDSETTINGS_PATH = xbmcvfs.translatePath("special://masterprofile/advancedsettings.xml")
RECOMMENDED_CURL_CLIENT_TIMEOUT = 120
RECOMMENDED_CURL_LOW_SPEED_TIME = 120

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


def ensure_xml_child(parent, tag):
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    return child


def indent_xml(element, level=0):
    prefix = "\n" + "    " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = prefix + "    "
        for child in element:
            indent_xml(child, level + 1)
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = prefix
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = prefix


def streaming_tuning_is_applied():
    if not xbmcvfs.exists(KODI_ADVANCEDSETTINGS_PATH):
        return False

    try:
        root = ET.parse(KODI_ADVANCEDSETTINGS_PATH).getroot()
    except (ET.ParseError, OSError):
        return False

    network = root.find("network")
    if network is None:
        return False

    client_timeout = network.findtext("curlclienttimeout", default="0")
    low_speed_time = network.findtext("curllowspeedtime", default="0")
    try:
        return (
            int(client_timeout) >= RECOMMENDED_CURL_CLIENT_TIMEOUT
            and int(low_speed_time) >= RECOMMENDED_CURL_LOW_SPEED_TIME
        )
    except ValueError:
        return False


def apply_streaming_tuning():
    if streaming_tuning_is_applied():
        DIALOG.ok(
            "Pentaract",
            (
                "Kodi ya tiene aplicado el ajuste de streaming recomendado.\n\n"
                "Si lo acabas de cambiar y todavia no surte efecto, reinicia Kodi."
            ),
        )
        render_root(prompt_login=False)
        return

    confirmed = DIALOG.yesno(
        "Pentaract",
        (
            "Este ajuste modificara advancedsettings.xml de Kodi para aumentar los timeouts HTTP "
            "globales y mejorar el streaming desde Pentaract.\n\n"
            "Valores aplicados:\n"
            "- curlclienttimeout = %d\n"
            "- curllowspeedtime = %d\n\n"
            "Quieres aplicarlo?"
        )
        % (RECOMMENDED_CURL_CLIENT_TIMEOUT, RECOMMENDED_CURL_LOW_SPEED_TIME),
    )
    if not confirmed:
        render_root(prompt_login=False)
        return

    try:
        settings_dir = os.path.dirname(KODI_ADVANCEDSETTINGS_PATH)
        xbmcvfs.mkdirs(settings_dir)

        if xbmcvfs.exists(KODI_ADVANCEDSETTINGS_PATH):
            tree = ET.parse(KODI_ADVANCEDSETTINGS_PATH)
            root = tree.getroot()
        else:
            root = ET.Element("advancedsettings")
            tree = ET.ElementTree(root)

        network = ensure_xml_child(root, "network")
        ensure_xml_child(network, "curlclienttimeout").text = str(RECOMMENDED_CURL_CLIENT_TIMEOUT)
        ensure_xml_child(network, "curllowspeedtime").text = str(RECOMMENDED_CURL_LOW_SPEED_TIME)

        indent_xml(root)
        tree.write(KODI_ADVANCEDSETTINGS_PATH, encoding="utf-8", xml_declaration=False)
    except Exception as error:
        log("Failed to update advancedsettings.xml: %s" % error, xbmc.LOGERROR)
        notify("No se pudo actualizar advancedsettings.xml", xbmcgui.NOTIFICATION_ERROR)
        render_root(prompt_login=False)
        return

    DIALOG.ok(
        "Pentaract",
        (
            "Ajuste aplicado correctamente.\n\n"
            "Reinicia Kodi para que los nuevos timeouts HTTP entren en vigor."
        ),
    )
    render_root(prompt_login=False)


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

    streaming_label = "[ Streaming optimizado ]" if streaming_tuning_is_applied() else "[ Aplicar ajuste de streaming recomendado ]"
    add_action_item("[ Configurar conexion ]", {"action": "configure"})
    add_action_item("[ Actualizar credenciales ]", {"action": "login"})
    add_action_item(streaming_label, {"action": "optimize_streaming"})
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
        stream_url = CLIENT.build_stream_url(storage_id, path)
    except PentaractAPIError as error:
        show_api_error(error)
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
    if action == "optimize_streaming":
        apply_streaming_tuning()
        return
    if action == "file_info":
        show_file_info()
        return
    render_root(prompt_login=True)


if __name__ == "__main__":
    route()
