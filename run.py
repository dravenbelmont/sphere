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
logger = logging.getLogger("PalBot")

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
# 3. Daily Reward & Shop Configurations
# -------------------------------------------------------------
DAILY_PACK_SHOP_POINTS = 1000
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
# 6. Palworld REST API Helpers
# -------------------------------------------------------------
async def call_palworld_api(endpoint: str, method: str = "GET", payload: dict = None):
    if not REST_API_URL or not ADMIN_PASSWORD:
        return None, "REST_API_URL or ADMIN_PASSWORD missing."
    
    base_url = REST_API_URL.rstrip('/')
    if not base_url.endswith('/v1/api'):
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

# -------------------------------------------------------------
# 7. Database Reward Handlers
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
            else:
                new_bal = (row['balance'] or 0) + DAILY_PACK_SHOP_POINTS
                await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE player_uid = $3', new_bal, now, str(player_uid))
                msg = f"@{player_name} Success! +{DAILY_PACK_SHOP_POINTS} shop points added. Balance: {new_bal}"
        else:
            dummy_discord_id = abs(hash(str(player_uid))) % (10**15)
            new_bal = DAILY_PACK_SHOP_POINTS
            await conn.execute('''
                INSERT INTO users (discord_id, player_uid, balance, last_daily)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (player_uid) DO UPDATE SET last_daily = $4, balance = users.balance + $3
            ''', dummy_discord_id, str(player_uid), new_bal, now)
            msg = f"@{player_name} Registered! +{DAILY_PACK_SHOP_POINTS} shop points added."

        if REST_API_URL and ADMIN_PASSWORD:
            await call_palworld_api("/announce", method="POST", payload={"message": msg})
            
    except Exception as e:
        logger.error(f"Error processing in-game daily for {player_name}: {e}")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 8. SFTP Chat Poller & In-Game Command Listener
# -------------------------------------------------------------
async def poll_paldefender_logs_loop():
    await bot.wait_until_ready()
    if not SFTP_HOST or not SFTP_USER:
        return

    logger.info(f"📂 Starting SFTP chat poller & in-game command listener on {SFTP_HOST}:{SFTP_PORT}")
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
                    line_lower = line_str.lower()
                    if "chat" not in line_lower and "global" not in line_lower: continue

                    player_name, message_text = None, None
                    chat_match = re.search(r"\[Chat::[^\]]+\]\s*'([^']+)'", line_str, re.IGNORECASE)
                    if chat_match:
                        player_name = chat_match.group(1).strip()
                        msg_match = re.search(r"\]:\s*(.*)$", line_str)
                        if msg_match: message_text = msg_match.group(1).strip()

                    if not player_name or not message_text:
                        parts = line_str.split(':')
                        if len(parts) >= 3:
                            quote_match = re.search(r"['\"]([^'\"]+)['\"]", line_str)
                            if quote_match:
                                player_name = quote_match.group(1).strip()
                                message_text = parts[-1].strip()

                    if player_name and message_text:
                        if channel:
                            await channel.send(f"💬 **{player_name}**: {message_text}")

                        # In-Game Chat Command Handler: !daily
                        if message_text.lower().startswith("!daily"):
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
                                if REST_API_URL and ADMIN_PASSWORD:
                                    await call_palworld_api("/announce", method="POST", payload={"message": f"@{player_name} You must be active on the server to claim daily rewards!"})

        except Exception as e:
            logger.error(f"❌ SFTP Polling Error (Reconnecting...): {e}")
            sftp = None

        await asyncio.sleep(10)

# -------------------------------------------------------------
# 9. Automated Player Tracker Loop
# -------------------------------------------------------------
known_online_players = set()
is_players_initialized = False

async def poll_palworld_players_loop():
    global known_online_players, last_known_player_names, is_players_initialized
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        if REST_API_URL and ADMIN_PASSWORD:
            try:
                data, error = await call_palworld_api("/players", method="GET")
                if not error and data:
                    players = data.get("players", [])
                    current_players_map = {}
                    
                    for p in players:
                        pid = p.get("playeruid") or p.get("userid") or p.get("name")
                        pname = p.get("name", "Unknown")
                        if pid:
                            current_players_map[str(pid)] = pname
                            last_known_player_names[str(pid)] = pname

                    current_ids = set(current_players_map.keys())
                    channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID) if DISCORD_CHAT_CHANNEL_ID else None

                    if not is_players_initialized:
                        known_online_players = current_ids
                        is_players_initialized = True
                    else:
                        joined_ids = current_ids - known_online_players
                        left_ids = known_online_players - current_ids

                        for jid in joined_ids:
                            name = current_players_map.get(jid, "A player")
                            if channel:
                                embed = discord.Embed(title="🟢 Player Joined", description=f"**{name}** has joined the server!", color=discord.Color.green())
                                await channel.send(embed=embed)

                        for lid in left_ids:
                            name = last_known_player_names.get(lid, "A player")
                            if channel:
                                embed = discord.Embed(title="🔴 Player Left", description=f"**{name}** has left the server.", color=discord.Color.red())
                                await channel.send(embed=embed)

                        known_online_players = current_ids
            except Exception as e:
                logger.error(f"Player polling loop error: {e}")
                
        await asyncio.sleep(25)

# -------------------------------------------------------------
# 10. Discord Bot Events & Startup
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
                    chat_text = f"[{message.author.display_name}] {clean_msg}"
                    await call_palworld_api("/announce", method="POST", payload={"message": chat_text})
                except Exception:
                    pass

@bot.command(name="shop")
async def shop(ctx):
    embed = discord.Embed(title="Palworld Shop", color=discord.Color.blue())
    for item_key, item_info in SHOP_ITEMS.items():
        embed.add_field(name=item_info['name'], value=f"Cost: {item_info['price']} points\nID: `{item_key}`", inline=False)
    await ctx.send(embed=embed)

# -------------------------------------------------------------
# 11. Web Server & Main Execution
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
