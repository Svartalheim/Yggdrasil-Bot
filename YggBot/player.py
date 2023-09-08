from datetime import timedelta
from asyncio import wait, create_task
from typing import Union, Tuple
from itertools import chain
from random import choice
from enum import Enum

from discord import (
    Member,
    Interaction,
    VoiceClient,
    Embed,
    Message,
    TextChannel,
    Guild,
    VoiceChannel,
    ButtonStyle,
    SelectOption,
)
from discord.ui import View, Select, button, select
from discord.errors import NotFound
from discord.ext import commands, tasks
from discord.app_commands import check

from wavelink import (
    Node,
    TrackEventPayload,
    WebsocketClosedPayload,
    QueueEmpty,
    BaseQueue,
)
from wavelink.player import Player
from wavelink.tracks import (
    YouTubePlaylist,
    YouTubeTrack,
    YouTubeMusicTrack,
    SoundCloudPlaylist,
    SoundCloudTrack,
    Playlist,
    Playable,
)
from wavelink.node import Node, NodePool
from wavelink.ext.spotify import (
    SpotifyDecodePayload,
    decode_url,
    SpotifySearchType,
    SpotifyTrack,
    SpotifyClient,
    SpotifyRequestError,
    BASEURL,
)

from .util import YggUtil
from config import YggConfig
from wavelink.types.track import Track as TrackPayload

class CustomYoutubeMusic(YouTubeMusicTrack):

    def __init__(self, data: TrackPayload) -> None:
        super().__init__(data)
        self.uri = self.uri.replace('www', 'music')


