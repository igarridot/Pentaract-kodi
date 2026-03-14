import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import xbmcvfs


class ConfigurationError(Exception):
    pass


class PentaractAPIError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.message = message
        self.status = status


class PentaractClient:
    def __init__(self, addon):
        self.addon = addon
        self._profile_dir = xbmcvfs.translatePath(self.addon.getAddonInfo("profile"))
        self._session_path = os.path.join(self._profile_dir, "session.json")
        self._settings_path = os.path.join(self._profile_dir, "settings.xml")

    @property
    def base_url(self):
        base_url = self._normalize_base_url(self.addon.getSettingString("base_url"))
        if self._is_legacy_default_base_url(base_url):
            self.addon.setSettingString("base_url", "")
            return ""
        return base_url

    @base_url.setter
    def base_url(self, value):
        self.addon.setSettingString("base_url", self._normalize_base_url(value))

    @property
    def username(self):
        return self.addon.getSettingString("username").strip()

    @username.setter
    def username(self, value):
        self.addon.setSettingString("username", (value or "").strip())

    @property
    def password(self):
        return self.addon.getSettingString("password")

    @password.setter
    def password(self, value):
        self.addon.setSettingString("password", value or "")

    @property
    def access_token(self):
        return self._load_session().get("access_token", "").strip()

    @access_token.setter
    def access_token(self, value):
        session = self._load_session()
        session["access_token"] = (value or "").strip()
        self._save_session(session)

    @property
    def token_expiry(self):
        raw_value = self._load_session().get("token_expiry", 0)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return 0

    @token_expiry.setter
    def token_expiry(self, value):
        session = self._load_session()
        session["token_expiry"] = int(value or 0)
        self._save_session(session)

    def clear_session(self):
        self._save_session({})

    def clear_credentials(self):
        self.clear_session()
        self.username = ""
        self.password = ""

    def ensure_token(self):
        if self._has_valid_token():
            return self.access_token
        return self.login()

    def login(self):
        if not self.base_url:
            raise ConfigurationError("Falta la URL base de Pentaract.")
        if not self.username or not self.password:
            raise ConfigurationError("Faltan las credenciales de acceso.")

        payload = {"email": self.username, "password": self.password}
        response = self._request(
            "POST",
            "/api/auth/login",
            payload=payload,
            include_auth=False,
            retry_auth=False,
        )
        token = response.get("access_token", "")
        expires_in = int(response.get("expires_in", 0))
        if not token:
            raise PentaractAPIError("La respuesta de login no incluye access_token.")
        self.access_token = token
        self.token_expiry = int(time.time()) + expires_in
        return token

    def list_storages(self):
        return self._request("GET", "/api/storages")

    def list_directory(self, storage_id, path):
        encoded_path = self._encode_path(path)
        return self._request(
            "GET",
            "/api/storages/%s/files/tree/%s" % (storage_id, encoded_path),
        )

    def build_stream_url(self, storage_id, path):
        token = self.ensure_token()
        query = urllib.parse.urlencode(
            {
                "inline": "1",
                "access_token": token,
            }
        )
        return "%s/api/storages/%s/files/download/%s?%s" % (
            self.base_url,
            storage_id,
            self._encode_path(path),
            query,
        )

    def open_stream(self, storage_id, path, byte_range=None, inline=True, timeout=60):
        if not self.base_url:
            raise ConfigurationError("Falta la URL base de Pentaract.")

        query = {}
        if inline:
            query["inline"] = "1"

        request_path = "/api/storages/%s/files/download/%s" % (
            storage_id,
            self._encode_path(path),
        )
        if query:
            request_path = "%s?%s" % (request_path, urllib.parse.urlencode(query))

        return self._open_binary_request(
            request_path,
            byte_range=byte_range,
            timeout=timeout,
        )

    def _request(self, method, path, payload=None, include_auth=True, retry_auth=True):
        if not self.base_url:
            raise ConfigurationError("Falta la URL base de Pentaract.")

        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            body = None

        if include_auth:
            headers["Authorization"] = "Bearer %s" % self.ensure_token()

        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw_data = response.read()
        except urllib.error.HTTPError as error:
            message = self._extract_error_message(error)
            if error.code == 401 and retry_auth and include_auth:
                self.clear_session()
                headers["Authorization"] = "Bearer %s" % self.login()
                request = urllib.request.Request(
                    self.base_url + path,
                    data=body,
                    headers=headers,
                    method=method,
                )
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        raw_data = response.read()
                except urllib.error.HTTPError as retry_error:
                    raise PentaractAPIError(
                        self._extract_error_message(retry_error),
                        retry_error.code,
                    )
                except urllib.error.URLError as retry_error:
                    raise PentaractAPIError(str(retry_error.reason))
            else:
                raise PentaractAPIError(message, error.code)
        except urllib.error.URLError as error:
            raise PentaractAPIError(str(error.reason))

        if not raw_data:
            return {}
        return json.loads(raw_data.decode("utf-8"))

    def _open_binary_request(self, path, byte_range=None, timeout=60, retry_auth=True):
        headers = {}
        if byte_range:
            headers["Range"] = byte_range

        response = self._perform_binary_open(
            path,
            headers=headers,
            timeout=timeout,
            include_auth=True,
        )
        response_status = getattr(response, "status", None)
        if response_status is None:
            response_status = getattr(response, "code", 200)

        if response_status != 401:
            return response

        response.close()
        if not retry_auth:
            raise PentaractAPIError("Credenciales no validas para reproducir el stream.", 401)

        self.clear_session()
        self.login()
        return self._perform_binary_open(
            path,
            headers=headers,
            timeout=timeout,
            include_auth=True,
        )

    def _perform_binary_open(self, path, headers=None, timeout=60, include_auth=True):
        request_headers = dict(headers or {})
        if include_auth:
            request_headers["Authorization"] = "Bearer %s" % self.ensure_token()

        request = urllib.request.Request(
            self.base_url + path,
            headers=request_headers,
            method="GET",
        )

        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                return error
            raise PentaractAPIError(self._extract_error_message(error), error.code)
        except urllib.error.URLError as error:
            raise PentaractAPIError(str(error.reason))

    def _has_valid_token(self):
        return bool(self.access_token) and self.token_expiry > int(time.time()) + 60

    def _normalize_base_url(self, value):
        normalized = (value or "").strip().rstrip("/")
        if normalized and "://" not in normalized:
            normalized = "http://" + normalized
        return normalized

    def _encode_path(self, path):
        return urllib.parse.quote((path or "").strip("/"), safe="/")

    def _extract_error_message(self, error):
        try:
            payload = json.loads(error.read().decode("utf-8"))
            if payload.get("message"):
                return payload["message"]
        except (TypeError, ValueError):
            pass
        return getattr(error, "reason", "") or "Error HTTP %s" % error.code

    def _load_session(self):
        try:
            with open(self._session_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {}
        return {}

    def _save_session(self, session):
        xbmcvfs.mkdirs(self._profile_dir)
        with open(self._session_path, "w", encoding="utf-8") as handle:
            json.dump(session or {}, handle)

    def _is_legacy_default_base_url(self, value):
        if value != "http://localhost:8000":
            return False

        try:
            tree = ET.parse(self._settings_path)
        except (ET.ParseError, FileNotFoundError, OSError):
            return False

        root = tree.getroot()
        for setting in root.findall("setting"):
            if setting.attrib.get("id") == "base_url" and setting.attrib.get("default") == "true":
                return True
        return False
