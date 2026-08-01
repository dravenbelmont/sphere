import os
import re
import sys
import stat
import time
import json
import posixpath
import asyncio
import threading
import traceback
import datetime
from zoneinfo import ZoneInfo
import aiohttp
import paramiko
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands, tasks
from gamercon_async import GameRCON
from dotenv import load_dotenv

load_dotenv()

# Set Server Timezone to Eastern Time (EST/EDT)
EST_TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------
# Helper: Clean Markdown Links & Formatting from Env Vars
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
# 2. Environment Variables & Setup
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

# Discord Invite Link for in-game promo broadcasts
DISCORD_INVITE_URL = clean_env_var(os.environ.get("DISCORD_INVITE_URL")) or "https://discord.gg/mVbdCCFHGp"

if not TOKEN:
    print("[FATAL ERROR] No Discord bot token found!", file=sys.stderr, flush=True)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Track active SFTP file and read offset
current_log_file = ""
last_log_offset = 0

# PalDefender Chat Line Matcher: Matches `[Chat::Global]['PlayerName'...]: Message`
PALDEFENDER_CHAT_REGEX = re.compile(
    r"\[Chat::\w+\]\['(?P<player>[^']+)'[^\]]*\](?:\[[^\]]+\])*:\s*(?P<message>.*)"
)

# EST Schedule tracking keys
last_warning_key = ""
last_restart_key = ""
last_promo_key = ""

RESTART_HOURS = [0, 4, 8, 12, 16, 20]  # 12AM, 4AM, 8AM, 12PM, 4PM, 8PM EST
WARNING_HOURS = [23, 3, 7, 11, 15, 19]  # 10 minutes prior to restart

# ---------------------------------------------------------
# 3. Points & Persistence System
# ---------------------------------------------------------
POINTS_FILE = "player_points.json"

def load_points() -> dict:
    if os.path.exists(POINTS_FILE):
        try:
            with open(POINTS_FILE, "r") as f:
                data = json.load(f)
                if "_claimed_starters" not in data:
                    data["_claimed_starters"] = []
                return data
        except Exception as e:
            print(f"[POINTS ERROR] Failed to load points file: {e}", file=sys.stderr, flush=True)
            return {"_claimed_starters": []}
    return {"_claimed_starters": []}

