#!/usr/bin/env python3
"""GET /base/<video_id> do subrim_server: cues processadas do base em disco.

Uso: python -m unittest test_subrim_server_base
"""

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror, request as urlrequest

import subrim_server

BASE = (
    "1\t0.000s\t1.500s\t你好\t[\"你好 (nǐ hǎo): olá\"]\tOlá\n"
    "2\t1.500s\t3.000s\t謝謝\tN/A\tN/A\n"
    "3\t3.000s\t4.000s\t嗯\t[]\tHum\n"
    "4\t5.000s\t6.500s\t你好\t[\"你好 (nǐ hǎo): olá\"]\tOlá\n"
)


class BaseEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cache = subrim_server.CACHE_DIR
        subrim_server.CACHE_DIR = Path(self.tmp.name)
        (subrim_server.CACHE_DIR / "abcdef123_base.txt").write_text(BASE, encoding="utf-8")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), subrim_server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        subrim_server.CACHE_DIR = self.old_cache
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urlrequest.urlopen(self.url + path) as r:
                return r.status, json.loads(r.read())
        except urlerror.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_devolve_so_processadas_com_repetidas(self):
        status, body = self.get("/base/abcdef123")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 4)
        self.assertEqual([c["start"] for c in body["cues"]], [0.0, 3.0, 5.0])
        self.assertEqual(body["cues"][0], {"start": 0.0, "end": 1.5, "zh": "你好",
                                           "pairs": ["你好 (nǐ hǎo): olá"], "pt": "Olá"})
        self.assertEqual(body["cues"][1]["pairs"], [])

    def test_sem_base_404(self):
        self.assertEqual(self.get("/base/semnadaaqui")[0], 404)

    def test_video_id_invalido_404(self):
        self.assertEqual(self.get("/base/..%2F..%2Fetc")[0], 404)


if __name__ == "__main__":
    unittest.main()
