import os
import csv
import sys
import discord
from discord.ext import commands

# -------------------------------------------------------------
# Environment & Configuration (Fail-safe)
# -------------------------------------------------------------
RCON_HOST = os.getenv("RCON_HOST", "167.114.174.145")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

def get_rcon_port() -> int:
    """Safely converts RCON_PORT env var to int without crashing on empty values."""
    port_str = os.getenv("RCON_PORT", "").strip()
    if not port_str:
        return 25575  # Default Palworld RCON port
    try:
        return int(port_str)
    except ValueError:
        print(f"[WARNING] Invalid RCON_PORT '{port_str}', defaulting to 25575", flush=True)
        return 25575

# -------------------------------------------------------------
# RCON Helper Functions
# -------------------------------------------------------------
async def send_rcon_command(command: str) -> str:
    """Sends an RCON command to the Palworld server safely."""
    if not ADMIN_PASSWORD:
        print("[RCON ERROR] ADMIN_PASSWORD environment variable is missing!", flush=True)
        return ""
    
    try:
        from gamercon_async import GameRCON
        port = get_rcon_port()
        async with GameRCON(RCON_HOST, port, ADMIN_PASSWORD, timeout=10) as rcon:
            response = await rcon.send(command)
            return response.strip()
    except Exception as e:
        print(f"[RCON ERROR] Failed to run '{command}': {e}", flush=True)
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
# Discord Commands
# -------------------------------------------------------------
# (Attach these to your existing 'bot' or 'client' instance)

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
