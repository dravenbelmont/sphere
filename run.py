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

RCON_HOST = (os.getenv("RCON_HOST") or "127.0.0.1").strip().strip("[]()").strip()
RCON_PORT = int(os.getenv("RCON_PORT", "25575").strip())

_channel_val = (os.getenv("DISCORD_CHAT_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "0").strip().strip("[]()").strip()
DISCORD_CHAT_CHANNEL_ID = int(_channel_val) if _channel_val.isdigit() else 0

# -------------------------------------------------------------
# 2. Daily Login Pack & Comprehensive Palworld 1.0 Shop Catalog
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
    # Pal Spheres
    "pal_sphere": {"name": "Pal Sphere", "id": "PalSphere", "price": 25, "category": "Spheres"},
    "mega_sphere": {"name": "Mega Sphere", "id": "Megasphere", "price": 75, "category": "Spheres"},
    "giga_sphere": {"name": "Giga Sphere", "id": "Gigasphere", "price": 200, "category": "Spheres"},
    "hyper_sphere": {"name": "Hyper Sphere", "id": "Hypersphere", "price": 375, "category": "Spheres"},
    "ultra_sphere": {"name": "Ultra Sphere", "id": "Ultisphere", "price": 750, "category": "Spheres"},
    "legendary_sphere": {"name": "Legendary Sphere", "id": "MasterSphere", "price": 1250, "category": "Spheres"},
    "ancient_sphere": {"name": "Ancient Sphere", "id": "AncientSphere", "price": 2000, "category": "Spheres"},

    # Ores & Raw Materials
    "stone": {"name": "Stone", "id": "Stone", "price": 1, "category": "Ores & Materials"},
    "wood": {"name": "Wood", "id": "Wood", "price": 1, "category": "Ores & Materials"},
    "fiber": {"name": "Fiber", "id": "Fiber", "price": 2, "category": "Ores & Materials"},
    "paldium": {"name": "Paldium Fragment", "id": "Palium_Ore", "price": 5, "category": "Ores & Materials"},
    "ore": {"name": "Ore", "id": "Ore", "price": 12, "category": "Ores & Materials"},
    "coal": {"name": "Coal", "id": "Coal", "price": 25, "category": "Ores & Materials"},
    "sulfur": {"name": "Sulfur", "id": "Sulfur", "price": 38, "category": "Ores & Materials"},
    "quartz": {"name": "Pure Quartz", "id": "Quartz", "price": 50, "category": "Ores & Materials"},
    "organic_oil": {"name": "High Quality Pal Oil", "id": "HighQualityPalOil", "price": 38, "category": "Ores & Materials"},
    "leather": {"name": "Leather", "id": "Leather", "price": 12, "category": "Ores & Materials"},
    "bone": {"name": "Bone", "id": "Bone", "price": 12, "category": "Ores & Materials"},
    "horn": {"name": "Horn", "id": "Horn", "price": 12, "category": "Ores & Materials"},
    "wool": {"name": "Wool", "id": "Wool", "price": 5, "category": "Ores & Materials"},
    "cloth": {"name": "Cloth", "id": "Cloth", "price": 10, "category": "Ores & Materials"},
    "fine_cloth": {"name": "Fine Cloth", "id": "FineCloth", "price": 40, "category": "Ores & Materials"},
    "pal_fluid": {"name": "Pal Fluid", "id": "PalFluid", "price": 25, "category": "Ores & Materials"},
    "venom_gland": {"name": "Venom Gland", "id": "VenomGland", "price": 25, "category": "Ores & Materials"},
    "electric_organ": {"name": "Electric Organ", "id": "ElectricOrgan", "price": 25, "category": "Ores & Materials"},
    "magma_organ": {"name": "Flame Organ", "id": "FlameOrgan", "price": 25, "category": "Ores & Materials"},
    "ice_organ": {"name": "Ice Organ", "id": "IceOrgan", "price": 25, "category": "Ores & Materials"},
    "small_pal_soul": {"name": "Small Pal Soul", "id": "PalsSoul_S", "price": 50, "category": "Ores & Materials"},
    "medium_pal_soul": {"name": "Medium Pal Soul", "id": "PalsSoul_M", "price": 150, "category": "Ores & Materials"},
    "large_pal_soul": {"name": "Large Pal Soul", "id": "PalsSoul_L", "price": 500, "category": "Ores & Materials"},
    "ancient_parts": {"name": "Ancient Civilization Parts", "id": "AncientCivilizationParts", "price": 100, "category": "Ores & Materials"},

    # Ingots & Advanced Metals
    "ingot": {"name": "Ingot", "id": "Ingot", "price": 25, "category": "Ingots & Metals"},
    "refined_ingot": {"name": "Refined Ingot", "id": "RefinedIngot", "price": 62, "category": "Ingots & Metals"},
    "pal_metal_ingot": {"name": "Pal Metal Ingot", "id": "PalMetalIngot", "price": 125, "category": "Ingots & Metals"},
    "soralite_ingot": {"name": "Soralite Ingot", "id": "SoraliteIngot", "price": 300, "category": "Ingots & Metals"},
    "paloxite_ingot": {"name": "Paloxite Ingot", "id": "PaloxiteIngot", "price": 400, "category": "Ingots & Metals"},
    "carbon_fiber": {"name": "Carbon Fiber", "id": "CarbonFiber", "price": 100, "category": "Ingots & Metals"},
    "polymer": {"name": "Polymer", "id": "Polymer", "price": 75, "category": "Ingots & Metals"},
    "cement": {"name": "Cement", "id": "Cement", "price": 38, "category": "Ingots & Metals"},

    # Weapons
    "old_bow": {"name": "Old Bow", "id": "OldBow", "price": 30, "category": "Weapons"},
    "crossbow": {"name": "Crossbow", "id": "Crossbow", "price": 150, "category": "Weapons"},
    "stone_spear": {"name": "Stone Spear", "id": "Spear", "price": 50, "category": "Weapons"},
    "metal_spear": {"name": "Metal Spear", "id": "Spear_Metal", "price": 300, "category": "Weapons"},
    "refined_metal_spear": {"name": "Refined Metal Spear", "id": "Spear_RefinedMetal", "price": 800, "category": "Weapons"},
    "lilys_spear": {"name": "Lily's Spear", "id": "Spear_ForestBoss", "price": 2500, "category": "Weapons"},
    "primitive_sword": {"name": "Primitive Sword", "id": "Sword", "price": 1200, "category": "Weapons"},
    "laser_sword": {"name": "Beam Sword", "id": "BeamSword", "price": 4000, "category": "Weapons"},
    "handgun": {"name": "Handgun", "id": "Handgun", "price": 2000, "category": "Weapons"},
    "assault_rifle": {"name": "Assault Rifle", "id": "AssaultRifle", "price": 6000, "category": "Weapons"},
    "pump_shotgun": {"name": "Pump-action Shotgun", "id": "Shotgun", "price": 8000, "category": "Weapons"},
    "rocket_launcher": {"name": "Rocket Launcher", "id": "RocketLauncher", "price": 12000, "category": "Weapons"},
    "flamethrower": {"name": "Flamethrower", "id": "FlameThrower", "price": 10000, "category": "Weapons"},
    "gatling_gun": {"name": "Gatling Gun", "id": "GatlingGun", "price": 15000, "category": "Weapons"},

    # Armor & Gear
    "cloth_hat": {"name": "Cloth Hat", "id": "ClothHat", "price": 50, "category": "Armor & Gear"},
    "fur_helmet": {"name": "Fur Helmet", "id": "FurHelmet", "price": 150, "category": "Armor & Gear"},
    "metal_helm": {"name": "Metal Helm", "id": "MetalHelmet", "price": 400, "category": "Armor & Gear"},
    "refined_metal_helm": {"name": "Refined Metal Helm", "id": "RefinedMetalHelmet", "price": 1000, "category": "Armor & Gear"},
    "pal_metal_helm": {"name": "Pal Metal Helm", "id": "PalMetalHelmet", "price": 2500, "category": "Armor & Gear"},
    "cloth_armor": {"name": "Cloth Armor", "id": "ClothArmor", "price": 100, "category": "Armor & Gear"},
    "metal_armor": {"name": "Metal Armor", "id": "MetalArmor", "price": 600, "category": "Armor & Gear"},
    "refined_metal_armor": {"name": "Refined Metal Armor", "id": "RefinedMetalArmor", "price": 1500, "category": "Armor & Gear"},
    "pal_metal_armor": {"name": "Pal Metal Armor", "id": "PalMetalArmor", "price": 4000, "category": "Armor & Gear"},
    "heat_resistant_armor": {"name": "Heat Resistant Metal Armor", "id": "HeatResistantMetalArmor", "price": 1800, "category": "Armor & Gear"},
    "cold_resistant_armor": {"name": "Cold Resistant Metal Armor", "id": "ColdResistantMetalArmor", "price": 1800, "category": "Armor & Gear"},

    # Ammunition
    "arrow": {"name": "Arrow", "id": "Arrow", "price": 2, "category": "Ammunition"},
    "fire_arrow": {"name": "Fire Arrow", "id": "FireArrow", "price": 5, "category": "Ammunition"},
    "poison_arrow": {"name": "Poison Arrow", "id": "PoisonArrow", "price": 5, "category": "Ammunition"},
    "coarse_ammo": {"name": "Coarse Ammo", "id": "RoughBullet", "price": 5, "category": "Ammunition"},
    "handgun_ammo": {"name": "Handgun Ammo", "id": "HandgunBullet", "price": 12, "category": "Ammunition"},
    "rifle_ammo": {"name": "Assault Rifle Ammo", "id": "AssaultRifleBullet", "price": 25, "category": "Ammunition"},
    "shotgun_ammo": {"name": "Shotgun Shells", "id": "ShotgunBullet", "price": 30, "category": "Ammunition"},
    "rocket_ammo": {"name": "Rocket Ammo", "id": "RocketBullet", "price": 250, "category": "Ammunition"},

    # Food & Consumables
    "red_berries": {"name": "Red Berries", "id": "RedBerries", "price": 3, "category": "Food & Consumables"},
    "baked_berries": {"name": "Baked Berries", "id": "BakedBerries", "price": 5, "category": "Food & Consumables"},
    "mushroom": {"name": "Mushroom", "id": "Mushroom", "price": 4, "category": "Food & Consumables"},
    "baked_mushroom": {"name": "Baked Mushroom", "id": "BakedMushroom", "price": 8, "category": "Food & Consumables"},
    "bread": {"name": "Bread", "id": "Bread", "price": 15, "category": "Food & Consumables"},
    "jam_bun": {"name": "Jam-Filled Bun", "id": "JamBun", "price": 25, "category": "Food & Consumables"},
    "egg": {"name": "Egg", "id": "Egg", "price": 10, "category": "Food & Consumables"},
    "milk": {"name": "Milk", "id": "Milk", "price": 12, "category": "Food & Consumables"},
    "honey": {"name": "Honey", "id": "Honey", "price": 20, "category": "Food & Consumables"},
    "cake": {"name": "Cake", "id": "Cake", "price": 250, "category": "Food & Consumables"},
    "salad": {"name": "Salad", "id": "Salad", "price": 120, "category": "Food & Consumables"},
    "pizza": {"name": "Pizza", "id": "Pizza", "price": 200, "category": "Food & Consumables"},
    "pancakes": {"name": "Pancakes", "id": "Pancakes", "price": 80, "category": "Food & Consumables"},
    "meat_mutton": {"name": "Mutton Meat", "id": "MuttonMeat", "price": 15, "category": "Food & Consumables"},
    "meat_beef": {"name": "Eieboar Pork", "id": "Meat_Boar", "price": 15, "category": "Food & Consumables"},
    "meat_chicken": {"name": "Chikipi Poultry", "id": "ChickenPalMeat", "price": 10, "category": "Food & Consumables"},

    # Medicine & Seeds
    "low_grade_medicine": {"name": "Low Grade Medical Kit", "id": "Medicina_1", "price": 50, "category": "Medicine & Seeds"},
    "medical_kit": {"name": "Medical Kit", "id": "Medicina_2", "price": 150, "category": "Medicine & Seeds"},
    "high_grade_medicine": {"name": "High Grade Medical Kit", "id": "Medicina_3", "price": 400, "category": "Medicine & Seeds"},
    "memory_reset_pill": {"name": "Memory Reset Pill", "id": "ResetPill", "price": 1000, "category": "Medicine & Seeds"},
    "wheat_seed": {"name": "Wheat Seeds", "id": "WheatSeed", "price": 20, "category": "Medicine & Seeds"},
    "tomato_seed": {"name": "Tomato Seeds", "id": "TomatoSeed", "price": 30, "category": "Medicine & Seeds"},
    "lettuce_seed": {"name": "Lettuce Seeds", "id": "LettuceSeed", "price": 30, "category": "Medicine & Seeds"},
    "berry_seed": {"name": "Red Berry Seeds", "id": "BerrySeed", "price": 10, "category": "Medicine & Seeds"},

    # Valuables & Cores
    "ruby": {"name": "Ruby", "id": "Ruby", "price": 1250, "category": "Valuables & Cores"},
    "sapphire": {"name": "Sapphire", "id": "Sapphire", "price": 3000, "category": "Valuables & Cores"},
    "emerald": {"name": "Emerald", "id": "Emerald", "price": 6250, "category": "Valuables & Cores"},
    "diamond": {"name": "Diamond", "id": "Diamond", "price": 12500, "category": "Valuables & Cores"},
    "gold_coin": {"name": "Gold Coin", "id": "GoldCoin", "price": 1, "category": "Valuables & Cores"},
    "dog_coin": {"name": "Dog Coin", "id": "DogCoin", "price": 150, "category": "Valuables & Cores"},
    "ancient_core": {"name": "Ancient Civilization Core", "id": "BossCivilizationCore", "price": 2500, "category": "Valuables & Cores"},
    "predator_core": {"name": "Predator Core", "id": "PredatorCore", "price": 2000, "category": "Valuables & Cores"},
    "ai_core": {"name": "AI Core", "id": "AIcore", "price": 3000, "category": "Valuables & Cores"}
}

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
        # Ensure unique index exists on player_uid for ON CONFLICT support even on existing tables
        await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_player_uid_idx ON users(player_uid)')
        await conn.close()
        logger.info("✅ Database initialized successfully with player_uid unique index.")
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
        logger.warning(f"Daily login skipped for {player_name}: DATABASE_URL or RCON_HOST missing.")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT discord_id, balance, last_daily FROM users WHERE player_uid = $1', str(player_uid))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        if row:
            last_daily = row['last_daily']
            if last_daily and now < last_daily + timedelta(hours=24):
                logger.info(f"Daily reward cooldown active for {player_name} (UID: {player_uid}). Last claimed: {last_daily}")
                return
            
            new_bal = (row['balance'] or 0) + DAILY_PACK_SHOP_POINTS
            await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE player_uid = $3', new_bal, now, str(player_uid))
            logger.info(f"Updated daily reward balance for registered user {player_name} to {new_bal}")
        else:
            dummy_discord_id = abs(hash(str(player_uid))) % (10**15)
            new_bal = DAILY_PACK_SHOP_POINTS
            await conn.execute('''
                INSERT INTO users (discord_id, player_uid, balance, last_daily)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (player_uid) DO UPDATE SET last_daily = $4, balance = users.balance + $3
            ''', dummy_discord_id, str(player_uid), new_bal, now)
            logger.info(f"Created auto-profile and granted daily reward for unregistered player {player_name} (UID: {player_uid})")

        # Deliver daily items via RCON
        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            for item in DAILY_PACK_ITEMS:
                res = await rcon.send(f"give {player_uid} {item['rcon_id']} {item['quantity']}")
                logger.info(f"RCON give response for {item['rcon_id']} to {player_uid}: {res}")
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
                        logger.info(f"Initialized player tracker. Currently online players: {len(current_ids)}")
                        for pid, pname in current_players_map.items():
                            asyncio.create_task(process_login_daily(pid, pname))
                    else:
                        joined_ids = current_ids - known_online_players
                        left_ids = known_online_players - current_ids

                        for jid in joined_ids:
                            name = current_players_map.get(jid, "A player")
                            logger.info(f"Player join detected: {name} ({jid})")
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
                            logger.info(f"Player leave detected: {name} ({lid})")
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
# 6. Automated Background Restart & Save Loop (1 min pre-save)
# -------------------------------------------------------------
async def automated_restart_loop():
    await bot.wait_until_ready()
    # Configure restart interval (Default: every 6 hours)
    RESTART_INTERVAL_HOURS = 6
    
    while not bot.is_closed():
        await asyncio.sleep(RESTART_INTERVAL_HOURS * 3600)
        if not RCON_HOST or not ADMIN_PASSWORD: continue
        
        try:
            logger.info("Starting automated server restart sequence...")
            total_countdown = 300 # 5 minutes warning total
            
            # 1. Broadcast initial restart warning
            async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
                await rcon.send(f"Broadcast Automated_server_restart_in_{total_countdown}_seconds!")
            
            # 2. Wait until exactly 1 minute remains
            sleep_duration = total_countdown - 60
            await asyncio.sleep(sleep_duration)
            
            # 3. Automatically save the server 1 minute before restart
            logger.info("Executing automatic world save 1 minute before restart...")
            async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
                await rcon.send("Save")
                await rcon.send("Broadcast Server_world_saved._Shutting_down_in_60_seconds!")
            
            # 4. Wait the final 60 seconds
            await asyncio.sleep(60)
            
            # 5. Clean shutdown
            async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
                await rcon.send("Shutdown 1 Automated_Restart_Shutdown")
            
            logger.info("Automated restart sequence completed successfully. World was safely saved 1 minute prior.")
        except Exception as e:
            logger.error(f"Automated restart loop error: {e}")

# -------------------------------------------------------------
# 7. Shop Pagination View UI
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
        embed = discord.Embed(title="🛒 Palworld 1.0 Complete Item Shop", color=discord.Color.blue())
        start = self.current_page * self.per_page
        for item_id, data in self.items[start:start + self.per_page]:
            embed.add_field(name=f"{data['name']} (`{item_id}`)", value=f"Price: 🪙 **{data['price']} points**\nCategory: {data['category']}", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages + 1} | Use !buy <item_key> <quantity>")
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
# 8. Discord Commands & Event Listeners
# -------------------------------------------------------------
@bot.event
async def on_ready():
    await init_db()
    logger.info(f"✅ Bot connected as {bot.user}")
    if not getattr(bot, "tasks_started", False):
        bot.tasks_started = True
        bot.loop.create_task(poll_palworld_players_loop())
        bot.loop.create_task(playtime_reward_loop())
        bot.loop.create_task(automated_restart_loop())

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
        row = await conn.fetchrow('SELECT player_uid, balance, last_daily FROM users WHERE discord_id = $1', ctx.author.id)
        if not row or not row['player_uid']: 
            return await ctx.send("❌ Use `!register <PlayerUID>` first!")
        
        balance, last_daily, player_uid = row['balance'], row['last_daily'], row['player_uid']
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if last_daily and now < last_daily + timedelta(days=1):
            return await ctx.send("⏳ You must wait 24 hours between claims.")
        
        new_bal = balance + DAILY_PACK_SHOP_POINTS
        await conn.execute('UPDATE users SET balance = $1, last_daily = $2 WHERE discord_id = $3', new_bal, now, ctx.author.id)
        
        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            for item in DAILY_PACK_ITEMS:
                await rcon.send(f"give {player_uid} {item['rcon_id']} {item['quantity']}")
        
        await ctx.send(f"💰 Claimed **{DAILY_PACK_SHOP_POINTS} shop points** & daily pack items delivered! Balance: {new_bal}")
    except Exception as e:
        logger.error(f"Manual daily claim error: {e}")
        await ctx.send(f"❌ Error claiming daily reward via RCON: {e}")
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
            response = await rcon.send(f"give {row['player_uid']} {item['id']} {quantity}")
            logger.info(f"RCON Give Response: {response}")
        
        new_bal = row['balance'] - cost
        await conn.execute('UPDATE users SET balance = $1 WHERE discord_id = $2', new_bal, ctx.author.id)
        await ctx.send(f"✅ Purchased {quantity}x **{item['name']}**! New balance: {new_bal}")
    except Exception as e:
        logger.error(f"RCON delivery failed for item {item_key} on host {RCON_HOST}:{RCON_PORT} -> {e}")
        await ctx.send(f"❌ Delivery failed: Could not connect to game server RCON. Please verify your RCON IP and port.")
    finally:
        await conn.close()

@bot.command(name="save")
@commands.has_permissions(administrator=True)
async def server_save(ctx):
    if not RCON_HOST or not ADMIN_PASSWORD:
        return await ctx.send("❌ RCON configuration missing.")
    try:
        async with GameRCON(RCON_HOST, RCON_PORT, ADMIN_PASSWORD, timeout=10) as rcon:
            res = await rcon.send("Save")
            logger.info(f"RCON Save response: {res}")
        await ctx.send("💾 Server world saved successfully!")
    except Exception as e:
        logger.error(f"Save command failed: {e}")
        await ctx.send(f"❌ Failed to save server: {e}")

# -------------------------------------------------------------
# 9. Web Server & Main
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
