import os
import asyncio
import logging
from aiohttp import web
import discord
from discord.ext import commands, tasks
from gamercon_async import GameRcon
from supabase import create_client, Client

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("PalworldBot")

# --- Environment Configuration ---
TOKEN = os.getenv("DISCORD_TOKEN")
RCON_HOST = os.getenv("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.getenv("RCON_PORT", 25575))
RCON_PASSWORD = os.getenv("RCON_PASSWORD", "your_rcon_password")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Connected to Supabase successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase: {e}")

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Expanded Palworld 1.0 Item Database ---
SHOP_ITEMS = {
    # Pal Spheres
    "pal_sphere": {"name": "Pal Sphere", "id": "PalSphere", "price": 100},
    "mega_sphere": {"name": "Mega Sphere", "id": "Megasphere", "price": 300},
    "giga_sphere": {"name": "Giga Sphere", "id": "Gigasphere", "price": 800},
    "hyper_sphere": {"name": "Hyper Sphere", "id": "Hypersphere", "price": 2000},
    "ultra_sphere": {"name": "Ultra Sphere", "id": "Ultisphere", "price": 5000},
    "legendary_sphere": {"name": "Legendary Sphere", "id": "MasterSphere", "price": 12000},
    "ancient_sphere": {"name": "Ancient Sphere", "id": "AncientSphere", "price": 15000},

    # Ores & Raw Materials
    "stone": {"name": "Stone", "id": "Stone", "price": 2},
    "wood": {"name": "Wood", "id": "Wood", "price": 2},
    "fiber": {"name": "Fiber", "id": "Fiber", "price": 3},
    "paldium": {"name": "Paldium Fragment", "id": "Palium_Ore", "price": 25},
    "ore": {"name": "Ore", "id": "Ore", "price": 15},
    "coal": {"name": "Coal", "id": "Coal", "price": 40},
    "sulfur": {"name": "Sulfur", "id": "Sulfur", "price": 50},
    "quartz": {"name": "Pure Quartz", "id": "Quartz", "price": 75},
    "organic_oil": {"name": "High Quality Pal Oil", "id": "HighQualityPalOil", "price": 100},
    "leather": {"name": "Leather", "id": "Leather", "price": 50},
    "bone": {"name": "Bone", "id": "Bone", "price": 40},
    "horn": {"name": "Horn", "id": "Horn", "price": 40},
    "venom_gland": {"name": "Venom Gland", "id": "VenomGland", "price": 30},
    "electric_organ": {"name": "Electric Organ", "id": "ElectricOrgan", "price": 60},
    "magma_organ": {"name": "Flame Organ", "id": "FlameOrgan", "price": 60},
    "ice_organ": {"name": "Ice Organ", "id": "IceOrgan", "price": 60},

    # Ingots & Advanced Metals
    "ingot": {"name": "Ingot", "id": "Ingot", "price": 50},
    "refined_ingot": {"name": "Refined Ingot", "id": "RefinedIngot", "price": 150},
    "pal_metal_ingot": {"name": "Pal Metal Ingot", "id": "PalMetalIngot", "price": 500},
    "soralite_ingot": {"name": "Soralite Ingot", "id": "SoraliteIngot", "price": 1200},
    "paloxite_ingot": {"name": "Paloxite Ingot", "id": "PaloxiteIngot", "price": 1500},
    "carbon_fiber": {"name": "Carbon Fiber", "id": "CarbonFiber", "price": 200},
    "polymer": {"name": "Polymer", "id": "Polymer", "price": 300},
    "cement": {"name": "Cement", "id": "Cement", "price": 100},

    # Weapons & Spears
    "stone_spear": {"name": "Stone Spear", "id": "Spear", "price": 150},
    "metal_spear": {"name": "Metal Spear", "id": "Spear_Metal", "price": 1200},
    "refined_metal_spear": {"name": "Refined Metal Spear", "id": "Spear_RefinedMetal", "price": 3500},
    "lilys_spear": {"name": "Lily's Spear", "id": "Spear_ForestBoss", "price": 10000},
    "primitive_sword": {"name": "Primitive Sword", "id": "Sword", "price": 5000},
    "laser_sword": {"name": "Beam Sword", "id": "BeamSword", "price": 15000},
    "assault_rifle": {"name": "Assault Rifle", "id": "AssaultRifle", "price": 25000},
    "rocket_launcher": {"name": "Rocket Launcher", "id": "RocketLauncher", "price": 50000},

    # Ammunition
    "arrow": {"name": "Arrow", "id": "Arrow", "price": 5},
    "coarse_ammo": {"name": "Coarse Ammo", "id": "RoughBullet", "price": 10},
    "handgun_ammo": {"name": "Handgun Ammo", "id": "HandgunBullet", "price": 15},
    "rifle_ammo": {"name": "Assault Rifle Ammo", "id": "AssaultRifleBullet", "price": 25},
    "shotgun_ammo": {"name": "Shotgun Shells", "id": "ShotgunBullet", "price": 30},
    "rocket_ammo": {"name": "Rocket Ammo", "id": "RocketBullet", "price": 500},

    # Foods & Consumables
    "red_berries": {"name": "Red Berries", "id": "RedBerries", "price": 10},
    "baked_berries": {"name": "Baked Berries", "id": "BakedBerries", "price": 20},
    "bread": {"name": "Bread", "id": "Bread", "price": 50},
    "jam_bun": {"name": "Jam-Filled Bun", "id": "JamBun", "price": 80},
    "cake": {"name": "Cake", "id": "Cake", "price": 1000},
    "salad": {"name": "Salad", "id": "Salad", "price": 500},
    "pizza": {"name": "Pizza", "id": "Pizza", "price": 800},

    # Cores & Valuables
    "ruby": {"name": "Ruby", "id": "Ruby", "price": 2500},
    "sapphire": {"name": "Sapphire", "id": "Sapphire", "price": 5000},
    "emerald": {"name": "Emerald", "id": "Emerald", "price": 7500},
    "diamond": {"name": "Diamond", "id": "Diamond", "price": 15000},
    "dog_coin": {"name": "Dog Coin", "id": "DogCoin", "price": 50},
    "ancient_core": {"name": "Ancient Civilization Core", "id": "BossCivilizationCore", "price": 10000},
    "predator_core": {"name": "Predator Core", "id": "PredatorCore", "price": 8000},
    "ai_core": {"name": "AI Core", "id": "AIcore", "price": 12000}
}

# --- RCON Helper Function ---
async def send_rcon_command(command: str) -> str:
    try:
        async with GameRcon(RCON_HOST, RCON_PORT, RCON_PASSWORD, timeout=5) as rcon:
            response = await rcon.send(command)
            return response
    except Exception as e:
        logger.error(f"RCON Error executing '{command}': {e}")
        return f"Error connecting to game server: {e}"

# --- Bot Events ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("Palworld shop database successfully synchronized with 1.0 item definitions.")

# --- Shop Commands ---
@bot.command(name="shop")
async def shop_list(ctx):
    """Displays available items in the Palcon shop."""
    embed = discord.Embed(
        title="🛒 Palcon In-Game Shop (Palworld 1.0 Database)",
        description="Use `!buy <item_key> <quantity>` to purchase items directly to your inventory.",
        color=discord.Color.blurple()
    )
    
    categories = {
        "Spheres": ["pal_sphere", "mega_sphere", "giga_sphere", "hyper_sphere", "ultra_sphere", "legendary_sphere", "ancient_sphere"],
        "Ores & Materials": ["stone", "wood", "fiber", "paldium", "ore", "coal", "sulfur", "quartz", "organic_oil", "leather"],
        "Ingots & Metals": ["ingot", "refined_ingot", "pal_metal_ingot", "soralite_ingot", "paloxite_ingot", "carbon_fiber", "polymer"],
        "Weapons & Spears": ["stone_spear", "metal_spear", "refined_metal_spear", "lilys_spear", "primitive_sword", "laser_sword", "assault_rifle", "rocket_launcher"],
        "Ammunition": ["arrow", "coarse_ammo", "handgun_ammo", "rifle_ammo", "shotgun_ammo", "rocket_ammo"],
        "Food & Consumables": ["red_berries", "baked_berries", "bread", "jam_bun", "cake", "salad", "pizza"],
        "Valuables & Cores": ["ruby", "sapphire", "emerald", "diamond", "dog_coin", "ancient_core", "predator_core", "ai_core"]
    }

    for cat_name, keys in categories.items():
        item_lines = []
        for k in keys:
            if k in SHOP_ITEMS:
                item = SHOP_ITEMS[k]
                item_lines.append(f"`{k}`: **{item['name']}** — {item['price']} pts")
        if item_lines:
            embed.add_field(name=cat_name, value="\n".join(item_lines), inline=False)

    await ctx.send(embed=embed)

@bot.command(name="buy")
async def buy_item(ctx, item_key: str, quantity: int = 1):
    """Purchases an item from the shop using shop points."""
    item_key = item_key.lower()
    if item_key not in SHOP_ITEMS:
        await ctx.send("❌ Invalid item key. Check `!shop` for available items.")
        return

    if quantity < 1:
        await ctx.send("❌ Quantity must be at least 1.")
        return

    item = SHOP_ITEMS[item_key]
    total_cost = item["price"] * quantity

    if not supabase:
        await ctx.send("❌ Database connection unavailable.")
        return

    try:
        # Check user points in Supabase
        res = supabase.table("player_points").select("points").eq("discord_id", str(ctx.author.id)).execute()
        if not res.data:
            await ctx.send("❌ You don't have a linked account or any shop points yet.")
            return

        current_points = res.data[0]["points"]
        if current_points < total_cost:
            await ctx.send(f"❌ You need **{total_cost}** points, but you only have **{current_points}** points.")
            return

        # Deduct points & deliver item via RCON
        new_points = current_points - total_cost
        supabase.table("player_points").update({"points": new_points}).eq("discord_id", str(ctx.author.id)).execute()

        # Retrieve player's in-game SteamID/UID if mapped in database
        link_res = supabase.table("player_links").select("game_id").eq("discord_id", str(ctx.author.id)).execute()
        if link_res.data:
            game_id = link_res.data[0]["game_id"]
            await send_rcon_command(f"give {game_id} {item['id']} {quantity}")
            await ctx.send(f"✅ Successfully purchased **{quantity}x {item['name']}** for **{total_cost}** points and delivered to your game inventory!")
        else:
            await ctx.send(f"⚠️ Points deducted, but your Discord account isn't linked to a game ID. Contact an admin.")

    except Exception as e:
        logger.error(f"Error processing purchase: {e}")
        await ctx.send("❌ An error occurred while processing your purchase.")

# --- Web Server Keep-Alive for Render ---
async def handle_ping(request):
    return web.Response(text="Palworld Discord Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server keep-alive listening on port {port}")

async def main():
    await start_web_server()
    if TOKEN:
        await bot.start(TOKEN)
    else:
        logger.error("DISCORD_TOKEN environment variable not set.")

if __name__ == "__main__":
    asyncio.run(main())
