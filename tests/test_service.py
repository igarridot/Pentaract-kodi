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

    def test_compute_buffer_plan_uses_smaller_targets_for_partial_content(self):
        module, _addon, _profile_dir = self.load_service_module()

        plan = module.compute_buffer_plan(
            content_length=128 * 1024 * 1024,
            prebuffer_bytes=16 * 1024 * 1024,
            chunk_size=256 * 1024,
            partial_content=True,
        )

        self.assertEqual(66, plan["queue_size"])
        self.assertEqual(256 * 1024, plan["network_read_size"])
        self.assertEqual(4 * 1024 * 1024, plan["target_bytes"])
        self.assertEqual(2 * 1024 * 1024, plan["rebuffer_target_bytes"])

    def test_is_partial_stream_response_detects_partial_status_or_headers(self):
        module, _addon, _profile_dir = self.load_service_module()

        self.assertTrue(module.is_partial_stream_response(FakeResponse(status=206)))
        self.assertTrue(module.is_partial_stream_response(FakeResponse(headers={"Content-Range": "bytes 0-9/100"})))
        self.assertFalse(module.is_partial_stream_response(FakeResponse(status=200)))

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
            def open_stream(self, storage_id, path, byte_range=None, timeout=60, download_id=None):
                client_calls.append(
                    {
                        "storage_id": storage_id,
                        "path": path,
                        "byte_range": byte_range,
                        "timeout": timeout,
                        "download_id": download_id,
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
                    "download_id": "session-1",
                }
            ],
            client_calls,
        )
        self.assertEqual(1, len(stream_calls))
        self.assertEqual(206, handler.status_code)
        self.assertTrue(remote_response.closed)
        self.assertFalse(runtime.buffer_state.snapshot()["active"])

    def test_forward_response_headers_closes_connection_after_each_response(self):
        module, _addon, _profile_dir = self.load_service_module()
        runtime = module.ProxyRuntime()
        handler = FakeHandler()
        response = FakeResponse(headers={"Content-Length": "123", "Content-Type": "video/mp4"}, status=206)

        runtime.forward_response_headers(handler, response, {})

        self.assertIn(("Connection", "close"), handler.sent_headers)
        self.assertTrue(handler.close_connection)

    def test_stream_with_prebuffer_reports_backend_ending_the_stream_short(self):
        module, _addon, _profile_dir = self.load_service_module()
        runtime = module.ProxyRuntime()
        handler = FakeHandler()
        payload = b"x" * 1000

        class ShortResponse(FakeResponse):
            def __init__(self):
                super().__init__(headers={"Content-Length": "4096"}, status=206)
                self._buffer = io.BytesIO(payload)

            def read(self, size=-1):
                return self._buffer.read(size)

        forwarded = runtime.stream_with_prebuffer(
            handler,
            ShortResponse(),
            "request-1",
            "Movie",
            prebuffer_bytes=8 * 1024 * 1024,
            chunk_size=256 * 1024,
            max_initial_wait_seconds=1,
        )

        self.assertEqual(len(payload), forwarded)
        self.assertEqual(payload, handler.wfile.getvalue())
        errors = [message for message, level in module.xbmc.logged if level == module.xbmc.LOGERROR]
        self.assertEqual(1, len(errors))
        self.assertIn("1000 of 4096 bytes", errors[0])

    def test_stream_with_prebuffer_stays_quiet_when_the_body_is_complete(self):
        module, _addon, _profile_dir = self.load_service_module()
        runtime = module.ProxyRuntime()
        handler = FakeHandler()
        payload = b"y" * 4096

        class CompleteResponse(FakeResponse):
            def __init__(self):
                super().__init__(headers={"Content-Length": str(len(payload))}, status=206)
                self._buffer = io.BytesIO(payload)

            def read(self, size=-1):
                return self._buffer.read(size)

        forwarded = runtime.stream_with_prebuffer(
            handler,
            CompleteResponse(),
            "request-2",
            "Movie",
            prebuffer_bytes=8 * 1024 * 1024,
            chunk_size=256 * 1024,
            max_initial_wait_seconds=1,
        )

        self.assertEqual(len(payload), forwarded)
        self.assertEqual(payload, handler.wfile.getvalue())
        errors = [message for message, level in module.xbmc.logged if level == module.xbmc.LOGERROR]
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
