import io
import unittest

from tests.kodi_test_utils import load_plugin_module


class FakeResponse:
    def __init__(self, headers=None, status=200):
        self.headers = dict(headers or {})
        self.status = status
        self.closed = False

    def close(self):
        self.closed = True


class FakeHandler:
    def __init__(self, byte_range=None):
        self.headers = {}
        if byte_range is not None:
            self.headers["Range"] = byte_range
        self.status_code = None
        self.sent_headers = []
        self.error = None
        self.wfile = io.BytesIO()

    def send_response(self, status_code):
        self.status_code = status_code

    def send_header(self, name, value):
        self.sent_headers.append((name, value))

    def end_headers(self):
        return None

    def send_error(self, status_code, message):
        self.error = (status_code, message)
        self.status_code = status_code


class ServiceModuleTests(unittest.TestCase):
    def load_service_module(self):
        return load_plugin_module(
            "pentaract_service_test",
            "service.py",
        )

    def test_compute_buffer_plan_clamps_targets(self):
        module, _addon, _profile_dir = self.load_service_module()

        plan = module.compute_buffer_plan(
            content_length=128 * 1024 * 1024,
            prebuffer_bytes=256 * 1024 * 1024,
            chunk_size=512 * 1024,
        )

        self.assertEqual(514, plan["queue_size"])
        self.assertEqual(512 * 1024, plan["network_read_size"])
        self.assertEqual(module.STARTUP_BUFFER_MAX_BYTES, plan["target_bytes"])
        self.assertEqual(module.REBUFFER_TARGET_MAX_BYTES, plan["rebuffer_target_bytes"])

    def test_compute_buffer_plan_uses_content_length_for_small_ranges(self):
        module, _addon, _profile_dir = self.load_service_module()

        plan = module.compute_buffer_plan(
            content_length=2 * 1024 * 1024,
            prebuffer_bytes=16 * 1024 * 1024,
            chunk_size=256 * 1024,
        )

        self.assertEqual(66, plan["queue_size"])
        self.assertEqual(256 * 1024, plan["network_read_size"])
        self.assertEqual(2 * 1024 * 1024, plan["target_bytes"])
        self.assertEqual(2 * 1024 * 1024, plan["rebuffer_target_bytes"])

    def test_forward_response_headers_uses_session_mime_fallback(self):
        module, _addon, _profile_dir = self.load_service_module()
        runtime = module.ProxyRuntime()
        handler = FakeHandler()
        response = FakeResponse(headers={"Content-Length": "123"}, status=206)

        runtime.forward_response_headers(handler, response, {"mime_type": "video/x-matroska"})

        self.assertEqual(206, handler.status_code)
        self.assertIn(("Content-Length", "123"), handler.sent_headers)
        self.assertIn(("Content-Type", "video/x-matroska"), handler.sent_headers)

    def test_handle_stream_request_forwards_range_and_closes_response(self):
        module, _addon, _profile_dir = self.load_service_module()
        runtime = module.ProxyRuntime()
        handler = FakeHandler(byte_range="bytes=1048576-")
        remote_response = FakeResponse(
            headers={
                "Content-Length": "4096",
                "Content-Range": "bytes 1048576-1052671/9999999",
                "Content-Type": "video/mp4",
            },
            status=206,
        )
        client_calls = []

        class FakeClient:
            def open_stream(self, storage_id, path, byte_range=None, timeout=60):
                client_calls.append(
                    {
                        "storage_id": storage_id,
                        "path": path,
                        "byte_range": byte_range,
                        "timeout": timeout,
                    }
                )
                return remote_response

        module.CLIENT = FakeClient()
        stream_calls = []
        runtime.stream_with_prebuffer = lambda *args: stream_calls.append(args)

        runtime.handle_stream_request(
            handler,
            "session-1",
            {
                "storage_id": "storage-42",
                "path": "Movies/movie.mp4",
                "title": "Movie",
                "request_timeout_seconds": 45,
                "prebuffer_bytes": 8 * 1024 * 1024,
                "chunk_size_bytes": 131072,
                "mime_type": "video/mp4",
            },
            send_body=True,
        )

        self.assertEqual(
            [
                {
                    "storage_id": "storage-42",
                    "path": "Movies/movie.mp4",
                    "byte_range": "bytes=1048576-",
                    "timeout": 45,
                }
            ],
            client_calls,
        )
        self.assertEqual(1, len(stream_calls))
        self.assertEqual(206, handler.status_code)
        self.assertTrue(remote_response.closed)
        self.assertFalse(runtime.buffer_state.snapshot()["active"])


if __name__ == "__main__":
    unittest.main()
