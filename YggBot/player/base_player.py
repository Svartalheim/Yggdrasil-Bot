from datetime import timedelta
from asyncio import gather, create_task, wait

from yarl import URL

from discord import (
    Interaction,
    Embed,
    Message,
    TextChannel,
    VoiceClient,
    Guild,
    Member
)
from discord.ext import commands, tasks
from discord.app_commands import check

from wavelink import (
    Node,
    TrackEventPayload,
    WebsocketClosedPayload,
    SoundCloudPlaylist,
    SoundCloudTrack,
    YouTubePlaylist,
    Playlist,
    Playable
)
from wavelink.ext.spotify import SpotifyTrack

from .interfaces import (
    CustomPlayer,
    CustomYouTubeMusicTrack,
    CustomYouTubeTrack,
    TrackType
)
from .view import TrackView
from .util_player import UtilTrackPlayer, MusixMatchAPI
from ..util import YggUtil
from config import YggConfig


class TrackPlayerDecorator:

    # Begin decorator
    @classmethod
    def is_user_join_checker(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            if not interaction.user.voice:
                await YggUtil.send_response(
                    interaction,
                    message="Can't do that. \nPlease Join Voice channel first!!",
                    emoji="❌",
                    ephemeral=True,
                )
                isTrue = False
            elif (
                interaction.guild.voice_client
                and interaction.guild.voice_client.channel
                != interaction.user.voice.channel
            ):
                await YggUtil.send_response(
                    interaction,
                    message="Cannot Join. \nThe bot is already connected to a voice channel!!",
                    emoji="❌",
                    ephemeral=True,
                )
                isTrue = False

            return isTrue

        return check(decorator)

    @classmethod
    def is_user_allowed(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            if not interaction.user.voice:
                await YggUtil.send_response(
                    interaction,
                    message="Can't do that. \nPlease Join Voice channel first!!",
                    emoji="❌",
                    ephemeral=True,
                )
                isTrue = False
            elif (
                interaction.guild.voice_client
                and interaction.guild.voice_client.channel
                != interaction.user.voice.channel
            ):
                await YggUtil.send_response(
                    interaction,
                    message="Can't do that. \nPlease join the same Voice Channel with bot!!",
                    emoji="🛑",
                    ephemeral=True,
                )
                isTrue = False

            return isTrue

        return check(decorator)

    @classmethod
    def is_client_exist(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            if not interaction.guild.voice_client:
                await YggUtil.send_response(
                    interaction,
                    message="Not joined a voice channel",
                    emoji="🛑",
                    ephemeral=True,
                )
                isTrue = False

            return isTrue

        return check(decorator)

    @classmethod
    def is_playing(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            player: CustomPlayer = interaction.guild.voice_client
            if player and player.current is None:
                await YggUtil.send_response(
                    interaction,
                    message="Can't do that. \nNothing is playing",
                    emoji="📪",
                )
                isTrue = False

            return isTrue

        return check(decorator)


class TrackPlayerBase:

    _bot: commands.Bot

    def __init__(self) -> None:
        self.__guilds: dict = dict()
        self.__timeout_minutes = 60
        super().__init__()

    # Begin inner work

    @tasks.loop(seconds=10)
    async def _timeout_check(self) -> None:
        for id, key in self.__guilds.items():
            if YggUtil.get_time() >= (
                key["timestamp"] + timedelta(minutes=self.__timeout_minutes)
            ):
                guild: Guild = self._bot.get_guild(id)
                if not guild.id == YggConfig.KANTIN_YOYOK_ID:
                    voice_client: VoiceClient = guild.voice_client
                    if not voice_client.is_playing() and not voice_client.is_paused():
                        interaction: Interaction = self.__guilds[id][
                            "interaction"
                        ]
                        channel: TextChannel = self._bot.get_channel(
                            interaction.channel_id
                        )
                        embed: Embed = Embed(
                            description="I'm stepping away because I haven't been active for the past hour. \
                                Feel free to summon me whenever you need, as I'm still here and ready to respond. This helps reduce server load.",
                            color=YggUtil.convert_color(
                                YggConfig.COLOR["general"]),
                            timestamp=YggUtil.get_time(),
                        )
                        msg: Message = await channel.send(embed=embed)
                        await wait(
                            [
                                create_task(msg.add_reaction("💨")),
                                create_task(voice_client.disconnect()),
                            ]
                        )
                    else:
                        self.__guilds[id]["timestamp"] = YggUtil.get_time()

    async def _custom_wavelink_player(self, query: str, track_type: TrackType, is_search: bool = False) -> Playable | Playlist | SpotifyTrack | list[SpotifyTrack]:
        """Will return either List of tracks or Single Tracks"""
        tracks: Playable | Playlist | SpotifyTrack | list[SpotifyTrack] = None
        is_playlist: bool = False
        search_limit: int = 30
        url: URL = None

        if query.startswith('http'):
            url = URL(query)

            if url.query.get('list'):
                is_playlist = True

        if track_type in (TrackType.YOUTUBE, TrackType.YOUTUBE_MUSIC):
            if is_playlist:
                tracks: YouTubePlaylist = await YouTubePlaylist.search(query)

            if track_type is TrackType.YOUTUBE_MUSIC:
                if is_playlist:
                    tracks.tracks = [CustomYouTubeMusicTrack(
                        data=trck.data) for trck in tracks.tracks]

                else:
                    tracks: CustomYouTubeMusicTrack = await CustomYouTubeMusicTrack.search(query)
            elif not is_playlist:
                tracks: CustomYouTubeTrack = await CustomYouTubeTrack.search(query)

        elif track_type is TrackType.SOUNCLOUD:
            if is_playlist:
                tracks: SoundCloudPlaylist = await SoundCloudPlaylist.search(query)

            else:
                tracks: SoundCloudTrack = await SoundCloudTrack.search(query)

        elif track_type is TrackType.SPOTIFY:
            tracks: list[SpotifyTrack] = list()
            if url:
                tracks = await SpotifyTrack.search(query)
            else:
                # Session from aiohttp bot main
                tracks = await UtilTrackPlayer.search_spotify_raw(self._bot.session, query=query, limit=search_limit)

            for trck in tracks:
                UtilTrackPlayer.spotify_patcher(trck)

        if is_search:
            tracks = tracks[0:search_limit]

        elif not is_playlist:
            tracks = tracks[0]

        elif is_playlist:
            index: int = UtilTrackPlayer.extract_index_youtube(url=url)
            tracks = tracks.tracks[index-1] if index else tracks

        return tracks
    
    async def _lyrics_finder(self, interaction: Interaction) -> Embed:
        player: CustomPlayer = interaction.guild.voice_client
        lyrics: str = None
        track: Playable | SpotifyTrack = player.current

        if isinstance(track, CustomYouTubeMusicTrack | CustomYouTubeTrack) and\
                track.spotify_original is not None:
            track = track.spotify_original

        ms: MusixMatchAPI = MusixMatchAPI(track, self._bot.session)

        try:
            lyrics: str = await ms.get_lyrics()
        except MusixMatchAPI.StatusCodeHandling as e:
            lyrics = f'```arm\n{e}\n```'

        embed: Embed = Embed(
            title="🎼 Lyrics",
            description=lyrics,
            color=YggUtil.convert_color(YggConfig.COLOR['general']),
            timestamp=YggUtil.get_time()
        )
        embed.set_footer(
            text=f"© {str(MusixMatchAPI.__name__).replace('API', '')}")
        embed.set_author(
            name=str(MusixMatchAPI.__name__).replace("API", ""),
            icon_url=ms.favicon
        )

        return embed

    async def _play_response(self, member: Member, /, track: Playlist | Playable | SpotifyTrack | list[SpotifyTrack],
                             is_playlist: bool = False, is_queued: bool = False, is_put_front: bool = False, is_autoplay: bool = False, uri: str = None) -> Embed:
        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.COLOR['success']), timestamp=YggUtil.get_time())
        embed.set_footer(
            text=f'From {member.name} ', icon_url=member.display_avatar)
        raw_data_spotify: dict = None

        if isinstance(track, list):
            # Session from aiohttp bot main
            raw_data_spotify = await UtilTrackPlayer.get_raw_spotify_uri(self._bot.session, uri)

        if is_playlist:
            playlist: Playlist | list[SpotifyTrack] = track
            embed.description = f"✅ Queued {'(on front)' if is_put_front else ''} - {len(playlist.tracks)  if not raw_data_spotify else len(playlist)} \
            tracks from ** [{playlist.name if not raw_data_spotify else raw_data_spotify['name']}]({uri if not raw_data_spotify else raw_data_spotify['uri']})**"

        elif is_queued:
            embed.description = f"✅ Queued {'(on front)' if is_put_front else ''} - **[{track.title}]({uri})**"

        else:
            embed.description = f"🎶 Playing - **[{track.title}]({uri})**"

        if is_autoplay:
            embed.description += " - **Autoplay**"

        return embed

    def _record_timestamp(self, guild_id: int, interaction: Interaction) -> None:
        if not guild_id in self.__guilds:
            self.__guilds.update({guild_id: dict()})

        if not 'timestamp' in self.__guilds[guild_id]:
            self.__guilds[guild_id].update(
                {'timestamp': YggUtil.get_time()})

        self.__guilds[guild_id].update(
            {'interaction': interaction})

    def _get_interaction(self, guild_id: int) -> Interaction:
        return self.__guilds[guild_id]['interaction']

    async def _update_player(self, guild_id: int) -> None:
        interaction: Interaction = self.__guilds[guild_id]['interaction']
        player: CustomPlayer = interaction.guild.voice_client

        if player and (player.is_playing() or player.is_paused()):
            message: Message = self.__guilds[interaction.guild_id]['message']

            view: TrackView = TrackView(self, player=player)
            embed: Embed = await view.create_embed()

            await message.edit(embed=embed, view=view)

    def __record_message(self, guild_id: int, message: Message) -> None:
        self.__guilds[guild_id]['message'] = message

    async def __clear_message(self, guild_id: int) -> None:
        message: Message = self.__guilds[guild_id]['message']
        await message.delete()

    # Event handling

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, node: Node) -> None:
        YggUtil.simple_log(f"Node {node.id}, {node.heartbeat} is ready!")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: TrackEventPayload) -> None:
        player:  CustomPlayer = payload.player
        interaction: Interaction = self.__guilds[player.guild.id]['interaction']
        channel: TextChannel = interaction.channel
        message: Message = None

        track_view: TrackView = TrackView(self, player=player)

        embed: Embed = await track_view.create_embed()
        # Wait message until sended
        res: list = await gather(channel.send(embed=embed))
        message: Message = res[0]

        self.__record_message(guild_id=player.guild.id, message=message)
        await message.edit(view=track_view)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: TrackEventPayload) -> None:
        player: CustomPlayer = payload.player

        await gather(self.__clear_message(player.guild.id))

        if not player.autoplay and not player.queue.is_empty:
            track: Playable | SpotifyTrack = await player.queue.get_wait()
            await player.play(track=track)

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: WebsocketClosedPayload) -> None:
        if payload.player.is_playing() or payload.player.is_paused():
            await self.__clear_message(payload.player.guild.id)

        if payload.by_discord:
            await payload.player.disconnect()
            del self.__guilds[payload.player.guild.id]
