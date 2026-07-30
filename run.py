import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Palworld Discord Bot is running!")

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logging in standard output

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Run the health check server in a background thread
threading.Thread(target=start_health_server, daemon=True).start()