def save_points(data: dict):
    try:
        with open(POINTS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[POINTS ERROR] Failed to save points: {e}", file=sys.stderr, flush=True)

def get_user_entry(points_data: dict, key_id: str) -> dict:
    """Gets or initializes a player record."""
    entry = points_data.get(key_id, {"points": 0, "last_daily": 0, "player_id": ""})
    if isinstance(entry, int):
        entry = {"points": entry, "last_daily": 0, "player_id": ""}
    return entry

def find_user_by_player_id(points_data: dict, target_p_id: str) -> tuple:
    """Locates a user record matching a specific Palworld Player/Steam ID."""
    for key, val in points_data.items():
        if key.startswith("_"):
            continue
        if isinstance(val, dict) and val.get("player_id") == target_p_id:
            return key, val
    return target_p_id, get_user_entry(points_data, target_p_id)

# ---------------------------------------------------------
# 4. Item Catalogs & Configurations
# ---------------------------------------------------------

# Automatic First-Time Join Starter Loadout (Delivered automatically on 1st login)
STARTER_LOADOUT = [
    {"item_id": "Bow", "count": 1, "name": "Old Bow"},
    {"item_id": "Armor_Pelt", "count": 1, "name": "Pelt Armor"},
    {"item_id": "Parachute_Default", "count": 1, "name": "Normal Glider"},
    {"item_id": "Arrow", "count": 500, "name": "Arrows"},
    {"item_id": "PalSphere_Mega", "count": 20, "name": "Mega Spheres"},
    {"item_id": "HeadEquip_Feather", "count": 1, "name": "Feathered Headband"},
    {"item_id": "Axe_Metal", "count": 1, "name": "Metal Axe"},
    {"item_id": "Pickaxe_Metal", "count": 1, "name": "Metal Pickaxe"},
    {"item_id": "Shield_1", "count": 1, "name": "Common Shield"},
]

# Daily Reward Kit (!daily) - Claimable every 24 hours
DAILY_STARTER_KIT = [
    {"item_id": "PredatorCore", "count": 10, "name": "Predator Cores"},
    {"item_id": "AncientCore", "count": 10, "name": "Ancient Civilization Cores"},
    {"item_id": "Cake", "count": 50, "name": "Vegetable Cakes"},
    {"item_id": "Money", "count": 50000, "name": "Gold Coins"},
]

# Shop Catalog (!shop & !buy)
SHOP_CATALOG = {
    "sphere": {"name": "Pal Sphere (x10)", "item_id": "PalSphere", "count": 10, "price": 100},
    "megasphere": {"name": "Mega Sphere (x10)", "item_id": "PalSphere_Mega", "count": 10, "price": 250},
    "gigasphere": {"name": "Giga Sphere (x5)", "item_id": "PalSphere_Giga", "count": 5, "price": 500},
    "ultrasphere": {"name": "Ultra Sphere (x3)", "item_id": "PalSphere_Tera", "count": 3, "price": 1000},
    "legendarysphere": {"name": "Legendary Sphere (x1)", "item_id": "PalSphere_Legend", "count": 1, "price": 1500},
    "cake": {"name": "Cake (x5)", "item_id": "Cake", "count": 5, "price": 300},
    "ingot": {"name": "Ingot (x50)", "item_id": "CopperIngot", "count": 50, "price": 200},
    "refinedingot": {"name": "Refined Ingot (x20)", "item_id": "RefinedIngot", "count": 20, "price": 500},
}

# ---------------------------------------------------------
# 5. REST API & RCON Helper Functions
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
                return None
    except Exception as e:
        print(f"[REST API ERROR] {url}: {e}", file=sys.stderr, flush=True)
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
                return resp.status == 200
    except Exception as e:
        print(f"[ANNOUNCE ERROR] {e}", file=sys.stderr, flush=True)
        return False

async def rcon_give_item(player_id: str, item_id: str, amount: int) -> bool:
    """Executes GiveItem via RCON to spawn items directly in-game."""
    if not RCON_HOST or not RCON_PASSWORD:
        return False
    try:
        async with GameRCON(RCON_HOST, RCON_PORT, RCON_PASSWORD, timeout=8) as rcon:
            response = await rcon.send(f"GiveItem {player_id} {item_id} {amount}")
            print(f"[RCON GIVE ITEM] Delivered {amount}x {item_id} to {player_id}. Response: {response}", flush=True)
            return True
    except Exception as e:
        print(f"[RCON ERROR] GiveItem failed: {e}", file=sys.stderr, flush=True)
        return False

async def rcon_get_online_players() -> list:
    """Fetches currently online players from the server via ShowPlayers."""
    if not RCON_HOST or not RCON_PASSWORD:
        return []
    try:
        async with GameRCON(RCON_HOST, RCON_PORT, RCON_PASSWORD, timeout=8) as rcon:
            response = await rcon.send("ShowPlayers")
            lines = response.strip().split("\n")
            if len(lines) <= 1:
                return []
            
            online_players = []
            for line in lines[1:]:
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    name = parts[0].strip()
                    playeruid = parts[1].strip()
                    steamid = parts[2].strip()
                    target_id = steamid if (steamid and steamid != "0") else playeruid
                    if target_id:
                        online_players.append({"id": target_id, "name": name})
            return online_players
    except Exception:
        return []

# ---------------------------------------------------------
# 6. In-Game Chat Command Interceptor
# ---------------------------------------------------------
async def process_ingame_command(player_name: str, message: str):
    """Processes commands typed in the in-game chat and broadcasts responses back."""
    parts = message.strip().split()
    cmd = parts[0].lower()
    
    online_players = await rcon_get_online_players()
    player_info = next((p for p in online_players if p["name"].lower() == player_name.lower()), None)
    
    if not player_info:
        return
        
    p_id = player_info["id"]
    points_data = load_points()
    record_key, user_entry = find_user_by_player_id(points_data, p_id)
    user_entry["player_id"] = p_id

    # --- IN-GAME !daily ---
    if cmd == "!daily":
        current_time = int(time.time())
        last_daily = user_entry.get("last_daily", 0)
        
        if current_time - last_daily < 86400:
            rem = 86400 - (current_time - last_daily)
            hrs, mins = rem // 3600, (rem % 3600) // 60
            await send_palworld_announce(f"[BOT] {player_name}, daily already claimed! Next claim in {hrs}h {mins}m.")
            return

        delivered = 0
        for item in DAILY_STARTER_KIT:
            if await rcon_give_item(p_id, item["item_id"], item["count"]):
                delivered += 1

        if delivered > 0:
            user_entry["points"] = user_entry.get("points", 0) + 200
            user_entry["last_daily"] = current_time
            points_data[record_key] = user_entry
            save_points(points_data)
            await send_palworld_announce(f"[BOT] {player_name} claimed Daily Rewards! +200 Shop Points (Total: {user_entry['points']}).")
        else:
            await send_palworld_announce(f"[BOT] Failed to deliver daily kit to {player_name}.")

    # --- IN-GAME !shop ---
    elif cmd == "!shop":
        items_str = ", ".join([f"{k}({v['price']}pts)" for k, v in SHOP_CATALOG.items()])
        await send_palworld_announce(f"[BOT SHOP] Available items: {items_str}. Type !buy <code_name>")

    # --- IN-GAME !buy <item_code> ---
    elif cmd == "!buy":
        if len(parts) < 2:
            await send_palworld_announce(f"[BOT] Usage: !buy <item_code> (e.g. !buy sphere)")
            return
        
        item_code = parts[1].lower()
        if item_code not in SHOP_CATALOG:
            await send_palworld_announce(f"[BOT] Item '{item_code}' not found! Type !shop to view items.")
            return

        item = SHOP_CATALOG[item_code]
        balance = user_entry.get("points", 0)

        if balance < item["price"]:
            await send_palworld_announce(f"[BOT] {player_name}, not enough points! Costs {item['price']} pts, you have {balance} pts.")
            return

        if await rcon_give_item(p_id, item["item_id"], item["count"]):
            user_entry["points"] = balance - item["price"]
            points_data[record_key] = user_entry
            save_points(points_data)
            await send_palworld_announce(f"[BOT] {player_name} bought {item['name']}! Remaining: {user_entry['points']} pts.")
        else:
            await send_palworld_announce(f"[BOT] Delivery failed for {player_name}. Points were not deducted.")

    # --- IN-GAME !points ---
    elif cmd == "!points":
        pts = user_entry.get("points", 0)
        await send_palworld_announce(f"[BOT] {player_name} currently has {pts} Shop Points.")

# ---------------------------------------------------------
# 7. Background Tasks
# ---------------------------------------------------------
@tasks.loop(seconds=10)
async def auto_give_starter_kit():
    """Polls online players every 10s and grants starter loadouts on 1st join ever."""
    online_players = await rcon_get_online_players()
    if not online_players:
        return

    points_data = load_points()
    claimed_starters = set(points_data.get("_claimed_starters", []))
    data_changed = False

    for player in online_players:
        p_id, p_name = player["id"], player["name"]
        if p_id not in claimed_starters:
            print(f"🎉 New player detected online: {p_name} ({p_id}). Delivering automatic Starter Kit...", flush=True)
            success_count = 0
            for item in STARTER_LOADOUT:
                if await rcon_give_item(p_id, item["item_id"], item["count"]):
                    success_count += 1
            if success_count > 0:
                claimed_starters.add(p_id)
                data_changed = True
                await send_palworld_announce(f"🎉 Welcome {p_name}! Your First Join Starter Kit has been delivered to your inventory.")

    if data_changed:
        points_data["_claimed_starters"] = list(claimed_starters)
        save_points(points_data)

@tasks.loop(seconds=4)
async def poll_sftp_chat():
    """Polls server logs over SFTP, forwards game chat to Discord & processes in-game commands."""
    global current_log_file, last_log_offset
    
    if not (SFTP_HOST and SFTP_USER and SFTP_PASS and SFTP_LOG_PATH):
        return

    def _read_remote_log():
        global current_log_file, last_log_offset
        new_lines = []
        transport = None
        try:
            transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
            transport.banner_timeout = 5
            transport.connect(username=SFTP_USER, password=SFTP_PASS)
            sftp = paramiko.SFTPClient.from_transport(transport)
            try:
                target_path = SFTP_LOG_PATH
                try:
                    file_stat = sftp.stat(SFTP_LOG_PATH)
                    if stat.S_ISDIR(file_stat.st_mode):
                        files = sftp.listdir_attr(SFTP_LOG_PATH)
                        log_files = [f for f in files if f.filename.endswith('.log')]
                        if log_files:
                            latest_file = max(log_files, key=lambda f: f.st_mtime)
                            target_path = posixpath.join(SFTP_LOG_PATH, latest_file.filename)
                        else:
                            return []
                except Exception:
                    pass

                if target_path != current_log_file:
                    current_log_file = target_path
                    last_log_offset = sftp.stat(target_path).st_size
                    print(f"[SFTP] Tailing active log file: {current_log_file}", flush=True)

                file_size = sftp.stat(target_path).st_size
                if file_size > last_log_offset:
                    with sftp.open(target_path, 'r') as f:
                        f.seek(last_log_offset)
                        content = f.read().decode('utf-8', errors='ignore')
                        last_log_offset = f.tell()
                        new_lines = content.splitlines()
                elif file_size < last_log_offset:
                    last_log_offset = 0
            finally:
                sftp.close()
        except Exception:
            pass
        finally:
            if transport:
                try:
                    transport.close()
                except Exception:
                    pass
        return new_lines

    lines = await asyncio.to_thread(_read_remote_log)
    
    if lines and CHANNEL_ID:
        channel = bot.get_channel(int(CHANNEL_ID))
        for line in lines:
            match = PALDEFENDER_CHAT_REGEX.search(line)
            if match:
                player_name = match.group("player")
                chat_msg = match.group("message").strip()
                
                # Forward to Discord channel
                if channel:
                    await channel.send(f"💬 **{player_name}**: {chat_msg}")
                
                # Check for and execute In-Game Commands
                if chat_msg.startswith("!"):
                    await process_ingame_command(player_name, chat_msg)

@poll_sftp_chat.error
async def poll_sftp_chat_error(error):
    await asyncio.sleep(5)
    if not poll_sftp_chat.is_running():
        poll_sftp_chat.start()

@tasks.loop(seconds=20)
async def restart_scheduler():
    """Automated EST Schedule: 10-min warning, auto-restart exit, and 2-hr Discord promo broadcast."""
    global last_warning_key, last_restart_key, last_promo_key
    
    now = datetime.datetime.now(EST_TZ)
    current_key = f"{now.day}-{now.hour}-{now.minute}"

    # 1. 10-Minute Warning before EST restarts
    if now.hour in WARNING_HOURS and now.minute == 50:
        if last_warning_key != current_key:
            last_warning_key = current_key
            await send_palworld_announce("⚠️ SERVER NOTICE: Server restart scheduled in 10 minutes! Please find a safe spot.")

    # 2. Exact Restart Hour Exit
    if now.hour in RESTART_HOURS and now.minute == 0:
        if last_restart_key != current_key:
            last_restart_key = current_key
            print(f"[EST SCHEDULE] Restart hour reached ({now.strftime('%I:%M %p EST')}). Rebooting...", flush=True)
            sys.exit(0)

    # 3. 2-Hour Discord Promo Broadcast
    if now.hour % 2 == 0 and now.minute == 30:
        if last_promo_key != current_key:
            last_promo_key = current_key
            await send_palworld_announce(f"📢 Join our Discord community for news, updates & trading! {DISCORD_INVITE_URL}")

@tasks.loop(minutes=2)
async def check_server_status():
    data = await fetch_palworld_api("players")
    if data and "players" in data:
        players = data["players"]
        print(f"[REST API] Online Players ({len(players)})", flush=True)

# ---------------------------------------------------------
# 8. Discord Events & Commands
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"==========================================", flush=True)
    print(f" SUCCESS: Bot logged in as {bot.user}", flush=True)
    print(f" Timezone: EST (America/New_York)", flush=True)
    print(f" In-Game Chat Interceptor: ACTIVE", flush=True)
    print(f" First-Join Auto Starter Kit: ACTIVE", flush=True)
    print(f"==========================================", flush=True)
    
    if not check_server_status.is_running():
        check_server_status.start()
    if not poll_sftp_chat.is_running() and SFTP_USER and SFTP_LOG_PATH:
        poll_sftp_chat.start()
    if not restart_scheduler.is_running():
        restart_scheduler.start()
    if not auto_give_starter_kit.is_running():
        auto_give_starter_kit.start()

