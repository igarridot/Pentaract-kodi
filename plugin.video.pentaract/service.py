import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, Queue
from urllib.parse import urlparse

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.api import ConfigurationError, PentaractAPIError, PentaractClient
from resources.lib.proxy import (
    PROXY_HOST as LISTEN_HOST,
    PROXY_PORT as LISTEN_PORT,
    cleanup_proxy_sessions,
    load_proxy_session,
)


ADDON = xbmcaddon.Addon("plugin.video.pentaract")
CLIENT = PentaractClient(ADDON)
POLL_INTERVAL_SECONDS = 0.2
IDLE_EXIT_SECONDS = 15 * 60
STARTUP_BUFFER_MAX_BYTES = 64 * 1024 * 1024
REBUFFER_TARGET_MAX_BYTES = 16 * 1024 * 1024
PARTIAL_STARTUP_BUFFER_MAX_BYTES = 8 * 1024 * 1024
PARTIAL_REBUFFER_TARGET_MAX_BYTES = 4 * 1024 * 1024
NETWORK_READ_MAX_BYTES = 1024 * 1024
MIN_NETWORK_READ_BYTES = 256 * 1024


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[plugin.video.pentaract.service] %s" % message, level)


def compute_buffer_plan(content_length, prebuffer_bytes, chunk_size, partial_content=False):
    normalized_chunk_size = max(int(chunk_size or 0), 1)
    normalized_prebuffer_bytes = max(int(prebuffer_bytes or 0), 0)
    normalized_content_length = max(int(content_length or 0), 0)

    queue_size = max(
        4,
        int(max(normalized_prebuffer_bytes, normalized_chunk_size) / float(normalized_chunk_size)) + 2,
    )
    network_read_size = min(max(normalized_chunk_size, MIN_NETWORK_READ_BYTES), NETWORK_READ_MAX_BYTES)

    if partial_content:
        # Range responses are typically seek/resume operations, so we use a
        # smaller warm-up target to reduce resume latency while still keeping a
        # few megabytes buffered before playback continues.
        target_bytes = max(
            normalized_chunk_size * 8,
            min(
                max(normalized_prebuffer_bytes // 4, normalized_chunk_size * 4),
                PARTIAL_STARTUP_BUFFER_MAX_BYTES,
            ),
        )
        if normalized_content_length > 0:
            target_bytes = min(target_bytes, normalized_content_length)
    else:
        target_bytes = normalized_prebuffer_bytes
        if normalized_content_length > 0:
            target_bytes = min(normalized_prebuffer_bytes, normalized_content_length)
        target_bytes = max(target_bytes, normalized_chunk_size * 4)
        target_bytes = min(target_bytes, STARTUP_BUFFER_MAX_BYTES)
    if target_bytes <= 0:
        target_bytes = normalized_chunk_size

    if partial_content:
        rebuffer_target_bytes = min(
            target_bytes,
            max(
                normalized_chunk_size * 4,
                min(
                    max(target_bytes // 2, normalized_chunk_size * 4),
                    PARTIAL_REBUFFER_TARGET_MAX_BYTES,
                ),
            ),
        )
    else:
        rebuffer_target_bytes = min(
            target_bytes,
            max(
                normalized_chunk_size * 4,
                min(max(normalized_prebuffer_bytes // 2, normalized_chunk_size * 4), REBUFFER_TARGET_MAX_BYTES),
            ),
        )
    if rebuffer_target_bytes <= 0:
        rebuffer_target_bytes = normalized_chunk_size * 2

    return {
        "queue_size": queue_size,
        "network_read_size": network_read_size,
        "target_bytes": target_bytes,
        "rebuffer_target_bytes": rebuffer_target_bytes,
    }


def is_partial_stream_response(remote_response):
    status_code = getattr(remote_response, "status", None) or getattr(remote_response, "code", 200)
    return status_code == 206 or bool(remote_response.headers.get("Content-Range"))


class BufferState:
    def __init__(self):
        self._lock = threading.Lock()
        self._request_id = ""
        self._title = "Pentaract"
        self._message = ""
        self._progress = 0
        self._active = False
        self._last_activity = time.time()

    def set_buffering(self, request_id, title, progress, message):
        with self._lock:
            self._request_id = request_id
            self._title = title or "Pentaract"
            self._progress = max(0, min(100, int(round(progress))))
            self._message = message
            self._active = True
            self._last_activity = time.time()

    def clear(self, request_id=None):
        with self._lock:
            if request_id is not None and request_id != self._request_id:
                return
            self._active = False
            self._message = ""
            self._progress = 0
            self._last_activity = time.time()

    def touch(self):
        with self._lock:
            self._last_activity = time.time()

    def snapshot(self):
        with self._lock:
            return {
                "request_id": self._request_id,
                "title": self._title,
                "message": self._message,
                "progress": self._progress,
                "active": self._active,
                "last_activity": self._last_activity,
            }


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, runtime):
        super().__init__(server_address, ProxyRequestHandler)
        self.runtime = runtime


class ProxyRequestHandler(BaseHTTPRequestHandler):
    server_version = "PentaractLocalProxy/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.server.runtime.handle_http_request(self, send_body=True)

    def do_HEAD(self):
        self.server.runtime.handle_http_request(self, send_body=False)

    def log_message(self, format_string, *args):
        return


class ProxyRuntime:
    def __init__(self):
        self.monitor = xbmc.Monitor()
        self.buffer_state = BufferState()
        self._dialog = xbmcgui.DialogProgressBG()
        self._dialog_visible = False
        self._server = None

    def start(self):
        cleanup_proxy_sessions()

        try:
            self._server = ProxyServer((LISTEN_HOST, LISTEN_PORT), self)
        except OSError as error:
            log("Local proxy already running or unavailable: %s" % error, xbmc.LOGINFO)
            return

        threading.Thread(target=self._server.serve_forever, name="pentaract-proxy", daemon=True).start()
        log("Local proxy listening on %s:%d" % (LISTEN_HOST, LISTEN_PORT))

        while not self.monitor.abortRequested():
            self.update_overlay()
            cleanup_proxy_sessions()
            if self.is_idle():
                log("Local proxy idle timeout reached; shutting down.")
                break
            if self.monitor.waitForAbort(POLL_INTERVAL_SECONDS):
                break

        self.shutdown()

    def shutdown(self):
        self.close_overlay()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def is_idle(self):
        snapshot = self.buffer_state.snapshot()
        return not snapshot["active"] and time.time() - snapshot["last_activity"] >= IDLE_EXIT_SECONDS

    def update_overlay(self):
        snapshot = self.buffer_state.snapshot()
        if not ADDON.getSettingBool("show_buffer_overlay"):
            self.close_overlay()
            return

        if not snapshot["active"]:
            self.close_overlay()
            return

        title = snapshot["title"] or "Pentaract"
        message = snapshot["message"] or "Buffering %d%%" % snapshot["progress"]
        if not self._dialog_visible:
            self._dialog.create(title, message)
            self._dialog_visible = True

        self._dialog.update(snapshot["progress"], title, message)

    def close_overlay(self):
        if not self._dialog_visible:
            return
        self._dialog.close()
        self._dialog_visible = False

    def load_session(self, session_id):
        return load_proxy_session(session_id)

    def handle_http_request(self, handler, send_body):
        parsed = urlparse(handler.path)
        if parsed.path == "/health":
            payload = json.dumps({"status": "ok"}).encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            if send_body:
                handler.wfile.write(payload)
            self.buffer_state.touch()
            return

        if parsed.path == "/status":
            payload = json.dumps(self.buffer_state.snapshot()).encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            if send_body:
                handler.wfile.write(payload)
            self.buffer_state.touch()
            return

        if not parsed.path.startswith("/stream/"):
            handler.send_error(404, "Unknown path")
            return

        session_id = parsed.path.split("/")[-1].strip()
        session = self.load_session(session_id)
        if not session:
            handler.send_error(404, "Unknown streaming session")
            return

        self.buffer_state.touch()
        self.handle_stream_request(handler, session_id, session, send_body)

    def handle_stream_request(self, handler, session_id, session, send_body):
        request_id = "%s-%d" % (session_id, int(time.time() * 1000))
        title = session.get("title") or "Pentaract"
        byte_range = handler.headers.get("Range")
        timeout = self._safe_int(session.get("request_timeout_seconds"), 60)
        prebuffer_bytes = self._safe_int(session.get("prebuffer_bytes"), 16 * 1024 * 1024)
        chunk_size = self._safe_int(session.get("chunk_size_bytes"), 262144)
        self.buffer_state.set_buffering(request_id, title, 0, "Preparando stream...")

        try:
            log(
                "Opening proxied stream for %s (range=%s, prebuffer=%s, chunk=%s)"
                % (
                    session.get("path", ""),
                    byte_range or "full",
                    prebuffer_bytes,
                    chunk_size,
                )
            )
            remote_response = CLIENT.open_stream(
                session["storage_id"],
                session["path"],
                byte_range=byte_range,
                timeout=timeout,
                download_id=session_id,
            )
        except ConfigurationError as error:
            handler.send_error(503, str(error))
            return
        except PentaractAPIError as error:
            handler.send_error(error.status or 502, error.message or "Streaming backend error")
            return

        try:
            self.forward_response_headers(handler, remote_response, session)
            if not send_body:
                return
            self.stream_with_prebuffer(
                handler,
                remote_response,
                request_id,
                title,
                prebuffer_bytes,
                chunk_size,
                min(timeout, 20),
            )
        finally:
            try:
                remote_response.close()
            except OSError:
                pass
            self.buffer_state.clear(request_id)

    def forward_response_headers(self, handler, remote_response, session):
        status_code = getattr(remote_response, "status", None) or getattr(remote_response, "code", 200)
        headers = remote_response.headers

        handler.send_response(status_code)
        for header_name in (
            "Accept-Ranges",
            "Content-Length",
            "Content-Range",
            "Content-Type",
            "ETag",
            "Last-Modified",
        ):
            header_value = headers.get(header_name)
            if header_value:
                handler.send_header(header_name, header_value)

        if not headers.get("Content-Type") and session.get("mime_type"):
            handler.send_header("Content-Type", session["mime_type"])

        handler.end_headers()

    def stream_with_prebuffer(
        self,
        handler,
        remote_response,
        request_id,
        title,
        prebuffer_bytes,
        chunk_size,
        max_initial_wait_seconds,
    ):
        partial_content = is_partial_stream_response(remote_response)
        buffer_plan = compute_buffer_plan(
            remote_response.headers.get("Content-Length"),
            prebuffer_bytes,
            chunk_size,
            partial_content=partial_content,
        )
        queue = Queue(maxsize=buffer_plan["queue_size"])
        network_read_size = buffer_plan["network_read_size"]
        queued_bytes = [0]
        producer_done = [False]
        producer_error = [None]
        stats_lock = threading.Lock()
        stop_event = threading.Event()

        def queue_size():
            with stats_lock:
                return queued_bytes[0]

        def update_queued(delta):
            with stats_lock:
                queued_bytes[0] += delta
                return queued_bytes[0]

        def mark_done(error=None):
            with stats_lock:
                producer_done[0] = True
                producer_error[0] = error

        def is_done():
            with stats_lock:
                return producer_done[0], producer_error[0]

        def producer():
            try:
                while not stop_event.is_set():
                    chunk = remote_response.read(network_read_size)
                    if not chunk:
                        break

                    while not stop_event.is_set():
                        try:
                            queue.put(chunk, timeout=0.2)
                            update_queued(len(chunk))
                            break
                        except Full:
                            continue
            except Exception as error:
                mark_done(error)
            else:
                mark_done(None)
            finally:
                while not stop_event.is_set():
                    try:
                        queue.put(None, timeout=0.2)
                        break
                    except Full:
                        continue

        producer_thread = threading.Thread(target=producer, name="pentaract-stream-producer", daemon=True)
        producer_thread.start()

        target_bytes = buffer_plan["target_bytes"]
        rebuffer_target_bytes = buffer_plan["rebuffer_target_bytes"]

        log(
            "Initial buffer target=%s bytes, rebuffer target=%s bytes, network_read=%s bytes, partial=%s"
            % (target_bytes, rebuffer_target_bytes, network_read_size, partial_content)
        )

        def wait_for_buffer(target_buffer_bytes, max_wait_seconds, label):
            wait_started_at = time.time()
            while queue_size() < target_buffer_bytes:
                done, error = is_done()
                buffered = queue_size()
                progress = 100.0 * float(buffered) / float(target_buffer_bytes or 1)
                self.buffer_state.set_buffering(
                    request_id,
                    title,
                    progress,
                    "%s %d%%" % (label, int(round(progress))),
                )
                if buffered > 0 and done:
                    break
                if error is not None and buffered == 0:
                    raise error
                if time.time() - wait_started_at >= max_wait_seconds:
                    break
                if time.time() - wait_started_at > 1 and done and buffered == 0:
                    break
                time.sleep(0.05)

        wait_for_buffer(target_bytes, max_initial_wait_seconds, "Buffering")

        self.buffer_state.clear(request_id)

        try:
            while not stop_event.is_set():
                try:
                    item = queue.get(timeout=0.5)
                except Empty:
                    done, error = is_done()
                    if done:
                        if error is not None:
                            raise error
                        break
                    wait_for_buffer(rebuffer_target_bytes, min(max_initial_wait_seconds, 12), "Rebuffering")
                    self.buffer_state.clear(request_id)
                    continue

                if item is None:
                    break

                self.buffer_state.clear(request_id)
                update_queued(-len(item))
                handler.wfile.write(item)
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, socket.error):
            stop_event.set()
        finally:
            stop_event.set()
            producer_thread.join(timeout=1.0)

    def _safe_int(self, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def run():
    runtime = ProxyRuntime()
    runtime.start()


if __name__ == "__main__":
    run()
