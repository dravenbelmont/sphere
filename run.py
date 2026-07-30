import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Background web server for Render port check
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Project Sphere is live!")
        
    def log_message(self, format, *args):
        pass

def start_health_check_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        print(f"Health check server notice: {e}")

threading.Thread(target=start_health_check_server, daemon=True).start()

# ==========================================
# REPOSITORY CODE STARTS BELOW
# ==========================================
