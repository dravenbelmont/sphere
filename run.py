import asyncio
import logging
import os
import sys
import stat
import re
import struct
from datetime import datetime, timedelta, timezone

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
import asyncpg
import paramiko

# -------------------------------------------------------------
# 1. Logging Setup
# -------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Sphere")

# -------------------------------------------------------------
# 2. Dynamic Environment Variable Scanner
# -------------------------------------------------------------
def find_env_val(*patterns, default=""):
    for k, v in os.environ.items():
        k_low = k.lower()
        if any(p in k_low for p in patterns):
            val = v.strip().strip("[]()").strip()
            if val:
                return val
    return default

def find_env_val_multi(*pattern_sets, default=""):
    for patterns in pattern_sets:
        val = find_env_val(*patterns)
        if val:
            return val
    return default

_port_val = os.getenv("PORT") or find_env_val("web_port") or "10000"
WEB_PORT = int(_port_val) if str(_port_val).isdigit() else 10000

DISCORD_TOKEN = find_env_val_multi(("discord_token",), ("bot_token",), ("token",))
BOT_PREFIX = find_env_val("prefix") or "!"
REST_API_URL = find_env_val_multi(("rest_api",), ("palworld_api",), ("api_url",), ("api",))
ADMIN_PASSWORD = find_env_val_multi(("admin_pass",), ("rcon_pass",), ("admin",), ("password",), ("pass",))
DATABASE_URL = find_env_val_multi(("database",), ("supabase",), ("db_url",), ("db",))

RCON_HOST = find_env_val_multi(("rcon_host",), ("server_ip",), ("host",), ("ip",)) or "127.0.0.1"
_rcon_port_val = find_env_val("rcon_port") or "25575"
RCON_PORT = int(_rcon_port_val) if str(_rcon_port_val).isdigit() else 25575

_channel_val = find_env_val_multi(("chat_channel",), ("channel_id",), ("channel",)) or "0"
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if str(_channel_val).isdigit() else 0

# SFTP Credentials
SFTP_HOST = find_env_val_multi(("sftp_host",), ("ftp_host",)) or RCON_HOST
_sftp_port_val = find_env_val("sftp_port") or "22"
SFTP_PORT = int(_sftp_port_val) if str(_sftp_port_val).isdigit() else 22
SFTP_USER = find_env_val_multi(("sftp_user",), ("ftp_user",), ("username",))
SFTP_PASSWORD = find_env_val_multi(("sftp_pass",), ("ftp_pass",)) or ADMIN_PASSWORD

ENABLE_SFTP_POLLING = os.getenv("ENABLE_SFTP_POLLING", "true").lower() in ("true", "1", "yes")

# Targeted Paths & Directories including /Logs folder
POSSIBLE_LOG_PATHS = [
    os.getenv("PALDEFENDER_LOG_PATH"),
    os.getenv("LOG_PATH"),
    "/server-data/Pal/Binaries/Win64/PalDefender/Logs/chat.log",
    "/server-data/Pal/Binaries/Win64/PalDefender/chat.log",
    "/home/container/Pal/Binaries/Win64/PalDefender/Logs/chat.log",
    "/home/container/Pal/Binaries/Win64/PalDefender/chat.log",
    "./Pal/Binaries/Win64/PalDefender/Logs/chat.log",
    "./Pal/Binaries/Win64/PalDefender/chat.log"
]

POSSIBLE_LOG_DIRS = [
    "/server-data/Pal/Binaries/Win64/PalDefender/Logs",
    "/server-data/Pal/Binaries/Win64/PalDefender",
    "/home/container/Pal/Binaries/Win64/PalDefender/Logs",
    "/home/container/Pal/Binaries/Win64/PalDefender",
    "./Pal/Binaries/Win64/PalDefender/Logs"
]

