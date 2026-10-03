"""Read-only acceptance probe for the optional AmazingHand live web server.

The probe deliberately makes only GET requests.  It checks the versioned
telemetry document and reads just enough of the MJPEG stream to establish that
the first JPEG frame is being served, then closes the connection.
"""

from __future__ import print_function

import argparse
import json
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


TELEMETRY_SCHEMA = "amazinghand.maixcam2.telemetry"
TELEMETRY_SCHEMA_VERSION = 1
MAX_TELEMETRY_BYTES = 64 * 1024
MAX_STREAM_BYTES = 512 * 1024

_REQUIRED_OBJECTS = (
    ("frame",), ("ai",), ("hand",), ("training",), ("training", "quality"),
    ("titan",), ("titan", "gate"), ("health",),
    ("health", "stale"), ("health", "faults"),
)


class ProbeError(Exception):
    """A failed read-only acceptance condition."""


class _NoRedirect(HTTPRedirectHandler):
    """Treat redirects as failures instead of following an unknown endpoint."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def normalize_base_url(value):
    """Return a safe base URL with no query, fragment, or trailing slash."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("base URL is required")
    try:
        parts = urlsplit(value.strip())
        username = parts.username
        password = parts.password
        port = parts.port  # Validate malformed port text while parsing.
    except ValueError as exc:
        raise ValueError("invalid base URL: {}".format(exc))
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("base URL scheme must be http or https")
    if not parts.hostname:
        raise ValueError("base URL must include a host")
    if username is not None or password is not None:
        raise ValueError("base URL must not include username or password")
    # Accessing port above only validates it; it remains in netloc for IPv6.
    del port
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def endpoint_url(base_url, endpoint):
    """Append one fixed read-only endpoint to a normalized base URL."""
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/") + "/" + endpoint.lstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _read_limited(response, maximum, label):
    length = response.headers.get("Content-Length")
    if length:
        try:
            if int(length) > maximum:
                raise ProbeError("{} response exceeds {} bytes".format(label, maximum))
        except ValueError:
            pass
    data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ProbeError("{} response exceeds {} bytes".format(label, maximum))
    return data


def _require_status(response, endpoint):
    status = getattr(response, "status", response.getcode())
    if status != 200:
        raise ProbeError("GET {} returned HTTP {} (expected 200)".format(endpoint, status))


def _open_get(opener, url, timeout):
    # Setting the method explicitly makes the GET-only contract auditable.
    return opener.open(Request(url, method="GET"), timeout=timeout)


def _get_object(document, path):
    current = document
    for key in path:
        if not isinstance(current, dict) or not isinstance(current.get(key), dict):
            raise ProbeError("telemetry object {} is missing or not an object".format(".".join(path)))
        current = current[key]
    return current


def validate_telemetry(document):
    """Validate the wire-level facts required by the desktop acceptance tool."""
    if not isinstance(document, dict):
        raise ProbeError("telemetry JSON root must be an object")
    if document.get("schema") != TELEMETRY_SCHEMA:
        raise ProbeError("telemetry schema is not {}".format(TELEMETRY_SCHEMA))
    if document.get("schema_version") != TELEMETRY_SCHEMA_VERSION:
        raise ProbeError("telemetry schema_version is not 1")
    for path in _REQUIRED_OBJECTS:
        _get_object(document, path)
    return document


def _display(value):
    if value is None:
        return "未上报"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def print_telemetry_summary(document, output):
    """Print the AI, Titan, and health facts useful during a live demo."""
    ai = document["ai"]
    titan = document["titan"]
    health = document["health"]
    fields = (
        ("AI", "model", ai.get("model")),
        ("AI", "mode", ai.get("mode")),
        ("AI", "target", ai.get("target")),
        ("AI", "confidence_pct", ai.get("confidence_pct")),
        ("AI", "detections", ai.get("detections")),
        ("AI", "inference_ms", ai.get("inference_ms")),
        ("AI", "inference_fps", ai.get("inference_fps")),
        ("Titan", "link", titan.get("link")),
        ("Titan", "rtt_ms", titan.get("rtt_ms")),
        ("Titan", "action", titan.get("action")),
        ("Titan", "reason", titan.get("reason")),
        ("Titan", "gate", titan.get("gate")),
        ("health", "stale", health.get("stale")),
        ("health", "faults", health.get("faults")),
    )
    for group, key, value in fields:
        output("{} {}={}".format(group, key, _display(value)))


