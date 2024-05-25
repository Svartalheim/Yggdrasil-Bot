from asyncio import gather, create_task, Lock
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
    Queue,
    QueueEmpty
)
from wavelink.node import Node
from wavelink.tracks import PlaylistInfo
from wavelink.types.request import Request as RequestPayload


class CustomYouTubeMusicPlayable(Playable):

    def __init__(self, data, *, playlist: PlaylistInfo | None = None) -> None:
        super().__init__(data, playlist=playlist)
        if playlist and playlist.url:
            self._playlist.url = playlist.url.replace('www', 'music')
        self._uri = self._uri.replace('www', 'music')


T_a: TypeAlias = list[Playable] | Playlist

logger: Logger = getLogger('wavelink.player')


class CustomPlayer(Player):

    def __init__(self, client: Client = ..., channel: Connectable = ..., *, nodes: list[Node] | None = None) -> None:
        super().__init__(client, channel, nodes=nodes)

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

        self.queue_lock = Lock()
        self.auto_queue_lock = Lock()
    # TODO Reset filter

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

    # TODO Reset inner work
    def reset_inner_work(self) -> None:
        self.interaction = None
        self.message = None

        self.reset_filter()

    # TODO get current filter state
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

    # TODO clean unused text
    @staticmethod
    def __clean_unused(text: str):
        text = sub(
            r'\b(?:official|vevo|video|audio|- topic)\b|[^a-zA-Z\s]', '', text)
        return text.strip()

    # TODO Fulfill ytms stuff
    # Link uri approcah is imppossible, uri doesnt always have same link
    async def fulfill_youtube_music(self, playable: Playable) -> Playable:
        print(playable.uri)

        try:
            trck: list[Playable] = await Pool.fetch_tracks(f'ytmsearch:{self.__clean_unused(playable.title)} {self.__clean_unused(playable.author)}')
            playable = next(
                (x for x in trck
                 if x.author.lower() in playable.author.lower()
                 and x.title.lower() in playable.title.lower()), playable)

            if not 'lh3' in playable.artwork:
                temp: list[Playable] = await Pool.fetch_tracks(playable.uri)
                playable = temp[0]

        except:
            pass

        return CustomYouTubeMusicPlayable(data=playable.raw_data, playlist=playable.playlist)

    # TODO Fulfill spotify info empty
    async def fulfill_spotify(self, playable: Playable) -> Playable:

        try:
            if playable.source == 'spotify':
                conv: list[Playable] = await Pool.fetch_tracks(playable.uri)
            else:
                conv: list[Playable] = await Pool.fetch_tracks(f'spsearch:{self.__clean_unused(playable.title)} {self.__clean_unused(playable.author)}')

            return conv[0]
        except:
            return playable

    # TODO Custom Recomendation
    async def _do_recommendation(
        self,
        *,
        populate_track: Playable | None = None,
        max_population: int | None = None,
    ) -> None:
        assert self.guild is not None
        assert self.queue.history is not None and self.auto_queue.history is not None

        max_population_: int = max_population if max_population else self._auto_cutoff

        if len(self.auto_queue) > self._auto_cutoff + 1 and not populate_track:
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

        # TODO Change variable name, to get mangled variable
        # Filter out tracks which are None...
        # type: ignore
        _previous: deque[str] = self._Player__previous_seeds._queue
        seeds: list[Playable] = [
            t for t in choices if t is not None and t.identifier not in _previous]
        shuffle(seeds)

        if populate_track:
            seeds.insert(0, populate_track)

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
            spotify_query = f"sprec:seed_tracks={
                ','.join(spotify_seeds)}&limit=10"

            for s_seed in spotify_seeds:
                self._add_to_previous_seeds(s_seed)

        # TODO Better way to get recomendation based on website
        if youtube:
            was_ytms: bool = isinstance(
                self._original, CustomYouTubeMusicPlayable)

            ytm_seed: str = youtube[0]
            if was_ytms:
                youtube_query = f"https://music.youtube.com/watch?v={
                    ytm_seed}8&list=RD{ytm_seed}"
            else:
                youtube_query = f"https://youtube.com/watch?v={
                    ytm_seed}8&list=RD{ytm_seed}"
            self._add_to_previous_seeds(ytm_seed)

        async def _search(query: str | None) -> T_a:
            if query is None:
                return []

            def _into_custom_ytms(trck: Playable) -> CustomYouTubeMusicPlayable:
                return CustomYouTubeMusicPlayable(data=trck.raw_data, playlist=trck.playlist)

            try:
                search: Search = await Pool.fetch_tracks(query)

                # TODO Change into ytms, if it was ytms
                if youtube and isinstance(self._original, CustomYouTubeMusicPlayable):
                    search.tracks = list(map(_into_custom_ytms, search.tracks))
            except (LavalinkLoadException, LavalinkException):
                return []

            if not search:
                return []

            tracks: list[Playable] = search.tracks.copy(
            ) if isinstance(search, Playlist) else search
            return tracks

        results: tuple[T_a, T_a] = await gather(_search(spotify_query), _search(youtube_query))

        # track for result in results for track in result...
        filtered_r: list[Playable] = [t for r in results for t in r]

        if not filtered_r and not self.auto_queue:
            logger.info(
                'Player "%s" could not load any songs via AutoPlay.', self.guild.id)
            self._inactivity_start()
            return

        # Possibly adjust these thresholds?
        history: list[Playable] = (
            self.auto_queue[:40] + self.queue[:40] +
            self.queue.history[:-41:-1] + self.auto_queue.history[:-61:-1]
        )

        added: int = 0

        shuffle(filtered_r)
        for track in filtered_r:
            if track in history:
                continue

            track._recommended = True
            added += await self.auto_queue.put_wait(track)

            if added >= max_population_:
                break

        logger.debug(
            'Player "%s" added "%s" tracks to the auto_queue via AutoPlay.', self.guild.id, added)

        if not self._current and not populate_track:
            try:
                now: Playable = self.auto_queue.get()
                self.auto_queue.history.put(now)

                # TODO Change it into True
                await self.play(now, add_history=True)
            except QueueEmpty:
                logger.info(
                    'Player "%s" could not load any songs via AutoPlay.', self.guild.id)
                self._inactivity_start()

    # TODO Custom play
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
        populate: bool = False,
        max_populate: int = 5,
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
        populate: bool
            Whether the player should find and fill AutoQueue with recommended tracks based on the track provided.
            Defaults to ``False``.

            Populate will only search for recommended tracks when the current tracks has been accepted by Lavalink.
            E.g. if this method does not raise an error.

            You should consider when you use the ``populate`` keyword argument as populating the AutoQueue on every
            request could potentially lead to a large amount of tracks being populated.
        max_populate: int
            The maximum amount of tracks that should be added to the AutoQueue when the ``populate`` keyword argument is
            set to ``True``. This is NOT the exact amount of tracks that will be added. You should set this to a lower
            amount to avoid the AutoQueue from being overfilled.

            This argument has no effect when ``populate`` is set to ``False``.

            Defaults to ``5``.


        Returns
        -------
        :class:`~wavelink.Playable`
            The track that began playing.


        .. versionchanged:: 3.0.0

            Added the ``paused`` parameter. Parameters ``replace``, ``start``, ``end``, ``volume`` and ``paused``
            are now all keyword-only arguments.

            Added the ``add_history`` keyword-only argument.

            Added the ``filters`` keyword-only argument.


        .. versionchanged:: 3.3.0

            Added the ``populate`` keyword-only argument.
        """
        assert self.guild is not None

        original_vol: int = self._volume
        vol: int = volume or self._volume

        if vol != self._volume:
            self._volume = vol

        task: list = list()

        # TODO search isrc and required things
        if not track.isrc or not track.artist.artwork or not track.album or track.source == 'spotify':
            task.append(create_task(self.fulfill_spotify(track)))

        # TODO Reqeuest straight to url, if its yotube
        if track.source == 'youtube':
            was_ytms: bool = isinstance(track, CustomYouTubeMusicPlayable)
            if was_ytms and not 'lh3' in track.artwork:
                task.append(create_task(self.fulfill_youtube_music(track)))

            if not was_ytms and 'maxres' not in track.artwork:
                task.append(create_task(Pool.fetch_tracks(track.uri)))

        # TODO Check if need to run task
        spot: Playable = None
        for x in await gather(*task):
            try:
                if isinstance(x, list):
                    x: Playable = x[0]

                if x.source == 'spotify':
                    spot = x
                else:
                    track = x
            except:
                pass

        # TODO Assign new info
        if spot:
            track._isrc = spot.isrc
            track._artist.artwork = spot.artist.artwork
            track._album = spot.album

        if replace or not self._current:
            self._current = track
            self._original = track

        old_previous = self._previous
        self._previous = self._current
        self.queue._loaded = track

        pause: bool = paused if paused is not None else self._paused

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
            self.queue._loaded = old_previous
            self._current = None
            self._original = None
            self._previous = old_previous
            self._volume = original_vol
            raise e

        self._paused = pause

        if add_history:
            assert self.queue.history is not None
            self.queue.history.put(track)

        if populate:
            await self._do_recommendation(populate_track=track, max_population=max_populate)

        # TODO Do caching
        create_task(self.do_caching_stuff())

        return track

    # TODO Caching logic
    async def do_caching_stuff(self) -> None:
        # TODO Caching stuff
        async def _cache_stuff(queue: Queue, lock: Lock):
            async with lock:
                cache_limit: int = 5
                if queue.is_empty:
                    return

                for x in range(cache_limit):
                    task: list = list()

                    if queue.count >= (x+1):
                        # TODO Do required task
                        if queue[x].isrc and queue[x].artist.artwork:
                            task.append(create_task(
                                self.fulfill_spotify(queue[x])))

                        if isinstance(queue[x], CustomYouTubeMusicPlayable) and 'lh3' not in queue[x].artwork:
                            task.append(create_task(
                                self.fulfill_youtube_music(queue[x])))

                        # TODO gather task, and assign it
                        temp_spot: Playable = None
                        for a in await gather(*task):
                            try:
                                if a.source == 'spotify':
                                    temp_spot = a
                                else:
                                    queue[x] = a
                            except:
                                pass

                        if temp_spot:
                            queue[x]._isrc = temp_spot.isrc
                            queue[x]._artist.artwork = temp_spot.artist.artwork
                            queue[x]._album = temp_spot.album

        # TODO Do caching
        create_task(_cache_stuff(self.queue, self.queue_lock))
        create_task(_cache_stuff(self.auto_queue, self.auto_queue_lock))

    # TODO Custom stop
    async def stop(self, *, force: bool = True) -> Playable | None:
        await super().stop(force=force)

        self.reset_inner_work()

        return


class FiltersTemplate(Enum):
    DISABLE = 0
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
    async def skip(self, interaction: Interaction, index: int = None, seconds: int = None) -> None:
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
