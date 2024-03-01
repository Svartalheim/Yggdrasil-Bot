from typing import cast
from asyncio import gather, wait, create_task
from functools import wraps

from discord import (
    Interaction,
    Embed,
    Message,
    TextChannel,
    Member,
    VoiceState,
    VoiceProtocol
)
from discord.ext import commands
from discord.app_commands import check
from discord.ui import View

from wavelink import (
    NodeReadyEventPayload,
    Playlist,
    Playable,
    TrackSource,
    Search,
    TrackStartEventPayload,
    WebsocketClosedEventPayload,
    TrackEndEventPayload,
    TrackExceptionEventPayload
)

from .interfaces import TrackType, CustomYouTubeMusicPlayable, CustomPlayer
from .view import TrackView, SelectViewSubtitle
from ..util import YggUtil
from .util_player import UtilTrackPlayer
from config import YggConfig


class TrackPlayerDecorator:

    # Begin decorator
    @classmethod
    def is_user_join_checker(cls):
        async def decorator(interaction: Interaction) -> bool:
            user_voice_state: VoiceState = interaction.user.voice
            guild_voice_client: VoiceProtocol = interaction.guild.voice_client

            if not user_voice_state:
                await YggUtil.send_response(interaction, message="Can't do that. \nPlease Join Voice channel first!!", emoji="❌", ephemeral=True)
                return False

            elif guild_voice_client and guild_voice_client.channel != user_voice_state.channel:
                await YggUtil.send_response(interaction, message="Cannot Join. \nThe bot is already connected to a voice channel!!", emoji="❌", ephemeral=True)
                return False

            return True

        return check(decorator)

    @classmethod
    def is_user_allowed(cls):
        async def decorator(interaction: Interaction) -> bool:
            user_voice_state: VoiceState = interaction.user.voice
            guild_voice_client: VoiceProtocol = interaction.guild.voice_client

            if not user_voice_state:
                await YggUtil.send_response(interaction, message="Can't do that. \nPlease Join Voice channel first!!", emoji="❌", ephemeral=True)
                return False

            elif guild_voice_client and guild_voice_client.channel != user_voice_state.channel:
                await YggUtil.send_response(interaction, message="Can't do that. \nPlease join the same Voice Channel with bot!!", emoji="🛑", ephemeral=True)
                return False

            return True

        return check(decorator)

    @classmethod
    def is_client_exist(cls):
        async def decorator(interaction: Interaction) -> bool:
            guild_voice_client: VoiceProtocol = interaction.guild.voice_client

            if not guild_voice_client:
                await YggUtil.send_response(interaction, message="Not joined a voice channel", emoji="🛑", ephemeral=True)
                return False

            return True

        return check(decorator)

    @classmethod
    def is_playing(cls):
        async def decorator(interaction: Interaction) -> bool:
            player: CustomPlayer = cast(
                CustomPlayer, interaction.guild.voice_client)

            if not player or not player.playing:
                await YggUtil.send_response(interaction, message="Can't do that. \nNothing is playing", emoji="📪", ephemeral=True)
                return False

            return True

        return check(decorator)

    @classmethod
    def record_interaction(cls):
        def decorator(func):
            @wraps(func)
            def wrapper(self, interaction: Interaction, *args, **kwargs) -> None:
                player: CustomPlayer = cast(
                    CustomPlayer, interaction.guild.voice_client)
                player.interaction = interaction

                return func(self, interaction, *args, **kwargs)
            return wrapper
        return decorator