def _boundary_from_content_type(content_type):
    for item in content_type.split(";")[1:]:
        key, separator, value = item.strip().partition("=")
        if key.lower() == "boundary" and separator:
            value = value.strip().strip('"')
            if value:
                return value.encode("ascii")
    raise ProbeError("stream Content-Type has no multipart boundary")


def _has_first_jpeg(data, boundary):
    marker = b"--" + boundary
    boundary_at = data.find(marker)
    if boundary_at < 0:
        return False
    jpeg_header_at = data.lower().find(b"content-type: image/jpeg", boundary_at + len(marker))
    if jpeg_header_at < 0:
        return False
    return data.find(b"\xff\xd8", jpeg_header_at + len(b"content-type: image/jpeg")) >= 0


def _report_cors(response, endpoint, output):
    cors = response.headers.get("Access-Control-Allow-Origin")
    if cors is None:
        output("WARN CORS {}: Access-Control-Allow-Origin missing; test file:// fetch in a browser".format(endpoint))
    else:
        output("CORS {} Access-Control-Allow-Origin={}".format(endpoint, cors))


def check_telemetry(opener, base_url, timeout, output):
    response = None
    try:
        response = _open_get(opener, endpoint_url(base_url, "telemetry"), timeout)
        _require_status(response, "/telemetry")
        _report_cors(response, "/telemetry", output)
        try:
            document = json.loads(_read_limited(response, MAX_TELEMETRY_BYTES, "telemetry").decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProbeError("telemetry response is not valid UTF-8 JSON: {}".format(exc))
        validate_telemetry(document)
        print_telemetry_summary(document, output)
        output("PASS /telemetry")
    finally:
        if response is not None:
            response.close()


def check_stream(opener, base_url, timeout, output):
    response = None
    try:
        response = _open_get(opener, endpoint_url(base_url, "stream"), timeout)
        _require_status(response, "/stream")
        content_type = response.headers.get("Content-Type", "")
        if "multipart/x-mixed-replace" not in content_type.lower():
            raise ProbeError("stream Content-Type must include multipart/x-mixed-replace (got {!r})".format(content_type))
        _report_cors(response, "/stream", output)
        boundary = _boundary_from_content_type(content_type)
        deadline = time.monotonic() + timeout
        data = bytearray()
        while len(data) < MAX_STREAM_BYTES:
            if time.monotonic() >= deadline:
                raise ProbeError("stream timed out before first JPEG frame")
            chunk = response.read(min(4096, MAX_STREAM_BYTES - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if _has_first_jpeg(data, boundary):
                output("PASS /stream first JPEG frame observed ({} bytes read)".format(len(data)))
                return
        if len(data) >= MAX_STREAM_BYTES:
            raise ProbeError("stream exceeded {} bytes before first JPEG frame".format(MAX_STREAM_BYTES))
        raise ProbeError("stream ended or was truncated before first JPEG frame")
    except socket.timeout:
        raise ProbeError("stream timed out before first JPEG frame")
    finally:
        if response is not None:
            response.close()


def run_probe(base_url, timeout=5.0, output=print):
    """Run both bounded GET checks and return ``True`` only on full success."""
    try:
        normalized = normalize_base_url(base_url)
        timeout = float(timeout)
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        output("Read-only probe: {} (timeout={}s)".format(normalized, timeout))
        opener = build_opener(_NoRedirect())
        check_telemetry(opener, normalized, timeout, output)
        check_stream(opener, normalized, timeout, output)
    except (ProbeError, HTTPError, URLError, OSError, ValueError) as exc:
        output("FAIL {}".format(exc))
        return False
    output("PASS AmazingHand live web acceptance")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only AmazingHand live web acceptance probe")
    parser.add_argument("--base-url", required=True, help="for example http://192.168.1.20:8080")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-request timeout in seconds (default: 5)")
    args = parser.parse_args(argv)
    return 0 if run_probe(args.base_url, args.timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
