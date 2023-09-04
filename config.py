from os import getenv
from dotenv import load_dotenv

load_dotenv()

class YggConfig:
    BOT_NAME = "Yggdrasil Bot"
    BOT_PREFIX = "!ygg"
    TIMEZONE = "Asia/Jakarta"
    COLOR = {"success": "198754", "failed": "CA0B00", "general": "E49B0F"}
    TOKEN = getenv("TOKEN")
    SPOTIFY_CLIENT = getenv("SPOTIFY_CLIENT")
    SPOTIFY_SECRET = getenv("SPOTIFY_SECRET")
    LAVALINK_SERVER = getenv("LAVALINK_SERVER")
    LAVALINK_PASSWORD = getenv("LAVALINK_PASSWORD")
