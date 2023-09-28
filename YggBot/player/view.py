from asyncio import wait, create_task
from itertools import chain
from random import choice

from discord import (
    Interaction,
    Embed,
    ButtonStyle,
    SelectOption,
)
from discord.ui import (
    View,
    Select,
    button,
    select
)
from discord.errors import NotFound

from wavelink import (
    QueueEmpty,
    BaseQueue,
    Playable
)
from wavelink.ext.spotify import SpotifyTrack

from .interfaces import (
    CustomPlayer,
    TrackPlayerInterface,
    CustomYouTubeMusicTrack,
    CustomYouTubeTrack,
    TrackType
)
from ..util import YggUtil
from .util_player import UtilTrackPlayer
from config import YggConfig


class TrackView(View):
    def __init__(self, control, /, player: CustomPlayer, *, timeout: float | None = None):
        self.__track_control: TrackPlayerInterface = control
        self.__player: CustomPlayer = player
        self.__is_playing: bool = self.__player.is_playing()
        self.__is_loop: bool = self.__player.queue.loop

        super().__init__(timeout=timeout)

    @property
    def __is_previous_disabled(self) -> bool:
        if self.__player.queue.history.is_empty or (
            self.__player.queue.history[-1] is self.__player.current and
            self.__player.queue.history.count <= 1
        ):
            return True

        return False

    async def create_embed(self) -> Embed:
        interaction: Interaction = self.__track_control._get_interaction(
            self.__player.guild.id)
        track: Playable | SpotifyTrack = self.__player.current
        self.__update_button()

        embed = Embed(
            title="🎶 Now Playing",
            color=YggUtil.convert_color(YggConfig.COLOR['general']),
            description=f"**[{track.title}]({track.uri})** - **{UtilTrackPlayer.parseSec(track.duration)}**",
            timestamp=interaction.created_at
        )

        if isinstance(track, CustomYouTubeMusicTrack | CustomYouTubeTrack):
            image: str = await track.fetch_thumbnail()
            embed.set_image(url=image)

            if track.spotify_original is not None:
                track = track.spotify_original

        track_type: TrackType = TrackType.what_type(track.uri)
        embed.set_author(name=str(track_type.name).replace(
            "_", " ").title(), icon_url=track_type.favicon())

        if isinstance(track, SpotifyTrack):
            embed.set_thumbnail(url=track.images[0])
            track_src: str = type(self.__player.current).__name__.replace(
                "Custom", "").replace("Track", "")
            embed.description += f"\n\ntrack source from {track_src}\n [{self.__player.current.title}]({self.__player.current.uri})\
                  - {UtilTrackPlayer.parseSec(self.__player.current.duration)}"

        embed.set_footer(
            text=f'Last control from {interaction.user.name}', icon_url=interaction.user.display_avatar)

        return embed

    async def __update_message(self, interaction: Interaction) -> None:
        self.__update_button()

        try:
            embed: Embed = await self.create_embed()
            await interaction.edit_original_response(view=self, embed=embed)
        except (NotFound, AttributeError):
            pass

    async def interaction_check(self, interaction: Interaction) -> bool:
        isTrue = True
        # Check whether user is joined
        if not interaction.user.voice:
            await YggUtil.send_response(
                interaction,
                message="Can't do that. \nPlease Join Voice channel first!!",
                emoji="❌",
                ephemeral=True,
            )
            isTrue = False

        # Check wheter user is allowed
        elif (
            interaction.guild.voice_client
            and interaction.guild.voice_client.channel != interaction.user.voice.channel
        ):
            await YggUtil.send_response(
                interaction,
                message="Can't do that. \nPlease join the same Voice Channel with bot!!",
                emoji="🛑",
                ephemeral=True,
            )
            isTrue = False

        if isTrue:
            self.__track_control._record_timestamp(
                guild_id=interaction.guild_id, interaction=interaction
            )

        return isTrue

    def __update_button(self) -> None:
        self._previous.disabled = self.__is_previous_disabled or self.__is_loop

        if self.__is_playing:
            self._pause.label = "Pause"
            self._pause.emoji = "⏸️"
            self._pause.style = ButtonStyle.blurple
        else:
            self._pause.label = "Resume"
            self._pause.emoji = "▶️"
            self._pause.style = ButtonStyle.green

        if not self.__is_loop:
            self._loop.label = "Loop"
            self._loop.style = ButtonStyle.green
        else:
            self._loop.label = "Unloop"
            self._loop.style = ButtonStyle.red

    @button(label="Previous", emoji="⏮️", style=ButtonStyle.secondary)
    async def _previous(self, interaction: Interaction, _) -> None:
        await wait(
            [
                create_task(interaction.response.defer()),
                create_task(self.__track_control.previous(interaction)),
            ]
        )

    @button(label="Pause", emoji="⏸️", style=ButtonStyle.blurple)
    async def _pause(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()

        self.__is_playing = not self.__is_playing
        if self.__is_playing:
            await self.__track_control.resume(interaction)
        else:
            await self.__track_control.pause(interaction)

        await self.__update_message(interaction)

    @button(label="Stop", emoji="⏹️", style=ButtonStyle.red)
    async def _stop(self, interaction: Interaction, _) -> None:
        await wait(
            [
                create_task(interaction.response.defer()),
                create_task(self.__track_control.stop(interaction)),
            ]
        )

    @button(label="Next", emoji="⏭️", style=ButtonStyle.secondary)
    async def _next(self, interaction: Interaction, _) -> None:
        await wait(
            [
                create_task(interaction.response.defer()),
                create_task(self.__track_control.skip(interaction)),
            ]
        )

    @button(label="Loop", emoji="🔁", style=ButtonStyle.green)
    async def _loop(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__is_loop = not self.__is_loop

        self.__track_control.loop(interaction)
        await self.__update_message(interaction)


class SelectView(View):

    SHOW_LIMIT = 25

    def __init__(
        self,
        control,
        intercation: Interaction,
        /,
        data: list[Playable | SpotifyTrack],
        is_jump_command: bool = False,
        autoplay: bool = None,
        force_play: bool = False,
        put_front: bool = False,
        *,
        timeout: float | None = 180
    ):
        self.__data: list[Playable | SpotifyTrack] = list(data)
        self.__track_control: TrackPlayerInterface = control
        self.__interaction: Interaction = intercation

        self.__selected: Playable | SpotifyTrack = None
        self.__is_jump_command: bool = is_jump_command
        self.__autoplay: bool = autoplay
        self.__force_play: bool = force_play
        self.__put_front: bool = put_front

        self.__current_page: int = 1

        self.__rand_emoji: list(
            str) = ["🎼", "🎵", "🎶", "🎸", "🎷", "🎺", "🎹", "🥁", "🪕", "🎻"]

        if not self.__data:
            raise IndexError

        super().__init__(timeout=timeout)

    @property
    def get_embed(self) -> Embed:
        data: list[Playable] = self.__get_current_page_data()
        self.__update_buttons()

        total_pages: int = self.__max_pages()
        self.__pass_data_to_option(data=data)
        embed: Embed = Embed(title=("🔍 Here's the result" if not self.__is_jump_command else "⏭️ Jump to which track?"),
                             description="To play/queue the track, open the dropdown menu and select the desired track. Your track will be played/queued after this",
                             color=YggUtil.convert_color(YggConfig.COLOR['general']))

        if total_pages > 1:
            embed.title += f" - Page {self.__current_page} of {total_pages}"
        else:
            self.__hide_paging()

        return embed

    def __get_current_page_data(self) -> list[Playable | SpotifyTrack]:
        start_index = 0
        end_index = self.SHOW_LIMIT

        if 1 <= self.__current_page <= (len(self.__data) + self.SHOW_LIMIT - 1) // self.SHOW_LIMIT:
            start_index = (self.__current_page - 1) * self.SHOW_LIMIT
            end_index = start_index + self.SHOW_LIMIT

        return self.__data[start_index:end_index]

    def __pass_data_to_option(self, data: list[Playable | SpotifyTrack]) -> None:
        if self._selector.options:
            self._selector.options.clear()

        index: int = (self.__current_page-1) * self.SHOW_LIMIT

        for track in data:
            author: str = track.author if not isinstance(
                track, SpotifyTrack) else track.artists
            self._selector.append_option(SelectOption(
                label=YggUtil.truncate_string(track.title, max=100), description=f"{YggUtil.truncate_string(author, max=50)}\
                      - {UtilTrackPlayer.parseSec(track.duration)}", emoji=choice(self.__rand_emoji), value=str(index)))
            index += 1

    def __max_pages(self) -> int:
        max_pages = len(self.__data) // self.SHOW_LIMIT
        if len(self.__data) % self.SHOW_LIMIT:
            max_pages += 1

        return max_pages

    def __hide_paging(self) -> None:
        self._children = [x for x in self.children if x in (
            self._selector, self._cancel_button)]

    def __update_state_selected(self) -> None:
        index: int = (self.__current_page-1) * self.SHOW_LIMIT

        self._prev_button.disabled = True
        self._first_page_button.disabled = True
        self._next_button.disabled = True
        self._last_page_button.disabled = True

        self._selector.disabled = True
        self._selector.placeholder = f"{self._selector.options[int(self._selector.values[0]) - index].emoji} {self._selector.options[int(self._selector.values[0]) - index].label}"
        self._cancel_button.disabled = True

    def __update_buttons(self):
        if self.__current_page == 1:
            self._prev_button.disabled = True
            self._first_page_button.disabled = True
        else:
            self._prev_button.disabled = False
            self._first_page_button.disabled = False

        if self.__current_page == (len(self.__data) + self.SHOW_LIMIT - 1) // self.SHOW_LIMIT:
            self._next_button.disabled = True
            self._last_page_button.disabled = True
        else:
            self._next_button.disabled = False
            self._last_page_button.disabled = False

    async def __update_message(self, interaction: Interaction):
        self.__update_buttons()
        await interaction.edit_original_response(view=self, embed=self.get_embed)

    async def interaction_check(self, interaction: Interaction) -> bool:
        isTrue: bool = True
        if interaction.user.id != self.__interaction.user.id:
            await YggUtil.send_response(
                interaction,
                message="Couldn't do that. \nThis is not your request!!",
                emoji="🛑",
                ephemeral=True,
            )
            isTrue = False

        return isTrue

    async def on_timeout(self) -> None:
        if self.__selected:
            await self.__interaction.delete_original_response()
        return await super().on_timeout()

    @select(placeholder="🎶 Select your track!")
    async def _selector(self, interaction: Interaction, select: Select) -> None:
        self.__update_state_selected()
        await wait([
            create_task(interaction.edit_original_response(view=self)),
            create_task(interaction.response.defer())
        ])
        player: CustomPlayer = interaction.guild.voice_client

        self.__selected = self.__data[int(select.values[0])]
        embed: Embed = await self.__track_control._play_response(
            self.__interaction.user,
            track=self.__selected,
            is_queued=True if player and player.is_playing() else False,
            is_put_front=True if self.__put_front or self.__force_play or self.__is_jump_command else False,
            is_autoplay=self.__autoplay,
            uri=self.__selected.uri
        )

        if not self.__is_jump_command:
            _, _, _ = await self.__track_control.play(interaction, query=self.__selected, autoplay=self.__autoplay, force_play=self.__force_play, put_front=self.__put_front)
        else:
            await self.__track_control.skip(
                interaction, index=self.__data.index(self.__selected))

        await interaction.edit_original_response(view=None, embed=embed)

    @button(label="Cancel", emoji="✖️", style=ButtonStyle.red)
    async def _cancel_button(self, interaction: Interaction, _) -> None:
        await wait([
            create_task(interaction.response.defer()),
            create_task(interaction.delete_original_response())
        ])

    @button(label="<<", style=ButtonStyle.secondary)
    async def _first_page_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page = 1
        await self.__update_message(interaction)

    @button(label="<", style=ButtonStyle.blurple)
    async def _prev_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page -= 1
        await self.__update_message(interaction)

    @button(label=">", style=ButtonStyle.blurple)
    async def _next_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page += 1
        await self.__update_message(interaction)

    @button(label=">>", style=ButtonStyle.secondary)
    async def _last_page_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page = (
            len(self.__data) + self.SHOW_LIMIT - 1) // self.SHOW_LIMIT
        await self.__update_message(interaction)


class QueueView(View):
    SHOW_LIMIT: int = 10

    def __init__(self, queue: chain | BaseQueue, interaction: Interaction, is_history: bool = False, *, timeout: float | None = 180):
        self.__data: list[Playable | SpotifyTrack] = list(queue)

        self.__current_page: int = 1
        self.__is_history: bool = is_history
        self.__interaction: Interaction = interaction

        if len(self.__data) == 0:
            raise QueueEmpty()

        super().__init__(timeout=timeout)

    @property
    def get_embed(self) -> Embed:
        data: list[Playable] = self.__get_current_page_data()
        self.__update_buttons()

        total_pages: int = self.__max_pages()
        embed: Embed = Embed(
            title=f"📃 Queue {'history' if self.__is_history else ''} - Page {self.__current_page} of {total_pages}",
            color=YggUtil.convert_color(YggConfig.COLOR['general']))
        count: int = (self.__current_page-1) * self.SHOW_LIMIT
        embed.description = str()

        for track in data:
            count += 1
            embed.description += f"{count}. **[{YggUtil.truncate_string(track.title)}]({track.uri})** - {UtilTrackPlayer.parseSec(track.duration)}\n"

        return embed

    def __get_current_page_data(self) -> list[Playable | SpotifyTrack]:
        start_index = 0
        end_index = self.SHOW_LIMIT

        if 1 <= self.__current_page <= (len(self.__data) + self.SHOW_LIMIT - 1) // self.SHOW_LIMIT:
            start_index = (self.__current_page - 1) * self.SHOW_LIMIT
            end_index = start_index + self.SHOW_LIMIT

        return self.__data[start_index:end_index]

    def __max_pages(self) -> int:
        max_pages = len(self.__data) // self.SHOW_LIMIT
        if len(self.__data) % self.SHOW_LIMIT:
            max_pages += 1

        return max_pages

    def __update_buttons(self):
        if self.__current_page == 1:
            self._prev_button.disabled = True
            self._first_page_button.disabled = True
        else:
            self._prev_button.disabled = False
            self._first_page_button.disabled = False

        if self.__current_page == (len(self.__data) + self.SHOW_LIMIT - 1) // self.SHOW_LIMIT:
            self._next_button.disabled = True
            self._last_page_button.disabled = True
        else:
            self._next_button.disabled = False
            self._last_page_button.disabled = False

    async def __update_message(self, interaction: Interaction):
        self.__update_buttons()
        await interaction.edit_original_response(view=self, embed=self.get_embed)

    async def on_timeout(self) -> None:
        await self.__interaction.delete_original_response()
        return await super().on_timeout()

    @button(label="<<", style=ButtonStyle.secondary)
    async def _first_page_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page = 1
        await self.__update_message(interaction)

    @button(label="<", style=ButtonStyle.blurple)
    async def _prev_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page -= 1
        await self.__update_message(interaction)

    @button(label=">", style=ButtonStyle.blurple)
    async def _next_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page += 1
        await self.__update_message(interaction)

    @button(label=">>", style=ButtonStyle.secondary)
    async def _last_page_button(self, interaction: Interaction, _) -> None:
        await interaction.response.defer()
        self.__current_page = (
            len(self.__data) + self.SHOW_LIMIT - 1) // self.SHOW_LIMIT
        await self.__update_message(interaction)
