import os
import sys
import asyncio
import threading
import traceback
import aiohttp
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands, tasks
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
        self.wfile.write(b"OK - Palworld Relay & REST API Active")

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

RCON_HOST = os.environ.get("RCON_HOST", "167.114.174.145")
RCON_PORT = int(os.environ.get("RCON_PORT", 25575)) if os.environ.get("RCON_PORT") else 25575
RCON_PASSWORD = os.environ.get("RCON_PASSWORD")

REST_API_URL = os.environ.get("REST_API_URL", "http://167.114.174.145:8212")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or RCON_PASSWORD

if not TOKEN:
    print("[FATAL ERROR] No Discord bot token found!", file=sys.stderr, flush=True)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ---------------------------------------------------------
# 3. REST API Helper Functions
# ---------------------------------------------------------
async def fetch_palworld_api(endpoint: str):
    """Fetches data from the Palworld REST API using Basic Auth (admin:AdminPassword)."""
    if not REST_API_URL or not ADMIN_PASSWORD:
        return None
        
    url = f"{REST_API_URL.rstrip('/')}/v1/api/{endpoint}"
    auth = aiohttp.BasicAuth(login="admin", password=ADMIN_PASSWORD)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth, timeout=5) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"[REST API ERROR] Status {resp.status} on {endpoint}", flush=True)
                    return None
    except Exception as e:
        print(f"[REST API CONNECTION ERROR] Failed to reach {url}: {e}", file=sys.stderr, flush=True)
        return None

# Background Task: Periodically Log Active Players
@tasks.loop(minutes=2)
async def check_server_status():
    data = await fetch_palworld_api("players")
    if data and "players" in data:
        players = data["players"]
        player_names = [p.get("name", "Unknown") for p in players]
        print(f"[REST API] Online Players ({len(players)}): {', '.join(player_names)}", flush=True)

# ---------------------------------------------------------
# 4. Events & Commands
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"==========================================", flush=True)
    print(f" SUCCESS: Bot logged in as {bot.user}", flush=True)
    print(f" Monitoring Channel ID: {CHANNEL_ID or 'NOT SET'}", flush=True)
    print(f" Target RCON Host: {RCON_HOST}:{RCON_PORT}", flush=True)
    print(f" Target REST API: {REST_API_URL}", flush=True)
    print(f"==========================================", flush=True)
    if not check_server_status.is_running():
        check_server_status.start()

@bot.command(name="players")
async def list_players(ctx):
    """Discord command: !players to see who is currently in-game."""
    data = await fetch_palworld_api("players")
    if not data or "players" not in data:
        await ctx.send("❌ Unable to reach Palworld REST API.")
        return
    
    players = data["players"]
    if not players:
        await ctx.send("🎮 Server is online, but no players are currently in-game.")
        return
        
    player_list = "\n".join([f"• **{p.get('name')}** (Level {p.get('level', '?')})" for p in players])
    embed = discord.Embed(
        title=f"Online Players ({len(players)})",
        description=player_list,
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Discord -> Game Broadcast Relay
    if CHANNEL_ID and str(message.channel.id) == str(CHANNEL_ID):
        author = message.author.display_name
        clean_content = message.clean_content.replace("\n", " ")
        print(f"[RELAY DISCORD -> GAME] {author}: {clean_content}", flush=True)
        
        # Send broadcast via RCON
        if RCON_HOST and RCON_PASSWORD:
            try:
                async with GameRCON(RCON_HOST, RCON_PORT, RCON_PASSWORD, timeout=10) as rcon:
                    await rcon.send(f"Broadcast {author}:_{clean_content}")
            except Exception as e:
                print(f"[RCON ERROR] {e}", file=sys.stderr, flush=True)

    await bot.process_commands(message)

# ---------------------------------------------------------
# 5. Entry Point
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
