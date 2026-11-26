"""Standard-library web frontend server for WardProof."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clinical.text import sanitize_text
from main import run as run_pipeline

INDEX_HTML = Path(__file__).resolve().parent / "index.html"


class WardProofHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/index.html"}:
            body = INDEX_HTML.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        if self.path == "/api/sanitize":
            text = str(data.get("text", ""))
            field = str(data.get("field", "clinical_note"))
            res = sanitize_text(text, field=field)
            self._send_json(
                HTTPStatus.OK,
                {
                    "text": res.text,
                    "counts": res.counts,
                    "language": res.language,
                    "assertions": [{"text": a.text, "polarity": a.polarity} for a in res.assertions],
                },
            )
            return

        if self.path == "/api/pipeline":
            inp = Path(str(data.get("input_dir", "")))
            if not inp.is_absolute():
                inp = (ROOT / inp).resolve()
            secret = str(data.get("secret", "practice")).encode("utf-8")
            if not inp.is_dir():
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "input_dir_not_found"})
                return
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                run_pipeline(inp, out, secret)
                report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self._send_json(
                HTTPStatus.OK,
                {
                    "counts": report["counts"],
                    "timing": report["timing"],
                    "sample_files": report["files"][:5],
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), WardProofHandler)
    print("WardProof frontend running at http://127.0.0.1:8765", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
