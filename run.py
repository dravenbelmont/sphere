import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from aiohttp import web
import discord
from discord.ext import commands
import paramiko
import asyncpg
import aiohttp

# -------------------------------------------------------------
# Logging Setup
# -------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("PalBot")

# -------------------------------------------------------------
# 1. Environment & Configuration (Auto-sanitized against brackets)
# -------------------------------------------------------------
DISCORD_TOKEN = (
    os.getenv("DISCORD_TOKEN")
    or os.getenv("BOT_TOKEN")
    or ""
).strip().strip("[]()").strip()

BOT_PREFIX = os.getenv("BOT_PREFIX", "!").strip()

# REST API Configuration
REST_API_URL = (
    os.getenv("REST_API_URL")
    or ""
).strip().strip("[]()").strip()

ADMIN_PASSWORD = (
    os.getenv("ADMIN_PASSWORD")
    or os.getenv("RCON_PASSWORD")
    or ""
).strip().strip("[]()").strip()

WEB_PORT = int(os.getenv("PORT", "10000"))

# Supabase Database URL
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("SUPABASE_URL")
    or ""
).strip().strip("[]()").strip()

# SFTP Settings
SFTP_HOST = (
    os.getenv("SFTP_HOST")
    or ""
).strip().strip("[]()").strip()

SFTP_PORT = int(os.getenv("SFTP_PORT", "22").strip())

SFTP_USER = (
    os.getenv("SFTP_USER")
    or ""
).strip().strip("[]()").strip()

SFTP_PASSWORD = (
    os.getenv("SFTP_PASSWORD")
    or ""
).strip().strip("[]()").strip()

SFTP_LOG_PATH = (
    os.getenv("SFTP_LOG_PATH")
    or "/Pal/Saved/SaveGames/PalDefender/Chat.log"
).strip().strip("[]()").strip()

_channel_val = (
    os.getenv("DISCORD_CHAT_CHANNEL_ID")
    or os.getenv("CHANNEL_ID")
    or "0"
).strip().strip("[]()").strip()
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if _channel_val.isdigit() else 0

# -------------------------------------------------------------
# 2. Economy & Shop Setup (Supabase / PostgreSQL)
# -------------------------------------------------------------
DAILY_REWARD_AMOUNT = 100

SHOP_ITEMS = {
    "sphere": {"id": "PalSphere", "price": 10, "name": "Pal Sphere"},
    "megasphere": {"id": "PalSphere_Mega", "price": 30, "name": "Mega Sphere"},
    "wood": {"id": "Wood", "price": 1, "name": "Wood"},
    "stone": {"id": "Stone", "price": 1, "name": "Stone"},
    "gold": {"id": "Money", "price": 5, "name": "Gold Coins"}
}

async def init_db():
    """Initializes the PostgreSQL table in Supabase."""
    if not DATABASE_URL:
        logger.critical("DATABASE_URL environment variable is missing!")
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
        await conn.close()
        logger.info("✅ Connected to Supabase and verified database table.")
    except Exception as e:
        logger.critical(f"Failed to connect to Supabase: {e}")

# -------------------------------------------------------------
# 3. Discord Bot Init
# -------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# -------------------------------------------------------------
# 4. Palworld REST API Helpers (Auto-fixes base path with /v1/api)
# -------------------------------------------------------------
async def call_palworld_api(endpoint: str, method: str = "GET", payload: dict = None):
    """Communicates with Palworld's native REST API via HTTP Basic Auth."""
    if not REST_API_URL or not ADMIN_PASSWORD:
        return None, "REST_API_URL or ADMIN_PASSWORD missing."
    
    base_url = REST_API_URL.rstrip('/')
    if not base_url.endswith('/v1/api'):
        if base_url.endswith('/v1'):
            base_url += '/api'
        else:
            base_url += '/v1/api'
            
    url = f"{base_url}{endpoint}"
    auth = aiohttp.BasicAuth("admin", ADMIN_PASSWORD)
    
    try:
        async with aiohttp.ClientSession(auth=auth) as session:
            if method == "GET":
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data, None
                    else:
                        text = await response.text()
                        return None, f"HTTP {response.status}: {text}"
            elif method == "POST":
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data, None
                    else:
                        text = await response.text()
                        return None, f"HTTP {response.status}: {text}"
    except Exception as e:
        logger.error(f"REST API Error: {e}")
        return None, str(e)

