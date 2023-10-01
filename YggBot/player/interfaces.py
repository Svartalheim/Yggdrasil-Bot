from asyncio import gather
from enum import Enum
from typing import Any, Tuple
from abc import ABC, abstractmethod

from yarl import URL

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
    NodePool
)
from wavelink.types.track import Track as TrackPayload
from wavelink.ext.spotify import (
    SpotifyTrack,
    SpotifyClient,
    SpotifyRequestError,
    SpotifyDecodePayload,
    decode_url,
    SpotifySearchType,
    RECURL
)

# from ..util import ModularUtil


class CustomYouTubeMusicTrack(YouTubeMusicTrack):

    def __init__(self, data: TrackPayload) -> None:
        super().__init__(data)
        self.uri = self.uri.replace('www', 'music')


class CustomSpotifyTrack(SpotifyTrack):

    __slots__ = ('fetched')

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

        self.uri: str = self.__spotify_link_fixed(self.uri)
        self.images: str = self.images[0]

        self.fetched: YouTubeTrack | CustomYouTubeMusicTrack = None

    def __str__(self) -> str:
        return f'{self.name} - {self.author}'

    @property
    def author(self):
        return ', '.join(self.artists).strip()

    @staticmethod
    def __spotify_link_fixed(uri: str) -> str:
        openable_link: str = "https://open.spotify.com/{track_type}/{id}"
        uri_split: list[str] = uri.split(":")
        id: str = uri_split[2]
        track_type: str = uri_split[1]

        return openable_link.format(track_type=track_type, id=id)

    @classmethod
    async def search(
            cls,
            query: str,
            *,
            node: Node | None = None,
            limit: int = 10
    ) -> list['CustomSpotifyTrack']:
        """|coro|

        Search for tracks with the given query.

        Parameters
        ----------
        query: str
            The Spotify URL to query for.
        node: Optional[:class:`wavelink.Node`]
            An optional Node to use to make the search with.

        Returns
        -------
        List[:class:`SpotifyTrack`]

        Examples
        --------
        Searching for a singular tack to play...

        .. code:: python3

            tracks: list[spotify.SpotifyTrack] = await spotify.SpotifyTrack.search(query=SPOTIFY_URL)
            if not tracks:
                # No tracks found, do something?
                return

            track: spotify.SpotifyTrack = tracks[0]


        Searching for all tracks in an album...

        .. code:: python3

            tracks: list[spotify.SpotifyTrack] = await spotify.SpotifyTrack.search(query=SPOTIFY_URL)
            if not tracks:
                # No tracks found, do something?
                return


        .. versionchanged:: 2.6.0

            This method no longer takes in the ``type`` parameter. The query provided will be automatically decoded,
            if the ``type`` returned by :func:`decode_url` is unusable, this method will return an empty :class:`list`
        """
        if node is None:
            node: Node = NodePool.get_connected_node()

        if not query.startswith('http'):
            data: dict = dict()

            sp_client: SpotifyClient = node._spotify
            if sp_client.is_token_expired():
                await sp_client._get_bearer_token()

            uri = "https://api.spotify.com/v1/search?q={q}&type={type}&limit={limit}"
            uri = uri.format(q=query, type="track", limit=limit)

            async with sp_client.session.get(uri, headers=sp_client.bearer_headers) as resp:
                if resp.status == 400:
                    return None

                elif resp.status != 200:
                    raise SpotifyRequestError(resp.status, resp.reason)

                data = await resp.json()
                data = data['tracks']['items']

            return [CustomSpotifyTrack(data=x) for x in data]
        else:
            decoded: SpotifyDecodePayload = decode_url(query)

            if not decoded or decoded.type is SpotifySearchType.unusable:
                # logger.debug(f'Spotify search handled an unusable search type for query: "{query}".')
                return []

            return [CustomSpotifyTrack(data=x.raw) for x in await node._spotify._search(query=query, type=decoded.type)]

    async def fulfill(self, *, player: Player, populate: bool) -> None:
        """Used to fulfill the :class:`wavelink.Player` Auto Play Queue.

        .. warning::

            Usually you would not call this directly. Instead you would set :attr:`wavelink.Player.autoplay` to true,
            and allow the player to fulfill this request automatically.


        Parameters
        ----------
        player: :class:`wavelink.player.Player`
            If :attr:`wavelink.Player.autoplay` is enabled, this search will fill the AutoPlay Queue with more tracks.
        cls
            The class to convert this Spotify Track to.
        """

        yt_track: YouTubeTrack = None
        ytms_track: CustomYouTubeMusicTrack = None

        async def __search_based(cls: YouTubeTrack | CustomYouTubeMusicTrack) -> YouTubeTrack | CustomYouTubeMusicTrack:
            tracks: CustomYouTubeMusicTrack | YouTubeTrack = None
            if not self.isrc:
                tracks: list[cls] = await cls.search(f'{self.name} - {self.artists[0]}')

            else:
                tracks: list[cls] = await cls.search(f'"{self.isrc}"')

                if not tracks:
                    tracks: list[cls] = await cls.search(f'{self.name} - {self.artists[0]}')

            return tracks[0] if tracks else None

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
            node: Node = player.current_node
            sc: SpotifyClient | None = node._spotify

            if not sc:
                raise RuntimeError(
                    f"There is no spotify client associated with <{node:!r}>")

            if sc.is_token_expired():
                await sc._get_bearer_token()

            if len(player._track_seeds) == 5:
                player._track_seeds.pop(0)

            player._track_seeds.append(self.id)

            url: str = RECURL.format(tracks=','.join(player._track_seeds))
            async with node._session.get(url=url, headers=sc.bearer_headers) as resp:
                if resp.status != 200:
                    raise SpotifyRequestError(resp.status, resp.reason)

                data = await resp.json()

            history = set(player.queue) | set(player.auto_queue) | set(
                    player.auto_queue.history) | {self}

            for reco in data['tracks']:
                reco = CustomSpotifyTrack(reco)

                if reco in history:
                    continue

                await player.auto_queue.put_wait(reco)

            return None

        yt_track, ytms_track = await gather(
            __search_based(cls=YouTubeTrack),
            __search_based(cls=CustomYouTubeMusicTrack)
        )

        if populate:
            await __populate_seeds()

        artist_converted: str = next((x['hepburn'] for x in kakasi().convert(
            text=self.author) if __was_contains_japanese(text=str(self.author))), self.author)

        if ytms_track and artist_converted.casefold() in ytms_track.author.casefold():
            self.fetched = ytms_track
            return
            # return ModularUtil.simple_log(f'Fulfilled {self} with {self.fetched} from {type(self.fetched).__name__}.', )

        if yt_track and ('music' in yt_track.title.casefold()
                         or 'topic' in yt_track.author.casefold()
                         or artist_converted.casefold() in yt_track.author.casefold()
                         ):
            yt_track: CustomYouTubeMusicTrack = CustomYouTubeMusicTrack(
                data=yt_track.data)

        self.fetched = yt_track
        return
        # return ModularUtil.simple_log(f'Fulfilled {self} with {self.fetched} from {type(self.fetched).__name__}.', )


