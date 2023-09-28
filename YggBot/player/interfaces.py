from asyncio import gather
from enum import Enum
from typing import Any, Tuple
from abc import ABC, abstractmethod

from pykakasi import kakasi

from discord import Interaction, Embed, Member

from wavelink import (
    Player,
    Playable,
    YouTubeMusicTrack,
    YouTubeTrack,
    YouTubePlaylist,
    Playlist,
    InvalidLavalinkResponse,
    Node,
)
from wavelink.types.track import Track as TrackPayload
from wavelink.ext.spotify import (
    SpotifyTrack,
    SpotifyClient,
    SpotifyRequestError,
    RECURL
)

from .util_player import UtilTrackPlayer


class CustomPlayer(Player):

    async def fulfill_spotify_custom(self, track: SpotifyTrack, populate: bool) -> Playable:
        yt_track: CustomYouTubeTrack = None
        ytms_track: CustomYouTubeMusicTrack = None

        async def __search_based(cls: CustomYouTubeTrack | CustomYouTubeMusicTrack) -> list[CustomYouTubeTrack | CustomYouTubeMusicTrack]:
            tracks: CustomYouTubeMusicTrack | CustomYouTubeTrack = None
            if not track.isrc:
                tracks: list[cls] = await cls.search(f'{track.name} - {track.artists}')
            else:
                tracks: list[cls] = await cls.search(f'"{track.isrc}"')
                if not tracks:
                    tracks: list[cls] = await cls.search(f'{track.name} - {track.artists}')

            tracks = tracks[0]
            return tracks

        def __was_contains_japanese(text: str) -> bool:
            for char in text:
                if ('\u4e00' <= char <= '\u9fff'  # Kanji
                    or '\u3040' <= char <= '\u309f'  # Hiragana
                    or '\u30a0' <= char <= '\u30ff'  # Katakana
                    or '\u31f0' <= char <= '\u31ff'  # Katakana Phonetic Extensions
                    or '\uff66' <= char <= '\uff9f'  # Halfwidth Katakana
                    ):
                    return True
            return False

        async def __populate_seeds() -> None:
            node: Node = self.current_node
            sc: SpotifyClient | None = node._spotify

            if not sc:
                raise RuntimeError(
                    f"There is no spotify client associated with <{node:!r}>")

            if sc.is_token_expired():
                await sc._get_bearer_token()

            if len(self._track_seeds) == 5:
                self._track_seeds.pop(0)

            self._track_seeds.append(track.id)

            url: str = RECURL.format(tracks=','.join(self._track_seeds))
            async with node._session.get(url=url, headers=sc.bearer_headers) as resp:
                if resp.status != 200:
                    raise SpotifyRequestError(resp.status, resp.reason)

                data = await resp.json()

            for reco in data['tracks']:
                reco = SpotifyTrack(reco)
                UtilTrackPlayer.spotify_patcher(reco)
                if reco in self.auto_queue or reco in self.auto_queue.history:
                    continue

                await self.auto_queue.put_wait(reco)

            return None

        yt_track, ytms_track = await gather(
            __search_based(cls=CustomYouTubeTrack),
            __search_based(cls=CustomYouTubeMusicTrack),
            # add Sleep Each request? Idk, sometimes youtube gave rate limit
            # sleep(2),
            return_exceptions=True
        )

        if isinstance(yt_track, IndexError) or isinstance(ytms_track, IndexError):
            track.title + "```(track load failed)```"
            track: Playable | SpotifyTrack = await self.queue.get_wait() if self.autoplay else await self.auto_queue.get_wait()
            await self.play(track=track, populate=self.autoplay)

        if populate:
            await __populate_seeds()

        artist_converted: str = next((x['hepburn'] for x in kakasi().convert(
            text=track.artists) if __was_contains_japanese(text=str(track.artists))), track.artists)

        if ytms_track and artist_converted.casefold() in ytms_track.author.casefold():
            ytms_track.spotify_original = track
            return ytms_track

        if yt_track and ('official' in yt_track.title.casefold() or artist_converted.casefold() in yt_track.author.casefold()):
            yt_track: CustomYouTubeMusicTrack = CustomYouTubeMusicTrack(
                data=yt_track.data)
        yt_track.spotify_original = track
        return yt_track

    async def play(self,
                   track: Playable | SpotifyTrack,
                   replace: bool = True,
                   start: int | None = None,
                   end: int | None = None,
                   volume: int | None = None,
                   *,
                   populate: bool = False
                   ) -> Playable:
        """|coro|

        Play a WaveLink Track.

        Parameters
        ----------
        track: :class:`tracks.Playable`
            The :class:`tracks.Playable` or :class:`~wavelink.ext.spotify.SpotifyTrack` track to start playing.
        replace: bool
            Whether this track should replace the current track. Defaults to ``True``.
        start: Optional[int]
            The position to start the track at in milliseconds.
            Defaults to ``None`` which will start the track at the beginning.
        end: Optional[int]
            The position to end the track at in milliseconds.
            Defaults to ``None`` which means it will play until the end.
        volume: Optional[int]
            Sets the volume of the player. Must be between ``0`` and ``1000``.
            Defaults to ``None`` which will not change the volume.
        populate: bool
            Whether to populate the AutoPlay queue. Defaults to ``False``.

            .. versionadded:: 2.0

        Returns
        -------
        :class:`~tracks.Playable`
            The track that is now playing.


        .. note::

            If you pass a :class:`~wavelink.YouTubeTrack` **or** :class:`~wavelink.ext.spotify.SpotifyTrack` and set
            ``populate=True``, **while** :attr:`~wavelink.Player.autoplay` is set to ``True``, this method will populate
            the ``auto_queue`` with recommended songs. When the ``auto_queue`` is low on tracks this method will
            automatically populate the ``auto_queue`` with more tracks, and continue this cycle until either the
            player has been disconnected or :attr:`~wavelink.Player.autoplay` is set to ``False``.


        Example
        -------

        .. code:: python3

            tracks: list[wavelink.YouTubeTrack] = await wavelink.YouTubeTrack.search(...)
            if not tracks:
                # Do something as no tracks were found...
                return

            await player.queue.put_wait(tracks[0])

            if not player.is_playing():
                await player.play(player.queue.get(), populate=True)


        .. versionchanged:: 2.6.0

            This method now accepts :class:`~wavelink.YouTubeTrack` or :class:`~wavelink.ext.spotify.SpotifyTrack`
            when populating the ``auto_queue``.
        """
        assert self._guild is not None

        if isinstance(track, YouTubeTrack) and self.autoplay and populate:
            was_ytms: bool = isinstance(track, CustomYouTubeMusicTrack)
            query: str = f'https://{"music" if was_ytms else "www"}.youtube.com/watch?v={track.identifier}&list=RD{track.identifier}'

            try:
                recos: YouTubePlaylist = await self.current_node.get_playlist(query=query, cls=YouTubePlaylist)
                recos: list[YouTubeTrack] = getattr(recos, 'tracks', [])

                queues = set(self.queue) | set(self.auto_queue) | set(
                    self.auto_queue.history) | {track}

                for track_ in recos:
                    track_ = CustomYouTubeTrack(data=track_.data)

                    if was_ytms:
                        track_ = CustomYouTubeMusicTrack(data=track_.data)

                    if track_ in queues:
                        continue

                    await self.auto_queue.put_wait(track_)

                self.auto_queue.shuffle()
            except ValueError:
                pass

        elif isinstance(track, SpotifyTrack):
            track = UtilTrackPlayer.spotify_patcher(track)
            original = track
            track: CustomYouTubeMusicTrack | CustomYouTubeTrack = await self.fulfill_spotify_custom(track=track, populate=populate)
            track.spotify_original = original

            if populate:
                self.auto_queue.shuffle()

            for attr, value in original.__dict__.items():
                if hasattr(track, attr):
                    # ModularUtil.simple_log(f'Player {self.guild.id} was unable to set attribute "{attr}" '
                    #                f'when converting a SpotifyTrack as it conflicts with the new track type.')
                    continue

                setattr(track, attr, value)

        data = {
            'encodedTrack': track.encoded,
            'position': start or 0,
            'volume': volume or self._volume
        }

        if end:
            data['endTime'] = end

        self._current = track
        self._original = track

        try:

            resp: dict[str, Any] = await self.current_node._send(
                method='PATCH',
                path=f'sessions/{self.current_node._session_id}/players',
                guild_id=self._guild.id,
                data=data,
                query=f'noReplace={not replace}'
            )

        except InvalidLavalinkResponse as e:
            self._current = None
            self._original = None
            # ModularUtil.simple_log(f'Player {self._guild.id} attempted to load track: {track}, but failed: {e}')
            raise e

        self._player_state['track'] = resp['track']['encoded']

        if not (self.queue.loop and self.queue._loaded):
            self.queue.history.put(track)

        self.queue._loaded = track

        # ModularUtil.simple_log(f'Player {self._guild.id} loaded and started playing track: {track}.', )
        return track


