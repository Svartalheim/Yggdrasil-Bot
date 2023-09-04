from typing import Union
from logging import Logger, getLogger, INFO, StreamHandler
from discord import (
    Embed,
    Emoji,
    Interaction,
    Message,
    InteractionResponded,
    MessageFlags,
)
from discord.utils import _ColourFormatter
from discord.ui import View
from config import YggConfig
from datetime import datetime
from pytz import timezone


class YggUtil:
    @classmethod
    def convert_color(cls, color: str) -> int:
        return int(color.lstrip("#"), 16)

    @classmethod
    def get_time(cls) -> datetime:
        return datetime.now(timezone(YggConfig.TIMEZONE))

    @classmethod
    def setup_log(cls):
        logger: Logger = getLogger(YggConfig.BOT_NAME)
        logger.setLevel(INFO)

        handler = StreamHandler()
        handler.setFormatter(_ColourFormatter())
        logger.addHandler(handler)

    @classmethod
    def simple_log(cls, message: str):
        logger: Logger = getLogger(YggConfig.BOT_NAME)
        logger.info(message)

    @classmethod
    async def send_response(
        cls,
        interaction: Interaction,
        /,
        message: str = None,
        embed: Embed = None,
        emoji: Union[Emoji, str] = None,
        view: View = None,
        ephemeral: bool = False,
    ) -> Message:
        msg: Message = None
        temp: str = str()

        if not view:
            view = View()

        def change_emoji(
            message: str, emoji: Union[Emoji, str], ephemeral: bool = False
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
