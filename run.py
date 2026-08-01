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
from gamercon_async import GameRCON  # RCON library for injecting items

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
# 1. Environment & Configuration
# -------------------------------------------------------------
DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or "").strip().strip("[]()").strip()
BOT_PREFIX = os.getenv("BOT_PREFIX", "!").strip()
REST_API_URL = (os.getenv("REST_API_URL") or "").strip().strip("[]()").strip()
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or os.getenv("RCON_PASSWORD") or "").strip().strip("[]()").strip()
WEB_PORT = int(os.getenv("PORT", "10000"))
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip().strip("[]()").strip()

SFTP_HOST = (os.getenv("SFTP_HOST") or "").strip().strip("[]()").strip()
SFTP_PORT = int(os.getenv("SFTP_PORT", "22").strip())
SFTP_USER = (os.getenv("SFTP_USER") or "").strip().strip("[]()").strip()
SFTP_PASSWORD = (os.getenv("SFTP_PASSWORD") or "").strip().strip("[]()").strip()
SFTP_LOG_PATH = (os.getenv("SFTP_LOG_PATH") or "/Pal/Saved/SaveGames/PalDefender/Chat.log").strip().strip("[]()").strip()

_channel_val = (os.getenv("DISCORD_CHAT_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "0").strip().strip("[]()").strip()
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if _channel_val.isdigit() else 0

# RCON specific for giving items
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))

# -------------------------------------------------------------
# 2. Economy & Balanced Vanilla Shop
# -------------------------------------------------------------
DAILY_REWARD_AMOUNT = 100

# Perfectly balanced around a 100 coin/day economy. No Dev items.
SHOP_ITEMS = {
    "wood": {"id": "Wood", "price": 5, "name": "Wood (x50)", "amount": 50},
    "stone": {"id": "Stone", "price": 5, "name": "Stone (x50)", "amount": 50},
    "paldium": {"id": "Pal_crystal", "price": 10, "name": "Paldium Fragment (x20)", "amount": 20},
    "ingot": {"id": "CopperIngot", "price": 25, "name": "Ingot (x20)", "amount": 20},
    "sphere": {"id": "PalSphere", "price": 5, "name": "Pal Sphere (x5)", "amount": 5},
    "megasphere": {"id": "PalSphere_Mega", "price": 15, "name": "Mega Sphere (x5)", "amount": 5},
    "gigasphere": {"id": "PalSphere_Giga", "price": 30, "name": "Giga Sphere (x5)", "amount": 5},
    "cake": {"id": "Cake", "price": 50, "name": "Cake (x1)", "amount": 1},
    "gold": {"id": "Money", "price": 20, "name": "Gold Coins (x500)", "amount": 500}
}

async def init_db():
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
# 4. Palworld REST API Helpers (For Status/Players)
# -------------------------------------------------------------
async def call_palworld_api(endpoint: str, method: str = "GET", payload: dict = None):
    if not REST_API_URL or not ADMIN_PASSWORD:
        return None, "REST_API_URL or ADMIN_PASSWORD missing."
    
    base_url = REST_API_URL.rstrip('/')
    if not base_url.endswith('/v1/api'):
        if base_url.endswith('/v1'): base_url += '/api'
        else: base_url += '/v1/api'
            
    url = f"{base_url}{endpoint}"
    auth = aiohttp.BasicAuth("admin", ADMIN_PASSWORD)
    
    try:
        async with aiohttp.ClientSession(auth=auth) as session:
            if method == "GET":
                async with session.get(url, timeout=10) as response:
                    if response.status == 200: return await response.json(), None
                    else: return None, f"HTTP {response.status}: {await response.text()}"
            elif method == "POST":
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200: return await response.json(), None
                    else: return None, f"HTTP {response.status}: {await response.text()}"
    except Exception as e:
        return None, str(e)

# -------------------------------------------------------------
# 5. SFTP Chat Listener
# -------------------------------------------------------------
def fetch_new_chat_lines(last_offset: int) -> tuple[list[str], int]:
    if not SFTP_USER or not SFTP_PASSWORD or not SFTP_HOST: return [], last_offset
    transport = sftp = None
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        stat = sftp.stat(SFTP_LOG_PATH)
        file_size = stat.st_size
        if last_offset == -1 or file_size < last_offset: return [], file_size
        if file_size == last_offset: return [], last_offset

        with sftp.open(SFTP_LOG_PATH, "r") as f:
            f.seek(last_offset)
            new_data = f.read().decode("utf-8", errors="replace")
            new_offset = f.tell()

        lines = [line.strip() for line in new_data.splitlines() if line.strip()]
        return lines, new_offset
    except: return [], last_offset
    finally:
        if sftp: sftp.close()
        if transport: transport.close()

