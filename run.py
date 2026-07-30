import os
import sys
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure standard output flushes immediately to Render logs
print("===> [DIAGNOSTIC 1/5] Starting run.py execution...", flush=True)

# ---------------------------------------------------------
# 1. Start HTTP Health Server for Render Free Tier
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Quiet HTTP logs

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"===> [DIAGNOSTIC 2/5] Starting HTTP health server on port {port}...", flush=True)
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        print(f"===> [ERROR] Health server failed: {e}", file=sys.stderr, flush=True)

# Run web server in a background thread
threading.Thread(target=start_health_server, daemon=True).start()

# ---------------------------------------------------------
# 2. Audit Render Environment Variables
# ---------------------------------------------------------
print("===> [DIAGNOSTIC 3/5] Auditing environment variables...", flush=True)

# Common key names used by Discord/Palworld bots
known_keys = ["DISCORD_TOKEN", "BOT_TOKEN", "TOKEN", "RCON_HOST", "RCON_PORT", "RCON_PASSWORD"]
found_keys = [key for key in known_keys if os.environ.get(key)]
missing_keys = [key for key in known_keys if not os.environ.get(key)]

print(f"  -> Found keys: {found_keys}", flush=True)
print(f"  -> Missing common keys: {missing_keys}", flush=True)

# Check for Discord token under common variable names
token = os.environ.get("DISCORD_TOKEN") or os.environ.get("BOT_TOKEN") or os.environ.get("TOKEN")

if not token:
    print("\n[FATAL ERROR] No Discord token detected in Render Environment Variables!", file=sys.stderr, flush=True)
    print("Please add DISCORD_TOKEN or BOT_TOKEN under your Render service's 'Environment' tab.\n", file=sys.stderr, flush=True)
    sys.exit(1)

# ---------------------------------------------------------
# 3. Launch Bot Execution
# ---------------------------------------------------------
print("===> [DIAGNOSTIC 4/5] Attempting bot startup...", flush=True)

try:
    # --- IF YOU HAVE EXISTING BOT LOGIC BELOW, INSERT OR IMPORT IT HERE ---
    import discord
    from discord.ext import commands

    print("===> [DIAGNOSTIC 5/5] discord.py successfully imported. Connecting to Discord...", flush=True)

    # Example generic client startup (replace with your specific bot/cog setup if needed)
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"===> [SUCCESS] Bot is online and logged in as {bot.user}!", flush=True)

    # Starts the bot and blocks execution (keeps the script running)
    bot.run(token)

except Exception as e:
    print("\n[FATAL ERROR] An uncaught exception crashed the bot during startup:", file=sys.stderr, flush=True)
    traceback.print_exc()
    sys.exit(1)
