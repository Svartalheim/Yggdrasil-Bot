from typing import cast
from itertools import chain
from datetime import timedelta

from discord import Interaction, Embed, VoiceChannel
from discord.ui import View

from wavelink import (
    Playable,
    Playlist,
    AutoPlayMode,
    QueueMode,
    Album,
    Artist,
    PlaylistInfo
)
from .interfaces import CustomPlayer, TrackType
from .interfaces import TrackType
from .util_player import UtilTrackPlayer
from .base_player import TrackPlayerBase, TrackPlayerDecorator
from .view import QueueView, SelectViewTrack

from ..util import YggConfig, YggUtil


class TrackPlayer(TrackPlayerBase):

    async def join(self, interaction: Interaction) -> None:
        channel:  VoiceChannel = interaction.user.voice.channel
        if not interaction.guild.voice_client:
            await channel.connect(cls=CustomPlayer)

        # TODO Manual Record interaction
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)
        player.interaction = interaction

    async def leave(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)
        await player.disconnect()

    async def search(self, interaction: Interaction, /, query: str, source: TrackType = TrackType.YOUTUBE,
                     autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> tuple[Embed, View]:
        view: View = None
        embed: Embed = None

        if query.startswith("http"):
            source = TrackType.what_type(query)

        tracks: Playable | Playlist = await self._custom_wavelink_searcher(query=query, track_type=source, is_search=True)
        view: SelectViewTrack = SelectViewTrack(self, interaction, data=tracks if not isinstance(
            tracks, Playlist) else tracks.tracks, autoplay=autoplay, force_play=force_play, put_front=put_front)
        embed = view.get_embed

        return (embed, view)

    async def play(self, interaction: Interaction, /, query: str | Playable, source: TrackType = TrackType.YOUTUBE,
                   autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> tuple[Playable | Playlist, bool, bool]:
        is_playlist = is_queued = False
        was_playable: bool = isinstance(query, Playable)
        player: CustomPlayer = None

        if not interaction.guild.voice_client:
            player = await interaction.user.voice.channel.connect(cls=CustomPlayer)

        else:
            player = cast(CustomPlayer, interaction.user.guild.voice_client)

        # TODO Record interaction
        player.interaction = interaction

        track_type: TrackType = (TrackType.what_type(
            uri=query) if not was_playable else None) or source

        if not was_playable:
            tracks: Playable | Playlist = await self._custom_wavelink_searcher(query=query, track_type=track_type)

        else:
            tracks = query

        # Enable autoplay, skip into next song
        if player.autoplay is AutoPlayMode.disabled:
            player.autoplay = AutoPlayMode.partial

        if autoplay is not None:
            player.autoplay = AutoPlayMode.enabled if autoplay is True else AutoPlayMode.partial

            if player.autoplay is AutoPlayMode.disabled:
                player.auto_queue.clear()

        if isinstance(tracks, Playlist):
            playlist: list[Playable] = tracks.tracks.copy()

            if player.playing and force_play:
                player.queue.put_at(0, player.queue.history.get_at(-1))

            # TODO Try extend left on here
            if put_front or force_play:
                playlist.extend(player.queue._items)
                player.queue._items = playlist

            else:
                player.queue._items.extend(playlist)

            player.queue._wakeup_next()

            if force_play and player.playing:
                await player.seek(player.current.length * 1000)
            elif not player.playing:
                trck: Playable = await player.queue.get_wait()
                await player.play(trck)

            is_playlist = True
        elif player.playing:
            if force_play:
                player.queue.put_at(0, player.queue.history.get_at(-1))
                player.queue.put_at(0, tracks)
                await player.seek(player.current.length * 1000)

            if put_front:
                player.queue.put_at(0, tracks)

            elif not force_play:
                await player.queue.put_wait(tracks)

            is_queued = True
        else:
            await player.play(tracks)

        return (tracks, is_playlist, is_queued)

    async def queue(self, interaction: Interaction, /, is_history: bool = False) -> tuple[Embed, View]:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)
        view: View = None
        embed: Embed = None

        view = QueueView(queue=reversed(player.queue.history) if is_history else chain(
            player.queue, player.auto_queue), interaction=interaction, is_history=is_history)
        embed = view.get_embed

        return (embed, view)

    @TrackPlayerDecorator.record_interaction()
    async def skip(self, interaction: Interaction, index: int = None) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        if index is not None:
            track: Playable = None

            if index < player.queue.count:
                track = player.queue.get_at(index)

            else:
                index -= player.queue.count
                track = player.auto_queue.get_at(index)

            player.queue.put_at(0, track)

        await player.seek(player.current.length * 1000)

        if player.paused:
            await player.pause(not player.paused)

    @TrackPlayerDecorator.record_interaction()
    async def jump(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        view: View = None
        embed: Embed = None

        view: SelectViewTrack = SelectViewTrack(
            self, interaction, data=chain(player.queue, player.auto_queue), is_jump_command=True)
        embed = view.get_embed

        return (embed, view)

    @TrackPlayerDecorator.record_interaction()
    async def previous(self, interaction: Interaction) -> tuple[bool, bool]:
        was_allowed: bool = True
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        was_on_loop: bool = player.queue.mode is QueueMode.loop
        if not player.queue.history.is_empty and player.queue.history.count >= 1 and player.queue.history[-1] is player._original:
            player.queue.put_at(0, player.queue.history.get_at(-1))
            player.queue.put_at(0, player.queue.history.get_at(-1))
            await player.seek(player.current.length * 1000)

        else:
            was_allowed = False

        if player.paused:
            await player.pause(not player.paused)

        return (was_allowed, was_on_loop)

    async def stop(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        if player.autoplay:
            player.autoplay = AutoPlayMode.disabled

        if not player.queue.is_empty or not player.auto_queue.is_empty:
            player.queue.reset()
            player.auto_queue.reset()

        await player.stop()

    @TrackPlayerDecorator.record_interaction()
    def clear(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        if player.autoplay:
            player.autoplay = AutoPlayMode.disabled

        if not player.queue.is_empty or not player.auto_queue.is_empty:
            player.queue.reset()
            player.auto_queue.reset()

    @TrackPlayerDecorator.record_interaction()
    def shuffle(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        player.queue.shuffle()

    def now_playing(self, interaction: Interaction) -> Embed:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)
        track: Playable = player._original
        time: int = (player.current.length - player.position)//1000
        duration: str = UtilTrackPlayer.parse_sec(player.current.length)

        embed: Embed = Embed(
            title="🎶 Now Playing",
            description=f"""**[{track.title}]({track.uri}) - {duration}** 
            \n** {str(timedelta(seconds=time)).split('.')[0]} left**""",
            color=YggUtil.convert_color(YggConfig.Color.GENERAL)
        )

        track_type: TrackType = TrackType.what_type(track.uri)
        embed.set_author(name=str(track_type.name).replace(
            "_", " ").title(), icon_url=track_type.favicon())

        embed.set_thumbnail(url=track.artist.artwork)
        embed.set_image(url=track.artwork)

        temp: dict = track.__dict__
        temp.pop('_encoded')
        temp.pop('_identifier')
        temp.pop('_is_seekable')
        temp.pop('_is_stream')
        temp.pop('_recommended')
        temp.pop('_extras')
        temp.pop('_raw_data')
        temp.pop('_title')

        for key, value in temp.items():
            if isinstance(value, Album):
                if not value.name:
                    continue

                if not value.url:
                    value = value.name
                else:
                    value = f'[{value.name}]({value.url})'
            elif isinstance(value, Artist):
                if not value.url:
                    continue
                else:
                    value = f'[{track.author}]({value.url})'
            elif isinstance(value, PlaylistInfo):
                value = value.url
            else:
                value = cast(str, value)

            if not value:
                continue

            if key == '_length':
                value = duration
            elif key == '_position':
                value = str(timedelta(seconds=value)).split('.')[0]
            elif key == '_source':
                value = TrackType.what_type(
                    track.uri).name.casefold().capitalize()
            elif key == '_uri':
                key = 'url'

            embed.add_field(
                name=key.removeprefix('_').replace('_', ' ').capitalize(),
                value=value if not value.startswith(
                    'http') else f'[here]({value})',
                inline=True
            )

        return embed

    @TrackPlayerDecorator.record_interaction()
    def loop(self, interaction: Interaction, /, is_queue: bool = False) -> bool:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)
        loop = False

        if player.queue.mode is QueueMode.normal:
            player.queue.mode = QueueMode.loop if not is_queue else QueueMode.loop_all
            loop = True

        else:
            player.queue.mode = QueueMode.normal
            loop = False

        if player.queue.mode is QueueMode.loop:
            player.queue.put_at(0, player.queue.history[-1])
        elif player.queue.mode is QueueMode.normal and not is_queue:
            player.queue.delete(0)

        return loop

    @TrackPlayerDecorator.record_interaction()
    async def pause(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        await player.pause(True)

    @TrackPlayerDecorator.record_interaction()
    async def resume(self, interaction: Interaction) -> None:
        player: CustomPlayer = cast(
            CustomPlayer, interaction.user.guild.voice_client)

        await player.pause(False)
