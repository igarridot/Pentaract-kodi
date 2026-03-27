import unittest

from tests.kodi_test_utils import load_plugin_module


class FakeJSONResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"{}"


class FakeBinaryResponse:
    def __init__(self, status=200):
        self.status = status


class APIModuleTests(unittest.TestCase):
    def load_api_module(self, addon_info=None):
        return load_plugin_module(
            "pentaract_api_test",
            "resources/lib/api.py",
            addon_info=addon_info,
        )

    def test_build_stream_url_appends_kodi_user_agent_header(self):
        module, addon, _profile_dir = self.load_api_module(addon_info={"version": "1.2.3"})
        client = module.PentaractClient(addon)
        client.base_url = "http://backend"
        client.access_token = "tok"
        client.token_expiry = 9999999999

        stream_url = client.build_stream_url("storage-1", "Videos/movie.mkv", download_id="stream-1")

        self.assertEqual(
            "http://backend/api/storages/storage-1/files/download/Videos/movie.mkv"
            "?inline=1&access_token=tok&download_id=stream-1"
            "|User-Agent=Pentaract-Kodi%2F1.2.3",
            stream_url,
        )

    def test_request_sends_user_agent_header(self):
        module, addon, _profile_dir = self.load_api_module(addon_info={"version": "1.2.3"})
        client = module.PentaractClient(addon)
        client.base_url = "http://backend"
        captured = {}

        def fake_urlopen(request, timeout=30):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeJSONResponse()

        module.urllib.request.urlopen = fake_urlopen

        client._request("GET", "/api/storages", include_auth=False, retry_auth=False)

        self.assertEqual("http://backend/api/storages", captured["url"])
        self.assertEqual("Pentaract-Kodi/1.2.3", captured["headers"]["User-agent"])
        self.assertEqual(30, captured["timeout"])

    def test_binary_open_sends_user_agent_and_authorization_headers(self):
        module, addon, _profile_dir = self.load_api_module(addon_info={"version": "1.2.3"})
        client = module.PentaractClient(addon)
        client.base_url = "http://backend"
        client.ensure_token = lambda: "tok"
        captured = {}

        def fake_urlopen(request, timeout=60):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeBinaryResponse()

        module.urllib.request.urlopen = fake_urlopen

        response = client._perform_binary_open(
            "/api/storages/storage-1/files/download/Videos/movie.mkv?inline=1",
            headers={"Range": "bytes=0-9"},
            timeout=45,
        )

        self.assertIsInstance(response, FakeBinaryResponse)
        self.assertEqual(
            "http://backend/api/storages/storage-1/files/download/Videos/movie.mkv?inline=1",
            captured["url"],
        )
        self.assertEqual("Pentaract-Kodi/1.2.3", captured["headers"]["User-agent"])
        self.assertEqual("Bearer tok", captured["headers"]["Authorization"])
        self.assertEqual("bytes=0-9", captured["headers"]["Range"])
        self.assertEqual(45, captured["timeout"])


if __name__ == "__main__":
    unittest.main()