# -------------------------------------------------------------
# 3. Daily Reward & Shop Items
# -------------------------------------------------------------
DAILY_SHOP_POINTS = 500
DAILY_ITEMS = [
    {"id": "PredatorCore", "amount": 10, "name": "Predator Cores"},
    {"id": "AncientCore", "amount": 10, "name": "Ancient Cores"},
    {"id": "DogCoin", "amount": 500, "name": "Dog Coins"},
    {"id": "Cake", "amount": 50, "name": "Special Cakes"},
    {"id": "GoldCoin", "amount": 50000, "name": "Gold"}
]

SHOP_ITEMS = {
    # Spheres
    "pal_sphere": {"name": "Pal Sphere", "id": "PalSphere", "price": 10, "category": "Spheres"},
    "mega_sphere": {"name": "Mega Sphere", "id": "MegaSphere", "price": 25, "category": "Spheres"},
    "giga_sphere": {"name": "Giga Sphere", "id": "GigaSphere", "price": 50, "category": "Spheres"},
    "hyper_sphere": {"name": "Hyper Sphere", "id": "HyperSphere", "price": 100, "category": "Spheres"},
    "ultimate_sphere": {"name": "Ultimate Sphere", "id": "UltimateSphere", "price": 250, "category": "Spheres"},
    "legend_sphere": {"name": "Legend Sphere", "id": "LegendSphere", "price": 500, "category": "Spheres"},
    "plasteel_sphere": {"name": "Plasteel Sphere", "id": "PlasteelSphere", "price": 800, "category": "Spheres"},

    # Shields
    "common_shield": {"name": "Common Shield", "id": "Armor_Shield_01", "price": 100, "category": "Shields"},
    "mega_shield": {"name": "Mega Shield", "id": "Armor_Shield_02", "price": 300, "category": "Shields"},
    "giga_shield": {"name": "Giga Shield", "id": "Armor_Shield_03", "price": 600, "category": "Shields"},
    "hyper_shield": {"name": "Hyper Shield", "id": "Armor_Shield_04", "price": 1200, "category": "Shields"},
    "ultra_shield": {"name": "Ultra Shield", "id": "Armor_Shield_05", "price": 2500, "category": "Shields"},

    # Armors
    "metal_armor": {"name": "Metal Armor", "id": "MetalArmor", "price": 400, "category": "Armors"},
    "refined_metal_armor": {"name": "Refined Metal Armor", "id": "RefinedMetalArmor", "price": 1000, "category": "Armors"},
    "pal_metal_armor": {"name": "Pal Metal Armor", "id": "PalMetalArmor", "price": 2500, "category": "Armors"},
    "plasteel_armor": {"name": "Plasteel Armor", "id": "PlasteelArmor", "price": 5000, "category": "Armors"},

    # Guns
    "musket": {"name": "Musket", "id": "Musket", "price": 200, "category": "Guns"},
    "handgun": {"name": "Made-in-Japan Handgun", "id": "Handgun", "price": 500, "category": "Guns"},
    "double_barrel": {"name": "Double-barreled Shotgun", "id": "DoubleBarrelShotgun", "price": 800, "category": "Guns"},
    "assault_rifle": {"name": "Assault Rifle", "id": "AssaultRifle", "price": 2000, "category": "Guns"},
    "pump_shotgun": {"name": "Pump-action Shotgun", "id": "PumpActionShotgun", "price": 2500, "category": "Guns"},
    "rocket_launcher": {"name": "Rocket Launcher", "id": "RocketLauncher", "price": 6000, "category": "Guns"},
    "laser_rifle": {"name": "Laser Rifle", "id": "LaserRifle", "price": 7500, "category": "Guns"},
    "gatling_gun": {"name": "Gatling Gun", "id": "GatlingGun", "price": 10000, "category": "Guns"},

    # Ammo
    "normal_bullet": {"name": "Normal Bullet (x100)", "id": "Bullet_Normal", "price": 150, "category": "Ammo"},
    "assault_bullet": {"name": "Assault Rifle Bullet (x100)", "id": "Bullet_AssaultRifle", "price": 300, "category": "Ammo"},
    "shotgun_shell": {"name": "Shotgun Shell (x50)", "id": "Bullet_Shotgun", "price": 250, "category": "Ammo"},
    "rocket_ammo": {"name": "Rocket Ammo (x10)", "id": "RocketValue", "price": 500, "category": "Ammo"},

    # Accessories
    "attack_ring": {"name": "Ring of Attack +2", "id": "RingOfAttack_02", "price": 3000, "category": "Accessories"},
    "defense_ring": {"name": "Ring of Defense +2", "id": "RingOfDefense_02", "price": 3000, "category": "Accessories"},
    "hp_ring": {"name": "Life Ring +2", "id": "RingOfHP_02", "price": 3000, "category": "Accessories"},
    "heat_undershirt": {"name": "Heat-Resistant Undershirt +2", "id": "HeatResistantUndershirt_02", "price": 2000, "category": "Accessories"},
    "cold_undershirt": {"name": "Cold-Resistant Undershirt +2", "id": "ColdResistantUndershirt_02", "price": 2000, "category": "Accessories"},

    # Saddles
    "direhowl_saddle": {"name": "Direhowl Saddle", "id": "DirehowlSaddle", "price": 500, "category": "Saddles"},
    "galeclaw_saddle": {"name": "Galeclaw Saddle", "id": "GaleclawSaddle", "price": 600, "category": "Saddles"},
    "faleris_saddle": {"name": "Faleris Saddle", "id": "FalerisSaddle", "price": 2000, "category": "Saddles"},
    "shadowbeak_saddle": {"name": "Shadowbeak Saddle", "id": "ShadowbeakSaddle", "price": 4000, "category": "Saddles"},
    "frostallion_saddle": {"name": "Frostallion Saddle", "id": "FrostallionSaddle", "price": 5000, "category": "Saddles"},
    "jetragon_saddle": {"name": "Jetragon Saddle", "id": "JetragonSaddle", "price": 6000, "category": "Saddles"},

    # Food & Consumables
    "cake": {"name": "Cake", "id": "Cake", "price": 250, "category": "Food & Consumables"}
}

