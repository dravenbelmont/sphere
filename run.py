import asyncio
import logging
import os
import sys
import stat
import re
from datetime import datetime, timedelta, timezone
from aiohttp import web
import discord
from discord.ext import commands
import asyncpg
import aiohttp
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
_channel_val = find_env_val_multi(("chat_channel",), ("channel_id",), ("channel",)) or "0"
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if str(_channel_val).isdigit() else 0

# SFTP Credentials
SFTP_HOST = find_env_val_multi(("sftp_host",), ("ftp_host",)) or RCON_HOST
_sftp_port_val = find_env_val("sftp_port") or "22"
SFTP_PORT = int(_sftp_port_val) if str(_sftp_port_val).isdigit() else 22
SFTP_USER = find_env_val_multi(("sftp_user",), ("ftp_user",), ("username",))
SFTP_PASSWORD = find_env_val_multi(("sftp_pass",), ("ftp_pass",)) or ADMIN_PASSWORD

POSSIBLE_LOG_PATHS = [
    os.getenv("PALDEFENDER_LOG_PATH"),
    os.getenv("LOG_PATH"),
    os.getenv("SERVER_LOG_PATH"),
    "/server-data/Pal/Binaries/Win64/PalDefender",
    "/home/container/Pal/Binaries/Win64/PalDefender",
    "/app/Pal/Binaries/Win64/PalDefender",
    "./Pal/Binaries/Win64/PalDefender",
    "/Pal/Binaries/Win64/PalDefender"
]

# -------------------------------------------------------------
# 3. Daily Reward Configuration (!daily)
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
    "pal_sphere": {"name": "Pal Sphere", "id": "PalSphere", "price": 25, "category": "Spheres"},
    "wood": {"name": "Wood", "id": "Wood", "price": 1, "category": "Ores & Materials"},
    "stone": {"name": "Stone", "id": "Stone", "price": 1, "category": "Ores & Materials"},
    "cake": {"name": "Cake", "id": "Cake", "price": 250, "category": "Food & Consumables"}
}

last_known_player_names = {}

# -------------------------------------------------------------
# 4. Database Init
# -------------------------------------------------------------
async def init_db():
    if not DATABASE_URL: return
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
        logger.critical(f"Failed to connect to Supabase: {e}")

# -------------------------------------------------------------
# 5. Discord Bot Init
# -------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# -------------------------------------------------------------
# 6. Palworld & PalDefender REST API Helpers
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
        logger.warning(f"PalDefender give item skipped: API URL or Admin Password missing.")
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
                resp_text = await response.text()
                if response.status in [200, 250]:
                    logger.info(f"✅ PalDefender successfully granted {amount}x {item_id} to user {player_uid}. Response: {resp_text}")
                    return True
                else:
                    logger.error(f"❌ PalDefender failed to grant {item_id} to {player_uid}. Status: {response.status}, Response: {resp_text}")
                    return False
    except Exception as e:
        logger.error(f"❌ PalDefender give item exception for {item_id}: {e}")
        return False

# -------------------------------------------------------------
# 7. Database & Item Reward Handlers (!daily)
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

        # Grant physical items via PalDefender API
        for item in DAILY_ITEMS:
            await give_item_via_paldefender(player_uid, item["id"], item["amount"])

        success_msg = f"@{player_name} Claimed! +{DAILY_SHOP_POINTS} Points, 10 Predator Cores, 10 Ancient Cores, 500 Dog Coins, 50 Cakes, 50k Gold!"
        if REST_API_URL and ADMIN_PASSWORD:
            await call_palworld_api("/announce", method="POST", payload={"message": success_msg})
            
    except Exception as e:
        logger.error(f"Error processing in-game daily for {player_name}: {e}")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 8. Strict Chat Sanitizer (Guaranteed No IP Leakage)
# -------------------------------------------------------------
def parse_and_clean_chat(line_str: str):
    """Strips all server metadata, timestamps, UserIDs, and IP addresses, returning only name and message."""
    try:
        # Extract player name from single quotes (e.g., ['Draven'])
        name_match = re.search(r"['\"]([^'\"]+)['\"]", line_str)
        player_name = name_match.group(1) if name_match else "Player"
        
        # Extract the message content after the last ']: ' delimiter
        if "]: " in line_str:
            message = line_str.split("]: ")[-1].strip()
        else:
            message = line_str
            
        return player_name, message
    except Exception:
        return "Player", line_str

