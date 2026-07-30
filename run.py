import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- RENDER FREE TIER HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Quiet log output

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Start HTTP server immediately in a background thread
threading.Thread(target=run_health_server, daemon=True).start()
# --------------------------------------

# Your bot startup code follows here...
