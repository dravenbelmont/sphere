import asyncio
import logging
import os
import re
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
REST_API_URL = (os.getenv("REST_API_URL") or os.getenv("PALWORLD_API_URL") or "").strip().strip("[]()").strip()
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or os.getenv("RCON_PASSWORD") or "").strip().strip("[]()").strip()
WEB_PORT = int(os.getenv("PORT", "10000"))
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip().strip("[]()").strip()

SFTP_HOST = (os.getenv("SFTP_HOST") or "").strip().strip("[]()").strip()
RCON_HOST = (os.getenv("RCON_HOST") or SFTP_HOST).strip().strip("[]()").strip()
SFTP_PORT = int(os.getenv("SFTP_PORT", "22").strip())
SFTP_USER = (os.getenv("SFTP_USER") or "").strip().strip("[]()").strip()
SFTP_PASSWORD = (os.getenv("SFTP_PASSWORD") or "").strip().strip("[]()").strip()
SFTP_LOG_PATH = (os.getenv("SFTP_LOG_PATH") or "/server-data/Pal/Binaries/Win64/PalDefender/Logs").strip().strip("[]()").strip()

_channel_val = (os.getenv("DISCORD_CHAT_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "0").strip().strip("[]()").strip()
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if _channel_val.isdigit() else 0

RCON_PORT = int(os.getenv("RCON_PORT", "25575").strip())

# -------------------------------------------------------------
# 2. Daily Login Pack & Shop Catalog Configuration
# -------------------------------------------------------------
DAILY_PACK_SHOP_POINTS = 1000
DAILY_PACK_ITEMS = [
    {"rcon_id": "Cake", "quantity": 50},
    {"rcon_id": "GoldCoin", "quantity": 10000},
    {"rcon_id": "BossCivilizationCore", "quantity": 10},
    {"rcon_id": "PredatorCore", "quantity": 10},
    {"rcon_id": "DogCoin", "quantity": 250}
]

PLAYTIME_REWARD_AMOUNT = 100

SHOP_ITEMS = {
    "palsphere": {"name": "Pal Sphere", "rcon_id": "PalSphere", "price": 25, "category": "Spheres"},
    "megasphere": {"name": "Mega Sphere", "rcon_id": "PalSphere_Mega", "price": 75, "category": "Spheres"},
    "gigasphere": {"name": "Giga Sphere", "rcon_id": "PalSphere_Giga", "price": 200, "category": "Spheres"},
    "hypersphere": {"name": "Hyper Sphere", "rcon_id": "PalSphere_Master", "price": 375, "category": "Spheres"},
    "ultrasphere": {"name": "Ultra Sphere", "rcon_id": "PalSphere_Exotic", "price": 750, "category": "Spheres"},
    "legendarysphere": {"name": "Legendary Sphere", "rcon_id": "PalSphere_Legend", "price": 1250, "category": "Spheres"},
    "ultimate_sphere": {"name": "Ultimate Sphere", "rcon_id": "PalSphere_Ultimate", "price": 2500, "category": "Spheres"},
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
    "ore": {"name": "Ore", "rcon_id": "CopperOre", "price": 12, "category": "Ores & Ingots"},
    "ingot": {"name": "Ingot", "rcon_id": "CopperIngot", "price": 25, "category": "Ores & Ingots"},
    "coal": {"name": "Coal", "rcon_id": "Coal", "price": 25, "category": "Ores & Ingots"},
    "refinedingot": {"name": "Refined Ingot", "rcon_id": "IronIngot", "price": 62, "category": "Ores & Ingots"},
    "sulfur": {"name": "Sulfur", "rcon_id": "Sulfur", "price": 38, "category": "Ores & Ingots"},
    "quartz": {"name": "Pure Quartz", "rcon_id": "Quartz", "price": 50, "category": "Ores & Ingots"},
    "palmetal": {"name": "Pal Metal Ingot", "rcon_id": "StealIngot", "price": 125, "category": "Ores & Ingots"},
    "plasteel": {"name": "Plasteel", "rcon_id": "Plasteel", "price": 250, "category": "Ores & Ingots"},
    "polymer": {"name": "Polymer", "rcon_id": "Polymer", "price": 75, "category": "Advanced Materials"},
    "carbonfiber": {"name": "Carbon Fiber", "rcon_id": "CarbonFiber", "price": 100, "category": "Advanced Materials"},
    "cement": {"name": "Cement", "rcon_id": "Cement", "price": 38, "category": "Advanced Materials"},
    "circuitboard": {"name": "Circuit Board", "rcon_id": "MachinePart", "price": 125, "category": "Advanced Materials"},
    "aicore": {"name": "AI Core", "rcon_id": "AIcore", "price": 500, "category": "Advanced Materials"},
    "dogcoin": {"name": "Dog Coin", "rcon_id": "DogCoin", "price": 150, "category": "Advanced Materials"},
    "arrow": {"name": "Arrow", "rcon_id": "Arrow", "price": 2, "category": "Ammunition"},
    "handgunammo": {"name": "Handgun Ammo", "rcon_id": "HandgunBullet", "price": 12, "category": "Ammunition"},
    "rifleammo": {"name": "Rifle Ammo", "rcon_id": "RifleBullet", "price": 25, "category": "Ammunition"},
    "shotgunammo": {"name": "Shotgun Shells", "rcon_id": "ShotgunBullet", "price": 30, "category": "Ammunition"},
    "assaultammo": {"name": "Assault Rifle Ammo", "rcon_id": "AssaultRifleBullet", "price": 38, "category": "Ammunition"},
    "rocketammo": {"name": "Rocket Ammo", "rcon_id": "ExplosiveBullet", "price": 250, "category": "Ammunition"},
    "ruby": {"name": "Ruby", "rcon_id": "Ruby", "price": 1250, "category": "Valuables"},
    "sapphire": {"name": "Sapphire", "rcon_id": "Sapphire", "price": 3000, "category": "Valuables"},
    "emerald": {"name": "Emerald", "rcon_id": "Emerald", "price": 6250, "category": "Valuables"},
    "diamond": {"name": "Diamond", "rcon_id": "Diamond", "price": 12500, "category": "Valuables"}
}

async def init_db():
    if not DATABASE_URL: return
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id BIGINT PRIMARY KEY,
                player_uid TEXT UNIQUE,
                balance INTEGER DEFAULT 0,
                last_daily TIMESTAMP
            )
        ''')
        await conn.close()
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
# 5. Automated Login Daily Reward & Player Tracking Loop
# -------------------------------------------------------------
known_online_players = set()
last_known_player_names = {}
is_players_initialized = False

async def process_login_daily(player_uid: str, player_name: str):
    if not DATABASE_URL or not RCON_HOST:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT discord_id, balance, last_daily FROM users WHERE player_uid = $1', str(player_uid))
        now = datetime.utcnow()
        
        if row:
            last_daily = row['last_daily']
            if last_daily and now < last_daily + timedelta(hours=24):
                return  # Cooldown active (< 24 hours)
            
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

        # Deliver daily items via RCON
        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            for item in DAILY_PACK_ITEMS:
                await rcon.send(f"give {player_uid} {item['rcon_id']} {item['quantity']}")
            await rcon.send(f"Broadcast Welcome back {player_name}! Your daily login pack has been delivered.")
            
        logger.info(f"Successfully delivered automated login daily pack to {player_name} (UID: {player_uid})")
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
                        pid = p.get("userid") or p.get("playeruid") or p.get("name")
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
                            # Trigger automatic login daily pack delivery
                            asyncio.create_task(process_login_daily(jid, name))

                            if channel:
                                embed = discord.Embed(
                                    title="🟢 Player Joined",
                                    description=f"**{name}** has joined the server!",
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

async def playtime_reward_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        if not DATABASE_URL or not REST_API_URL: continue
        try:
            data, error = await call_palworld_api("/players", method="GET")
            if error or not data: continue
            players = data.get("players", [])
            if not players: continue
            
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                for p in players:
                    uid = p.get("playeruid", p.get("userid"))
                    if not uid: continue
                    row = await conn.fetchrow('SELECT discord_id, balance FROM users WHERE player_uid = $1', str(uid))
                    if row:
                        new_bal = row['balance'] + PLAYTIME_REWARD_AMOUNT
                        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_bal, row['discord_id'])
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Playtime loop error: {e}")

# -------------------------------------------------------------
# 6. Shop Pagination View UI
# -------------------------------------------------------------
class ShopPaginator(discord.ui.View):
    def __init__(self, items_list, author_id):
        super().__init__(timeout=180)
        self.items = items_list
        self.author_id = author_id
        self.current_page = 0
        self.per_page = 8
        self.max_pages = (len(items_list) - 1) // self.per_page

    def get_embed(self):
        embed = discord.Embed(title="🛒 Palworld Server Shop", color=discord.Color.blue())
        start = self.current_page * self.per_page
        for item_id, data in self.items[start:start + self.per_page]:
            embed.add_field(name=f"{data['name']} (`{item_id}`)", value=f"Price: 🪙 **{data['price']} coins**", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages + 1} | Use !buy <item_id> <quantity>")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id: return await interaction.response.send_message("Not your menu!", ephemeral=True)
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id: return await interaction.response.send_message("Not your menu!", ephemeral=True)
        if self.current_page < self.max_pages:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.defer()

# -------------------------------------------------------------
# 7. Discord Commands & Event Listeners
# -------------------------------------------------------------
@bot.event
async def on_ready():
    await init_db()
    logger.info(f"✅ Bot connected as {bot.user}")
    if not getattr(bot, "tasks_started", False):
        bot.tasks_started = True
        bot.loop.create_task(poll_palworld_players_loop())
        bot.loop.create_task(playtime_reward_loop())

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != DISCORD_CHAT_CHANNEL_ID:
        await bot.process_commands(message)
        return

    if message.content.startswith(BOT_PREFIX):
        await bot.process_commands(message)
        return

    if REST_API_URL and ADMIN_PASSWORD:
        try:
            chat_text = f"[Discord] {message.author.display_name}: {message.content}"
            _, error = await call_palworld_api("/announce", method="POST", payload={"message": chat_text})
            if error:
                logger.error(f"Failed to relay message via REST API: {error}")
        except Exception as e:
            logger.error(f"Failed to relay Discord message to game server: {e}")

    await bot.process_commands(message)

@bot.command(name="players")
async def list_players(ctx):
    data, error = await call_palworld_api("/players", method="GET")
    if error: return await ctx.send(f"❌ Error: `{error}`")
    players = data.get("players", [])
    if not players: return await ctx.send("🎮 0 players online.")
    list_str = "\n".join([f"• **{p.get('name', 'Unknown')}** (Level {p.get('level', '?')})" for p in players])
    await ctx.send(embed=discord.Embed(title=f"Online Players ({len(players)})", description=list_str, color=discord.Color.blue()))

@bot.command(name="register")
async def register(ctx, player_uid: str):
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute('INSERT INTO users (discord_id, player_uid) VALUES ($1, $2) ON CONFLICT (discord_id) DO UPDATE SET player_uid = $2', ctx.author.id, player_uid)
        await ctx.send("✅ Registered linked UID.")
    finally:
        await conn.close()

@bot.command(name="daily")
async def daily(ctx):
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT balance, last_daily FROM users WHERE discord_id = $1', ctx.author.id)
        if not row: return await ctx.send("❌ Use `!register <PlayerUID>` first!")
        balance, last_daily = row
        now = datetime.utcnow()
        if last_daily and now < last_daily + timedelta(days=1):
            return await ctx.send("⏳ You must wait 24 hours between claims.")
        new_bal = balance + DAILY_PACK_SHOP_POINTS
        await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE discord_id = $3', new_bal, now, ctx.author.id)
        await ctx.send(f"💰 Claimed **{DAILY_PACK_SHOP_POINTS} shop points**! Balance: {new_bal}")
    finally:
        await conn.close()

@bot.command(name="balance")
async def balance(ctx):
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT balance FROM users WHERE discord_id = $1', ctx.author.id)
        await ctx.send(f"💳 Balance: **{row['balance'] if row else 0} shop points**.")
    finally:
        await conn.close()

@bot.command(name="shop")
async def shop(ctx):
    view = ShopPaginator(list(SHOP_ITEMS.items()), ctx.author.id)
    await ctx.send(embed=view.get_embed(), view=view)

@bot.command(name="buy")
async def buy(ctx, item_key: str, quantity: int = 1):
    if not DATABASE_URL: return
    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS or quantity <= 0: return await ctx.send("❌ Invalid item or quantity.")
    item = SHOP_ITEMS[item_key]
    cost = item['price'] * quantity

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT player_uid, balance FROM users WHERE discord_id = $1', ctx.author.id)
        if not row or row['balance'] < cost:
            return await ctx.send("❌ Not registered or insufficient funds.")
        
        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            response = await rcon.send(f"give {row['player_uid']} {item['rcon_id']} {quantity}")
            logger.info(f"RCON Give Response: {response}")
        
        new_bal = row['balance'] - cost
        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_bal, ctx.author.id)
        await ctx.send(f"✅ Purchased {quantity}x **{item['name']}**! New balance: {new_bal}")
    except Exception as e:
        logger.error(f"RCON delivery failed for item {item_key} on host {RCON_HOST}:{RCON_PORT} -> {e}")
        await ctx.send(f"❌ Delivery failed: Could not connect to game server RCON. Please verify your RCON IP and port.")
    finally:
        await conn.close()

# -------------------------------------------------------------
# 8. Web Server & Main
# -------------------------------------------------------------
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    async with bot: await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
