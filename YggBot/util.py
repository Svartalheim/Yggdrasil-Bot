from datetime import datetime
from logging import (
    Logger,
    getLogger,
    INFO,
    StreamHandler
)

from pytz import timezone

from discord import (
    Embed,
    Emoji,
    Interaction,
    Message,
    InteractionResponded,
    MessageFlags
)
from discord.utils import _ColourFormatter
from discord.ui import View

from config import YggConfig


class YggUtil:

    @staticmethod
    def convert_color(color: str) -> int:
        return int(color.lstrip("#"), 16)

    @staticmethod
    def get_time() -> datetime:
        return datetime.now(timezone(YggConfig.TIMEZONE))

    @staticmethod
    def truncate_string(text: str, /, max: int = 150) -> str:
        if len(text) > max:
            return text[:max-3] + "..."
        return text

    @staticmethod
    def setup_log():
        logger: Logger = getLogger(YggConfig.BOT_NAME)
        logger.setLevel(INFO)

        handler = StreamHandler()
        handler.setFormatter(_ColourFormatter())
        logger.addHandler(handler)

    @staticmethod
    def simple_log(message: str):
        logger: Logger = getLogger(YggConfig.BOT_NAME)
        logger.info(message)

    @staticmethod
    async def send_response(
        interaction: Interaction,
        /,
        message: str = None,
        embed: Embed = None,
        emoji: Emoji | str = None,
        view: View = None,
        ephemeral: bool = False,
    ) -> Message:
        msg: Message = None
        temp: str = str()

        if not view:
            view = View()

        def change_emoji(
            message: str, emoji: Emoji | str, ephemeral: bool = False
        ) -> str:
            if isinstance(emoji, str) and ephemeral:
                return f"{emoji} {message}"

            if isinstance(emoji, Emoji):
                return f"{str(emoji)} {message}"

            return message

        try:
            temp = change_emoji(message, emoji, ephemeral)
            await interaction.response.send_message(
                temp, embed=embed, ephemeral=ephemeral, view=view
            )
            msg = await interaction.original_response()
        except InteractionResponded:
            msg = await interaction.original_response()
            flags: MessageFlags = msg.flags
            ephemeral = flags.ephemeral

            temp = change_emoji(message, emoji, ephemeral)

            msg = await interaction.followup.send(
                temp, embed=embed, ephemeral=ephemeral, view=view, wait=True
            )

        if emoji and not ephemeral:
            await msg.add_reaction(emoji)

        return msg
