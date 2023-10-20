from json import loads
from re import sub

from pykakasi import kakasi

from aiohttp import ClientSession

from yarl import URL

from wavelink import Playable, Node, NodePool
from wavelink.ext.spotify import (
    SpotifyClient,
    SpotifyRequestError,
    SpotifyDecodePayload,
    decode_url,
    BASEURL
)

from .interfaces import CustomSpotifyTrack
from config import YggConfig


class UtilTrackPlayer:

    @staticmethod
    async def get_raw_spotify_playlist(uri: str) -> dict:
        node: Node = NodePool.get_connected_node()
        decoded: SpotifyDecodePayload = decode_url(url=uri)
        id: str = decoded.id
        track_type: str = decoded.type.name
        data: dict = dict()

        sp_client: SpotifyClient = node._spotify
        session: ClientSession = sp_client.session
        if sp_client.is_token_expired():
            await sp_client._get_bearer_token()

        uri = BASEURL.format(entity=track_type, identifier=id)

        async with session.get(uri, headers=sp_client.bearer_headers) as resp:
            if resp.status == 400:
                return None

            elif resp.status != 200:
                raise SpotifyRequestError(resp.status, resp.reason)

            data = await resp.json()
            data.pop("tracks")

        data['uri'] = data['external_urls']['spotify']

        return data

    @staticmethod
    def extract_index_youtube(q: str) -> int:
        index: int = None

        if q.startswith('http'):
            url = URL(q)
            index = int(url.query.get('start_radio')) or int(
                url.query.get('index'))

        return index

    @staticmethod
    def parseSec(sec: int) -> str:
        sec = sec // 1000
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if sec >= 3600:
            return f'{h:d}h {m:02d}m {s:02d}s'
        else:
            return f'{m:02d}m {s:02d}s'


class MusixMatchAPI:

    class StatusCodeHandling(Exception):

        STATUS_CODES = {
            200: "The request was successful.",
            400: "The request had bad syntax or was inherently impossible to be satisfied.",
            401: "Authentication failed, probably because of invalid/missing API key.",
            402: "The usage limit has been reached, either you exceeded per day requests limits or your balance is insufficient.",
            403: "You are not authorized to perform this operation.",
            404: "The requested resource was not found.",
            405: "The requested method was not found.",
            500: "Ops. Something were wrong.",
            503: "Our system is a bit busy at the moment and your request can't be satisfied.",
        }

        def __init__(self, status_code: int) -> None:
            if status_code in self.STATUS_CODES:
                message = self.STATUS_CODES[status_code]
            else:
                message = f"Unexpected status code: {status_code}"

            super().__init__(message)

    API_URL: str = "https://api.musixmatch.com/ws/1.1/"

    def __init__(self, track: Playable | CustomSpotifyTrack, session: ClientSession) -> None:
        self.__track: Playable | CustomSpotifyTrack = track
        self.__session: ClientSession = session

        self.__params: dict = {
            'apikey': YggConfig.MUSIXMATCH_KEY
        }

    @property
    def favicon(self) -> str:
        return "https://www.google.com/s2/favicons?domain={domain}&sz=256".format(domain="https://musixmatch.com")

    def __was_contains_japanese(self, text: str) -> bool:
        for char in text:
            if ('\u4e00' <= char <= '\u9fff'  # Kanji
                    or '\u3040' <= char <= '\u309f'  # Hiragana
                    or '\u30a0' <= char <= '\u30ff'  # Katakana
                    or '\u31f0' <= char <= '\u31ff'  # Katakana Phonetic Extensions
                    or '\uff66' <= char <= '\uff9f'  # Halfwidth Katakana
                    ):
                return True
        return False

    async def __fulfill_with_spotify(self) -> None:
        spot: list[CustomSpotifyTrack] = await CustomSpotifyTrack.search(
            query=self.__track.title,
            limit=1
        )
        self.__track = spot[0]

    async def __requester(self, path: str, /, params: dict) -> dict:
        data: dict = None
        self.__params.update(params)

        async with self.__session.get(url=self.API_URL+path, params=self.__params) as resp:
            if resp.status != 200:
                raise self.StatusCodeHandling(resp.status)

            data = await resp.text(encoding='utf-8')
            data = loads(data)

            if data['message']['header']['status_code'] != 200:
                raise self.StatusCodeHandling(
                    data['message']['header']['status_code'])

        return data['message']['body']

    async def __get_track_id(self) -> int:
        path: str = 'track.search'
        params: dict = None

        if not isinstance(self.__track, CustomSpotifyTrack):
            await self.__fulfill_with_spotify()

        if self.__track.isrc is not None:
            params = {
                'track_isrc': self.__track.isrc,
            }
        else:
            params = {
                'q_track': self.__track.title,
                'q_artist': self.__track.artists[0]
            }

        data: dict = await self.__requester(path, params=params)
        if not data['track_list']:
            params['q'] = params['q_track']
            params.pop('q_track')
            params.pop('q_artist')

            data = await self.__requester(path, params=params)
            if not data['track_list']:
                raise self.StatusCodeHandling(404)

        return int(data['track_list'][0]['track']['track_id'])

    async def get_lyrics(self) -> str:
        track_id: int = await self.__get_track_id()
        path: str = 'track.lyrics.get'
        params: dict = {
            'track_id': track_id,
        }

        data: dict = await self.__requester(path, params=params)
        converted_lyrics: str = data['lyrics']['lyrics_body']
        converted_lyrics = converted_lyrics.replace(
            "This Lyrics is NOT for Commercial use", "").replace("*", "").strip()

        for i in converted_lyrics:

            if self.__was_contains_japanese(text=i):
                conv: str = next(
                    (x['hepburn'] for x in kakasi().convert(i)), i) + " ".replace("\n", "")
                converted_lyrics = converted_lyrics.replace(i, conv)

        converted_lyrics = sub(r'\(\d+\)', '', converted_lyrics)
        converted_lyrics += f"\n(only 30% of the lyrics are returned)\n**{self.__track.title} - {self.__track.author}**"

        return converted_lyrics
