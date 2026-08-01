import os
import csv
from gamercon_async import GameRCON

# RCON Credentials from Environment
RCON_HOST = os.getenv("RCON_HOST", "167.114.174.145")
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))  # Default RCON port for Palworld
RCON_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


async def send_rcon_command(command: str) -> str:
    """Sends an RCON command to the Palworld server and returns the response."""
    if not RCON_PASSWORD:
        print("[RCON ERROR] ADMIN_PASSWORD environment variable is missing!", flush=True)
        return ""
    
    try:
        async with GameRCON(RCON_HOST, RCON_PORT, RCON_PASSWORD, timeout=10) as rcon:
            response = await rcon.send(command)
            return response.strip()
    except Exception as e:
        print(f"[RCON ERROR] Failed to run '{command}': {e}", flush=True)
        return ""


async def get_online_players_rcon() -> list[dict]:
    """
    Fetches online players via RCON 'ShowPlayers' command.
    Returns a list of dicts: [{'name': '...', 'playeruid': '...', 'steamid': '...'}]
    """
    raw_response = await send_rcon_command("ShowPlayers")
    if not raw_response:
        return []

    players = []
    lines = [line.strip() for line in raw_response.splitlines() if line.strip()]
    
    # Palworld ShowPlayers returns CSV data: name,playeruid,steamid
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
    """
    Broadcasts an in-game message via RCON 'Broadcast'.
    Note: Palworld RCON requires underscores instead of spaces in some builds.
    """
    # Replace spaces with underscores to prevent word truncation
    formatted_msg = message.replace(" ", "_")
    response = await send_rcon_command(f"Broadcast {formatted_msg}")
    return bool(response)
