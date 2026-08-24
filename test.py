from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hello from deployment-test v2!")

server = HTTPServer(("0.0.0.0", 8000), Handler)

print("Hello from deployment-test v2!")
server.serve_forever()