class TrackView(View):

    def __init__(self, control, /, player: Player, *, timeout: float | None = None):
        self._track_control: MusicPlayer = control
        self._player: Player = player
        self._is_playing: bool = self._player.is_playing()
        self._is_loop: bool = self._player.queue.loop

        super().__init__(timeout=timeout)

    @property
    def _is_previous_disabled(self) -> bool:
        if self._player.queue.history.is_empty:
            return True

        if self._player.queue.history[self._player.queue.history.count - 1] is self._player.current and self._player.queue.history.count <= 1:
            return True

        return False

    async def create_embed(self) -> Embed:
        interaction: Interaction = self._track_control._guild_message[
            self._player.guild.id]['interaction']
        self._update_button()

        track_type: TrackType = TrackType.what_type(self._player.current.uri)

        embed = Embed(
            title="🎶 Now Playing",
            color=YggUtil.convert_color(YggConfig.COLOR['general']),
            description=f"**[{self._player.current.title}]({self._player.current.uri}) - {self._track_control._parseSec(self._player.current.duration)}**",
            timestamp=interaction.created_at
        )

        if isinstance(self._player.current, YouTubeTrack):
            image: str = await self._player.current.fetch_thumbnail()
            embed.set_image(url=image)

        embed.set_author(name=str(track_type.name).replace(
            "_", " ").title(), icon_url=track_type.favicon())
        embed.set_footer(
            text=f'Last control from {interaction.user.name}', icon_url=interaction.user.display_avatar)

        return embed

    async def _update_message(self, interaction: Interaction) -> None:
        self._update_button()

        try:
            embed: Embed = await self.create_embed()
            await interaction.edit_original_response(view=self, embed=embed)
        except (NotFound, AttributeError):
            pass

    async def interaction_check(self, interaction: Interaction) -> bool:
        isTrue = True
        # Check whether user is joined
        if not interaction.user.voice:
            await YggUtil.send_response(interaction, message="Can't do that. \nPlease Join Voice channel first!!", emoji="❌", ephemeral=True)
            isTrue = False
        # Check wheter user is allowed
        elif interaction.guild.voice_client and interaction.guild.voice_client.channel != interaction.user.voice.channel:
            await YggUtil.send_response(interaction, message="Can't do that. \nPlease join the same Voice Channel with bot!!", emoji="🛑", ephemeral=True)
            isTrue = False

        if isTrue:
            self._track_control._record_timestamp(
                guild_id=interaction.guild_id,
                interaction=interaction
            )

        return isTrue

    def _update_button(self) -> None:
        self._previous.disabled = self._is_previous_disabled or self._is_loop
        self._next.disabled = self._is_loop

        self._pause.label = "Resume" if not self._is_playing else "Pause"
        self._pause.emoji = "▶️" if not self._is_playing else "⏸️"
        self._pause.style = ButtonStyle.green if not self._is_playing else ButtonStyle.blurple

        self._loop.label = "Loop" if not self._is_loop else "Unloop"
        self._loop.style = ButtonStyle.green if not self._is_loop else ButtonStyle.red

    @button(label="Previous", emoji="⏮️", style=ButtonStyle.secondary)
    async def _previous(self, interaction: Interaction, _) -> None:
        await wait([
            create_task(interaction.response.defer()),
            create_task(self._track_control.previous(interaction))
        ])

    @button(label="Pause", emoji="⏸️", style=ButtonStyle.blurple)
    async def _pause(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()

        self._is_playing = not self._is_playing
        if self._is_playing:
            await self._track_control.resume(interaction)
        else:
            await self._track_control.pause(interaction)

        await self._update_message(interaction)

    @button(label="Stop", emoji="⏹️", style=ButtonStyle.red)
    async def _stop(self, interaction: Interaction, _) -> None:
        await wait([
            create_task(interaction.response.defer()),
            create_task(self._track_control.stop(interaction))
        ])

    @button(label="Next", emoji="⏭️", style=ButtonStyle.secondary)
    async def _next(self, interaction: Interaction, _) -> None:
        await wait([
            create_task(interaction.response.defer()),
            create_task(self._track_control.skip(interaction))
        ])

    @button(label="Loop", emoji="🔁", style=ButtonStyle.green)
    async def _loop(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self._is_loop = not self._is_loop

        self._track_control.loop(interaction)
        await self._update_message(interaction)


class SelectView(View):

    SHOW_LIMIT = 25

    def __init__(self, control, author: Member, /, data: list[Union[Playable, SpotifyTrack]], is_jump_command: bool = False, autoplay: bool = None, *, timeout: float | None = 180):
        self._data: list[Union[Playable, SpotifyTrack]] = list(data)[
            0:self.SHOW_LIMIT]
        self._track_control: MusicPlayer = control
        self._author: Member = author
        self._selected: Union[Playable, SpotifyTrack] = None
        self._is_jump_command: bool = is_jump_command
        self._autoplay: bool = autoplay
        self.rand_emoji: list(
            str) = ["🎼", "🎵", "🎶", "🎸", "🎷", "🎺", "🎹", "🥁", "🪕", "🎻"]

        super().__init__(timeout=timeout)

    @property
    def get_embed(self) -> Embed:
        self._pass_data_to_option()
        embed: Embed = Embed(title="🔍 Here's the result" if not self._is_jump_command else "⏭️ Jump to which track?",
                             description="To play/queue the track, open the dropdown menu and select the desired track. Your track will be played/queued after this",
                             color=YggUtil.convert_color(YggConfig.COLOR['general']))

        return embed

    def _pass_data_to_option(self) -> None:
        if not self._data:
            raise IndexError

        for index, track in enumerate(self._data):
            if isinstance(track, SpotifyTrack):
                track = MusicPlayerBase._spotify_patcher(track)

            self._selector.options.append(SelectOption(
                label=track.title, description=f"{track.author if not isinstance(track, SpotifyTrack) else track.artists}\
                      - {MusicPlayerBase._parseSec(track.duration)}", emoji=choice(self.rand_emoji), value=str(index)))

    async def interaction_check(self, interaction: Interaction) -> bool:
        isTrue: bool = True
        if interaction.user.id != self._author.id:
            await YggUtil.send_response(interaction, message="Couldn't do that. \nThis is not your request!!", emoji="🛑", ephemeral=True)
            isTrue = False

        return isTrue

    @select(placeholder="🎶 Select your search result!")
    async def _selector(self, interaction: Interaction, select: Select) -> None:
        await interaction.response.defer()
        player: Player = interaction.guild.voice_client

        self._selected = self._data[int(select.values[0])]
        embed: Embed = await self._track_control._play_response(
            self._author, track=self._selected, is_queued=True if player and player.is_playing() else False, is_put_front=True if self._is_jump_command else False, is_autoplay=self._autoplay)

        if not self._is_jump_command:
            _, _, _ = await self._track_control.play(interaction, query=self._selected, autoplay=self._autoplay)
        else:
            await self._track_control.skip(
                interaction, index=self._data.index(self._selected))

        await interaction.edit_original_response(view=None, embed=embed)

    @button(label="Cancel", emoji="✖️", style=ButtonStyle.red)
    async def _cancel_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        await interaction.delete_original_response()


class QueueView(View):

    def __init__(self, queue: Union[chain, BaseQueue], is_history: bool = False, *, timeout: float | None = 180):
        self._data: list[Union[Playable, SpotifyTrack]] = list(queue)
        for x in self._data:
            if isinstance(x, SpotifyTrack):
                x = MusicPlayerBase._spotify_patcher(x)

        self._current_page: int = 1
        self._limit_show: int = 10
        self._is_history: bool = is_history

        super().__init__(timeout=timeout)

    @property
    def get_embed(self) -> Embed:
        if len(self._data) == 0:
            raise QueueEmpty()

        data: list[Playable] = self._get_current_page_data()

        self._update_buttons()

        embed: Embed = Embed(
            title=f"📃 Queue {'history' if self._is_history else ''} - Page {self._current_page} of {int(len(self._data) / self._limit_show) + 1}",
            color=YggUtil.convert_color(YggConfig.COLOR['general']))
        count: int = (self._current_page-1) * \
            self._limit_show if self._current_page != 1 else 0
        embed.description = str()

        for track in data:
            count += 1
            embed.description += f"{count}. **[{track.title}]({track.uri})** - {MusicPlayerBase._parseSec(track.duration)}\n"

        return embed

    def _get_current_page_data(self) -> list[Union[Playable, SpotifyTrack]]:
        start_index = 0
        end_index = self._limit_show

        if 1 <= self._current_page <= (len(self._data) + self._limit_show - 1) // self._limit_show:
            start_index = (self._current_page - 1) * self._limit_show
            end_index = start_index + self._limit_show

        return self._data[start_index:end_index]

    def _update_buttons(self):
        if self._current_page == 1:
            self._prev_button.disabled = True
            self._first_page_button.disabled = True
        else:
            self._prev_button.disabled = False
            self._first_page_button.disabled = False

        if self._current_page == (len(self._data) + self._limit_show - 1) // self._limit_show:
            self._next_button.disabled = True
            self._last_page_button.disabled = True
        else:
            self._next_button.disabled = False
            self._last_page_button.disabled = False

    async def _update_message(self, interaction: Interaction):
        self._update_buttons()
        await interaction.edit_original_response(view=self, embed=self.get_embed)

    @button(label="<<", style=ButtonStyle.secondary)
    async def _first_page_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self._current_page = 1
        await self._update_message(interaction)

    @button(label="<", style=ButtonStyle.blurple)
    async def _prev_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self._current_page -= 1
        await self._update_message(interaction)

    @button(label=">", style=ButtonStyle.blurple)
    async def _next_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self._current_page += 1
        await self._update_message(interaction)

    @button(label=">>", style=ButtonStyle.secondary)
    async def _last_page_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self._current_page = (
            len(self._data) + self._limit_show - 1) // self._limit_show
        await self._update_message(interaction)


# Begin Player Base

class TrackType(Enum):
    YOUTUBE = 1
    YOUTUBE_MUSIC = 2
    SOUNCLOUD = 3
    SPOTIFY = 4

    @classmethod
    def what_type(cls, uri: str):
        if uri.startswith("http"):
            if 'spotify.com' in uri:
                return cls.SPOTIFY

            if 'music.youtube.com' in uri:
                return cls.YOUTUBE_MUSIC

            if 'youtube.com' in uri:
                return cls.YOUTUBE

            if 'soundcloud.com' in uri:
                return cls.SOUNCLOUD

    def favicon(self) -> str:
        favicon: str = "https://www.google.com/s2/favicons?domain={domain}&sz=256"

        if self == self.YOUTUBE:
            return favicon.format(domain="https://youtube.com")

        if self is self.YOUTUBE_MUSIC:
            return favicon.format(domain="https://music.youtube.com")

        if self is self.SPOTIFY:
            return favicon.format(domain="https://spotify.com")

        if self is self.SOUNCLOUD:
            return favicon.format(domain="https://soundcloud.com")


class MusicPlayerBase:

    def __init__(self) -> None:
        self._guild_message: dict = dict()
        self._timeout_minutes = 30
        super().__init__()

    # Begin decorator

    @classmethod
    def _is_user_join_checker(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            if not interaction.user.voice:
                await YggUtil.send_response(interaction, message="Can't do that. \nPlease Join Voice channel first!!", emoji="❌", ephemeral=True)
                isTrue = False
            elif interaction.guild.voice_client and interaction.guild.voice_client.channel != interaction.user.voice.channel:
                await YggUtil.send_response(interaction, message="Cannot Join. \nThe bot is already connected to a voice channel!!", emoji="❌", ephemeral=True)
                isTrue = False

            return isTrue

        return check(decorator)

    @classmethod
    def _is_user_allowed(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            if not interaction.user.voice:
                await YggUtil.send_response(interaction, message="Can't do that. \nPlease Join Voice channel first!!", emoji="❌", ephemeral=True)
                isTrue = False
            elif interaction.guild.voice_client and interaction.guild.voice_client.channel != interaction.user.voice.channel:
                await YggUtil.send_response(interaction, message="Can't do that. \nPlease join the same Voice Channel with bot!!", emoji="🛑", ephemeral=True)
                isTrue = False

            return isTrue

        return check(decorator)

    @classmethod
    def _is_client_exist(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            if not interaction.guild.voice_client:
                await YggUtil.send_response(interaction, message="Not joined a voice channel", emoji="🛑", ephemeral=True)
                isTrue = False

            return isTrue

        return check(decorator)

    @classmethod
    def _is_playing(cls):
        async def decorator(interaction: Interaction) -> bool:
            isTrue: bool = True
            player: Player = interaction.guild.voice_client
            if player and player.current is None:
                await YggUtil.send_response(interaction, message="Can't do that. \nNothing is playing", emoji="📪")
                isTrue = False

            return isTrue

        return check(decorator)

    # Begin inner work

    @tasks.loop(seconds=10)
    async def _timeout_check(self) -> None:
        for id, key in self._guild_message.copy().items():
            if YggUtil.get_time() >= (
                key["timestamp"] + timedelta(minutes=self._timeout_minutes)
            ):
                guild: Guild = self._bot.get_guild(id)
                voice_client: VoiceClient = guild.voice_client
                if not voice_client.is_playing() and not voice_client.is_paused():
                    await YggUtil.send_response(
                        self._guild_message[id]["interaction"],
                        message="I'm leaving because haven't been used for 1 hour\nSummon me anytime, i'm still responding. (this is for reducing server load)",
                        emoji="💨",
                        ephemeral=True,
                    )
                    await voice_client.disconnect()
                else:
                    self._guild_message[id]["timestamp"] = YggUtil.get_time()

    @staticmethod
    def _parseSec(sec: int) -> str:
        sec = sec // 1000
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if sec > 3600:
            return f'{h:d}h {m:02d}m {s:02d}s'
        else:
            return f'{m:02d}m {s:02d}s'
        
    @classmethod
    def _spotify_patcher(cls, child: SpotifyTrack) -> SpotifyTrack:

        def _spotify_link_fixed(uri: str) -> str:
            openable_link: str = "https://open.spotify.com/{track_type}/{id}"
            uri_split: list[str] = uri.split(":")
            id: str = uri_split[2]
            track_type: str = uri_split[1]

            return openable_link.format(track_type=track_type, id=id)

        if not "//" in child.uri:
            child.uri = _spotify_link_fixed(child.uri)
            child.artists = ', '.join(child.artists)

        return child

    @staticmethod
    async def _custom_wavelink_player(query: str, track_type: TrackType, is_search: bool = False) -> Union[Playable, Playlist, SpotifyTrack, list[SpotifyTrack]]:
        """Will return either List of tracks or Single Tracks"""
        tracks: Union[Playable, Playlist,
                      SpotifyTrack, list[SpotifyTrack]] = list()
        is_playlist: bool = False
        search_limit: int = 30

        if track_type in (TrackType.YOUTUBE, TrackType.YOUTUBE_MUSIC):
            # if 'playlist?' in query:
            #     is_playlist = True
                # tracks: YouTubePlaylist = await YouTubePlaylist.search(query)

            if track_type is TrackType.YOUTUBE_MUSIC:
                if is_playlist:
                    tracks.tracks = [CustomYoutubeMusic(
                        data=trck.data) for trck in tracks.tracks]
                else:
                    tracks: CustomYoutubeMusic = CustomYoutubeMusic.search(
                        query)
            else:
                tracks: YouTubeTrack = await YouTubeTrack.search(query)
        elif track_type is TrackType.SOUNCLOUD:
            if 'sc-playlists' in query:
                is_playlist = True
                tracks: SoundCloudPlaylist = await SoundCloudPlaylist.search(query)
            else:
                tracks: SoundCloudTrack = await SoundCloudTrack.search(query)
        elif track_type is TrackType.SPOTIFY:
            if 'http' in query:
                track_type_spotify: SpotifySearchType = decode_url(query).type
                is_playlist = True if track_type_spotify in (
                    SpotifySearchType.album, SpotifySearchType.playlist) else False
                tracks: list[SpotifyTrack] = await SpotifyTrack.search(query)
            else:
                tracks: YouTubeTrack = await YouTubeTrack.search(query)

        if is_search:
            tracks = tracks[0:search_limit]
        elif not is_playlist:
            tracks = tracks[0]

        return tracks

    async def _play_response(self, member: Member, /, track: Union[Playlist, Playable, SpotifyTrack, list[SpotifyTrack]],
                             is_playlist: bool = False, is_queued: bool = False, is_put_front: bool = False, is_autoplay: bool = False, raw_uri: str = None) -> Embed:
        embed: Embed = Embed(color=YggUtil.convert_color(
            YggConfig.COLOR['success']), timestamp=YggUtil.get_time())
        embed.set_footer(
            text=f'From {member.name} ', icon_url=member.display_avatar)

        if isinstance(track, SpotifyTrack):
            track = self._spotify_patcher(track)

        async def _get_raw_spotify_playlist(uri_ori: str) -> dict:
            node: Node = NodePool.get_connected_node()
            decoded: SpotifyDecodePayload = decode_url(url=uri_ori)
            id: str = decoded.id
            track_type: str = decoded.type.name
            data: dict = dict()

            sp_client: SpotifyClient = node._spotify
            if sp_client.is_token_expired():
                await sp_client._get_bearer_token()

            uri = BASEURL.format(entity=track_type, identifier=id)

            async with self._bot.session.get(uri, headers=sp_client.bearer_headers) as resp:
                if resp.status == 400:
                    return None
                elif resp.status != 200:
                    raise SpotifyRequestError(resp.status, resp.reason)

                data = await resp.json()
                data.pop("tracks",  None)

            data['uri'] = uri_ori

            return data

        raw_data_spotify: dict = dict()

        if raw_uri and isinstance(track, list):
            raw_data_spotify = await _get_raw_spotify_playlist(raw_uri)
        if is_playlist:
            playlist: Union[Playlist, list[SpotifyTrack]] = track
            embed.description = f"✅ Queued {'(on front)' if is_put_front == 1 else ''} - {len(playlist.tracks)  if not isinstance(playlist, list) else len(playlist)} \
            tracks from ** [{playlist.name if not isinstance(playlist, list) else raw_data_spotify['name']}]({raw_uri if not isinstance(playlist, list) else raw_data_spotify['uri']})**"
        elif is_queued:
            embed.description = f"✅ Queued {'(on front)' if is_put_front == 1 else ''} - **[{track.title}]({track.uri})**"
        else:
            embed.description = f"🎶 Playing - **[{track.title}]({track.uri})**"

        if is_autoplay:
            embed.description += " - Autoplay"

        return embed

    def _record_timestamp(self, guild_id: int, interaction: Interaction) -> None:
        if not guild_id in self._guild_message:
            self._guild_message.update({guild_id: dict()})

        if not 'timestamp' in self._guild_message[guild_id]:
            self._guild_message[guild_id].update(
                {'timestamp': YggUtil.get_time()})

        self._guild_message[guild_id].update(
            {'interaction': interaction})

    def _record_message(self, guild_id: int, message: Message) -> None:
        self._guild_message[guild_id]['message'] = message

    async def _clear_message(self, guild_id: int) -> None:
        message: Message = self._guild_message[guild_id]['message']
        await message.delete()

    async def _update_player(self, guild_id: int) -> None:
        interaction: Interaction = self._guild_message[guild_id]['interaction']
        player: Player = interaction.guild.voice_client

        if player and (player.is_playing() or player.is_paused()):
            message: Message = self._guild_message[interaction.guild_id]['message']

            view: TrackView = TrackView(self, player=player)
            embed: Embed = await view.create_embed()

            await message.edit(embed=embed, view=view)

    # Event handling

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, node: Node) -> None:
        YggUtil.simple_log(f"Node {node.id}, {node.heartbeat} is ready!")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: TrackEventPayload) -> None:
        player:  Player = payload.player
        interaction: Interaction = self._guild_message[player.guild.id]['interaction']
        channel: TextChannel = interaction.channel
        message: Message = None
        track_view: TrackView = TrackView(self, player=player)
        embed: Embed = await track_view.create_embed()
        message: Message = await channel.send(embed=embed)
        self._record_message(guild_id=player.guild.id, message=message)
        await message.edit(view=track_view)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: TrackEventPayload) -> None:
        player: Player = payload.player

        await self._clear_message(player.guild.id)

        if not player.autoplay and not player.queue.is_empty:
            track: Playable | SpotifyTrack = await player.queue.get_wait()
            if isinstance(track, SpotifyTrack):
                track = await track.fulfill(player=player, cls=CustomYoutubeMusic, populate=player.autoplay)
            await player.play(track=track)

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: WebsocketClosedPayload) -> None:
        if payload.player.is_playing() or payload.player.is_paused():
            await wait([create_task(self._clear_message(payload.player.guild.id))])

        if payload.by_discord:
            await payload.player.disconnect()
            del self._guild_message[payload.player.guild.id]


class MusicPlayer(MusicPlayerBase):

    async def join(self, interaction: Interaction) -> None:
        channel:  VoiceChannel = interaction.user.voice.channel

        await channel.connect(cls=Player)

    async def leave(self, interaction: Interaction) -> None:
        player: Player = interaction.user.guild.voice_client

        await player.disconnect()

    async def search(self, query: str, user: Member, source: TrackType = TrackType.YOUTUBE, autoplay: bool = None) -> Tuple[Embed, View]:
        view: View = None
        embed: Embed = None

        if query.startswith("http"):
            source = TrackType.what_type(query)

        tracks: Union[Playable, Playlist, SpotifyTrack, list[SpotifyTrack]] = await self._custom_wavelink_player(query=query, track_type=source, is_search=True)
        view: SelectView = SelectView(self, user, data=tracks if not isinstance(
            tracks, Playlist) else tracks.tracks, autoplay=autoplay)
        embed = view.get_embed

        return (embed, view)

    async def play(self, interaction: Interaction, /, query: Union[str, Playable, SpotifyTrack], source: TrackType = TrackType.YOUTUBE,
                   autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> Tuple[Union[Playable, Playlist, SpotifyTrack], bool, bool]:
        is_playlist = is_queued = False
        player: Player = None

        if not interaction.guild.voice_client:
            player = await interaction.user.voice.channel.connect(cls=Player)
        else:
            player = interaction.user.guild.voice_client

        track_type: TrackType = (TrackType.what_type(
            uri=query) if not isinstance(query, (Playable, SpotifyTrack)) else None) or source

        if not isinstance(query, (Playable, SpotifyTrack)):
            tracks: Union[Playable, Playlist, SpotifyTrack, list[SpotifyTrack]] = await self._custom_wavelink_player(query=query, track_type=track_type)
        else:
            tracks = query

        if autoplay is None:
            player.autoplay = player.autoplay
        else:
            player.autoplay = autoplay

        if isinstance(tracks, (Playlist, list)):
            playlist: Union[Playlist, list[SpotifyTrack]] = tracks
            if force_play:
                player.queue.put_at_front(player.queue.history.pop())

            if put_front or force_play:
                for track in reversed(playlist.tracks if isinstance(playlist, Playlist) else playlist):
                    player.queue.put_at_front(track)
            else:
                player.queue.extend(playlist.tracks if isinstance(
                    playlist, Playlist) else playlist)

            if force_play and player.is_playing():
                await player.seek(player.current.length * 1000)
            if not player.is_playing():
                trck: Union[Playable, SpotifyTrack] = await player.queue.get_wait()
                if isinstance(trck, SpotifyTrack):
                    trck = await trck.fulfill(
                        player=player, cls=CustomYoutubeMusic, populate=False)
                await player.play(trck)

            is_playlist = True
        elif player.is_playing():
            if force_play:
                player.queue.put_at_front(player.queue.history.pop())
                player.queue.put_at_front(tracks)
                await player.seek(player.current.length * 1000)

            if put_front:
                player.queue.put_at_front(tracks)
            else:
                await player.queue.put_wait(tracks)

            is_queued = True
        else:
            trck = tracks
            if isinstance(trck, SpotifyTrack):
                trck = await trck.fulfill(player=player, cls=CustomYoutubeMusic,
                                              populate=True if autoplay and track_type is not TrackType.SOUNCLOUD else False)
            await player.play(trck, populate=True if autoplay and track_type is not TrackType.SOUNCLOUD else False)
        return (tracks, is_playlist, is_queued)

    async def queue(self, interaction: Interaction, /, is_history: bool = False) -> Tuple[Embed, View]:
        player: Player = interaction.user.guild.voice_client
        view: View = None
        embed: Embed = None

        view = QueueView(queue=player.queue.history if is_history else chain(
            player.queue, player.auto_queue), is_history=is_history)
        embed = view.get_embed

        return (embed, view)

    async def skip(self, interaction: Interaction, index: int = None) -> None:
        player: Player = interaction.user.guild.voice_client

        if index is not None:
            track: Union[Playable, SpotifyTrack] = None

            if index < player.queue.count:
                track = player.queue[index]
                del player.queue[index]
            else:
                index -= player.queue.count
                track = player.auto_queue[index]
                del player.auto_queue[index]
            player.queue.put_at_front(track)

        await player.seek(player.current.length * 1000)

        if player.is_paused():
            await player.resume()

    async def jump(self, interaction: Interaction) -> None:
        player: Player = interaction.user.guild.voice_client

        view: View = None
        embed: Embed = None

        view: SelectView = SelectView(
            self, interaction.user, data=chain(player.queue, player.auto_queue), is_jump_command=True)
        embed = view.get_embed

        return (embed, view)

    async def previous(self, interaction: Interaction) -> bool:
        was_allowed: bool = True
        player: Player = interaction.user.guild.voice_client

        if not player.queue.history.is_empty and player.queue.history.count >= 1 and player.queue.history[player.queue.history.count - 1] is player.current:
            player.queue.put_at_front(player.queue.history.pop())
            player.queue.put_at_front(player.queue.history.pop())
            await player.seek(player.current.length * 1000)
        else:
            was_allowed = False

        if player.is_paused():
            await player.resume()

        return was_allowed

    async def stop(self, interaction: Interaction) -> None:
        player: Player = interaction.user.guild.voice_client

        if player.autoplay:
            player.autoplay = False

        if not player.queue.is_empty or not player.auto_queue.is_empty:
            player.queue.reset()
            player.auto_queue.reset()

        await player.stop()

    def clear(self, interaction: Interaction) -> None:
        player: Player = interaction.user.guild.voice_client

        if player.autoplay:
            player.autoplay = False

        if not player.queue.is_empty or not player.auto_queue.is_empty:
            player.queue.reset()
            player.auto_queue.reset()

    def shuffle(self, interaction: Interaction) -> None:
        player: Player = interaction.user.guild.voice_client

        player.queue.shuffle()

    def now_playing(self, interaction: Interaction) -> Tuple[Player, int]:
        player: Player = interaction.user.guild.voice_client

        time: int = (player.current.duration - player.position)//1000

        return (player, time)

    def loop(self, interaction: Interaction, /, is_queue: bool = False) -> bool:
        player: Player = interaction.user.guild.voice_client
        loop = False

        if not is_queue:
            player.queue.loop = not player.queue.loop
            loop = player.queue.loop
        else:
            player.queue.loop_all = not player.queue.loop_all
            loop = player.queue.loop_all

        if player.queue.loop:
            player.queue.put_at_front(player.queue.history.pop())
        else:
            player.queue.history.put(player.queue.get())

        return loop

    async def pause(self, interaction: Interaction) -> None:
        player: Player = interaction.user.guild.voice_client

        await player.pause()

    async def resume(self, interaction: Interaction) -> bool:
        player: Player = interaction.user.guild.voice_client

        if player.is_paused():
            await player.resume()
            return True

        return False
