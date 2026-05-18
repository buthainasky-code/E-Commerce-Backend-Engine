import requests
import itertools
import threading
import sys
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

BACKENDS = ['http://127.0.0.1:8001', 'http://127.0.0.1:8002']
backend_cycle = itertools.cycle(BACKENDS)

semaphore = threading.Semaphore(8)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._forward('GET')
    def do_POST(self):
        self._forward('POST')

    def _forward(self, method):
        backend = next(backend_cycle)
        url = f"{backend}{self.path}"

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length else None

        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ('host', 'connection'):
                headers[k] = v
        # Force close after each request to avoid dead-pool connections
        headers['Connection'] = 'close'

        with semaphore:
            try:
                # Use a fresh requests call (no persistent session)
                resp = requests.request(
                    method, url, headers=headers, data=body, timeout=10
                )
                self.send_response(resp.status_code)
                for k, v in resp.headers.items():
                    if k.lower() != 'transfer-encoding':
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.content)
            except Exception as e:
                print(f"ERROR to {backend}: {e}", file=sys.stderr)
                self.send_response(502)
                self.end_headers()
                self.wfile.write(f"Backend error: {e}".encode())

if __name__ == '__main__':
    server = ThreadingTCPServer(('127.0.0.1', 8000), Handler)
    server.request_queue_size = 128
    print("Load balancer (semaphore=8, no keep‑alive) -> :8001, :8002")
    server.serve_forever()