@bot.command(name="register")
async def register_player(ctx, player_id: str = None):
    """Links your Palworld Player ID or Steam ID to your Discord account."""
    if not player_id:
        await ctx.send("❌ **Usage:** `!register <PlayerID_or_SteamID>`\nExample: `!register 76561198000000000`")
        return

    user_id = str(ctx.author.id)
    points_data = load_points()
    user_entry = get_user_entry(points_data, user_id)

    user_entry["player_id"] = player_id.strip()
    points_data[user_id] = user_entry
    save_points(points_data)

    await ctx.send(f"✅ **Registered!** Linked **{ctx.author.display_name}** to Player ID `{player_id}`.")

@bot.command(name="daily")
async def claim_daily(ctx, player_id: str = None):
    """Claim daily free points + in-game Daily Kit!"""
    user_id = str(ctx.author.id)
    points_data = load_points()
    user_entry = get_user_entry(points_data, user_id)

    target_player_id = player_id or user_entry.get("player_id")
    if not target_player_id:
        await ctx.send("❌ **Player ID required!** Register first with `!register <PlayerID>` or use `!daily <PlayerID>`.")
        return

    current_time = int(time.time())
    last_daily = user_entry.get("last_daily", 0)

    if current_time - last_daily < 86400:
        rem = 86400 - (current_time - last_daily)
        hours, minutes = rem // 3600, (rem % 3600) // 60
        await ctx.send(f"⏳ **{ctx.author.display_name}**, daily reward already claimed! Next claim in **{hours}h {minutes}m**.")
        return

    delivered_items = []
    for item in DAILY_STARTER_KIT:
        if await rcon_give_item(target_player_id, item["item_id"], item["count"]):
            delivered_items.append(f"• **{item['count']:,}x {item['name']}**")

    if not delivered_items:
        await ctx.send("⚠️ **Delivery Failed:** Could not send items via RCON. Make sure you are logged into the server!")
        return

    reward_points = 200
    user_entry["points"] = user_entry.get("points", 0) + reward_points
    user_entry["last_daily"] = current_time
    if player_id:
        user_entry["player_id"] = player_id

    points_data[user_id] = user_entry
    save_points(points_data)

    embed = discord.Embed(title="🎁 Daily Rewards Claimed!", color=discord.Color.green())
    embed.add_field(name="💰 Shop Points", value=f"+**{reward_points}** pts (Total: **{user_entry['points']:,}** pts)", inline=False)
    embed.add_field(name="📦 Items Delivered", value="\n".join(delivered_items), inline=False)
    embed.set_footer(text=f"Delivered to ID: {target_player_id}")
    await ctx.send(embed=embed)

