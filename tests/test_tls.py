import http.server
import json
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from tests.kodi_test_utils import load_plugin_module


def make_self_signed_certificate(directory, name):
    cert = Path(directory) / ("%s.pem" % name)
    key = Path(directory) / ("%s.key" % name)
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-keyout", str(key), "-out", str(cert), "-subj", "/CN=pentaract",
            "-addext", "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    return cert, key, der


class RecordingHandler(http.server.BaseHTTPRequestHandler):
    """A tiny Pentaract backend: login, storages and a ranged download."""

    def do_POST(self):
        self.server.requests.append(("POST", self.path, self.headers.get("Authorization")))
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self._json({"access_token": "tok", "expires_in": 3600})

    def do_GET(self):
        self.server.requests.append(("GET", self.path, self.headers.get("Authorization")))
        if "/files/download/" in self.path:
            body = b"0123456789"
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json([{"id": "s1", "name": "Main"}])

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        pass


@unittest.skipUnless(shutil.which("openssl"), "openssl not installed")
class SelfSignedCertificateTests(unittest.TestCase):
    """The addon against a real HTTPS server with a self-signed certificate,
    like the nginx front of the Pentaract backend."""

    @classmethod
    def setUpClass(cls):
        cls.cert_dir = tempfile.mkdtemp(prefix="pentaract-kodi-tls-")
        cls.cert, cls.key, cls.der = make_self_signed_certificate(cls.cert_dir, "server")
        _cert, _key, cls.other_der = make_self_signed_certificate(cls.cert_dir, "other")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.cert_dir, ignore_errors=True)

    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        self.server.requests = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert), str(self.key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.module, self.addon, _profile = load_plugin_module(
            "pentaract_api_tls_test",
            "resources/lib/api.py",
            addon_settings={"username": "me@example.com", "password": "secret"},
        )
        self.client = self.module.PentaractClient(self.addon)
        self.client.base_url = "https://127.0.0.1:%d" % self.server.server_address[1]

    def fingerprint(self, der):
        return self.module.certificate_fingerprint(der)

    def test_unknown_self_signed_certificate_reports_its_fingerprint(self):
        with self.assertRaises(self.module.UntrustedCertificateError) as raised:
            self.client.list_storages()

        self.assertEqual(self.fingerprint(self.der), raised.exception.fingerprint)
        self.assertFalse(raised.exception.changed)
        self.assertEqual([], self.server.requests, "nothing may be sent to an untrusted server")

    def test_trusted_certificate_lets_requests_through(self):
        self.client.trust_certificate(self.fingerprint(self.der).lower())

        self.assertEqual([{"id": "s1", "name": "Main"}], self.client.list_storages())

        self.assertEqual(
            [("POST", "/api/auth/login", None), ("GET", "/api/storages", "Bearer tok")],
            self.server.requests,
        )

    def test_trusted_certificate_also_covers_the_proxy_stream(self):
        self.client.trust_certificate(self.fingerprint(self.der))

        response = self.client.open_stream("s1", "Videos/movie.mkv", byte_range="bytes=0-9")
        try:
            self.assertEqual(b"0123456789", response.read())
        finally:
            response.close()

    def test_changed_certificate_is_rejected_before_credentials_are_sent(self):
        self.client.trust_certificate(self.fingerprint(self.other_der))

        with self.assertRaises(self.module.UntrustedCertificateError) as raised:
            self.client.login()

        self.assertEqual(self.fingerprint(self.der), raised.exception.fingerprint)
        self.assertTrue(raised.exception.changed)
        self.assertEqual([], self.server.requests, "the password must not reach a server with another certificate")

    def test_direct_playback_url_skips_kodi_verification_only_for_a_trusted_certificate(self):
        self.client.access_token = "tok"
        self.client.token_expiry = 9999999999

        self.assertNotIn("verifypeer", self.client.build_stream_url("s1", "movie.mkv"))

        self.client.trust_certificate(self.fingerprint(self.der))
        self.assertTrue(self.client.build_stream_url("s1", "movie.mkv").endswith("&verifypeer=false"))

        # A plain http:// server never needs it, whatever was trusted before.
        self.client.base_url = "http://backend"
        self.assertNotIn("verifypeer", self.client.build_stream_url("s1", "movie.mkv"))


if __name__ == "__main__":
    unittest.main()
