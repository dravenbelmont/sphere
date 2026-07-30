import os
import sys
import asyncio
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
from gamercon_async import GameRCON
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# 1. Background Health Server for Render
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Palworld Relay Active")

    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        print(f"[HEALTH CHECK ERROR] {e}", file=sys.stderr, flush=True)

threading.Thread(target=start_health_server, daemon=True).start()

# ---------------------------------------------------------
# 2. Environment Variables & Bot Setup
# ---------------------------------------------------------
TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_TOKEN") or os.environ.get("TOKEN")
PREFIX = os.environ.get("BOT_PREFIX", "!")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

RCON_HOST = os.environ.get("RCON_HOST")
RCON_PORT = int(os.environ.get("RCON_PORT", 25575)) if os.environ.get("RCON_PORT") else None
RCON_PASSWORD = os.environ.get("RCON_PASSWORD")

if not TOKEN:
    print("[FATAL ERROR] No Discord bot token found!", file=sys.stderr, flush=True)
    sys.exit(1)

if not CHANNEL_ID:
    print("[WARNING] CHANNEL_ID is missing in Render environment variables! Chat relay will not know which channel to watch.", flush=True)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Helper function to send RCON commands safely
async def send_rcon_command(command: str):
    if not RCON_HOST or not RCON_PORT or not RCON_PASSWORD:
        print("[RCON ERROR] RCON environment variables (RCON_HOST, RCON_PORT, RCON_PASSWORD) are incomplete.", flush=True)
        return None
    try:
        async with GameRCON(RCON_HOST, RCON_PORT, RCON_PASSWORD, timeout=10) as rcon:
            response = await rcon.send(command)
            return response
    except Exception as e:
        print(f"[RCON CONNECTION ERROR] Failed to send command '{command}': {e}", file=sys.stderr, flush=True)
        return None

# ---------------------------------------------------------
# 3. Events & Chat Relay
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"==========================================", flush=True)
    print(f" SUCCESS: Bot logged in as {bot.user}", flush=True)
    print(f" Monitoring Channel ID: {CHANNEL_ID or 'NOT SET'}", flush=True)
    print(f" Target RCON Host: {RCON_HOST}:{RCON_PORT}", flush=True)
    print(f"==========================================", flush=True)

@bot.event
async def on_message(message: discord.Message):
    # Ignore messages sent by the bot itself
    if message.author.bot:
        return

    # Check if the message was sent in the designated relay channel
    if CHANNEL_ID and str(message.channel.id) == str(CHANNEL_ID):
        author = message.author.display_name
        clean_content = message.clean_content.replace("\n", " ")
        
        print(f"[RELAY DISCORD -> GAME] {author}: {clean_content}", flush=True)
        
        # Palworld RCON broadcast command (Replaces spaces with underscores for clean formatting if needed)
        rcon_msg = f"Broadcast {author}:_{clean_content}"
        await send_rcon_command(rcon_msg)

    # Allow prefix commands to still work
    await bot.process_commands(message)

# ---------------------------------------------------------
# 4. Entry Point
# ---------------------------------------------------------
async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[INFO] Bot shutting down...", flush=True)
    except Exception as e:
        print(f"[FATAL ERROR] {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
