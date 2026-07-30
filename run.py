import os
import sys
import asyncio
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load local .env file if present
load_dotenv()

# ---------------------------------------------------------
# 1. Background HTTP Health Server (Keeps Render Service Live)
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Palworld Bot Service Active")

    def log_message(self, format, *args):
        pass  # Quiet HTTP logs to keep stdout clean

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"[HEALTH CHECK] Web server running on port {port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"[HEALTH CHECK ERROR] {e}", file=sys.stderr, flush=True)

# Start health check server on a background thread immediately
threading.Thread(target=start_health_server, daemon=True).start()

# ---------------------------------------------------------
# 2. Bot Configuration & Environment Check
# ---------------------------------------------------------
TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_TOKEN") or os.environ.get("TOKEN")
PREFIX = os.environ.get("BOT_PREFIX", "!")

if not TOKEN:
    print("[FATAL ERROR] No Discord bot token found in environment variables!", file=sys.stderr, flush=True)
    sys.exit(1)

# Configure Discord Intents
intents = discord.Intents.default()
intents.message_content = True  # Resolves message intent warning
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ---------------------------------------------------------
# 3. Dynamic Cog Loading & Events
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"==========================================", flush=True)
    print(f" SUCCESS: Logged in as {bot.user} (ID: {bot.user.id})", flush=True)
    print(f" Command Prefix: {PREFIX}", flush=True)
    print(f" Guilds Connected: {len(bot.guilds)}", flush=True)
    print(f"==========================================", flush=True)

async def load_cogs():
    """Automatically loads all .py cog files in the /cogs directory if it exists."""
    if os.path.exists("./cogs"):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_path = f"cogs.{filename[:-3]}"
                try:
                    await bot.load_extension(cog_path)
                    print(f"[COG LOADED] {cog_path}", flush=True)
                except Exception as e:
                    print(f"[COG ERROR] Failed to load {cog_path}: {e}", file=sys.stderr, flush=True)

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

# ---------------------------------------------------------
# 4. Entry Point Execution
# ---------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[INFO] Bot shutting down...", flush=True)
    except Exception as e:
        print(f"[FATAL ERROR] Uncaught exception: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
