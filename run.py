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
from gamercon_async import GameRCON

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
SFTP_LOG_PATH = (os.getenv("SFTP_LOG_PATH") or "/server-data/Pal/Binaries/Win64/PalDefender/Logs").strip().strip("[]()").strip()

_channel_val = (os.getenv("DISCORD_CHAT_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "0").strip().strip("[]()").strip()
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if _channel_val.isdigit() else 0

RCON_PORT = int(os.getenv("RCON_PORT", "25575"))

# -------------------------------------------------------------
# 2. Economy & Categorized Full Shop Catalog (Legit Items, -75% Total Discount)
# -------------------------------------------------------------
DAILY_REWARD_AMOUNT = 500

SHOP_ITEMS = {
    # === SPHERES ===
    "palsphere": {"name": "Pal Sphere", "rcon_id": "PalSphere", "price": 25, "category": "Spheres"},
    "megasphere": {"name": "Mega Sphere", "rcon_id": "PalSphere_Mega", "price": 75, "category": "Spheres"},
    "gigasphere": {"name": "Giga Sphere", "rcon_id": "PalSphere_Giga", "price": 200, "category": "Spheres"},
    "hypersphere": {"name": "Hyper Sphere", "rcon_id": "PalSphere_Master", "price": 375, "category": "Spheres"},
    "ultrasphere": {"name": "Ultra Sphere", "rcon_id": "PalSphere_Exotic", "price": 750, "category": "Spheres"},
    "legendarysphere": {"name": "Legendary Sphere", "rcon_id": "PalSphere_Legend", "price": 1250, "category": "Spheres"},

    # === BASIC MATERIALS ===
    "wood": {"name": "Wood", "rcon_id": "Wood", "price": 1, "category": "Basic Materials"},
    "stone": {"name": "Stone", "rcon_id": "Stone", "price": 1, "category": "Basic Materials"},
    "fiber": {"name": "Fiber", "rcon_id": "Fiber", "price": 2, "category": "Basic Materials"},
    "paldium": {"name": "Paldium Fragment", "rcon_id": "Pal_crystal", "price": 5, "category": "Basic Materials"},
    "leather": {"name": "Leather", "rcon_id": "Leather", "price": 12, "category": "Basic Materials"},
    "bone": {"name": "Bone", "rcon_id": "Bone", "price": 12, "category": "Basic Materials"},
    "horn": {"name": "Horn", "rcon_id": "Horn", "price": 12, "category": "Basic Materials"},
    "wool": {"name": "Wool", "rcon_id": "Wool", "price": 5, "category": "Basic Materials"},
    "palfluids": {"name": "Pal Fluids", "rcon_id": "PalFluid", "price": 25, "category": "Basic Materials"},
    "paloil": {"name": "High Quality Pal Oil", "rcon_id": "PalOil", "price": 38, "category": "Basic Materials"},
    "flameorgan": {"name": "Flame Organ", "rcon_id": "FireOrgan", "price": 25, "category": "Basic Materials"},
    "iceorgan": {"name": "Ice Organ", "rcon_id": "IceOrgan", "price": 25, "category": "Basic Materials"},
    "electricorgan": {"name": "Electric Organ", "rcon_id": "ElectricOrgan", "price": 25, "category": "Basic Materials"},
    "venomgland": {"name": "Venom Gland", "rcon_id": "PoisonGland", "price": 25, "category": "Basic Materials"},

    # === ORES & INGOTS ===
    "ore": {"name": "Ore", "rcon_id": "CopperOre", "price": 12, "category": "Ores & Ingots"},
    "ingot": {"name": "Ingot", "rcon_id": "CopperIngot", "price": 25, "category": "Ores & Ingots"},
    "coal": {"name": "Coal", "rcon_id": "Coal", "price": 25, "category": "Ores & Ingots"},
    "refinedingot": {"name": "Refined Ingot", "rcon_id": "IronIngot", "price": 62, "category": "Ores & Ingots"},
    "sulfur": {"name": "Sulfur", "rcon_id": "Sulfur", "price": 38, "category": "Ores & Ingots"},
    "quartz": {"name": "Pure Quartz", "rcon_id": "Quartz", "price": 50, "category": "Ores & Ingots"},
    "palmetal": {"name": "Pal Metal Ingot", "rcon_id": "StealIngot", "price": 125, "category": "Ores & Ingots"},

    # === ADVANCED MATERIALS ===
    "polymer": {"name": "Polymer", "rcon_id": "Polymer", "price": 75, "category": "Advanced Materials"},
    "carbonfiber": {"name": "Carbon Fiber", "rcon_id": "CarbonFiber", "price": 100, "category": "Advanced Materials"},
    "cement": {"name": "Cement", "rcon_id": "Cement", "price": 38, "category": "Advanced Materials"},
    "circuitboard": {"name": "Circuit Board", "rcon_id": "MachinePart", "price": 125, "category": "Advanced Materials"},
    "aicore": {"name": "AI Core", "rcon_id": "AIcore", "price": 500, "category": "Advanced Materials"},

    # === AMMUNITION ===
    "arrow": {"name": "Arrow", "rcon_id": "Arrow", "price": 2, "category": "Ammunition"},
    "firearrow": {"name": "Fire Arrow", "rcon_id": "FireArrow", "price": 5, "category": "Ammunition"},
    "poisonarrow": {"name": "Poison Arrow", "rcon_id": "PoisonArrow", "price": 5, "category": "Ammunition"},
    "coarseammo": {"name": "Coarse Ammo", "rcon_id": "RoughBullet", "price": 7, "category": "Ammunition"},
    "handgunammo": {"name": "Handgun Ammo", "rcon_id": "HandgunBullet", "price": 12, "category": "Ammunition"},
    "rifleammo": {"name": "Rifle Ammo", "rcon_id": "RifleBullet", "price": 25, "category": "Ammunition"},
    "shotgunammo": {"name": "Shotgun Shells", "rcon_id": "ShotgunBullet", "price": 30, "category": "Ammunition"},
    "assaultammo": {"name": "Assault Rifle Ammo", "rcon_id": "AssaultRifleBullet", "price": 38, "category": "Ammunition"},
    "rocketammo": {"name": "Rocket Ammo", "rcon_id": "ExplosiveBullet", "price": 250, "category": "Ammunition"},
    "energycartridge": {"name": "Energy Cartridge", "rcon_id": "EnergyCartridge", "price": 50, "category": "Ammunition"},

    # === WEAPONS ===
    "oldbow": {"name": "Old Bow", "rcon_id": "OldBow", "price": 125, "category": "Weapons"},
    "crossbow": {"name": "Crossbow", "rcon_id": "Crossbow", "price": 375, "category": "Weapons"},
    "handgun": {"name": "Handgun", "rcon_id": "Handgun", "price": 1250, "category": "Weapons"},
    "singleshotrifle": {"name": "Single-shot Rifle", "rcon_id": "Rifle", "price": 2000, "category": "Weapons"},
    "assaultrifle": {"name": "Assault Rifle", "rcon_id": "AssaultRifle", "price": 5000, "category": "Weapons"},
    "pumpactionshotgun": {"name": "Pump-action Shotgun", "rcon_id": "PumpActionShotgun", "price": 6250, "category": "Weapons"},
    "rocketlauncher": {"name": "Rocket Launcher", "rcon_id": "RocketLauncher", "price": 18750, "category": "Weapons"},

    # === ARMOR & SHIELDS ===
    "clotharmor": {"name": "Cloth Armor", "rcon_id": "ClothArmor", "price": 100, "category": "Armor & Shields"},
    "peltarmor": {"name": "Pelt Armor", "rcon_id": "PeltArmor", "price": 300, "category": "Armor & Shields"},
    "metalarmor": {"name": "Metal Armor", "rcon_id": "MetalArmor", "price": 1250, "category": "Armor & Shields"},
    "refinedmetalarmor": {"name": "Refined Metal Armor", "rcon_id": "RefinedMetalArmor", "price": 5000, "category": "Armor & Shields"},
    "palmetalarmor": {"name": "Pal Metal Armor", "rcon_id": "PalMetalArmor", "price": 20000, "category": "Armor & Shields"},
    "megashield": {"name": "Mega Shield", "rcon_id": "MegaShield", "price": 750, "category": "Armor & Shields"},
    "gigashield": {"name": "Giga Shield", "rcon_id": "GigaShield", "price": 2500, "category": "Armor & Shields"},
    "hypershield": {"name": "Hyper Shield", "rcon_id": "HyperShield", "price": 7500, "category": "Armor & Shields"},

    # === MEDICINE & CONSUMABLES ===
    "lowmeds": {"name": "Low Grade Medical Supplies", "rcon_id": "Herb", "price": 50, "category": "Medicine & Consumables"},
    "meds": {"name": "Medical Supplies", "rcon_id": "Medicines", "price": 125, "category": "Medicine & Consumables"},
    "highmeds": {"name": "High Grade Medical Supplies", "rcon_id": "LuxuryMedicines", "price": 250, "category": "Medicine & Consumables"},
    "memorywipe": {"name": "Memory Wiping Medicine", "rcon_id": "MemoryWipeMedicine", "price": 2500, "category": "Medicine & Consumables"},
    "berries": {"name": "Red Berries", "rcon_id": "Berry", "price": 2, "category": "Medicine & Consumables"},
    "bread": {"name": "Bread", "rcon_id": "Bread", "price": 25, "category": "Medicine & Consumables"},
    "honey": {"name": "Honey", "rcon_id": "Honey", "price": 25, "category": "Medicine & Consumables"},

    # === VALUABLES ===
    "ruby": {"name": "Ruby", "rcon_id": "Ruby", "price": 1250, "category": "Valuables"},
    "sapphire": {"name": "Sapphire", "rcon_id": "Sapphire", "price": 3000, "category": "Valuables"},
    "emerald": {"name": "Emerald", "rcon_id": "Emerald", "price": 6250, "category": "Valuables"},
    "diamond": {"name": "Diamond", "rcon_id": "Diamond", "price": 12500, "category": "Valuables"}
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
# 4. Palworld REST API Helpers
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
    except Exception as e:
        return None, str(e)

# -------------------------------------------------------------
# 5. SFTP Chat Listener (Multi-Log Directory Scanner)
# -------------------------------------------------------------
last_position = 0 
last_file_name = None

async def sftp_chat_listener_loop():
    global last_position, last_file_name
    await bot.wait_until_ready()
    if not DISCORD_CHAT_CHANNEL_ID or not SFTP_USER: return
    channel = bot.get_channel(DISCORD_CHAT_CHANNEL_ID)
    if not channel: return

    logger.info(f"📡 SFTP Listener Active Directory: {SFTP_LOG_PATH}")
    while not bot.is_closed():
        try:
            def scan_logs():
                global last_position, last_file_name
                transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
                transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
                sftp = paramiko.SFTPClient.from_transport(transport)
                
                files = sftp.listdir_attr(SFTP_LOG_PATH)
                log_files = [f for f in files if f.filename.endswith('.log')]
                if not log_files:
                    sftp.close()
                    transport.close()
                    return []
                    
                latest_file = sorted(log_files, key=lambda x: x.st_mtime, reverse=True)[0]
                full_file_path = f"{SFTP_LOG_PATH}/{latest_file.filename}"

                if last_file_name != latest_file.filename:
                    last_file_name = latest_file.filename
                    last_position = 0 

                with sftp.open(full_file_path, "r") as f:
                    f.seek(last_position)
                    new_data = f.read().decode("utf-8", errors="replace")
                    last_position = f.tell()

                sftp.close()
                transport.close()
                return [line.strip() for line in new_data.splitlines() if line.strip()]

            new_lines = await asyncio.to_thread(scan_logs)
            for line in new_lines:
                if "Chat:" in line:
                    await channel.send(f"💬 `{line}`")
        except Exception as e:
            logger.error(f"SFTP Error: {e}")
            
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
    """Displays categorized items available for purchase."""
    embed = discord.Embed(
        title="🛒 Palworld Server Shop",
        description="Use `!buy <item_id> <quantity>` to have items delivered directly in-game!",
        color=discord.Color.blue()
    )

    categories = {}
    for item_id, item_data in SHOP_ITEMS.items():
        cat = item_data.get("category", "Other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(f"`{item_id}` - {item_data['name']} (🪙 {item_data['price']})")

    for cat, items in categories.items():
        field_value = "\n".join(items)
        embed.add_field(name=f"**{cat}**", value=field_value, inline=False)

    embed.set_footer(text="Use !buy <item_id> <quantity> to purchase!")
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

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT player_uid, balance FROM users WHERE discord_id = $1', ctx.author.id)
        if not row:
            await ctx.send("❌ You are not registered. Use `!register <PlayerUID>` first.")
            return
            
        player_uid = row['player_uid']
        current_balance = row['balance']

        if current_balance < total_cost:
            await ctx.send(f"❌ Not enough coins! This costs **{total_cost}**, but you only have **{current_balance}**.")
            return

        # 1. Attempt to give the item in-game via RCON
        try:
            async with GameRCON(SFTP_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
                rcon_command = f"give {player_uid} {item['rcon_id']} {quantity}"
                logger.info(f"Executing RCON: {rcon_command}")
                await rcon.send(rcon_command)
        except Exception as e:
            logger.error(f"RCON Error during buy: {e}")
            await ctx.send(f"❌ **Delivery Failed:** Could not connect to the game server via RCON. Your coins were **not** deducted.")
            return

        # 2. Deduct balance upon successful RCON transmission
        new_balance = current_balance - total_cost
        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_balance, ctx.author.id)
        
        await ctx.send(f"✅ Successfully purchased {quantity}x **{item['name']}**!\n🎁 *Injected into your in-game inventory via PalDefender!*\n💳 Deducted **{total_cost} coins**. Remaining: **{new_balance}**.")
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
