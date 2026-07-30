import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Background web server to satisfy Render's port binding requirement
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Project Sphere is live!")
    def log_message(self, format, *args):
        return  # Silence standard HTTP logs in Render output

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_check_server, daemon=True).start()
