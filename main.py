from discord import (
    Intents,
    Embed,
    Interaction,
    Activity,
    ActivityType,
)
from discord.app_commands import guild_only
from discord.ext import commands, tasks
from wavelink import Node, NodePool
from config import YggConfig
from wavelink.ext.spotify import SpotifyClient
from random import choice
from YggBot import YggUtil
from discord import Status


class YggTask:
    async def _begin_loop_task(self):
        if not self._change_activity.is_running():
            self._change_activity.start()

    @staticmethod
    async def _connect_nodes(bot: commands.Bot) -> None:
        await bot.wait_until_ready()
        sc: SpotifyClient = SpotifyClient(
            client_id=YggConfig.SPOTIFY_CLIENT, client_secret=YggConfig.SPOTIFY_SECRET
        )
        node: Node = Node(
            uri=YggConfig.LAVALINK_SERVER, password=YggConfig.LAVALINK_PASSWORD
        )
        await NodePool.connect(client=bot, nodes=[node], spotify=sc)

    @tasks.loop(seconds=60)
    async def _change_activity(self) -> None:
        await bot.wait_until_ready()
        member_count: int = len([x for x in self.get_all_members()])

        async def a() -> None:
            await self.change_presence(
                status=Status.idle,
                activity=Activity(
                    type=ActivityType.playing,
                    name=f"with {member_count} Disciple",
                )
            )

        async def b() -> None:
            await self.change_presence(
                status=Status.idle,
                activity=Activity(
                    type=ActivityType.listening,
                    name=f"you",
                )
            )

        async def c() -> None:
            competing_list=["Hell Like Heaven", "\"Flower on a High Peak\"", "Obscurity"]
            await self.change_presence(
                status=Status.idle,
                activity=Activity(
                    type=ActivityType.competing,
                    name=choice(competing_list),
                )
            )
            
        async def d() -> None:
            watching_list=["Ragnarok", "Dramaturgy"]
            await self.change_presence(
                status=Status.idle,
                activity=Activity(
                    type=ActivityType.watching,
                    name=choice(watching_list),
                )
            )
            
        async def e() -> None:
            await self.change_presence(
                status=Status.idle,
                activity=Activity(
                    type=ActivityType.listening,
                    name="Ignorance is Bliss",
                )
            )

        await choice([a, b, c, d, e])()


class YggBase(commands.Bot):
    async def _help_embed(self, server_name, bot_name) -> Embed:
        desc: str = f"Here's a few feature that's available on {server_name}."
        embed: Embed = Embed(
            title=f"Commands for {server_name}",
            description=desc,
            color=YggUtil.convert_color(YggConfig.COLOR["general"]),
        )

        for command in await self.tree.fetch_commands():
            embed.add_field(
                name=f"**/{command.name}**", value=command.description, inline=True
            )
        embed.set_author(name=self.user.name, icon_url=self.user.display_avatar)
        embed.set_footer(
            text=f" © {bot_name} • Still under develop, if there is something wrong contact @svartalheim"
        )
        return embed


class YggClient(YggBase, YggTask):
    def __init__(self) -> None:
        intents: Intents = Intents.default()
        intents.members = True

        super().__init__(YggConfig.BOT_PREFIX, intents=intents)

        self.synced: bool = False

    async def setup_hook(self) -> None:
        YggUtil.setup_log()

        self.loop.create_task(self._connect_nodes(self))

        await self.load_extension("YggBot.command")

        return await super().setup_hook()

    async def on_ready(self) -> None:
        YggUtil.simple_log(
            f"Logged as {self.user.name}, {self.user.id}, Member count: {len([x for x in self.get_all_members()])}"
        )

        if not self.synced:
            await self.tree.sync()
            self.synced = True

        await self._begin_loop_task()


bot: commands.Bot = YggClient()


@bot.tree.command(name="help", description="Help user to find command")
@guild_only()
async def _help(interaction: Interaction) -> None:
    YggUtil.simple_log(f"{interaction.guild.me.name} AKA {interaction.guild.me.nick}")
    bot_name = ""
    if interaction.guild.me.nick is None:
        bot_name = interaction.guild.me.name
    else:
        bot_name = f"{interaction.guild.me.name} AKA {interaction.guild.me.nick}"
    await YggUtil.send_response(
        interaction,
        embed=await bot._help_embed(
            interaction.guild.name,
            bot_name,
        ),
  
    )


bot.run(token=YggConfig.TOKEN.strip())