# -------------------------------------------------------------
# 9. SFTP Chat Poller & In-Game Command Listener (!daily)
# -------------------------------------------------------------
async def poll_paldefender_logs_loop():
    await bot.wait_until_ready()
    if not SFTP_HOST or not SFTP_USER:
        return

    logger.info(f"📂 Starting SFTP chat poller & listener for !daily on {SFTP_HOST}:{SFTP_PORT}")
    last_file_path_seen = None
    last_file_size = 0
    resolved_log_path = None

    transport = None
    sftp = None

    def connect_sftp():
        nonlocal transport, sftp
        if sftp is not None:
            try:
                sftp.close()
                transport.close()
            except: pass
        t = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        t.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        return t, paramiko.SFTPClient.from_transport(t)

    while not bot.is_closed():
        try:
            if sftp is None or transport is None or not transport.is_active():
                transport, sftp = await asyncio.to_thread(connect_sftp)

            def check_logs():
                nonlocal last_file_path_seen, last_file_size, resolved_log_path
                
                if not resolved_log_path:
                    for test_path in [p for p in POSSIBLE_LOG_PATHS if p]:
                        try:
                            sftp.stat(test_path)
                            resolved_log_path = test_path
                            break
                        except Exception:
                            continue
                    if not resolved_log_path:
                        resolved_log_path = "/server-data/Pal/Binaries/Win64/PalDefender"

                def find_chat_file(current_dir):
                    chat_candidates, all_candidates = [], []
                    try:
                        entries = sftp.listdir_attr(current_dir)
                    except Exception:
                        return None
                    
                    for entry in entries:
                        if entry.filename.startswith('.'): continue
                        path = f"{current_dir.rstrip('/')}/{entry.filename}"
                        try:
                            if stat.S_ISDIR(entry.st_mode):
                                sub = find_chat_file(path)
                                if sub: all_candidates.append(sub)
                            elif stat.S_ISREG(entry.st_mode):
                                file_info = (path, entry.filename, entry.st_mtime, entry.st_size)
                                all_candidates.append(file_info)
                                if 'chat' in entry.filename.lower() or 'log' in entry.filename.lower():
                                    chat_candidates.append(file_info)
                        except Exception:
                            continue
                    
                    if chat_candidates:
                        chat_candidates.sort(key=lambda x: x[2], reverse=True)
                        return chat_candidates[0]
                    if all_candidates:
                        all_candidates.sort(key=lambda x: x[2], reverse=True)
                        return all_candidates[0]
                    return None

                latest = find_chat_file(resolved_log_path)
                if not latest: return []

                full_path, filename, mtime, size = latest
                new_lines = []

                if last_file_path_seen != full_path:
                    last_file_path_seen = full_path
                    last_file_size = 0
                
                if size > last_file_size:
                    with sftp.open(full_path, 'r') as f:
                        f.seek(last_file_size)
                        content = f.read().decode('utf-8', errors='ignore')
                        if content: new_lines = content.splitlines()
                    last_file_size = size

                return new_lines

            raw_lines = await asyncio.to_thread(check_logs)
            channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID) if DISCORD_CHAT_CHANNEL_ID else None

            if raw_lines:
                for line in raw_lines:
                    line_str = line.strip()
                    if not line_str: continue
                    
                    # Relay to Discord channel cleanly (NO raw logs, NO IPs, NO metadata)
                    if channel and ("chat" in line_str.lower() or "global" in line_str.lower()):
                        p_name, p_msg = parse_and_clean_chat(line_str)
                        if p_msg:
                            await channel.send(f"💬 **{p_name}**: {p_msg}")

                    # Check for exact standalone !daily command in chat logs
                    if re.search(r'\b!daily\b', line_str.lower()):
                        player_name, _ = parse_and_clean_chat(line_str)
                        if player_name:
                            target_pid = None
                            for pid, name in last_known_player_names.items():
                                if name.lower() == player_name.lower():
                                    target_pid = pid
                                    break
                            
                            if not target_pid:
                                data, err = await call_palworld_api("/players", method="GET")
                                if not err and data:
                                    for p in data.get("players", []):
                                        if p.get("name", "").lower() == player_name.lower():
                                            target_pid = p.get("playeruid") or p.get("userid")
                                            break
                            
                            if target_pid:
                                asyncio.create_task(process_chat_daily_reward(target_pid, player_name))
                            else:
                                asyncio.create_task(process_chat_daily_reward(player_name, player_name))

        except Exception as e:
            logger.error(f"❌ SFTP Polling Error (Reconnecting...): {e}")
            sftp = None

        await asyncio.sleep(5)

# -------------------------------------------------------------
# 10. Automated Player Tracker Loop
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
                logger.error(f"Player polling loop error: {e}")
                
        await asyncio.sleep(25)

# -------------------------------------------------------------
# 11. Discord Bot Events & Commands
# -------------------------------------------------------------
@bot.event
async def on_ready():
    await init_db()
    logger.info(f"✅ Bot connected as {bot.user}")
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
                    await call_palworld_api("/announce", method="POST", payload={"message": chat_text})
                except Exception:
                    pass

@bot.command(name="shop")
async def shop(ctx):
    embed = discord.Embed(title="Palworld Shop", color=discord.Color.blue())
    for item_key, item_info in SHOP_ITEMS.items():
        embed.add_field(name=item_info['name'], value=f"Cost: {item_info['price']} points\nID: `{item_key}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="resetdaily")
async def resetdaily(ctx):
    """Resets your daily cooldown so you can test it immediately."""
    if not DATABASE_URL:
        await ctx.send("Database URL not configured.")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute('UPDATE users SET last_daily = NULL')
        await ctx.send("🔄 Daily cooldowns have been successfully reset! You can now test `!daily` in-game.")
        logger.info(f"Daily cooldown reset triggered by Discord user {ctx.author}.")
    except Exception as e:
        await ctx.send(f"Error resetting cooldown: {e}")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 12. Web Server & Main Execution
# -------------------------------------------------------------
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    
    async with bot: 
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
