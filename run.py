import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from aiohttp import web
import discord
from discord.ext import commands
import asyncpg
import aiohttp
from gamercon_async import GameRCON
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
# 2. Environment & Configuration
# -------------------------------------------------------------
DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or "").strip().strip("[]()").strip()
BOT_PREFIX = os.getenv("BOT_PREFIX", "!").strip()
REST_API_URL = (os.getenv("REST_API_URL") or os.getenv("PALWORLD_API_URL") or "").strip().strip("[]()").strip()
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or os.getenv("RCON_PASSWORD") or "").strip().strip("[]()").strip()
WEB_PORT = int(os.getenv("PORT", "10000"))
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip().strip("[]()").strip()

RCON_HOST = (os.getenv("RCON_HOST") or "127.0.0.1").strip().strip("[]()").strip()
_rcon_port_val = (os.getenv("RCON_PORT") or os.getenv("PALWORLD_RCON_PORT") or os.getenv("SERVER_RCON_PORT") or "25575").strip().strip("[]()").strip()
RCON_PORT = int(_rcon_port_val) if _rcon_port_val.isdigit() else 25575

_channel_val = (os.getenv("DISCORD_CHAT_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "0").strip().strip("[]()").strip()
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if _channel_val.isdigit() else 0

# SFTP Credentials for reading Pal Defender logs from the game server
SFTP_HOST = os.getenv("SFTP_HOST", RCON_HOST).strip().strip("[]()").strip()
_sftp_port_val = os.getenv("SFTP_PORT", "22").strip().strip("[]()").strip()
SFTP_PORT = int(_sftp_port_val) if _sftp_port_val.isdigit() else 22
SFTP_USER = os.getenv("SFTP_USER", "").strip().strip("[]()").strip()
SFTP_PASSWORD = os.getenv("SFTP_PASSWORD", ADMIN_PASSWORD).strip().strip("[]()").strip()
PALDEFENDER_LOG_PATH = os.getenv("PALDEFENDER_LOG_PATH", "/server-data/Pal/Binaries/Win64/PalDefender").strip()

# -------------------------------------------------------------
# 3. Daily Login Pack & Shop Items
# -------------------------------------------------------------
DAILY_PACK_SHOP_POINTS = 1000
DAILY_PACK_ITEMS = [
    {"rcon_id": "Cake", "quantity": 50},
    {"rcon_id": "GoldCoin", "quantity": 10000},
    {"rcon_id": "BossCivilizationCore", "quantity": 10},
    {"rcon_id": "PredatorCore", "quantity": 10},
    {"rcon_id": "DogCoin", "quantity": 250}
]

SHOP_ITEMS = {
    "pal_sphere": {"name": "Pal Sphere", "id": "PalSphere", "price": 25, "category": "Spheres"},
    "wood": {"name": "Wood", "id": "Wood", "price": 1, "category": "Ores & Materials"},
    "stone": {"name": "Stone", "id": "Stone", "price": 1, "category": "Ores & Materials"},
    "cake": {"name": "Cake", "id": "Cake", "price": 250, "category": "Food & Consumables"}
}

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
# 7. Pal Defender SFTP Log Poller
# -------------------------------------------------------------
async def poll_paldefender_logs_loop():
    await bot.wait_until_ready()
    if not SFTP_HOST or not SFTP_USER:
        logger.info("⚠️ SFTP credentials not provided. Pal Defender SFTP log polling disabled.")
        return

    logger.info(f"📂 Starting SFTP Pal Defender log watcher on {SFTP_HOST}:{SFTP_PORT} -> {PALDEFENDER_LOG_PATH}")
    last_file_name = None
    last_file_size = 0

    while not bot.is_closed():
        try:
            def check_logs():
                nonlocal last_file_name, last_file_size
                transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
                transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
                sftp = paramiko.SFTPClient.from_transport(transport)
                
                try:
                    files = sftp.listdir_attr(PALDEFENDER_LOG_PATH)
                    log_files = [f for f in files if f.filename.endswith(('.log', '.txt'))]
                    if not log_files:
                        sftp.close()
                        transport.close()
                        return []

                    log_files.sort(key=lambda x: x.st_mtime, reverse=True)
                    latest_file = log_files[0]
                    current_file_path = f"{PALDEFENDER_LOG_PATH.rstrip('/')}/{latest_file.filename}"

                    new_lines = []
                    if last_file_name != latest_file.filename:
                        logger.info(f"🔄 New Pal Defender log file detected: {latest_file.filename}")
                        last_file_name = latest_file.filename
                        last_file_size = latest_file.st_size
                    elif latest_file.st_size > last_file_size:
                        with sftp.open(current_file_path, 'r') as f:
                            f.seek(last_file_size)
                            content = f.read().decode('utf-8', errors='ignore')
                            if content:
                                new_lines = content.splitlines()
                        last_file_size = latest_file.st_size

                    sftp.close()
                    transport.close()
                    return new_lines
                except Exception as e:
                    sftp.close()
                    transport.close()
                    raise e

            new_lines = await asyncio.to_thread(check_logs)
            channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID) if DISCORD_CHAT_CHANNEL_ID else None

            if channel and new_lines:
                for line in new_lines:
                    line_str = line.strip()
                    if line_str:
                        await channel.send(f"💬 {line_str}")

        except Exception as e:
            logger.error(f"SFTP Log Polling Error: {e}")

        await asyncio.sleep(3)

# -------------------------------------------------------------
# 8. Automated Login Daily Reward & Player Tracking Loop
# -------------------------------------------------------------
known_online_players = set()
last_known_player_names = {}
is_players_initialized = False

async def process_login_daily(player_uid: str, player_name: str, account_id: str):
    if not DATABASE_URL or not RCON_HOST:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT discord_id, balance, last_daily FROM users WHERE player_uid = $1', str(player_uid))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        if row:
            last_daily = row['last_daily']
            if last_daily and now < last_daily + timedelta(hours=24):
                return
            
            new_bal = (row['balance'] or 0) + DAILY_PACK_SHOP_POINTS
            await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE player_uid = $3', new_bal, now, str(player_uid))
        else:
            dummy_discord_id = abs(hash(str(player_uid))) % (10**15)
            new_bal = DAILY_PACK_SHOP_POINTS
            await conn.execute('''
                INSERT INTO users (discord_id, player_uid, balance, last_daily)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (player_uid) DO UPDATE SET last_daily = $4, balance = users.balance + $3
            ''', dummy_discord_id, str(player_uid), new_bal, now)

        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            for item in DAILY_PACK_ITEMS:
                await rcon.send(f"give {account_id} {item['rcon_id']} {item['quantity']}")
            await rcon.send(f"Broadcast Welcome back {player_name}! Your daily login pack has been delivered.")
            
    except Exception as e:
        logger.error(f"Error processing login daily pack for {player_name}: {e}")
    finally:
        await conn.close()

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
                        account_id = p.get("userId") or p.get("userid") or p.get("accountId") or p.get("accountid") or "Unknown ID"
                        
                        if pid:
                            current_players_map[str(pid)] = {"name": pname, "account_id": account_id}
                            last_known_player_names[str(pid)] = pname

                    current_ids = set(current_players_map.keys())
                    channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID) if DISCORD_CHAT_CHANNEL_ID else None

                    if not is_players_initialized:
                        known_online_players = current_ids
                        is_players_initialized = True
                        for pid, pdata in current_players_map.items():
                            asyncio.create_task(process_login_daily(pid, pdata["name"], pdata["account_id"]))
                    else:
                        joined_ids = current_ids - known_online_players
                        left_ids = known_online_players - current_ids

                        for jid in joined_ids:
                            pdata = current_players_map.get(jid, {"name": "A player", "account_id": "Unknown ID"})
                            name = pdata["name"]
                            account_id = pdata["account_id"]
                            
                            logger.info(f"Player join detected: {name} (ID: {account_id})")
                            asyncio.create_task(process_login_daily(jid, name, account_id))

                            if channel:
                                embed = discord.Embed(
                                    title="🟢 Player Joined",
                                    description=f"**{name}** has joined the server!\n**Steam / Console ID:** `{account_id}`",
                                    color=discord.Color.green()
                                )
                                await channel.send(embed=embed)

                        for lid in left_ids:
                            name = last_known_player_names.get(lid, "A player")
                            if channel:
                                embed = discord.Embed(
                                    title="🔴 Player Left",
                                    description=f"**{name}** has left the server.",
                                    color=discord.Color.red()
                                )
                                await channel.send(embed=embed)

                        known_online_players = current_ids
            except Exception as e:
                logger.error(f"Player polling loop error: {e}")
                
        await asyncio.sleep(5)