class TrackPlayerBase:

    _bot: commands.Bot

    def __init__(self) -> None:
        super().__init__()

    async def _custom_wavelink_searcher(self, query: str, track_type: TrackType, is_search: bool = False) -> Playable | Playlist:
        """Will return either List of tracks or Single Tracks"""
        tracks: Search = None
        is_playlist: bool = track_type.is_playlist(query)
        was_youtube: bool = track_type in (
            TrackType.YOUTUBE, TrackType.YOUTUBE_MUSIC)
        search_limit: int = 30

        def _into_custom_ytms(trck: Playable) -> CustomYouTubeMusicPlayable:
            return CustomYouTubeMusicPlayable(data=trck.raw_data, playlist=trck.playlist)

        if was_youtube:
            tracks = await Playable.search(query, source=TrackSource.YouTube if not track_type is TrackType.YOUTUBE_MUSIC else TrackSource.YouTubeMusic)

        elif track_type is TrackType.SOUNCLOUD:
            tracks = await Playable.search(query, source=TrackSource.SoundCloud)

        elif track_type is TrackType.SPOTIFY:
            tracks = await Playable.search(query, source='spsearch')

        # TODO Logic here
        if is_playlist:
            tracks.url = query

        if is_playlist and was_youtube:
            if track_type is TrackType.YOUTUBE_MUSIC:
                tracks.tracks = list(map(_into_custom_ytms, tracks.tracks))

            index: int = UtilTrackPlayer.extract_index_youtube(q=query)
            tracks = tracks[index-1] if index else tracks

        elif is_search and not is_playlist:
            tracks = tracks[0:search_limit]

            if track_type is TrackType.YOUTUBE_MUSIC:
                tracks = list(map(_into_custom_ytms, tracks))

        elif not is_playlist:
            tracks = tracks[0]

            if track_type is TrackType.YOUTUBE_MUSIC:
                tracks = CustomYouTubeMusicPlayable(data=tracks.raw_data, playlist=tracks.playlist)

        return tracks

    async def _play_response(self, member: Member, tracks: Playlist | Playable, /, *,
                             is_playlist: bool = False, is_queued: bool = False, is_put_front: bool = False, is_autoplay: bool = False) -> Embed:
        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.Color.SUCCESS))
        embed.set_footer(
            text=f'From {member.name} ', icon_url=member.display_avatar)

        if is_playlist:
            embed.description = f"✅ Queued {'(on front)' if is_put_front else ''} - {len(tracks)} \
             tracks from ** [{tracks.name}]({tracks.url})**"

        elif is_queued:
            embed.description = f"✅ Queued {'(on front)' if is_put_front else ''} - **[{tracks.title}]({tracks.uri})**"

        else:
            embed.description = f"🎶 Playing - **[{tracks.title}]({tracks.uri})**"

        if is_autoplay:
            embed.description += " - **Autoplay**"

        return embed

    async def _lyrics_finder(self, interaction: Interaction) -> tuple[Embed, View]:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.guild.voice_client)

        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.Color.FAILED))

        view: View = SelectViewSubtitle(
            self._bot.session, player._original, interaction)
        embed: Embed = await view.create_embed()

        return (embed, view)

    async def _update_player(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.guild.voice_client)
        interaction: Interaction = player.interaction

        if player:
            message: Message = player.message

            view: TrackView = TrackView(self, player)
            embed: Embed = view.get_embed

            await message.edit(embed=embed, view=view)

    # Event handling

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: NodeReadyEventPayload) -> None:
        YggUtil.simple_log(
            f"Node {payload.node.session_id}, {payload.node.heartbeat} is ready!")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: TrackStartEventPayload) -> None:
        player:  CustomPlayer = payload.player
        interaction: Interaction = player.interaction
        channel: TextChannel = interaction.channel
        message: Message = None

        view: TrackView = TrackView(self, player)
        embed: Embed = view.get_embed

        # Wait message until sended
        res: list = await gather(channel.send(embed=embed))
        message: Message = res[0]

        player.message = message
        await message.edit(view=view)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: TrackEndEventPayload) -> None:
        player: CustomPlayer = payload.player

        if player:
            await gather(player.message.delete())

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: WebsocketClosedEventPayload) -> None:
        player: CustomPlayer = payload.player
        if player and player.playing:
            await player.message.delete()

        if player and payload.by_remote:
            await player.disconnect()

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: CustomPlayer) -> None:
        if player.guild.id != YggConfig.KANTIN_YOYOK_ID:
            embed: Embed = Embed(
                description="I'm stepping away because I haven't been active for the past hour. \
                            Feel free to summon me whenever you need, as I'm still here and ready to respond. This helps reduce server load.",
                color=YggUtil.convert_color(
                            YggConfig.Color.GENERAL),
                timestamp=YggUtil.get_time(),
            )
            ms: Message = await player.interaction.channel.send(embed=embed)
            return await wait([
                create_task(ms.add_reaction("💨")),
                create_task(player.disconnect()),
            ])

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: TrackExceptionEventPayload) -> None:
        player: CustomPlayer = cast(CustomPlayer, payload.player)

        embed: Embed = Embed(
            title="💥Something went wrong, while playing the track!",
            description=f'```arm\n{payload.exception}\n```',
            color=YggUtil.convert_color(YggConfig.Color.FAILED),
            timestamp=YggUtil.get_time()
        )
        embed.set_footer(text="LavaLink Node problem")

        await YggUtil.send_response(player.interaction, embed=embed)