last_known_player_names = {}

# -------------------------------------------------------------
# 4. Database Init
# -------------------------------------------------------------
async def init_db():
    if not DATABASE_URL:
        logger.warning("⚠️ DATABASE_URL not set. Database features disabled.")
        return
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id BIGINT PRIMARY KEY,
                player_uid TEXT,
                balance INTEGER DEFAULT 0,
                last_daily TIMESTAMP
            )
        ''')
        await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_player_uid_idx ON users(player_uid)')
        await conn.close()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.critical(f"❌ Failed to connect to Database: {e}")

# -------------------------------------------------------------
# 5. Discord Bot Init
# -------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# -------------------------------------------------------------
# 6. REST API & RCON Helpers
# -------------------------------------------------------------
async def call_palworld_api(endpoint: str, method: str = "GET", payload: dict = None):
    if not REST_API_URL or not ADMIN_PASSWORD:
        return None, "REST_API_URL or ADMIN_PASSWORD missing."
    
    base_url = REST_API_URL.rstrip('/')
    if not base_url.endswith('/v1/api') and not base_url.endswith('/v1/pdapi'):
        if base_url.endswith('/v1'): base_url += '/api'
        else: base_url += '/v1/api'
            
    url = f"{base_url}{endpoint}"
    auth_header = {"Authorization": aiohttp.encode_basic_auth("admin", ADMIN_PASSWORD)}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=payload, headers=auth_header, timeout=10) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        return await response.json(), None
                    else:
                        text = await response.text()
                        return {"text": text}, None
                else:
                    return None, f"HTTP {response.status}"
    except Exception as e:
        return None, str(e)

async def give_item_via_paldefender(player_uid: str, item_id: str, amount: int):
    if not REST_API_URL or not ADMIN_PASSWORD:
        return False
    
    base_url = REST_API_URL.rstrip('/')
    if '/v1/api' in base_url:
        base_url = base_url.replace('/v1/api', '/v1/pdapi')
    elif not base_url.endswith('/v1/pdapi'):
        base_url += '/v1/pdapi'
        
    url = f"{base_url}/give/items/"
    payload = {"userid": str(player_uid), "item_id": item_id, "amount": int(amount)}
    auth_header = {"Authorization": aiohttp.encode_basic_auth("admin", ADMIN_PASSWORD)}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=auth_header, timeout=10) as response:
                return response.status in [200, 250]
    except Exception as e:
        logger.error(f"PalDefender give item exception: {e}")
        return False

async def send_rcon_command(command: str):
    if not RCON_HOST or not ADMIN_PASSWORD:
        return False, "RCON config missing"
    
    SERVERDATA_EXECCOMMAND = 2
    SERVERDATA_AUTH = 3
    
    try:
        reader, writer = await asyncio.open_connection(RCON_HOST, RCON_PORT)
        
        auth_payload = struct.pack('<ii', 1, SERVERDATA_AUTH) + ADMIN_PASSWORD.encode('utf-8') + b'\x00\x00'
        writer.write(struct.pack('<i', len(auth_payload)) + auth_payload)
        await writer.drain()
        await reader.read(4096)
        
        cmd_payload = struct.pack('<ii', 2, SERVERDATA_EXECCOMMAND) + command.encode('utf-8') + b'\x00\x00'
        writer.write(struct.pack('<i', len(cmd_payload)) + cmd_payload)
        await writer.drain()
        
        await reader.read(4096)
        writer.close()
        await writer.wait_closed()
        return True, "Success"
    except Exception as e:
        logger.error(f"RCON Exception: {e}")
        return False, str(e)

# -------------------------------------------------------------
# 7. In-Game Daily Reward System
# -------------------------------------------------------------
async def process_chat_daily_reward(player_uid: str, player_name: str):
    if not DATABASE_URL:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT discord_id, balance, last_daily FROM users WHERE player_uid = $1', str(player_uid))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        if row:
            last_daily = row['last_daily']
            if last_daily and now < last_daily + timedelta(hours=24):
                remaining = (last_daily + timedelta(hours=24)) - now
                hours = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                msg = f"@{player_name} Daily already claimed! Available in {hours}h {mins}m."
                if REST_API_URL and ADMIN_PASSWORD:
                    await call_palworld_api("/announce", method="POST", payload={"message": msg})
                return
            else:
                new_bal = (row['balance'] or 0) + DAILY_SHOP_POINTS
                await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE player_uid = $3', new_bal, now, str(player_uid))
        else:
            dummy_discord_id = abs(hash(str(player_uid))) % (10**15)
            new_bal = DAILY_SHOP_POINTS
            await conn.execute('''
                INSERT INTO users (discord_id, player_uid, balance, last_daily)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (player_uid) DO UPDATE SET last_daily = $4, balance = users.balance + $3
            ''', dummy_discord_id, str(player_uid), new_bal, now)

        for item in DAILY_ITEMS:
            await give_item_via_paldefender(player_uid, item["id"], item["amount"])

        success_msg = f"@{player_name} Claimed! +{DAILY_SHOP_POINTS} Points, 10 Cores, 500 Dog Coins, 50 Cakes, 50k Gold!"
        if REST_API_URL and ADMIN_PASSWORD:
            await call_palworld_api("/announce", method="POST", payload={"message": success_msg})
            
    except Exception as e:
        logger.error(f"Error processing in-game daily for {player_name}: {e}")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 8. IP-Stripping Chat Sanitizer
# -------------------------------------------------------------
def parse_and_clean_chat(line_str: str):
    try:
        # Extract quoted player name if present
        name_match = re.search(r"['\"]([^'\"]+)['\"]", line_str)
        if name_match:
            player_name = name_match.group(1)
        else:
            if "]: " in line_str:
                player_name = line_str.split("]: ")[0].split()[-1]
            else:
                player_name = "Player"

        # Strip any IPv4 address (e.g. 192.168.1.1 or 127.0.0.1:25575)
        player_name = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b', '', player_name)
        
        # Strip brackets, parentheses, and extra whitespace
        player_name = re.sub(r'[\(\)\[\]<>]', '', player_name)
        player_name = re.sub(r'\s+', ' ', player_name).strip()
        
        if not player_name or player_name.lower() in ("chat", "global", "info"):
            player_name = "Player"

        # Extract message text
        if "]: " in line_str:
            message = line_str.split("]: ")[-1].strip()
        elif ": " in line_str:
            message = line_str.split(": ", 1)[-1].strip()
        else:
            message = line_str.strip()

        return player_name, message
    except Exception:
        return "Player", line_str

# -------------------------------------------------------------
# 9. SFTP Chat Poller Loop (Single-Discovery & Lock-In)
# -------------------------------------------------------------
async def poll_paldefender_logs_loop():
    await bot.wait_until_ready()
    if not ENABLE_SFTP_POLLING:
        logger.info("🛡️ SFTP log polling is DISABLED.")
        return

    if not SFTP_HOST or not SFTP_USER:
        logger.warning("⚠️ SFTP Host or User missing. SFTP polling offline.")
        return

    logger.info(f"📂 Starting SFTP chat poller on {SFTP_HOST}:{SFTP_PORT}")
    
    transport = None
    sftp = None
    locked_log_path = None
    last_file_size = 0

    def connect_sftp():
        nonlocal transport, sftp
        if sftp:
            try: sftp.close()
            except: pass
        if transport:
            try: transport.close()
            except: pass
        
        t = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        t.set_keepalive(30)
        t.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        return t, paramiko.SFTPClient.from_transport(t)

    def discover_and_lock_log():
        nonlocal locked_log_path, last_file_size
        
        # 1. Check direct file path targets
        for candidate in POSSIBLE_LOG_PATHS:
            if not candidate: continue
            try:
                sftp.stat(candidate)
                locked_log_path = candidate
                logger.info(f"🔒 Locked onto active log file: {locked_log_path}")
                return
            except Exception:
                continue

        # 2. Check directory listing if explicit paths failed
        for log_dir in POSSIBLE_LOG_DIRS:
            try:
                files = sftp.listdir(log_dir)
                log_files = [f for f in files if f.endswith('.log')]
                if log_files:
                    log_files.sort()
                    latest = log_files[-1]
                    locked_log_path = f"{log_dir.rstrip('/')}/{latest}"
                    logger.info(f"🔒 Discovered and locked onto log file in {log_dir}: {locked_log_path}")
                    return
            except Exception:
                continue

    while not bot.is_closed():
        try:
            if sftp is None or transport is None or not transport.is_active():
                transport, sftp = await asyncio.to_thread(connect_sftp)
                locked_log_path = None # Reset lock on new SFTP session

            def read_locked_file():
                nonlocal locked_log_path, last_file_size
                
                # Perform discovery ONCE if not currently locked onto a file
                if not locked_log_path:
                    discover_and_lock_log()
                    if not locked_log_path:
                        return []

                try:
                    stat_info = sftp.stat(locked_log_path)
                except Exception as e:
                    logger.warning(f"⚠️ Lost handle on {locked_log_path} (Server Restart?): {e}")
                    locked_log_path = None
                    last_file_size = 0
                    return []

                size = stat_info.st_size
                if size < last_file_size:
                    # Log file truncated/reset on 24h server restart
                    last_file_size = 0

                new_lines = []
                if size > last_file_size:
                    with sftp.open(locked_log_path, 'r') as f:
                        f.seek(last_file_size)
                        content = f.read().decode('utf-8', errors='ignore')
                        if content:
                            new_lines = content.splitlines()
                    last_file_size = size
                return new_lines

            raw_lines = await asyncio.to_thread(read_locked_file)
            channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID) if DISCORD_CHAT_CHANNEL_ID else None

            if raw_lines:
                for line in raw_lines:
                    line_str = line.strip()
                    if not line_str: continue
                    
                    if channel and ("chat" in line_str.lower() or "global" in line_str.lower()):
                        p_name, p_msg = parse_and_clean_chat(line_str)
                        if p_msg:
                            await channel.send(f"💬 **{p_name}**: {p_msg}")

                    if re.search(r'\b!daily\b', line_str.lower()):
                        player_name, _ = parse_and_clean_chat(line_str)
                        if player_name:
                            target_pid = None
                            for pid, name in last_known_player_names.items():
                                if name.lower() == player_name.lower():
                                    target_pid = pid
                                    break
                            
                            if target_pid:
                                asyncio.create_task(process_chat_daily_reward(target_pid, player_name))

        except Exception as e:
            logger.error(f"❌ SFTP Loop Exception: {e}")
            sftp = None
            transport = None
            locked_log_path = None

        await asyncio.sleep(10)

# -------------------------------------------------------------
# 10. Player Tracker Loop
# -------------------------------------------------------------
async def poll_palworld_players_loop():
    global last_known_player_names
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        if REST_API_URL and ADMIN_PASSWORD:
            try:
                data, error = await call_palworld_api("/players", method="GET")
                if not error and data:
                    for p in data.get("players", []):
                        pid = p.get("playeruid") or p.get("userid") or p.get("name")
                        pname = p.get("name", "Unknown")
                        if pid:
                            last_known_player_names[str(pid)] = pname
            except Exception as e:
                logger.error(f"Player poll error: {e}")
                
        await asyncio.sleep(30)

# -------------------------------------------------------------
# 11. Discord Commands
# -------------------------------------------------------------
@bot.event
async def on_ready():
    await init_db()
    logger.info(f"✅ Sphere Bot ready as {bot.user}")
    if not getattr(bot, "tasks_started", False):
        bot.tasks_started = True
        bot.loop.create_task(poll_palworld_players_loop())
        bot.loop.create_task(poll_paldefender_logs_loop())

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.author.bot: return
    
    if DISCORD_CHAT_CHANNEL_ID != 0 and message.channel.id == DISCORD_CHAT_CHANNEL_ID:
        if not message.content.startswith(BOT_PREFIX):
            if REST_API_URL and ADMIN_PASSWORD:
                try:
                    clean_msg = message.clean_content.replace('"', '').replace('\n', ' ')
                    chat_text = f"[Discord: {message.author.display_name}] {clean_msg}"
                    res, err = await call_palworld_api("/announce", method="POST", payload={"message": chat_text})
                    if err:
                        logger.error(f"❌ REST API Announce Failed: {err}")
                    else:
                        logger.info(f"📡 Sent to In-Game: {chat_text}")
                except Exception as e:
                    logger.error(f"❌ Broadcast Exception: {e}")
            else:
                logger.warning("⚠️ Skipping broadcast: REST_API_URL or ADMIN_PASSWORD missing.")

@bot.command(name="shop")
async def shop(ctx, category: str = None):
    embed = discord.Embed(title="🛒 Palworld Community Shop", color=discord.Color.blue())
    categories = {}
    for key, info in SHOP_ITEMS.items():
        cat = info['category']
        if category and cat.lower() != category.lower():
            continue
        sell_price = int(info['price'] * 0.5)
        categories.setdefault(cat, []).append(f"`{key}`: **{info['name']}** (Buy: {info['price']} | Sell: {sell_price} pts)")
    
    for cat_name, items in categories.items():
        embed.add_field(name=cat_name, value="\n".join(items), inline=False)
    
    embed.set_footer(text="Use !buy <item> [amount] to purchase or !sell <item> [amount] to sell items!")
    await ctx.send(embed=embed)

@bot.command(name="buy")
async def buy(ctx, item_key: str, amount: int = 1):
    if not DATABASE_URL:
        await ctx.send("❌ Database URL not configured.")
        return
    
    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS:
        await ctx.send(f"❌ Unknown item `{item_key}`. Check `!shop` for items.")
        return
    
    if amount < 1: amount = 1
    item = SHOP_ITEMS[item_key]
    total_cost = item['price'] * amount

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        user_row = await conn.fetchrow('SELECT player_uid, balance FROM users WHERE discord_id = $1', ctx.author.id)
        if not user_row or not user_row['player_uid']:
            await ctx.send("❌ Your Discord account is not linked to an in-game Player UID.")
            return
        
        balance = user_row['balance'] or 0
        if balance < total_cost:
            await ctx.send(f"❌ Insufficient points! You have **{balance}** pts, need **{total_cost}** pts.")
            return
        
        player_uid = user_row['player_uid']
        new_balance = balance - total_cost
        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_balance, ctx.author.id)
        
        success = await give_item_via_paldefender(player_uid, item['id'], amount)
        if success:
            await ctx.send(f"✅ Purchased **{amount}x {item['name']}** for **{total_cost} points**!")
        else:
            await conn.execute('UPDATE users SET balance = balance + $1 WHERE discord_id = $2', total_cost, ctx.author.id)
            await ctx.send("❌ Delivery failed via PalDefender API. Points refunded.")

    except Exception as e:
        logger.error(f"Buy error: {e}")
        await ctx.send(f"❌ Error: {e}")
    finally:
        await conn.close()

@bot.command(name="sell")
async def sell(ctx, item_key: str, amount: int = 1):
    if not DATABASE_URL:
        await ctx.send("❌ Database URL not configured.")
        return
    
    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS:
        await ctx.send(f"❌ Unknown item `{item_key}`.")
        return
    
    if amount < 1: amount = 1
    item = SHOP_ITEMS[item_key]
    total_payout = int(item['price'] * 0.5) * amount

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        user_row = await conn.fetchrow('SELECT player_uid FROM users WHERE discord_id = $1', ctx.author.id)
        if not user_row or not user_row['player_uid']:
            await ctx.send("❌ Your Discord account is not linked to a Player UID.")
            return
        
        player_uid = user_row['player_uid']
        rcon_cmd = f"delitem {player_uid} {item['id']} {amount}"
        success, err = await send_rcon_command(rcon_cmd)
        
        if success:
            await conn.execute('''
                INSERT INTO users (discord_id, player_uid, balance) 
                VALUES ($1, $2, $3) 
                ON CONFLICT (discord_id) 
                DO UPDATE SET balance = users.balance + $3
            ''', ctx.author.id, player_uid, total_payout)
            
            await ctx.send(f"✅ Sold **{amount}x {item['name']}** for **{total_payout} points**!")
        else:
            await ctx.send(f"❌ RCON item deletion failed: {err}")

    except Exception as e:
        logger.error(f"Sell error: {e}")
        await ctx.send(f"❌ Error: {e}")
    finally:
        await conn.close()

@bot.command(name="resetdaily")
async def resetdaily(ctx):
    if not DATABASE_URL:
        await ctx.send("Database URL not configured.")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute('UPDATE users SET last_daily = NULL')
        await ctx.send("🔄 Daily cooldowns reset!")
    except Exception as e:
        await ctx.send(f"Error resetting daily: {e}")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 12. Web Server & Execution
# -------------------------------------------------------------
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Sphere Bot Active"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    
    async with bot: 
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