@bot.command(name="shop")
async def show_shop(ctx):
    """Lists all available items in the server shop."""
    embed = discord.Embed(title="🛒 Palworld Server Item Shop", color=discord.Color.gold())
    for code, info in SHOP_CATALOG.items():
        embed.add_field(
            name=f"• {info['name']} (`!buy {code}`)",
            value=f"💰 **Price:** {info['price']} points | **Code:** `{code}`",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="buy")
async def buy_item(ctx, item_code: str = None, player_id: str = None):
    """Buy an item from the shop and receive it in-game."""
    if not item_code:
        await ctx.send("❌ **Usage:** `!buy <item_code>` (e.g. `!buy sphere`)")
        return

    item_code = item_code.lower()
    if item_code not in SHOP_CATALOG:
        await ctx.send(f"❌ Item `{item_code}` not found. Type `!shop` to see available items.")
        return

    user_id = str(ctx.author.id)
    points_data = load_points()
    user_entry = get_user_entry(points_data, user_id)

    target_player_id = player_id or user_entry.get("player_id")
    if not target_player_id:
        await ctx.send("❌ **Player ID required!** Register first with `!register <PlayerID>` or use `!buy <item_code> <PlayerID>`.")
        return

    item = SHOP_CATALOG[item_code]
    user_balance = user_entry.get("points", 0)

    if user_balance < item["price"]:
        await ctx.send(f"❌ Not enough points! **{item['name']}** costs **{item['price']} points**, but you only have **{user_balance} points**.")
        return

    if await rcon_give_item(target_player_id, item["item_id"], item["count"]):
        user_entry["points"] = user_balance - item["price"]
        if player_id:
            user_entry["player_id"] = player_id
        points_data[user_id] = user_entry
        save_points(points_data)
        await ctx.send(f"✅ **Purchase Successful!** Delivered **{item['name']}** to ID `{target_player_id}`. Remaining balance: **{user_entry['points']} points**.")
    else:
        await ctx.send("⚠️ **Delivery Failed:** Could not connect to RCON or deliver item. Your points were **not** deducted.")