# -------------------------------------------------------------
# 5. SFTP Chat Listener
# -------------------------------------------------------------
def fetch_new_chat_lines(last_offset: int) -> tuple[list[str], int]:
    if not SFTP_USER or not SFTP_PASSWORD or not SFTP_HOST:
        return [], last_offset
    transport = sftp = None
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        stat = sftp.stat(SFTP_LOG_PATH)
        file_size = stat.st_size
        if last_offset == -1 or file_size < last_offset:
            return [], file_size
        if file_size == last_offset:
            return [], last_offset

        with sftp.open(SFTP_LOG_PATH, "r") as f:
            f.seek(last_offset)
            new_data = f.read().decode("utf-8", errors="replace")
            new_offset = f.tell()

        lines = [line.strip() for line in new_data.splitlines() if line.strip()]
        return lines, new_offset
    except Exception as e:
        return [], last_offset
    finally:
        if sftp: sftp.close()
        if transport: transport.close()

async def sftp_chat_listener_loop():
    await bot.wait_until_ready()
    if not DISCORD_CHAT_CHANNEL_ID or not SFTP_USER:
        return

    channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID)
    if not channel: return

    logger.info(f"📡 SFTP Listener Active: {SFTP_LOG_PATH}")
    last_offset = -1
    while not bot.is_closed():
        new_lines, new_offset = await asyncio.to_thread(fetch_new_chat_lines, last_offset)
        last_offset = new_offset
        for line in new_lines:
            if line: await channel.send(f"💬 `{line}`")
        await asyncio.sleep(3)

# -------------------------------------------------------------
# 6. Discord Events & Standard Commands
# -------------------------------------------------------------
@bot.event
async def on_ready():
    await init_db()
    logger.info(f"✅ Bot connected as {bot.user}")
    if not getattr(bot, "sftp_task_started", False):
        bot.sftp_task_started = True
        bot.loop.create_task(sftp_chat_listener_loop())

@bot.command(name="players")
async def list_players(ctx):
    data, error = await call_palworld_api("/players", method="GET")
    if error:
        await ctx.send(
            f"❌ **REST API Connection Error:**\n`{error}`\n\n"
            "*(Please check your `REST_API_URL` and `ADMIN_PASSWORD` in Render environment settings.)*"
        )
        return
    if not data or "players" not in data:
        await ctx.send("🎮 Server responded, but player data was empty.")
        return

    players = data["players"]
    if not players:
        await ctx.send("🎮 **Server Status:** 0 players currently online.")
        return

    player_list = "\n".join([f"• **{p.get('name', 'Unknown')}** (Level {p.get('level', '?')}, UID: `{p.get('playeruid', p.get('userId', 'N/A'))}`)" for p in players])
    embed = discord.Embed(title=f"Online Players ({len(players)})", description=player_list, color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="announce")
@commands.has_permissions(administrator=True)
async def announce_ingame(ctx, *, message: str):
    payload = {"message": f"[Discord] {message}"}
    data, error = await call_palworld_api("/announce", method="POST", payload=payload)
    if error:
        await ctx.send(f"❌ Failed to send broadcast: `{error}`")
    else:
        await ctx.send(f"✅ Broadcast sent: **{message}**")

# -------------------------------------------------------------
# 7. Economy & Shop Commands (Supabase Backend)
# -------------------------------------------------------------
@bot.command(name="register")
async def register(ctx, player_uid: str):
    """Links your Discord account to your Palworld UID."""
    if not DATABASE_URL:
        await ctx.send("❌ Database is not configured.")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute('''
            INSERT INTO users (discord_id, player_uid) 
            VALUES ($1, $2) 
            ON CONFLICT (discord_id) DO UPDATE SET player_uid = $2
        ''', ctx.author.id, player_uid)
        await ctx.send(f"✅ Registered! Your Discord is now linked to Palworld UID: `{player_uid}`")
    except Exception as e:
        logger.error(f"Database error on register: {e}")
        await ctx.send("❌ An error occurred while registering.")
    finally:
        await conn.close()