class CustomPlayer(Player):

    async def play(self,
                   track: Playable | CustomSpotifyTrack,
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

        original: Playable | CustomSpotifyTrack = track
        if isinstance(track, YouTubeTrack) and self.autoplay and populate:
            was_ytms: bool = isinstance(track, CustomYouTubeMusicTrack)
            query: str = f'https://{"music" if was_ytms else "www"}.youtube.com/watch?v={track.identifier}&list=RD{track.identifier}'

            try:
                recos: YouTubePlaylist = await self.current_node.get_playlist(query=query, cls=YouTubePlaylist)
                recos: list[YouTubeTrack] = getattr(recos, 'tracks', [])

                queues = set(self.queue) | set(self.auto_queue) | set(
                    self.auto_queue.history) | {track}

                for track_ in recos:
                    track_ = CustomYouTubeMusicTrack(
                        data=track_.data) if was_ytms else track_

                    if track_ in queues:
                        continue

                    await self.auto_queue.put_wait(track_)

            except ValueError:
                pass

        elif isinstance(track, CustomSpotifyTrack):
            if not track.fetched:
                await track.fulfill(player=self, populate=populate)

            track = track.fetched

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
        self._original = original

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
            self.queue.history.put(original)

        self.queue._loaded = track

        # ModularUtil.simple_log(f'Player {self._guild.id} loaded and started playing track: {track}.', )
        return track


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

            elif 'youtube.com' in uri or 'youtu.be' in uri:
                return cls.YOUTUBE

            elif 'soundcloud.com' in uri:
                return cls.SOUNCLOUD

    def is_playlist(self, uri: str):
        if uri.startswith('http'):
            url: URL = URL(uri)

            if self is self.SPOTIFY \
                    and decode_url(uri).type in (SpotifySearchType.playlist, SpotifySearchType.album):
                return True
            elif url.query.get('list') or 'sets' in url.path:
                return True

        return False

    def favicon(self) -> str:
        favicon: str = "https://www.google.com/s2/favicons?domain={domain}&sz=256"

        if self is self.YOUTUBE:
            return favicon.format(domain="https://youtube.com")

        elif self is self.YOUTUBE_MUSIC:
            return favicon.format(domain="https://music.youtube.com")

        elif self is self.SPOTIFY:
            return favicon.format(domain="https://spotify.com")

        elif self is self.SOUNCLOUD:
            return favicon.format(domain="https://soundcloud.com")


class TrackPlayerInterface(ABC):

    @abstractmethod
    async def _play_response(self, member: Member, /, track: Playlist | Playable | CustomSpotifyTrack | list[CustomSpotifyTrack],
                             is_playlist: bool = False, is_queued: bool = False, is_put_front: bool = False, is_autoplay: bool = False, uri: str = None) -> Embed:
        pass

    @abstractmethod
    def _record_timestamp(self, guild_id: int, interaction: Interaction) -> None:
        pass

    @abstractmethod
    def _get_interaction(self, guild_id: int) -> Interaction:
        pass

    @abstractmethod
    async def play(self, interaction: Interaction, /, query: str | Playable | CustomSpotifyTrack, source: TrackType = TrackType.YOUTUBE,
                   autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> Tuple[Playable | Playlist | CustomSpotifyTrack, bool, bool]:
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