# -------------------------------------------------------------
# 9. Discord Commands & Event Listeners
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
    
    if message.author.bot:
        return
        
    if DISCORD_CHAT_CHANNEL_ID != 0 and message.channel.id == DISCORD_CHAT_CHANNEL_ID:
        if not message.content.startswith(BOT_PREFIX):
            if REST_API_URL and ADMIN_PASSWORD:
                try:
                    clean_msg = message.clean_content.replace('"', '').replace('\n', ' ')
                    chat_text = f"[{message.author.display_name}] {clean_msg}"
                    
                    _, error = await call_palworld_api("/announce", method="POST", payload={"message": chat_text})
                    if error:
                        logger.error(f"Failed to relay message via REST API: {error}")
                except Exception as e:
                    logger.error(f"Failed to relay Discord message to game server: {e}")

@bot.command(name="shop")
async def shop(ctx):
    embed = discord.Embed(title="Palworld Shop", color=discord.Color.blue())
    for item_key, item_info in SHOP_ITEMS.items():
        embed.add_field(name=item_info['name'], value=f"Cost: {item_info['price']} points\nID: `{item_key}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="givedaily")
@commands.has_permissions(administrator=True)
async def givedaily(ctx, account_id: str):
    """Manually gives the daily reward pack to a specific Steam/Console ID."""
    try:
        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            for item in DAILY_PACK_ITEMS:
                await rcon.send(f"give {account_id} {item['rcon_id']} {item['quantity']}")
            
        await ctx.send(f"✅ Successfully sent the daily pack to Steam/Console ID: `{account_id}`")
    except Exception as e:
        await ctx.send(f"❌ Failed to send items: {e}")

# -------------------------------------------------------------
# 10. Web Server & Main Execution
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
