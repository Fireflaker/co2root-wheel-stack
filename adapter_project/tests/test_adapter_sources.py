import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapter_main import (  # noqa: E402
    DEFAULT_CONFIG,
    HttpFfbSource,
    InjectFfbSource,
    SerialFfbSource,
    WebSocketFfbSource,
    build_source,
    load_config,
)


class AdapterSourceTests(unittest.TestCase):
    def test_load_config_creates_default_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = load_config(cfg_path)
            self.assertTrue(cfg_path.exists())
            self.assertEqual(cfg["elmo_port"], DEFAULT_CONFIG["elmo_port"])

    def test_load_config_merges_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps({"sim_source": "http", "max_tc": 123}), encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg["sim_source"], "http")
            self.assertEqual(cfg["max_tc"], 123)
            self.assertEqual(cfg["elmo_port"], DEFAULT_CONFIG["elmo_port"])

    def test_build_source_dispatch(self):
        base = dict(DEFAULT_CONFIG)

        s_cfg = dict(base)
        s_cfg["sim_source"] = "serial"
        self.assertIsInstance(build_source(s_cfg), SerialFfbSource)

        h_cfg = dict(base)
        h_cfg["sim_source"] = "http"
        self.assertIsInstance(build_source(h_cfg), HttpFfbSource)

        w_cfg = dict(base)
        w_cfg["sim_source"] = "websocket"
        self.assertIsInstance(build_source(w_cfg), WebSocketFfbSource)

        i_cfg = dict(base)
        i_cfg["sim_source"] = "inject"
        self.assertIsInstance(build_source(i_cfg), InjectFfbSource)

    def test_http_extract_nested_force(self):
        src = HttpFfbSource("http://127.0.0.1:8888", deadband=0)
        payload = {
            "meta": {"name": "sim"},
            "telemetry": {
                "forceFeedback": -321,
            },
        }
        self.assertEqual(src._extract(payload), -321)

    def test_websocket_extract_variants(self):
        src = WebSocketFfbSource("ws://127.0.0.1:8888", deadband=0)
        self.assertEqual(src._extract("FFB=777"), 777)
        self.assertEqual(src._extract('{"telemetry": {"torque": -88}}'), -88)
        self.assertIsNone(src._extract("not-json-and-no-int"))


if __name__ == "__main__":
    unittest.main()
