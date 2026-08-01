import asyncio
import csv
import logging
import os
import sys
from aiohttp import web
import discord
from discord.ext import commands

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
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
RCON_HOST = os.getenv("RCON_HOST", "167.114.174.145").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
WEB_PORT = int(os.getenv("PORT", "10000"))  # Default Render HTTP port


def get_rcon_port() -> int:
    """Safely converts RCON_PORT env var to int without crashing."""
    port_str = os.getenv("RCON_PORT", "").strip()
    if not port_str:
        return 25575  # Standard Palworld RCON port
    try:
        return int(port_str)
    except ValueError:
        logger.warning(f"Invalid RCON_PORT '{port_str}', defaulting to 25575")
        return 25575

# -------------------------------------------------------------
# 2. Discord Bot Instance Initialization
# -------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------------------------------------
# 3. RCON Helper Functions
# -------------------------------------------------------------
async def send_rcon_command(command: str) -> str:
    """Sends an RCON command to the Palworld server safely."""
    if not ADMIN_PASSWORD:
        logger.error("ADMIN_PASSWORD environment variable is missing!")
        return ""

    try:
        from gamercon_async import GameRCON
        port = get_rcon_port()
        async with GameRCON(RCON_HOST, port, ADMIN_PASSWORD, timeout=10) as rcon:
            response = await rcon.send(command)
            return response.strip()
    except Exception as e:
        logger.error(f"Failed to execute RCON command '{command}': {e}")
        return ""


async def get_online_players_rcon() -> list[dict]:
    """Fetches online players via RCON 'ShowPlayers'."""
    raw_response = await send_rcon_command("ShowPlayers")
    if not raw_response:
        return []

    players = []
    lines = [line.strip() for line in raw_response.splitlines() if line.strip()]

    if len(lines) > 1:
        reader = csv.DictReader(lines)
        for row in reader:
            name = row.get("name", "").strip()
            uid = row.get("playeruid", "").strip()
            steamid = row.get("steamid", "").strip()
            if name:
                players.append({"name": name, "playeruid": uid, "steamid": steamid})

    return players


async def broadcast_announcement_rcon(message: str) -> bool:
    """Broadcasts an in-game message via RCON 'Broadcast'."""
    formatted_msg = message.replace(" ", "_")
    response = await send_rcon_command(f"Broadcast {formatted_msg}")
    return bool(response)

# -------------------------------------------------------------
# 4. Discord Bot Events & Commands
# -------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"✅ Discord Bot connected successfully as {bot.user} (ID: {bot.user.id})")


@bot.command(name="players")
async def list_players(ctx):
    """Lists online players using RCON."""
    players = await get_online_players_rcon()

    if not players:
        await ctx.send("🎮 **Server Status:** No players currently online (or RCON unreachable).")
        return

    player_list = "\n".join([f"• **{p['name']}** (UID: `{p['playeruid']}`)" for p in players])

    embed = discord.Embed(
        title=f"Online Players ({len(players)})",
        description=player_list,
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)


@bot.command(name="announce")
@commands.has_permissions(administrator=True)
async def announce_ingame(ctx, *, message: str):
    """Sends a message to in-game players via RCON."""
    success = await broadcast_announcement_rcon(f"[Discord] {message}")
    if success:
        await ctx.send(f"✅ In-game broadcast sent: **{message}**")
    else:
        await ctx.send("❌ Failed to send in-game broadcast via RCON.")

# -------------------------------------------------------------
# 5. Render HTTP Server (Prevents Render Health Check Timeouts)
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
    logger.info(f"🌐 Health check web server running on port {WEB_PORT}")

# -------------------------------------------------------------
# 6. Main Execution Loop
# -------------------------------------------------------------
async def main():
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN environment variable is missing!")
        sys.exit(1)

    # Start the dummy HTTP server for Render health checks
    await start_web_server()

    # Launch Discord Bot
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually stopped.")
    except Exception as e:
        logger.critical(f"Fatal startup error: {e}")
        sys.exit(1)
