from asyncio import gather, Queue, create_task
from random import shuffle
from enum import Enum
from typing import TypeAlias
from abc import ABC, abstractmethod
from collections import deque
from logging import Logger, getLogger
from re import sub

from yarl import URL

from discord import (
    Client,
    Interaction,
    Embed,
    Member,
    Message
)
from discord.abc import Connectable

from wavelink import (
    Playable,
    Playlist,
    Player,
    Pool,
    Search,
    LavalinkException,
    LavalinkLoadException,
    Filters,
    AutoPlayMode,
    Queue as waveQ
)
from wavelink.node import Node
from wavelink.tracks import PlaylistInfo
from wavelink.types.request import Request as RequestPayload
from wavelink.enums import NodeStatus, QueueMode
from wavelink.payloads import TrackEndEventPayload


class CustomYouTubeMusicPlayable(Playable):

    def __init__(self, data, *, playlist: PlaylistInfo | None = None) -> None:
        super().__init__(data, playlist=playlist)
        if playlist is not None and playlist.url:
            self._playlist.url = playlist.url.replace(
                'www', 'music') or playlist.url
        self._uri = self._uri.replace('www', 'music')


T_a: TypeAlias = list[Playable] | Playlist

logger: Logger = getLogger('wavelink.Player')


class CustomPlayer(Player):

    def __init__(self, client: Client = ..., channel: Connectable = ..., *, nodes: list[Node] | None = None) -> None:
        super().__init__(client, channel, nodes=nodes)
        self.__previous_seeds: Queue[str] = Queue(
            maxsize=self._previous_seeds_cutoff)

        self.interaction: Interaction = None
        self.message: Message = None

        # TODO Filter list
        self.karaoke_filter: bool = False
        self.rotation_filter: bool = False
        self.tremolo_filter: bool = False
        self.vibrato_filter: bool = False

        # TODO Filter template list
        self.nigthcore_filter: bool = False
        self.vaporwave_filter: bool = False
        self.bass_boost_filter: bool = False
        self.soft_filter: bool = False
        self.pop_filter: bool = False
        self.treble_bass: bool = False

    def reset_filter(self) -> None:
        # TODO Filter list
        self.karaoke_filter: bool = False
        self.rotation_filter: bool = False
        self.tremolo_filter: bool = False
        self.vibrato_filter: bool = False

        # TODO Filter template list
        self.nigthcore_filter: bool = False
        self.vaporwave_filter: bool = False
        self.bass_boost_filter: bool = False
        self.soft_filter: bool = False
        self.pop_filter: bool = False
        self.treble_bass: bool = False

    def reset_inner_work(self) -> None:
        self.interaction = None
        self.message = None

        self.reset_filter()

    def current_filter_state(self) -> dict:
        return dict({
            'karaoke': self.karaoke_filter,
            'rotation': self.rotation_filter,
            'tremolo': self.tremolo_filter,
            'vibrato': self.vibrato_filter,
            'nightcore': self.nigthcore_filter,
            'vaporwave': self.vaporwave_filter,
            'bass boost': self.bass_boost_filter,
            'soft': self.soft_filter,
            'pop': self.pop_filter,
            'treble bass': self.treble_bass
        })

    # TODO Create YTMusic Converter
    async def covert_into_ytm(self, playable: Playable):
        try:
            conv: Playable = await Pool.fetch_tracks(f'ytmsearch:{playable.title}')
            conv = conv[0]
            return CustomYouTubeMusicPlayable(data=conv.raw_data, playlist=conv.playlist)
        except:
            return CustomYouTubeMusicPlayable(data=playable.raw_data, playlist=playable.playlist)

    # TODO Fulfill spotify info empty
    async def fulfill_spotify(self, playable: Playable):
        try:

            if playable.source == 'spotify':
                conv: Playable = await Pool.fetch_tracks(playable.uri)
            else:
                def __clean_official(query: str):
                    query = sub(r'\s*\(.*?\)', '', playable.title)
                    return query.strip()

                conv: Playable = await Pool.fetch_tracks(f'spsearch:{__clean_official(playable.title)}')

            conv = conv[0]
            return conv
        except:
            return playable

    async def _auto_play_event(self, payload: TrackEndEventPayload) -> None:
        if self._autoplay is AutoPlayMode.disabled:
            self._inactivity_start()
            return

        if self._error_count >= 3:
            logger.warning(
                "AutoPlay was unable to continue as you have received too many consecutive errors."
                "Please check the error log on Lavalink."
            )
            self._inactivity_start()
            return

        if payload.reason == "replaced":
            self._error_count = 0
            return

        elif payload.reason == "loadFailed":
            self._error_count += 1

        else:
            self._error_count = 0

        if self.node.status is not NodeStatus.CONNECTED:
            logger.warning(
                f'"Unable to use AutoPlay on Player for Guild "{self.guild}" due to disconnected Node.')
            return

        if not isinstance(self.queue, waveQ) or not isinstance(self.auto_queue, waveQ):  # type: ignore
            logger.warning(
                f'"Unable to use AutoPlay on Player for Guild "{self.guild}" due to unsupported Queue.')
            self._inactivity_start()
            return

        if self.queue.mode is QueueMode.loop:
            await self._do_partial(history=False)

        elif self.queue.mode is QueueMode.loop_all:
            await self._do_partial()

        elif self._autoplay is AutoPlayMode.partial or self.queue:
            await self._do_partial()

        elif self._autoplay is AutoPlayMode.enabled:
            async with self._auto_lock:
                await self._do_recommendation()

            # TODO YTMS Caching
            async def _cache_convert_ytm():
                cache_limit: int = 3
                if self.auto_queue.is_empty:
                    return

                for x in range(cache_limit):
                    if self.auto_queue.count >= x \
                            and not 'music' in self.auto_queue[x].uri:
                        self.auto_queue[x] = await self.covert_into_ytm(self.auto_queue[x])

            # TODO Begin converting auto queue in backgroud
            if isinstance(self._original, CustomYouTubeMusicPlayable):
                create_task(_cache_convert_ytm())

    async def _do_recommendation(self):
        assert self.guild is not None
        assert self.queue.history is not None and self.auto_queue.history is not None

        # TODO get rec. only when lower than cuttof
        if self.queue.count > self._auto_cutoff:
            return

        if len(self.auto_queue) > self._auto_cutoff + 1:
            # We still do the inactivity start here since if play fails and we have no more tracks...
            # we should eventually fire the inactivity event...
            self._inactivity_start()

            track: Playable = self.auto_queue.get()
            self.auto_queue.history.put(track)

            # TODO Change it into True
            await self.play(track, add_history=True)
            return

        weighted_history: list[Playable] = self.queue.history[::-
                                                              1][: max(5, 5 * self._auto_weight)]
        weighted_upcoming: list[Playable] = self.auto_queue[: max(
            3, int((5 * self._auto_weight) / 3))]
        choices: list[Playable | None] = [*weighted_history,
                                          *weighted_upcoming, self._current, self._previous]

        # Filter out tracks which are None...
        _previous: deque[str] = self.__previous_seeds._queue  # type: ignore
        seeds: list[Playable] = [
            t for t in choices if t is not None and t.identifier not in _previous]
        shuffle(seeds)

        spotify: list[str] = [
            t.identifier for t in seeds if t.source == "spotify"]
        youtube: list[str] = [
            t.identifier for t in seeds if t.source == "youtube"]

        spotify_query: str | None = None
        youtube_query: str | None = None

        count: int = len(self.queue.history)
        changed_by: int = min(
            3, count) if self._history_count is None else count - self._history_count

        if changed_by > 0:
            self._history_count = count

        changed_history: list[Playable] = self.queue.history[::-1]

        added: int = 0
        for i in range(min(changed_by, 3)):
            track: Playable = changed_history[i]

            if added == 2 and track.source == "spotify":
                break

            if track.source == "spotify":
                spotify.insert(0, track.identifier)
                added += 1

            elif track.source == "youtube":
                youtube[0] = track.identifier

        if spotify:
            spotify_seeds: list[str] = spotify[:3]
            spotify_query = f"sprec:seed_tracks={','.join(spotify_seeds)}&limit=10"

            for s_seed in spotify_seeds:
                self._add_to_previous_seeds(s_seed)

        # TODO Better way to get recomendation based on website
        was_ytms: bool = isinstance(self._original, CustomYouTubeMusicPlayable)
        if youtube:
            ytm_seed: str = youtube[0]
            if was_ytms:
                youtube_query = f"https://music.youtube.com/watch?v={ytm_seed}8&list=RD{ytm_seed}"
            else:
                youtube_query = f"https://youtube.com/watch?v={ytm_seed}8&list=RD{ytm_seed}"
            self._add_to_previous_seeds(ytm_seed)

        async def _search(query: str | None) -> T_a:
            if query is None:
                return []

            try:
                search: Search = await Pool.fetch_tracks(query)
            except (LavalinkLoadException, LavalinkException):
                return []

            if not search:
                return []

            tracks: list[Playable]
            if isinstance(search, Playlist):
                tracks = search.tracks.copy()
            else:
                tracks = search

            return tracks

        results: tuple[T_a, T_a] = await gather(_search(spotify_query), _search(youtube_query))

        # track for result in results for track in result...
        filtered_r: list[Playable] = [t for r in results for t in r]

        if not filtered_r:
            logger.debug(
                f'Player "{self.guild.id}" could not load any songs via AutoPlay.')
            self._inactivity_start()
            return

        if not self._current:
            # TODO Convert using yt_ms converter
            now: CustomYouTubeMusicPlayable | Playable = await self.covert_into_ytm(filtered_r.pop(1)) if was_ytms else filtered_r.pop(1)
            now._recommended = True
            self.auto_queue.history.put(now)

            # TODO Change it into True
            await self.play(now, add_history=True)

        # Possibly adjust these thresholds?
        history: list[Playable] = (
            self.auto_queue[:40] + self.queue[:40] +
            self.queue.history[:-41:-1] + self.auto_queue.history[:-61:-1]
        )

        added: int = 0
        for track in filtered_r:
            if track in history:
                continue

            track._recommended = True
            added += await self.auto_queue.put_wait(track)

        # TODO Disable caching
        # shuffle(self.auto_queue._items)
        logger.debug(
            f'Player "{self.guild.id}" added "{added}" tracks to the auto_queue via AutoPlay.')

        # Probably don't need this here as it's likely to be cancelled instantly...
        self._inactivity_start()

    async def play(
        self,
        track: Playable,
        *,
        replace: bool = True,
        start: int = 0,
        end: int | None = None,
        volume: int | None = None,
        paused: bool | None = None,
        add_history: bool = True,
        filters: Filters | None = None,
    ) -> Playable:
        """Play the provided :class:`~wavelink.Playable`.

        Parameters
        ----------
        track: :class:`~wavelink.Playable`
            The track to being playing.
        replace: bool
            Whether this track should replace the currently playing track, if there is one. Defaults to ``True``.
        start: int
            The position to start playing the track at in milliseconds.
            Defaults to ``0`` which will start the track from the beginning.
        end: Optional[int]
            The position to end the track at in milliseconds.
            Defaults to ``None`` which means this track will play until the very end.
        volume: Optional[int]
            Sets the volume of the player. Must be between ``0`` and ``1000``.
            Defaults to ``None`` which will not change the current volume.
            See Also: :meth:`set_volume`
        paused: bool | None
            Whether the player should be paused, resumed or retain current status when playing this track.
            Setting this parameter to ``True`` will pause the player. Setting this parameter to ``False`` will
            resume the player if it is currently paused. Setting this parameter to ``None`` will not change the status
            of the player. Defaults to ``None``.
        add_history: Optional[bool]
            If this argument is set to ``True``, the :class:`~Player` will add this track into the
            :class:`wavelink.Queue` history, if loading the track was successful. If ``False`` this track will not be
            added to your history. This does not directly affect the ``AutoPlay Queue`` but will alter how ``AutoPlay``
            recommends songs in the future. Defaults to ``True``.
        filters: Optional[:class:`~wavelink.Filters`]
            An Optional[:class:`~wavelink.Filters`] to apply when playing this track. Defaults to ``None``.
            If this is ``None`` the currently set filters on the player will be applied.


        Returns
        -------
        :class:`~wavelink.Playable`
            The track that began playing.


        .. versionchanged:: 3.0.0

            Added the ``paused`` parameter. Parameters ``replace``, ``start``, ``end``, ``volume`` and ``paused``
            are now all keyword-only arguments.

            Added the ``add_history`` keyword-only argument.

            Added the ``filters`` keyword-only argument.
        """
        assert self.guild is not None

        original_vol: int = self._volume
        vol: int = volume or self._volume

        if vol != self._volume:
            self._volume = vol

        # TODO Do Spotify fulfill if playlist
        if track.source == 'spotify' and not track.artist.artwork:
            tmp: Playable = await self.fulfill_spotify(track)
            track = tmp

        if replace or not self._current:
            self._current = track
            self._original = track

        old_previous = self._previous
        self._previous = self._current

        pause: bool
        if paused is not None:
            pause = paused
        else:
            pause = self._paused

        if filters:
            self._filters = filters

        request: RequestPayload = {
            "track": {"encoded": track.encoded, "userData": dict(track.extras)},
            "volume": vol,
            "position": start,
            "endTime": end,
            "paused": pause,
            "filters": self._filters(),
        }

        try:
            await self.node._update_player(self.guild.id, data=request, replace=replace)
        except LavalinkException as e:
            self._current = None
            self._original = None
            self._previous = old_previous
            self._volume = original_vol
            raise e

        # TODO Do isrc finding here too
        if not track.isrc:
            tmp: Playable = await self.fulfill_spotify(track)
            track._isrc = tmp.isrc

        # TODO Reasign track
        if replace or not self._current:
            self._current = track
            self._original = track

        self._paused = pause

        if add_history:
            assert self.queue.history is not None
            self.queue.history.put(track)

        # TODO do recomendation after playing, if auto_queue empty
        if self.autoplay is AutoPlayMode.enabled and self.auto_queue.is_empty:
            create_task(self._do_recommendation())

        # TODO Spotify fullfill
        async def _cache_fulfill_sp(queue: waveQ):
            cache_limit: int = 3
            if queue.is_empty:
                return
            for x in range(cache_limit):
                try:
                    if queue.count >= x \
                            and queue[x].source == 'spotify' \
                            and not queue[x].artist.artwork:
                        queue[x] = await self.fulfill_spotify(queue[x])
                except:
                    continue

        # TODO ISRC caching
        async def _cache_isrc(queue: waveQ):
            cache_limit: int = 3
            if self.queue.is_empty:
                return

            for x in range(cache_limit):
                try:
                    if self.queue.count >= x \
                            and not queue[x].isrc:
                        temp: Playable = await self.fulfill_spotify(queue[x])
                        queue[x]._isrc = temp.isrc
                except:
                    continue

        # TODO Begin searching next isrc
        create_task(_cache_isrc(self.queue))
        create_task(_cache_isrc(self.auto_queue))

        # TODO Begin fulfill in background
        create_task(_cache_fulfill_sp(self.queue))
        create_task(_cache_fulfill_sp(self.auto_queue))

        return track


class FiltersTemplate(Enum):
    NIGHT_CORE = 1
    VAPOR_WAVE = 2
    BASS_BOOST = 3
    SOFT = 4
    POP = 5
    TREBLE_BASS = 6


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

            # TODO Checking palylist
            if url.query.get('list') or any(item in url.path for item in ['playlist', 'album', 'sets']):
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
    async def _play_response(self, member: Member, track: Playlist | Playable, /, *,
                             is_playlist: bool = False, is_queued: bool = False, is_put_front: bool = False, is_autoplay: bool = False) -> Embed:
        pass

    @abstractmethod
    async def play(self, interaction: Interaction, /, query: str | Playable, source: TrackType = TrackType.YOUTUBE,
                   autoplay: bool = None, force_play: bool = False, put_front: bool = False) -> tuple[Playable | Playlist, bool, bool]:
        pass

    @abstractmethod
    async def skip(self, interaction: Interaction, index: int = None) -> None:
        pass

    @abstractmethod
    async def previous(self, interaction: Interaction) -> tuple[bool, bool]:
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
    async def resume(self, interaction: Interaction) -> None:
        pass