@bot.command(name="points")
async def check_points(ctx):
    """Check your current point balance and registered Player ID."""
    user_id = str(ctx.author.id)
    points_data = load_points()
    user_entry = get_user_entry(points_data, user_id)

    balance = user_entry.get("points", 0)
    linked_id = user_entry.get("player_id", "Not registered")

    embed = discord.Embed(title=f"👤 Player Profile | {ctx.author.display_name}", color=discord.Color.purple())
    embed.add_field(name="💳 Shop Points", value=f"**{balance:,}** pts", inline=True)
    embed.add_field(name="🆔 Linked ID", value=f"`{linked_id}`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="addpoints")
@commands.has_permissions(administrator=True)
async def add_points(ctx, member: discord.Member, amount: int):
    """Admin Command: Grant points to a member."""
    user_id = str(member.id)
    points_data = load_points()
    user_entry = get_user_entry(points_data, user_id)

    user_entry["points"] = user_entry.get("points", 0) + amount
    points_data[user_id] = user_entry
    save_points(points_data)

    await ctx.send(f"👑 Added **{amount:,} points** to {member.mention}. New balance: **{user_entry['points']:,} points**.")

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

    # Relay Discord messages to in-game chat
    if CHANNEL_ID and str(message.channel.id) == str(CHANNEL_ID):
        author = message.author.display_name
        clean_content = message.clean_content.replace("\n", " ")
        await send_palworld_announce(f"{author}: {clean_content}")

    await bot.process_commands(message)

# ---------------------------------------------------------
# 9. Entry Point
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
