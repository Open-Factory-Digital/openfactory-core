"""A stand-in for the application a preview fixture builds: `runserver` answers `/health` on the
address it is given; `migrate` and `loaddata` finish at once — enough for a live preview of S1 to
be judged ready, to run its one-shot and its data step."""

import http.server
import sys


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — the stdlib's name
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "runserver"
    if command == "runserver":
        host, _, port = (sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0:8000").rpartition(":")
        http.server.ThreadingHTTPServer((host or "0.0.0.0", int(port)), _Health).serve_forever()
    print(f"{command}: nothing to do")