class CustomYouTubeTrack(YouTubeTrack):

    def __init__(self, data: TrackPayload) -> None:
        super().__init__(data)
        self.spotify_original: SpotifyTrack = None


class CustomYouTubeMusicTrack(YouTubeMusicTrack):

    def __init__(self, data: TrackPayload) -> None:
        super().__init__(data)
        self.uri = self.uri.replace('www', 'music')
        self.spotify_original: SpotifyTrack = None


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

            elif 'music.youtube.com' in uri:
                return cls.YOUTUBE_MUSIC

            elif 'youtube.com' in uri:
                return cls.YOUTUBE

            elif 'soundcloud.com' in uri:
                return cls.SOUNCLOUD

    def favicon(self) -> str:
        favicon: str = "https://www.google.com/s2/favicons?domain={domain}&sz=256"

        if self == self.YOUTUBE:
            return favicon.format(domain="https://youtube.com")

        elif self is self.YOUTUBE_MUSIC:
            return favicon.format(domain="https://music.youtube.com")

        elif self is self.SPOTIFY:
            return favicon.format(domain="https://spotify.com")

        elif self is self.SOUNCLOUD:
            return favicon.format(domain="https://soundcloud.com")


class TrackPlayerInterface(ABC):

    @abstractmethod
    async def _play_response(self, member: Member, /, track: Playlist | Playable | SpotifyTrack | list[SpotifyTrack],
                             is_playlist: bool = False, is_queued: bool = False, is_put_front: bool = False, is_autoplay: bool = False, uri: str = None) -> Embed:
        pass

    @abstractmethod
    def _record_timestamp(self, guild_id: int, interaction: Interaction) -> None:
        pass

    @abstractmethod
    def _get_interaction(self, guild_id: int) -> Interaction:
        pass

    @abstractmethod
    async def play(self, interaction: Interaction, /, query: str | Playable | SpotifyTrack, source: TrackType = TrackType.YOUTUBE,
                   autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> Tuple[Playable | Playlist | SpotifyTrack, bool, bool]:
        pass

    @abstractmethod
    async def skip(self, interaction: Interaction, index: int = None) -> None:
        pass

    @abstractmethod
    async def previous(self, interaction: Interaction) -> Tuple[bool, bool]:
        pass

    @abstractmethod
    async def stop(self, interaction: Interaction) -> None:
        pass

    @abstractmethod
    def loop(self, interaction: Interaction, /, is_queue: bool = False) -> bool:
        pass

    @abstractmethod
    async def pause(self, interaction: Interaction) -> None:
        pass

    @abstractmethod
    async def resume(self, interaction: Interaction) -> bool:
        pass
