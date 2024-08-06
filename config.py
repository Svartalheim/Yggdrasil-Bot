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

    @staticmethod
    def get_secret(key: str) -> str | int | None:
        with open(getenv(key), 'r') as a:
            return a.read()

    TOKEN: str = get_secret('TOKEN')

    LAVALINK_SERVER: str = getenv("LAVALINK_SERVER")
    LAVALINK_PASSWORD: str = getenv("LAVALINK_PASSWORD")

    KANTIN_YOYOK_ID: int = int(getenv("KANTIN_YOYOK_ID"))