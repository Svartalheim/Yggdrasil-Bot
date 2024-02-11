from os import getenv
# from dotenv import load_dotenv

# load_dotenv()

class YggConfig:
    BOT_NAME: str = "Yggdrasil Bot"
    BOT_PREFIX: str = "!ygg"
    TIMEZONE: str = "Asia/Jakarta"
    
    class Color:
        SUCCESS: str = "198754"
        FAILED: str = "CA0B00"
        GENERAL: str = "E49B0F"
    TOKEN = getenv("TOKEN")

    LAVALINK_SERVER = getenv("LAVALINK_SERVER")
    LAVALINK_PASSWORD = getenv("LAVALINK_PASSWORD")

    KANTIN_YOYOK_ID = int(getenv("KANTIN_YOYOK_ID"))