@bot.command(name="daily")
async def daily(ctx):
    """Claim your daily coins."""
    if not DATABASE_URL:
        await ctx.send("❌ Database is not configured.")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT balance, last_daily FROM users WHERE discord_id = $1', ctx.author.id)
            
        if not row:
            await ctx.send("❌ You need to `!register <PlayerUID>` first!")
            return
            
        balance, last_daily = row
        now = datetime.utcnow()
        
        if last_daily:
            if now < last_daily + timedelta(days=1):
                wait_time = (last_daily + timedelta(days=1)) - now
                hours, remainder = divmod(wait_time.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                await ctx.send(f"⏳ You must wait {hours}h {minutes}m before claiming your next daily.")
                return

        new_balance = balance + DAILY_REWARD_AMOUNT
        await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE discord_id = $3', 
                         new_balance, now, ctx.author.id)
        await ctx.send(f"🎁 You claimed your daily reward of **{DAILY_REWARD_AMOUNT} coins**! New balance: **{new_balance}**.")
    except Exception as e:
        logger.error(f"Database error on daily: {e}")
        await ctx.send("❌ An error occurred processing your daily reward.")
    finally:
        await conn.close()

@bot.command(name="balance")
async def balance(ctx):
    """Check your coin balance."""
    if not DATABASE_URL:
        await ctx.send("❌ Database is not configured.")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT balance FROM users WHERE discord_id = $1', ctx.author.id)
        if row:
            await ctx.send(f"💰 You have **{row['balance']} coins**.")
        else:
            await ctx.send("❌ You are not registered. Use `!register <PlayerUID>`.")
    except Exception as e:
        logger.error(f"Database error on balance: {e}")
        await ctx.send("❌ An error occurred fetching your balance.")
    finally:
        await conn.close()

@bot.command(name="shop")
async def shop(ctx):
    """Displays items available for purchase."""
    embed = discord.Embed(title="🛒 Chillet & Chill Shop", color=discord.Color.gold())
    for key, item in SHOP_ITEMS.items():
        embed.add_field(name=f"{item['name']} (`{key}`)", value=f"Price: **{item['price']} coins**", inline=False)
    embed.set_footer(text="Use !buy <item> <quantity> to purchase!")
    await ctx.send(embed=embed)

@bot.command(name="buy")
async def buy(ctx, item_key: str, quantity: int = 1):
    """Buy items from the shop."""
    if not DATABASE_URL:
        await ctx.send("❌ Database is not configured.")
        return

    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS:
        await ctx.send("❌ Item not found. Check `!shop` for available items.")
        return
        
    if quantity <= 0:
        await ctx.send("❌ Quantity must be at least 1.")
        return

    item = SHOP_ITEMS[item_key]
    total_cost = item['price'] * quantity

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT player_uid, balance FROM users WHERE discord_id = $1', ctx.author.id)
            
        if not row:
            await ctx.send("❌ You are not registered. Use `!register <PlayerUID>`.")
            return
            
        player_uid = row['player_uid']
        current_balance = row['balance']

        if current_balance < total_cost:
            await ctx.send(f"❌ You don't have enough coins! This costs **{total_cost}**, but you only have **{current_balance}**.")
            return

        new_balance = current_balance - total_cost
        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_balance, ctx.author.id)
        
        await ctx.send(f"✅ Successfully purchased {quantity}x **{item['name']}**! Deducted **{total_cost} coins**. Remaining balance: **{new_balance}**.")
    except Exception as e:
        logger.error(f"Database error on buy: {e}")
        await ctx.send("❌ An error occurred processing your purchase.")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 8. Web Server & Main Loop
# -------------------------------------------------------------
async def health_check_handler(request):
    return web.Response(text="OK - Palworld Bot is active")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()

async def main():
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN missing!")
        sys.exit(1)
    await start_web_server()
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually stopped.")
