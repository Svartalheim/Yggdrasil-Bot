from asyncio import wait, create_task, gather
from datetime import timedelta
from typing import Union

from discord import Interaction, Embed
from discord.ext import commands
from discord.app_commands import (
    Choice,
    AppCommandError,
    describe,
    choices,
    command,
    guild_only,
    CheckFailure,
)
from discord.ui import View

from wavelink import Playable, Player, Playlist, QueueEmpty
from wavelink.ext.spotify import SpotifyTrack

from .util import YggUtil
from .player import MusicPlayerBase, MusicPlayer, TrackType
from config import YggConfig


async def setup(bot: commands.Bot) -> None:
    cog_tasks = [
        bot.add_cog(Multimedia(bot))
    ]
    await gather(*cog_tasks)

    YggUtil.simple_log("Cog loaded")


@guild_only()
class Multimedia(commands.Cog, MusicPlayer):

    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self._timeout_check.is_running():
            self._timeout_check.start()

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.command is not (self._queue):
            self._record_timestamp(guild_id=interaction.guild_id,
                                   interaction=interaction)

        return super().interaction_check(interaction)

    @command(name="join", description="Join an voice channel")
    @MusicPlayerBase._is_user_join_checker()
    async def _join(self, interaction: Interaction) -> None:
        await wait([
            create_task(self.join(interaction)),
            create_task(YggUtil.send_response(
                interaction, message="Joined", emoji="✅", ephemeral=True))
        ])

    @command(name="leave", description="Leave the voice channel")
    @MusicPlayerBase._is_user_join_checker()
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    async def _leave(self, interaction: Interaction) -> None:
        await wait([
            create_task(self.leave(interaction)),
            create_task(YggUtil.send_response(
                interaction, message="Succesfully Disconnected ", emoji="✅", ephemeral=True))
        ])

    @command(name="search", description="Search your track by query")
    @describe(query="Track keyword(You can pass through playlist to pick on it)", 
              source="Get track from different source(Default is Youtube, Spotify will automatically convert into Youtube)",
              autoplay="Autoplay recomendation from you've been played(Soundcloud not supported)")
    @choices(autoplay=[
        Choice(name='True', value=1),
        Choice(name='False', value=0)])
    @MusicPlayerBase._is_user_join_checker()
    @MusicPlayerBase._is_user_allowed()
    async def _search(self, interaction: Interaction, query: str, source: TrackType = TrackType.YOUTUBE, autoplay: Choice[int] = 0) -> None:
        await interaction.response.defer()
        convert_autoplay: bool = False
        view: View = View()
        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.COLOR['failed']))
        
        autoplay = Choice(
            name="None", value=None) if autoplay == 0 else autoplay
        
        if autoplay.value == None:
            convert_autoplay = None

        if autoplay.value == 1:
            convert_autoplay = True

        try:
            embed, view = await self.search(query=query, user=interaction.user, source=source, autoplay=convert_autoplay)
        except IndexError:
            embed.description = "❌ Track not found, check your keyword or source"

        await YggUtil.send_response(interaction, embed=embed, view=view)

    @command(name="play", description="To play a track from Youtube/Soundcloud/Spotify")
    @describe(query="Youtube/Soundcloud/Spotify link or keyword",
              source="(OPTIONAL, still working without selecting any of this) Get track from different source(Default is Youtube, Spotify will automatically convert into Youtube)",
              autoplay="(OPTIONAL) Autoplay recomendation from you've been played(Soundcloud not supported)",
              force_play="(OPTIONAL) Force to play the track(Previous queue still saved)",
              put_front="(OPTIONAL) Put track on front. Will play after current track end")
    @choices(autoplay=[
        Choice(name='True', value=1),
        Choice(name='False', value=0)],
        force_play=[
        Choice(name='True', value=1),
        Choice(name='False', value=0)],
        put_front=[
        Choice(name='True', value=1),
        Choice(name='False', value=0)])
    @MusicPlayerBase._is_user_join_checker()
    @MusicPlayerBase._is_user_allowed()
    async def _play(self, interaction: Interaction, query: str, source: TrackType = TrackType.YOUTUBE, autoplay: Choice[int] = 0, force_play: Choice[int] = 0, put_front: Choice[int] = 0) -> None:
        await interaction.response.defer()

        autoplay = Choice(
            name="None", value=None) if autoplay == 0 else autoplay
        force_play = Choice(
            name="None", value=None) if force_play == 0 else force_play
        put_front = Choice(
            name="None", value=None) if put_front == 0 else put_front

        convert_autoplay: bool = False
        convert_force_play: bool = False
        convert_put_front: bool = False
        track: Union[Playlist, Playable, SpotifyTrack] = None
        is_playlist = is_queued = False
        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.COLOR['failed']), description="❌ Track not found")

        if autoplay.value == None:
            convert_autoplay = None

        if autoplay.value == 1:
            convert_autoplay = True

        if force_play.value == 1:
            convert_force_play = True

        if put_front.value == 1:
            convert_put_front = True

        try:
            track, is_playlist, is_queued = await self.play(interaction,
                                                            query=query,
                                                            source=source,
                                                            autoplay=convert_autoplay,
                                                            force_play=convert_force_play,
                                                            put_front=convert_put_front)

            embed = await self._play_response(interaction.user, track=track, is_playlist=is_playlist, is_queued=is_queued, is_put_front=convert_put_front, is_autoplay=convert_autoplay, raw_uri=query)
        except IndexError:
            pass

        await YggUtil.send_response(interaction, embed=embed)

    @command(name="queue", description="Show current player queue")
    @describe(is_history="Show player history instead queue")
    @choices(is_history=[
        Choice(name='True', value=1),
        Choice(name='False', value=0)])
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _queue(self, interaction: Interaction, is_history: Choice[int] = 0) -> None:
        await interaction.response.defer(ephemeral=True)

        is_history = Choice(
            name="None", value=None) if is_history == 0 else is_history

        convert_is_history: bool = False
        embed: Embed = Embed(description="📪 No tracks found", color=YggUtil.convert_color(
            YggConfig.COLOR['failed']))
        view: View = None

        if is_history.value == 1:
            convert_is_history = True

        try:
            embed, view = await self.queue(interaction, is_history=convert_is_history)
        except QueueEmpty:
            pass

        await YggUtil.send_response(interaction, embed=embed, view=view)

    @command(name="skip", description="Skip current track")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _skip(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        embed: Embed = Embed(
            description="⏯️ Skipped",
            color=YggUtil.convert_color(YggConfig.COLOR['failed'])
        )

        await wait([
            create_task(self.skip(interaction)),
            create_task(YggUtil.send_response(interaction, embed=embed))
        ])

    @command(name="jump", description="Jump on specific music(Put selected track into front)")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _jump(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        view: View = View()
        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.COLOR['failed']))

        try:
            embed, view = await self.jump(interaction)
        except IndexError:
            embed.description = "📪 Queue is empty"

        await YggUtil.send_response(interaction, embed=embed, view=view)

    @command(name="previous", description="Play previous track(All queue still saved)")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _previous(self, interaction: Interaction) -> None:
        await interaction.response.defer()

        embed: Embed = Embed(
            description="⏮️ Previous",
            color=YggUtil.convert_color(YggConfig.COLOR['failed'])
        )

        was_allowed: bool = await self.previous(interaction)

        if not was_allowed:
            embed.description = "📪 History is empty"

        await YggUtil.send_response(interaction, embed=embed)

    @command(name="stop", description="Stop anything(This will reset player back to initial state)")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _stop(self, interaction: Interaction) -> None:
        await interaction.response.defer()

        embed: Embed = Embed(
            description="⏹️ Stopped",
            color=YggUtil.convert_color(YggConfig.COLOR['failed'])
        )

        await wait([
            create_task(self.stop(interaction)),
            create_task(YggUtil.send_response(interaction, embed=embed))
        ])

    @command(name="clear", description="Clear current queue(This will also disable Autoplay and any loop state)")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _clear(self, interaction: Interaction) -> None:
        await interaction.response.defer()

        embed: Embed = Embed(
            description="✅ Cleared",
            color=YggUtil.convert_color(YggConfig.COLOR['success'])
        )

        self.clear(interaction)
        await YggUtil.send_response(interaction, embed=embed)

    @command(name="shuffle", description="Shuffle current queue")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _shuffle(self, interaction: Interaction) -> None:
        await interaction.response.defer()

        embed: Embed = Embed(
            description="🔀 Shuffled",
            color=YggUtil.convert_color(YggConfig.COLOR['success'])
        )

        self.shuffle(interaction)
        await wait([
            create_task(YggUtil.send_response(interaction, embed=embed)),
            create_task(self._update_player(guild_id=interaction.guild_id))
        ])

    @command(name="now_playing", description="Show current playing track")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _now_playing(self, interaction: Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        player: Player = None
        time: int = int()

        player, time = self.now_playing(interaction)
        YggUtil.simple_log(player.current.duration)
        YggUtil.simple_log(time)
        embed: Embed = Embed(
            title="🎶 Now Playing",
            description=f"""**[{player.current.title}]({player.current.uri}) - {self._parseSec(player.current.duration)}** 
            \n** {str(timedelta(seconds=time//1000)).split('.')[0]} left**""",
            color=YggUtil.convert_color(YggConfig.COLOR['general'])
        )

        await YggUtil.send_response(interaction, embed=embed)

    @command(name="loop", description="Loop current track")
    @describe(is_queue="Loop current player queue, instead current track(History are included)")
    @choices(is_queue=[
        Choice(name='True', value=1),
        Choice(name='False', value=0)])
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _loop(self, interaction: Interaction, is_queue: Choice[int] = 0) -> None:
        await interaction.response.defer()
        loop = False

        is_queue = Choice(
            name="None", value=None) if is_queue == 0 else is_queue

        convert_is_queue: bool = False
        embed: Embed = Embed(
            color=YggUtil.convert_color(YggConfig.COLOR['success'])
        )

        if is_queue.value == 1:
            convert_is_queue = True

        loop = self.loop(interaction, is_queue=convert_is_queue)

        if not convert_is_queue:
            embed.description = "✅ Loop Track" if loop else "✅ Unloop Track"
        else:
            embed.description = "✅ Loop Queue" if loop else "✅ Unloop Queue"

        await wait([
            create_task(YggUtil.send_response(interaction, embed=embed)),
            create_task(self._update_player(guild_id=interaction.guild_id))
        ])

    @command(name="pause", description="Pause current track")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _pause(self, interaction: Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        embed: embed = Embed(
            description="⏸️ Paused",
            color=YggUtil.convert_color(YggConfig.COLOR['success'])
        )

        await wait([
            create_task(self.pause(interaction)),
            create_task(YggUtil.send_response(interaction, embed=embed)),
            create_task(self._update_player(guild_id=interaction.guild_id))
        ])

    @command(name="resume", description="Resume current track")
    @MusicPlayerBase._is_client_exist()
    @MusicPlayerBase._is_user_allowed()
    @MusicPlayerBase._is_playing()
    async def _resume(self, interaction: Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        embed: Embed = Embed(
            description="▶️ Resumed",
            color=YggUtil.convert_color(YggConfig.COLOR['success'])
        )

        res: bool = await self.resume(interaction)

        if not res:
            return await YggUtil.send_response(interaction, message="Nothing is paused", emoji="📭")

        await wait([
            create_task(YggUtil.send_response(interaction, embed=embed)),
            create_task(self._update_player(guild_id=interaction.guild_id))
        ])

    async def cog_app_command_error(self, interaction: Interaction, error: AppCommandError) -> None:
        if not isinstance(error, CheckFailure):
            await YggUtil.send_response(interaction, message=f"Unknown error, {Exception(error)}", emoji="❓")

        return await super().cog_app_command_error(interaction, error)