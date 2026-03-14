import json
import time
import urllib.error
import urllib.parse
import urllib.request


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

    @property
    def base_url(self):
        return self._normalize_base_url(self.addon.getSettingString("base_url"))

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
        return self.addon.getSettingString("access_token").strip()

    @access_token.setter
    def access_token(self, value):
        self.addon.setSettingString("access_token", (value or "").strip())

    @property
    def token_expiry(self):
        raw_value = self.addon.getSettingString("token_expiry").strip()
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return 0

    @token_expiry.setter
    def token_expiry(self, value):
        self.addon.setSettingString("token_expiry", str(int(value or 0)))

    def clear_session(self):
        self.access_token = ""
        self.token_expiry = 0

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
