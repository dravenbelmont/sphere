import os
import re
import sys
import stat
import posixpath
import asyncio
import threading
import traceback
import aiohttp
import paramiko
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands, tasks
from gamercon_async import GameRCON
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# Helper: Clean Markdown Links & Extra Formatting from Env Vars
# ---------------------------------------------------------
def clean_env_var(val: str) -> str:
    """Strips Markdown link syntax, brackets, and quotes from env vars."""
    if not val:
        return ""
    val = val.strip()
    
    md_match = re.search(r'\[.*?\]\((https?://[^\)]+)\)', val)
    if md_match:
        return md_match.group(1).strip()
        
    if "http://" in val or "https://" in val:
        url_match = re.search(r'https?://[^\s\)\]"]+', val)
        if url_match:
            return url_match.group(0).strip()
            
    return val.strip(" []()\"'")

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
TOKEN = clean_env_var(os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_TOKEN") or os.environ.get("TOKEN"))
PREFIX = clean_env_var(os.environ.get("BOT_PREFIX", "!"))
CHANNEL_ID = clean_env_var(os.environ.get("CHANNEL_ID"))

RCON_HOST = clean_env_var(os.environ.get("RCON_HOST", "167.114.174.145"))
RCON_PORT_RAW = clean_env_var(os.environ.get("RCON_PORT", "25575"))
RCON_PORT = int(RCON_PORT_RAW) if RCON_PORT_RAW.isdigit() else 25575
RCON_PASSWORD = clean_env_var(os.environ.get("RCON_PASSWORD"))

REST_API_URL = clean_env_var(os.environ.get("REST_API_URL", "http://167.114.174.145:27014"))
ADMIN_PASSWORD = clean_env_var(os.environ.get("ADMIN_PASSWORD")) or RCON_PASSWORD

# SFTP Configuration for Game -> Discord Chat Tailing
SFTP_HOST = clean_env_var(os.environ.get("SFTP_HOST")) or RCON_HOST
SFTP_PORT_RAW = clean_env_var(os.environ.get("SFTP_PORT", "22"))
SFTP_PORT = int(SFTP_PORT_RAW) if SFTP_PORT_RAW.isdigit() else 22
SFTP_USER = clean_env_var(os.environ.get("SFTP_USER"))
SFTP_PASS = clean_env_var(os.environ.get("SFTP_PASSWORD"))
SFTP_LOG_PATH = clean_env_var(os.environ.get("SFTP_LOG_PATH"))

if not TOKEN:
    print("[FATAL ERROR] No Discord bot token found!", file=sys.stderr, flush=True)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Track active file and read offset in remote log file
current_log_file = ""
last_log_offset = 0

# PalDefender Chat Line Matcher: Matches `[Chat::Global]['PlayerName'...]: Message`
PALDEFENDER_CHAT_REGEX = re.compile(
    r"\[Chat::\w+\]\['(?P<player>[^']+)'[^\]]*\](?:\[[^\]]+\])*:\s*(?P<message>.*)"
)

# ---------------------------------------------------------
# 3. REST API Helper Functions
# ---------------------------------------------------------
async def fetch_palworld_api(endpoint: str):
    """Fetches data from the Palworld REST API using Basic Auth."""
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
                    return None
    except Exception as e:
        print(f"[REST API ERROR] Failed to reach {url}: {e}", file=sys.stderr, flush=True)
        return None

async def send_palworld_announce(message_text: str) -> bool:
    """Broadcasts a message to players in-game via REST API /v1/api/announce."""
    if not REST_API_URL or not ADMIN_PASSWORD:
        return False
        
    url = f"{REST_API_URL.rstrip('/')}/v1/api/announce"
    auth = aiohttp.BasicAuth(login="admin", password=ADMIN_PASSWORD)
    payload = {"message": message_text}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, auth=auth, json=payload, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[ANNOUNCE SUCCESS] Sent in-game: {message_text}", flush=True)
                    return True
                else:
                    return False
    except Exception as e:
        print(f"[ANNOUNCE ERROR] Failed to send broadcast: {e}", file=sys.stderr, flush=True)
        return False

# ---------------------------------------------------------
# 4. Background Tasks (Players & SFTP Chat Tailer)
# ---------------------------------------------------------
@tasks.loop(minutes=2)
async def check_server_status():
    data = await fetch_palworld_api("players")
    if data and "players" in data:
        players = data["players"]
        player_names = [p.get("name", "Unknown") for p in players]
        print(f"[REST API] Online Players ({len(players)}): {', '.join(player_names)}", flush=True)

@tasks.loop(seconds=4)
async def poll_sftp_chat():
    """Polls server log file over SFTP and forwards in-game chat to Discord."""
    global current_log_file, last_log_offset
    
    if not (SFTP_HOST and SFTP_USER and SFTP_PASS and SFTP_LOG_PATH):
        return

    def _read_remote_log():
        global current_log_file, last_log_offset
        new_lines = []
        try:
            transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
            transport.connect(username=SFTP_USER, password=SFTP_PASS)
            sftp = paramiko.SFTPClient.from_transport(transport)

            try:
                target_path = SFTP_LOG_PATH
                
                # Check if SFTP_LOG_PATH is a directory or direct file
                try:
                    file_stat = sftp.stat(SFTP_LOG_PATH)
                    if stat.S_ISDIR(file_stat.st_mode):
                        files = sftp.listdir_attr(SFTP_LOG_PATH)
                        log_files = [f for f in files if f.filename.endswith('.log')]
                        if log_files:
                            # Pick the file with the newest modification timestamp
                            latest_file = max(log_files, key=lambda f: f.st_mtime)
                            target_path = posixpath.join(SFTP_LOG_PATH, latest_file.filename)
                        else:
                            return []
                except Exception:
                    pass

                # If server rebooted and created a new timestamped log file
                if target_path != current_log_file:
                    current_log_file = target_path
                    last_log_offset = sftp.stat(target_path).st_size  # Start at end of new file
                    print(f"[SFTP] Tailing active log file: {current_log_file}", flush=True)

                file_size = sftp.stat(target_path).st_size

                if file_size > last_log_offset:
                    with sftp.open(target_path, 'r') as f:
                        f.seek(last_log_offset)
                        content = f.read().decode('utf-8', errors='ignore')
                        last_log_offset = f.tell()
                        new_lines = content.splitlines()
                elif file_size < last_log_offset:
                    # Log was wiped or truncated
                    last_log_offset = 0

            finally:
                sftp.close()
                transport.close()
        except Exception as e:
            print(f"[SFTP ERROR] {e}", file=sys.stderr, flush=True)

        return new_lines

    # Run blocking SFTP operations in a background thread
    lines = await asyncio.to_thread(_read_remote_log)
    
    if lines and CHANNEL_ID:
        channel = bot.get_channel(int(CHANNEL_ID))
        if channel:
            for line in lines:
                # 1. Parse PalDefender chat format
                match = PALDEFENDER_CHAT_REGEX.search(line)
                if match:
                    player_name = match.group("player")
                    chat_msg = match.group("message")
                    await channel.send(f"💬 **{player_name}**: {chat_msg}")
                    continue

                # 2. Fallback check for standard plugin chat lines
                if any(kw in line.lower() for kw in ["chat::", "[chat]", "playerchat"]):
                    clean_line = re.sub(r'^\s*\[.*?\]\s*', '', line).strip()
                    await channel.send(f"💬 **[Game Chat]** {clean_line if clean_line else line}")

# ---------------------------------------------------------
# 5. Events & Commands
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"==========================================", flush=True)
    print(f" SUCCESS: Bot logged in as {bot.user}", flush=True)
    print(f" Monitoring Channel ID: {CHANNEL_ID or 'NOT SET'}", flush=True)
    print(f" Target REST API: {REST_API_URL}", flush=True)
    print(f" SFTP Log Monitoring: {'ENABLED' if SFTP_USER and SFTP_LOG_PATH else 'DISABLED (Missing Credentials)'}", flush=True)
    print(f"==========================================", flush=True)
    
    if not check_server_status.is_running():
        check_server_status.start()
        
    if not poll_sftp_chat.is_running() and SFTP_USER and SFTP_LOG_PATH:
        poll_sftp_chat.start()

@bot.command(name="players")
async def list_players(ctx):
    """Discord command: !players"""
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

    # Discord -> Game Announcement Relay
    if CHANNEL_ID and str(message.channel.id) == str(CHANNEL_ID):
        author = message.author.display_name
        clean_content = message.clean_content.replace("\n", " ")
        announcement = f"{author}: {clean_content}"
        
        print(f"[RELAY DISCORD -> GAME] Sending: {announcement}", flush=True)
        await send_palworld_announce(announcement)

    await bot.process_commands(message)

# ---------------------------------------------------------
# 6. Entry Point
# ---------------------------------------------------------
async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        async carefully = asyncio.run(main())
    except KeyboardInterrupt:
        print("[INFO] Bot shutting down...", flush=True)
    except Exception as e:
        print(f"[FATAL ERROR] {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