async def sftp_chat_listener_loop():
    await bot.wait_until_ready()
    if not DISCORD_CHAT_CHANNEL_ID or not SFTP_USER: return
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
        await ctx.send(f"❌ **REST API Error:**\n`{error}`")
        return
    players = data.get("players", [])
    if not players:
        await ctx.send("🎮 **Server Status:** 0 players currently online.")
        return

    player_list = "\n".join([f"• **{p.get('name', 'Unknown')}** (Level {p.get('level', '?')}, UID: `{p.get('playeruid', p.get('userId', 'N/A'))}`)" for p in players])
    embed = discord.Embed(title=f"Online Players ({len(players)})", description=player_list, color=discord.Color.blue())
    await ctx.send(embed=embed)

# -------------------------------------------------------------
# 7. Economy & Shop Commands
# -------------------------------------------------------------
@bot.command(name="register")
async def register(ctx, player_uid: str):
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute('''
            INSERT INTO users (discord_id, player_uid) 
            VALUES ($1, $2) 
            ON CONFLICT (discord_id) DO UPDATE SET player_uid = $2
        ''', ctx.author.id, player_uid)
        await ctx.send(f"✅ Registered! Your Discord is now linked to Palworld UID: `{player_uid}`")
    except Exception as e:
        await ctx.send("❌ An error occurred while registering.")
    finally:
        await conn.close()

@bot.command(name="daily")
async def daily(ctx):
    """Claim your daily Discord coins to use in the shop."""
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT balance, last_daily FROM users WHERE discord_id = $1', ctx.author.id)
        if not row:
            await ctx.send("❌ You need to `!register <PlayerUID>` first!")
            return
            
        balance, last_daily = row
        now = datetime.utcnow()
        
        if last_daily and now < last_daily + timedelta(days=1):
            wait_time = (last_daily + timedelta(days=1)) - now
            hours, remainder = divmod(wait_time.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await ctx.send(f"⏳ You must wait {hours}h {minutes}m before claiming your next daily.")
            return

        new_balance = balance + DAILY_REWARD_AMOUNT
        await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE discord_id = $3', new_balance, now, ctx.author.id)
        await ctx.send(f"💰 You claimed your daily reward of **{DAILY_REWARD_AMOUNT} coins**! Use `!shop` to see what you can buy.\n💳 **New balance:** {new_balance} coins.")
    finally:
        await conn.close()

@bot.command(name="balance")
async def balance(ctx):
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT balance FROM users WHERE discord_id = $1', ctx.author.id)
        if row: await ctx.send(f"💳 You have **{row['balance']} coins**.")
        else: await ctx.send("❌ You are not registered. Use `!register <PlayerUID>`.")
    finally:
        await conn.close()

@bot.command(name="shop")
async def shop(ctx):
    """Displays items available for purchase."""
    embed = discord.Embed(title="🛒 Chillet & Chill Supply Shop", description="Use `!daily` to get coins, then `!buy <item>` to have it delivered in-game!", color=discord.Color.gold())
    for key, item in SHOP_ITEMS.items():
        embed.add_field(name=f"{item['name']} (`{key}`)", value=f"Price: **{item['price']} coins**", inline=False)
    embed.set_footer(text="Use !buy <item> <quantity> to purchase!")
    await ctx.send(embed=embed)

@bot.command(name="buy")
async def buy(ctx, item_key: str, quantity: int = 1):
    """Buy items and deposit them directly in-game via RCON."""
    if not DATABASE_URL: return

    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS:
        await ctx.send("❌ Item not found. Check `!shop`.")
        return
        
    if quantity <= 0: return

    item = SHOP_ITEMS[item_key]
    total_cost = item['price'] * quantity
    total_amount_in_game = item['amount'] * quantity

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT player_uid, balance FROM users WHERE discord_id = $1', ctx.author.id)
        if not row:
            await ctx.send("❌ You are not registered. Use `!register <PlayerUID>`.")
            return
            
        player_uid = row['player_uid']
        current_balance = row['balance']

        if current_balance < total_cost:
            await ctx.send(f"❌ Not enough coins! This costs **{total_cost}**, but you only have **{current_balance}**.")
            return

        # 1. Attempt to give the item in-game via RCON BEFORE deducting coins
        try:
            async with GameRCON(SFTP_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
                # 'give' is the standard command for Palguard/Server-Commands mods
                rcon_command = f"give {player_uid} {item['id']} {total_amount_in_game}"
                logger.info(f"Executing RCON: {rcon_command}")
                await rcon.send(rcon_command)
        except Exception as e:
            logger.error(f"RCON Error during buy: {e}")
            await ctx.send(f"❌ **Delivery Failed:** Could not connect to the game server. Your coins were **not** deducted.\n*(Admin Note: Make sure the server has a mod like Palguard installed to support the `give` command, and that `RCON_PORT` is set in Render).*")
            return

        # 2. If RCON succeeds, deduct the balance
        new_balance = current_balance - total_cost
        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_balance, ctx.author.id)
        
        await ctx.send(f"✅ Successfully purchased {quantity}x **{item['name']}**!\n🎁 *The items have been injected into your Palworld inventory!*\n💳 Deducted **{total_cost} coins**. Remaining: **{new_balance}**.")
    except Exception as e:
        logger.error(f"Database error on buy: {e}")
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
    if not DISCORD_TOKEN: sys.exit(1)
    await start_web_server()
    async with bot: await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
