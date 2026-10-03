import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from probe_live_web import MAX_TELEMETRY_BYTES, normalize_base_url, run_probe  # noqa: E402


def telemetry_document():
    return {
        "schema": "amazinghand.maixcam2.telemetry", "schema_version": 1,
        "timestamp_ms": 1,
        "frame": {}, "ai": {"model": None}, "hand": {},
        "training": {"quality": {}},
        "titan": {"link": "online", "gate": {}},
        "health": {"stale": {}, "faults": {}},
    }


class ProbeHandler(BaseHTTPRequestHandler):
    scenario = "pass"
    methods = []

    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        type(self).methods.append(self.command)
        if self.path == "/telemetry":
            document = telemetry_document()
            if type(self).scenario == "bad_schema":
                document["schema"] = "wrong"
            payload = json.dumps(document).encode("utf-8")
            if type(self).scenario == "too_large":
                payload = b"x" * (MAX_TELEMETRY_BYTES + 1)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/stream":
            self.send_response(200)
            content_type = "multipart/x-mixed-replace; boundary=frame"
            if type(self).scenario == "bad_stream_type":
                content_type = "image/jpeg"
            self.send_header("Content-Type", content_type)
            self.end_headers()
            if type(self).scenario == "no_frame":
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
            elif type(self).scenario == "stream_timeout":
                self.wfile.flush()
                time.sleep(0.3)
            else:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8\xff\xd9")
            return
        self.send_error(404)


class ProbeLiveWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = "http://127.0.0.1:{}".format(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        ProbeHandler.scenario = "pass"
        ProbeHandler.methods = []

    def probe(self, timeout=0.1):
        output = []
        result = run_probe(self.base_url + "/?discard=this#and-this", timeout, output.append)
        return result, output

    def test_full_pass_only_uses_get(self):
        result, output = self.probe()
        self.assertTrue(result, output)
        self.assertEqual(ProbeHandler.methods, ["GET", "GET"])
        self.assertTrue(any("未上报" in line for line in output))

    def test_schema_error_fails(self):
        ProbeHandler.scenario = "bad_schema"
        result, output = self.probe()
        self.assertFalse(result)
        self.assertIn("FAIL", output[-1])
        self.assertEqual(ProbeHandler.methods, ["GET"])

    def test_oversized_telemetry_fails(self):
        ProbeHandler.scenario = "too_large"
        result, _output = self.probe()
        self.assertFalse(result)
        self.assertEqual(ProbeHandler.methods, ["GET"])

    def test_bad_stream_type_fails(self):
        ProbeHandler.scenario = "bad_stream_type"
        result, _output = self.probe()
        self.assertFalse(result)
        self.assertEqual(ProbeHandler.methods, ["GET", "GET"])

    def test_stream_without_first_frame_fails(self):
        ProbeHandler.scenario = "no_frame"
        result, _output = self.probe()
        self.assertFalse(result)

    def test_truncated_stream_timeout_fails(self):
        ProbeHandler.scenario = "stream_timeout"
        result, output = self.probe(timeout=0.05)
        self.assertFalse(result)
        self.assertIn("timed out", output[-1])

    def test_urls_with_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "username or password"):
            normalize_base_url("http://user:secret@example.test:8080/")


if __name__ == "__main__":
    unittest.main()
