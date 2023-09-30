from typing import Tuple
from itertools import chain

from discord import Interaction, Embed, VoiceChannel
from discord.ui import View

from wavelink import Playable, Playlist

from .interfaces import CustomPlayer, TrackType, CustomSpotifyTrack
from .util_player import UtilTrackPlayer
from .base_player import TrackPlayerBase
from .view import QueueView, SelectView


class TrackPlayer(TrackPlayerBase):

    async def join(self, interaction: Interaction) -> None:
        channel:  VoiceChannel = interaction.user.voice.channel
        await channel.connect(cls=CustomPlayer)

    async def leave(self, interaction: Interaction) -> None:
        player: CustomPlayer = interaction.user.guild.voice_client
        await player.disconnect()

    async def search(self, query: str, interaction: Interaction, source: TrackType = TrackType.YOUTUBE,
                     autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> Tuple[Embed, View]:
        view: View = None
        embed: Embed = None

        if query.startswith("http"):
            source = TrackType.what_type(query)

        tracks: Playable | Playlist | CustomSpotifyTrack | list[CustomSpotifyTrack] = await self._custom_wavelink_player(query=query, track_type=source, is_search=True)
        view: SelectView = SelectView(self, interaction, data=tracks if not isinstance(
            tracks, Playlist) else tracks.tracks, autoplay=autoplay, force_play=force_play, put_front=put_front)
        embed = view.get_embed

        return (embed, view)

    async def play(self, interaction: Interaction, /, query: str | Playable | CustomSpotifyTrack, source: TrackType = TrackType.YOUTUBE,
                   autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> Tuple[Playable | Playlist | CustomSpotifyTrack, bool, bool]:
        is_playlist = is_queued = False
        was_playable: bool = isinstance(query, Playable | CustomSpotifyTrack)
        player: CustomPlayer = None

        if not interaction.guild.voice_client:
            player = await interaction.user.voice.channel.connect(cls=CustomPlayer)

        else:
            player = interaction.user.guild.voice_client

        track_type: TrackType = (TrackType.what_type(
            uri=query) if not was_playable else None) or source

        if not was_playable:
            tracks: Playable | Playlist | CustomSpotifyTrack | list[CustomSpotifyTrack] = await self._custom_wavelink_player(query=query, track_type=track_type)

        else:
            tracks = query

        if autoplay is not None:
            player.autoplay = autoplay

            if not player.autoplay:
                player.auto_queue.clear()

        if isinstance(tracks, Playlist | list):
            playlist: list = tracks.tracks if isinstance(
                tracks, Playlist) else tracks

            if player.is_playing() and force_play:
                player.queue.put_at_front(player.queue.history.pop())

            if put_front or force_play:
                player.queue.put_at_front(playlist.pop())

                if playlist:
                    player.queue._queue.extendleft(playlist)

            else:
                player.queue.extend(playlist)

            if force_play and player.is_playing():
                await player.seek(player.current.length * 1000)

            elif not player.is_playing():
                trck: Playable | CustomSpotifyTrack = await player.queue.get_wait()
                await player.play(trck)

            is_playlist = True
        elif player.is_playing() or player.is_paused():
            if force_play:
                player.queue.put_at_front(player.queue.history.pop())
                player.queue.put_at_front(tracks)
                await player.seek(player.current.length * 1000)

            if put_front:
                player.queue.put_at_front(tracks)

            elif not force_play:
                await player.queue.put_wait(tracks)

            is_queued = True
        else:
            await player.play(tracks, populate=True if autoplay and track_type is not TrackType.SOUNCLOUD else False)

        return (tracks, is_playlist, is_queued)

    async def queue(self, interaction: Interaction, /, is_history: bool = False) -> Tuple[Embed, View]:
        player: CustomPlayer = interaction.user.guild.voice_client
        view: View = None
        embed: Embed = None

        view = QueueView(queue=player.queue.history if is_history else chain(
            player.queue, player.auto_queue), interaction=interaction, is_history=is_history)
        embed = view.get_embed

        return (embed, view)

    async def skip(self, interaction: Interaction, index: int = None) -> None:
        player: CustomPlayer = interaction.user.guild.voice_client

        if index is not None:
            track: Playable | CustomSpotifyTrack = None

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
        player: CustomPlayer = interaction.user.guild.voice_client

        view: View = None
        embed: Embed = None

        view: SelectView = SelectView(
            self, interaction, data=chain(player.queue, player.auto_queue), is_jump_command=True)
        embed = view.get_embed

        return (embed, view)

    async def previous(self, interaction: Interaction) -> Tuple[bool, bool]:
        was_allowed: bool = True
        player: CustomPlayer = interaction.user.guild.voice_client

        was_on_loop: bool = player.queue.loop
        if not player.queue.history.is_empty and player.queue.history.count >= 1 and player.queue.history[-1] is player._original:
            player.queue.put_at_front(player.queue.history.pop())
            player.queue.put_at_front(player.queue.history.pop())
            await player.seek(player.current.length * 1000)

        else:
            was_allowed = False

        if player.is_paused():
            await player.resume()

        return (was_allowed, was_on_loop)

    async def stop(self, interaction: Interaction) -> None:
        player: CustomPlayer = interaction.user.guild.voice_client

        if player.autoplay:
            player.autoplay = False

        if not player.queue.is_empty or not player.auto_queue.is_empty:
            player.queue.reset()
            player.auto_queue.reset()

        await player.stop()

    def clear(self, interaction: Interaction) -> None:
        player: CustomPlayer = interaction.user.guild.voice_client

        if player.autoplay:
            player.autoplay = False

        if not player.queue.is_empty or not player.auto_queue.is_empty:
            player.queue.reset()
            player.auto_queue.reset()

    def shuffle(self, interaction: Interaction) -> None:
        player: CustomPlayer = interaction.user.guild.voice_client

        player.queue.shuffle()

    def now_playing(self, interaction: Interaction) -> Tuple[Playable, int, int]:
        player: CustomPlayer = interaction.user.guild.voice_client

        time: int = (player.current.duration - player.position)//1000
        duration: str = UtilTrackPlayer.parseSec(player.current.duration)

        return (player.current, time, duration)

    def loop(self, interaction: Interaction, /, is_queue: bool = False) -> bool:
        player: CustomPlayer = interaction.user.guild.voice_client
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
        player: CustomPlayer = interaction.user.guild.voice_client

        await player.pause()

    async def resume(self, interaction: Interaction) -> bool:
        player: CustomPlayer = interaction.user.guild.voice_client

        if player.is_paused():
            await player.resume()
            return True

        return False
