import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugin.video.pentaract"


class FakeAddon:
    def __init__(self, profile_dir, settings=None, info=None, localized_strings=None):
        self._settings = dict(settings or {})
        self._info = {
            "profile": str(profile_dir),
            "path": str(PLUGIN_ROOT),
        }
        self._info.update(info or {})
        self._localized_strings = dict(localized_strings or {})
        self.open_settings_calls = 0

    def getSettingString(self, setting_id):
        return str(self._settings.get(setting_id, ""))

    def setSettingString(self, setting_id, value):
        self._settings[setting_id] = "" if value is None else str(value)

    def getSettingBool(self, setting_id):
        value = self._settings.get(setting_id, False)
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    def getAddonInfo(self, key):
        return self._info.get(key, "")

    def getLocalizedString(self, string_id):
        return self._localized_strings.get(string_id, "")

    def openSettings(self):
        self.open_settings_calls += 1


class FakeDialog:
    def __init__(self):
        self.notifications = []
        self.ok_calls = []

    def notification(self, title, message, icon, duration):
        self.notifications.append((title, message, icon, duration))

    def ok(self, title, message):
        self.ok_calls.append((title, message))
        return True


class FakeDialogProgressBG:
    def __init__(self):
        self.created = []
        self.updated = []
        self.closed = 0

    def create(self, title, message):
        self.created.append((title, message))

    def update(self, progress, title, message):
        self.updated.append((progress, title, message))

    def close(self):
        self.closed += 1


class FakeListItem:
    def __init__(self, label="", path=""):
        self.label = label
        self.path = path
        self.art = {}
        self.info = {}
        self.properties = {}
        self.mime_type = None
        self.content_lookup = True

    def setArt(self, art):
        self.art = dict(art)

    def setMimeType(self, mime_type):
        self.mime_type = mime_type

    def setContentLookup(self, value):
        self.content_lookup = value

    def setInfo(self, media_type, info):
        self.info[media_type] = dict(info)

    def setProperty(self, key, value):
        self.properties[key] = value


class FakeMonitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout):
        return False


def purge_modules(*prefixes):
    for module_name in list(sys.modules):
        for prefix in prefixes:
            if module_name == prefix or module_name.startswith(prefix + "."):
                del sys.modules[module_name]
                break


def install_kodi_stubs(profile_dir, addon_settings=None, addon_info=None, localized_strings=None):
    addon = FakeAddon(profile_dir, settings=addon_settings, info=addon_info, localized_strings=localized_strings)

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGINFO = 1
    xbmc.LOGERROR = 4
    xbmc.logged = []
    xbmc.builtins = []
    xbmc.log = lambda message, level=xbmc.LOGINFO: xbmc.logged.append((message, level))
    xbmc.executebuiltin = lambda command: xbmc.builtins.append(command)
    xbmc.sleep = lambda milliseconds: None
    xbmc.Monitor = FakeMonitor

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = lambda addon_id=None: addon

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.NOTIFICATION_INFO = 0
    xbmcgui.NOTIFICATION_ERROR = 1
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgressBG = FakeDialogProgressBG
    xbmcgui.ListItem = FakeListItem

    xbmcplugin = types.ModuleType("xbmcplugin")
    xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE = 0
    xbmcplugin.calls = []
    xbmcplugin.setPluginCategory = lambda handle, category: xbmcplugin.calls.append(("setPluginCategory", handle, category))
    xbmcplugin.setContent = lambda handle, content: xbmcplugin.calls.append(("setContent", handle, content))
    xbmcplugin.addSortMethod = lambda handle, method: xbmcplugin.calls.append(("addSortMethod", handle, method))
    xbmcplugin.addDirectoryItem = (
        lambda handle, url, list_item, folder: xbmcplugin.calls.append(("addDirectoryItem", handle, url, list_item, folder))
    )
    xbmcplugin.endOfDirectory = lambda handle, cacheToDisc=False: xbmcplugin.calls.append(
        ("endOfDirectory", handle, cacheToDisc)
    )
    xbmcplugin.setResolvedUrl = lambda handle, succeeded, list_item: xbmcplugin.calls.append(
        ("setResolvedUrl", handle, succeeded, list_item)
    )

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda path: str(path)
    xbmcvfs.mkdirs = lambda path: os.makedirs(path, exist_ok=True)

    sys.modules["xbmc"] = xbmc
    sys.modules["xbmcaddon"] = xbmcaddon
    sys.modules["xbmcgui"] = xbmcgui
    sys.modules["xbmcplugin"] = xbmcplugin
    sys.modules["xbmcvfs"] = xbmcvfs

    return addon


def load_plugin_module(module_name, relative_path, addon_settings=None, addon_info=None, localized_strings=None, argv=None):
    plugin_root = str(PLUGIN_ROOT)
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)

    profile_dir = tempfile.mkdtemp(prefix="pentaract-kodi-tests-")
    addon = install_kodi_stubs(
        profile_dir,
        addon_settings=addon_settings,
        addon_info=addon_info,
        localized_strings=localized_strings,
    )

    purge_modules(module_name, "resources")

    module_path = PLUGIN_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    previous_argv = list(sys.argv)
    if argv is not None:
        sys.argv = list(argv)

    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.argv = previous_argv

    return module, addon, Path(profile_dir)
