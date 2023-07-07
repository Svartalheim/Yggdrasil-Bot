import discord
from discord import app_commands
from discord.ext import commands
from discord import Interaction
from discord import Embed
import wavelink
import re
import datetime
import pytz
import random
from asyncio import TimeoutError
from wavelink.ext import spotify
import spotify as spotifyClient
from dotenv import load_dotenv
from os import getenv
load_dotenv()

MY_SPOTIFY_CLIENT = getenv('SPOTIFY_CLIENT')
MY_SPOTIFY_SECRET = getenv('SPOTIFY_SECRET')
spotify_client = spotifyClient.Client(MY_SPOTIFY_CLIENT, MY_SPOTIFY_SECRET)
spotify_http = spotifyClient.HTTPClient(MY_SPOTIFY_CLIENT, MY_SPOTIFY_SECRET)


def parseSec(sec):
  sec = round(sec) // 1000
  m, s = divmod(sec, 60)
  h, m = divmod(m, 60)
  if sec > 3600:
    return f'{h:d}h {m:02d}m {s:02d}s'
  else:
    return f'{m:02d}m {s:02d}s'


def embedWrapper(color, interaction):
  e = Embed(
      color=int(color.lstrip('#'), 16),
      timestamp=datetime.datetime.now(pytz.timezone('Asia/Jakarta'))
  ).set_footer(
      text=f'From {interaction.user} \u200b',
      icon_url=interaction.user.display_avatar
  )
  return e


async def isConnected(self, interaction):
  if not interaction.user.guild.voice_client:
    try:
      vc: wavelink.Player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
    except:
      return await interaction.followup.send(f"❌ Cannot Play. \nPlease Join Voice channel first", ephemeral=True)
  else:
    vc: wavelink.Player = interaction.user.guild.voice_client
  self.guild_id[interaction.guild_id] = interaction.channel_id
  return vc


async def parseURI(uri):
  url = 'https://open.spotify.com/', uri[0], "/", uri[1]
  return ''.join(url)


async def wavelinkSearcher(query, embed, vc, interaction, type=''):
  search = ''
  URL_REGEX = re.compile(
    r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)+(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"
      )
  try:
    decoded = spotify.decode_url(query)
    # For Spotify
    if decoded:
      if decoded['type'] is spotify.SpotifySearchType.track:
        search: list[spotify.SpotifyTrack] = await spotify.SpotifyTrack.search(query=query)
        if not search:
          return
        search = search[0]
        search.uri = await parseURI(search.uri.split(":")[-2:])
      elif decoded['type'] is spotify.SpotifySearchType.playlist:
        info_playlist = await spotify_http.get_playlist(decoded['id'])
        length = 0
        async for partial in spotify.SpotifyTrack.iterator(query=query):
          partial.uri = await parseURI(partial.uri.split(":")[-2:])
          await vc.queue.put_wait(partial)
          length += 1
        if not vc.is_playing():
          search = await vc.queue.get_wait()
          await vc.play(search)
        embed.description = f"✅ Queued - {length} tracks from ** [{info_playlist['name']}]({info_playlist['external_urls']['spotify']})**"
        return await interaction.followup.send(embed=embed)
      elif decoded['type'] is spotify.SpotifySearchType.album:
        info_playlist = await spotify_client.get_album(decoded['id'])
        length = 0
        async for partial in spotify.SpotifyTrack.iterator(query=query):
          partial.uri = await parseURI(partial.uri.split(":")[-2:])
          await vc.queue.put_wait(partial)
          length += 1
        if not vc.is_playing():
          search = await vc.queue.get_wait()
          await vc.play(search)
        embed.description = f"✅ Queued - {length} tracks from ** [{info_playlist.name}]({info_playlist.url})**"
        return await interaction.followup.send(embed=embed)
    else:
      # For Youtube
      if type == "search":
        search = await wavelink.YouTubeTrack.search(query)
        if URL_REGEX.match(query):
          search = await wavelink.NodePool.get_node().get_tracks(wavelink.YouTubeTrack, query)
        return search
      if query.startswith("https://"):
        if "playlist?" in query:
          playlist = await wavelink.YouTubePlaylist.search(query)
          for search in playlist.tracks:
            # print(type(search))
            await vc.queue.put_wait(search)
          if not vc.is_playing():
            search = await vc.queue.get_wait()
            await vc.play(search)
          embed.description = f"✅ Queued - {len(playlist.tracks)} tracks from **[{playlist.name}]({query})**"
          return await interaction.followup.send(embed=embed)
        else:
          search = await wavelink.NodePool.get_node().get_tracks(wavelink.YouTubeTrack, query)
          search = search[0]
      else:
        search = await wavelink.YouTubeTrack.search(query, return_first=True)
      if search == '' or search == []:
        return await interaction.followup.send(f"❌ Cannot Play. \nCould not found the track.", ephemeral=True)
  except IndexError:
    print(search, 'error index')
    return await interaction.followup.send(f"❌ Cannot Play. \nCould not found the track.", ephemeral=True)

  return search


class Player(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot
    self.guild_id = {}
    self.message_id = {}
    self.synced = False
    super().__init__()

  Response_color = {
    'success': '198754',
    'failed': 'CA0B00',
    'general': 'E49B0F'
  }

  @commands.Cog.listener()
  async def on_wavelink_track_start(self, payload: wavelink.TrackEventPayload):
    channel = self.bot.get_channel(self.guild_id[payload.player.guild.id])
    try:
      embed = Embed(
          title="Now Playing",
          color=int(self.Response_color['general'].lstrip('#'), 16),
          description=f"**[{payload.track.title}]({payload.track.uri}) - {parseSec(payload.track.duration)}**"
      )
      get_id = await channel.send(embed=embed)
      self.message_id[payload.player.guild.id] = get_id.id
    except Exception as e:
      print(e, 'error on start')

  @commands.Cog.listener()
  async def on_wavelink_track_end(self, payload: wavelink.TrackEventPayload):
    try:
      channel = self.bot.get_channel(self.guild_id[payload.player.guild.id])
      msg = await channel.fetch_message(self.message_id[payload.player.guild.id])
      await msg.delete()
    except:
      pass

    if hasattr(payload.player, 'loop') and payload.player.loop is True:
      payload.player.queue.put_at_front(payload.track)
    elif hasattr(payload.player, 'qloop') and payload.player.qloop is True:
      await payload.player.queue.put_wait(payload.track)

    if not payload.player.queue.is_empty:
      next_track = await payload.player.queue.get_wait()
      await payload.player.play(next_track)

  @commands.Cog.listener()
  async def on_ready(self):
    if not self.synced:
      await self.bot.tree.sync()
      self.synced = True
    await self.bot.change_presence(status=discord.Status.idle)

  @commands.command()
  async def ping(self, ctx):
    await ctx.send('Pong! {0} ms'.format(round(self.bot.latency * 1000, 1)))

  @app_commands.command(name="join", description="Join an voice channel")
  async def join(self, interaction: Interaction):
    await interaction.response.defer()
    if interaction.guild.voice_client:
      return await interaction.followup.send("❌ Cannot Join. \nThe bot is already connected to a voice channel!!", ephemeral=True)

    vc = await isConnected(self, interaction=interaction)
    if vc:
      await interaction.followup.send(f"Joined")

  @app_commands.command(name="play", description='Play a song from youtube')
  @app_commands.describe(query="Link youtube / keyword")
  async def play(self, interaction: Interaction, query: str):
    await interaction.response.defer()
    vc = await isConnected(self, interaction=interaction)
    embed = embedWrapper(self.Response_color['success'], interaction)
    if not "<class 'discord.webhook" in str(type(vc)):
      search = await wavelinkSearcher(
        query=query, vc=vc, interaction=interaction, embed=embed)
      if hasattr(search, 'title'):
        if vc.is_playing():
          await vc.queue.put_wait(item=search)
          embed.description = f"✅ Queued - **[{search.title}]({search.uri})**"
          await interaction.followup.send(embed=embed)
        else:
          await vc.play(search)
          embed.description = f"🎶 Playing - **[{search.title}]({search.uri})**"
          await interaction.followup.send(embed=embed)

  @app_commands.command(name="insert", description='Play a single song from youtube/spotify')
  @app_commands.describe(query="Link youtube / keyword")
  async def insert(self, interaction: Interaction, query: str):
    await interaction.response.defer()
    vc = await isConnected(self, interaction=interaction)
    embed = embedWrapper(self.Response_color['success'], interaction)

    if not "<class 'discord.webhook" in str(type(vc)):
      if not vc.is_playing() and vc.queue.is_empty:
        embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
        embed.description = f"❌ Can't insert, please use \u0060/play\u0060 because the bot isn't playing"
        return await interaction.followup.send(embed=embed)

      search = await wavelinkSearcher(
          query=query, vc=vc, interaction=interaction, embed=embed)

      try:
        if vc.is_playing():
          vc.queue.put_at_front(item=search)
          embed.description = f"✅ Inserted - **[{search.title}]({search.uri})**"
          await interaction.followup.send(embed=embed)
        else:
          embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
          embed.description = f"❌ Please use single track for insert"
          return await interaction.followup.send(embed=embed)
      except Exception as e:
        print(e, 'what could be wrong lol')

  @app_commands.command(name="search", description='Search a song/playlist from youtube')
  @app_commands.describe(query="Link youtube / keyword")
  async def search(self, interaction: Interaction, query: str):
    embed = Embed(
        color=int(self.Response_color['general'].lstrip('#'), 16),
      )
    vc = await isConnected(self, interaction=interaction)
    if not "<class 'discord.webhook" in str(type(vc)):
      search = await wavelinkSearcher(
        query=query, vc=vc, interaction=interaction, embed=embed, type="search")
      iterate = 1
      queue = ''
      for a in search:
        if iterate > 10:
          break
        queue += f"{iterate}. **[{a.title}]({a.uri})** - {parseSec(a.duration) }\n"
        iterate += 1
      embed.description = queue
      embed.set_footer(
        text="Type 1-10 from the list above that you want to play. \nThis message will disappear in 30 seconds"
      )
      await interaction.response.send_message(embed=embed)

      def check(m):
        return interaction.user.id == m.author.id and m.content.isnumeric() and int(m.content) < 11

      try:
        msg = await self.bot.wait_for('message', check=check, timeout=30.0)
      except TimeoutError:
        await interaction.delete_original_response()

      option = int(msg.content)

      embed = embedWrapper(self.Response_color['success'], interaction)
      channel = self.bot.get_channel(interaction.channel_id)
      msg_del = await channel.fetch_message(msg.id)
      await msg_del.delete()

      search = search[option - 1]

      try:
        if vc.is_playing():
          await vc.queue.put_wait(item=search)
          embed.description = f"✅ Queued - **[{search.title}]({search.uri})**"
          await interaction.edit_original_response(embed=embed)
        else:
          await vc.play(search)
          embed.description = f"🎶 Playing - **[{search.title}]({search.uri})**"
          await interaction.edit_original_response(embed=embed)
      except Exception as e:
        print(e)

  @app_commands.command(name="queue", description="Song queue")
  async def queue(self, interaction: Interaction):
    embed = embedWrapper(
      self.Response_color['general'], interaction=interaction)
    try:
      vc: wavelink.Playlist = interaction.user.guild.voice_client
    except:
      embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
      embed.description = "No music queued"
      return await interaction.response.send_message(embed=embed, ephemeral=True)

    await interaction.response.defer()
    iterate = 10
    queue = ''
    try:
      for count, ele in enumerate(vc.queue):
        if count == iterate:
          break
        queue += f"{count+1}. **[{ele.title}]({ele.uri})** - {parseSec(ele.duration) }\n"
      if queue != '':
        embed.description = queue
        if vc.queue.count > 10:
          embed.description += f"\n and {len(vc.queue) - 10} more... \n"
        if hasattr(vc, 'loop'):
          embed.description += f"Track loop is {vc.loop}"
        if hasattr(vc, 'qloop'):
          embed.description += f"Queue loop is {vc.qloop}"
        embed.title = "Queue List"
        return await interaction.followup.send(embed=embed)
      else:
        raise Exception("no queue")
    except:
      embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
      embed.description = "No music queued"
      return await interaction.followup.send(embed=embed, ephemeral=True)

  @app_commands.command(name="leave", description="Leave the voice channel")
  async def leave(self, interaction: Interaction):
    channel = interaction.user.guild.voice_client
    if not channel:
      await interaction.response.send_message("❌ Not joined a voice channel", ephemeral=True)
    await channel.disconnect()
    await interaction.response.send_message("✅ Succesfully Disconnected ")

    try:
      del self.guild_id[interaction.guild.id]
      del self.message_id[interaction.guild.id]
    except:
      pass

  @app_commands.command(name="np", description="Now playing song")
  async def np(self, interaction: Interaction):
    await interaction.response.defer()
    try:
      if interaction.user.guild.voice_client:
        vc: wavelink.Player = interaction.user.guild.voice_client
        if vc.is_playing():
          pos = vc.position
          duration = vc.current.duration
          time = duration - pos
          embed = Embed(
            title="Now Playing",
            description=f"""**[{vc.current.title}]({vc.current.uri}) - {parseSec(vc.current.duration)}**
            \n** {str(datetime.timedelta(seconds=time//1000)).split('.')[0]} left**""",
            color=int(self.Response_color['general'].lstrip('#'), 16)
          )
          await interaction.followup.send(embed=embed)
        else:
          return await interaction.followup.send("Nothing is playing")
      else:
        await interaction.followup.send("The bot is not connected to a voice channel", ephemeral=True)
    except Exception as e:
      print(e, 'np err')

  @app_commands.command(name="pause", description="Pause song")
  async def pause(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="⏸️ Paused",
        color=int(self.Response_color['success'].lstrip('#'), 16)
    )
    vc: wavelink.Player = interaction.user.guild.voice_client
    if interaction.user.guild.voice_client:
      if vc.is_playing() and not vc.is_paused():
        await vc.pause()
        await interaction.followup.send(embed=embed)
      else:
        return await interaction.followup.send("Nothing is playing")
    else:
      await interaction.followup.send("The bot is not connected to a voice channel", ephemeral=True)

  @app_commands.command(name="shuffle", description="Shuffle song")
  async def shuffle(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="🔀 Shuffled",
        color=int(self.Response_color['success'].lstrip('#'), 16)
    )
    vc: wavelink.Player = interaction.user.guild.voice_client
    if interaction.user.guild.voice_client:
      if not vc.queue.is_empty:
        random.shuffle(vc.queue._queue)
        await interaction.followup.send(embed=embed)
      else:
        return await interaction.followup.send("Queue is empty")
    else:
      await interaction.followup.send("The bot is not connected to a voice channel", ephemeral=True)

  @app_commands.command(name="remove", description="Remove song from index")
  @app_commands.describe(query="index in the queue present")
  async def shuffle(self, interaction: Interaction, query: int):
    await interaction.response.defer()
    embed = Embed(
        description="✅ Successfully removed the song from queue",
        color=int(self.Response_color['success'].lstrip('#'), 16)
    )
    vc: wavelink.Player = interaction.user.guild.voice_client
    if interaction.user.guild.voice_client:
      if not vc.queue.is_empty:
        try:
          del vc.queue[query - 1]
        except Exception as e:
          embed.description = 'Index not found in the queue'
          embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
          await interaction.followup.send(embed=embed, ephemeral=True)
        await interaction.followup.send(embed=embed)
      else:
        return await interaction.followup.send("Queue is empty")
    else:
      await interaction.followup.send("The bot is not connected to a voice channel", ephemeral=True)

  @app_commands.command(name="resume", description="Resume song")
  async def resume(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="▶️ Resumed",
        color=int(self.Response_color['success'].lstrip('#'), 16)
    )
    vc: wavelink.Player = interaction.user.guild.voice_client
    if interaction.user.guild.voice_client:
      if vc.is_paused():
        await vc.resume()
        await interaction.followup.send(embed=embed)
      else:
        return await interaction.followup.send("Nothing is paused")
    else:
      await interaction.followup.send("The bot is not connected to a voice channel", ephemeral=True)

  @app_commands.command(name="clear", description="Clear queue")
  async def clear(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="❌ Cannot clear. \nPlease make sure to have a queue list",
        color=int(self.Response_color['failed'].lstrip('#'), 16)
    )
    if interaction.user.guild.voice_client:
      player: wavelink.Player = interaction.user.guild.voice_client
      if not player.queue.is_empty:
        player.queue.clear()
        embed.description = "✅ Cleared"
        embed.color = int(self.Response_color['success'].lstrip('#'), 16)

    await interaction.followup.send(embed=embed)

  @app_commands.command(name="track-loop", description="Loop single track")
  async def trackloop(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="❌ Cannot loop. \nPlease make sure to have a music playing or joined a voice channel",
        color=int(self.Response_color['failed'].lstrip('#'), 16)
    )
    try:
      if interaction.user.guild.voice_client:
        player: wavelink.Player = interaction.user.guild.voice_client
        if not player.is_playing:
          return interaction.followup.send(embed=embed)

        try:
          if player.loop:
            player.loop = False
          elif player.loop is False:
            player.loop = True
        except:
          setattr(player, 'loop', True)
          pass
        if player.loop:
          embed.description = "✅ Loop Track"
          embed.color = int(self.Response_color['success'].lstrip('#'), 16)
        else:
          embed.description = "✅ Unloop Track"
          embed.color = int(self.Response_color['success'].lstrip('#'), 16)
    except Exception as e:
      print('asd', e)

    await interaction.followup.send(embed=embed)

  @app_commands.command(name="queue-loop", description="Loop queue track")
  async def queueloop(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="❌ Cannot loop. \nPlease make sure to have a queue list or joined a voice channel",
        color=int(self.Response_color['failed'].lstrip('#'), 16)
    )
    try:
      if interaction.user.guild.voice_client:
        player: wavelink.Player = interaction.user.guild.voice_client
        if player.queue.is_empty and not player.is_playing:
          return interaction.followup.send(embed=embed)

        try:
          if player.qloop:
            player.qloop = False
          elif player.qloop is False:
            player.qloop = True
        except Exception as e:
          setattr(player, 'qloop', True)
          pass

        if player.qloop:
          embed.description = f"✅ Loop Queue - **{len(player.queue)+1} Tracks**"
          embed.color = int(self.Response_color['success'].lstrip('#'), 16)
        else:
          embed.description = "✅ Unloop Queue"
          embed.color = int(self.Response_color['success'].lstrip('#'), 16)
    except Exception as e:
      print('asd', e)

    await interaction.followup.send(embed=embed)

  @app_commands.command(name="skip", description="Skip song")
  async def skip(self, interaction: Interaction):
    await interaction.response.defer()
    embed = Embed(
        description="⏯️ Skipped",
        color=int(self.Response_color['success'].lstrip('#'), 16)
    )
    vc: wavelink.Player = interaction.user.guild.voice_client
    if interaction.user.guild.voice_client:
      if not vc.is_playing():
        return await interaction.followup.send("Nothing is playing")

      await interaction.followup.send(embed=embed)
      if vc.queue.is_empty:
        return await vc.stop()
      await vc.seek(vc.current.length * 1000)
      if vc.is_paused():
        await vc.resume()
    else:
      await interaction.followup.send("The bot is not connected to a voice channel")

  # @play.error
  # async def play_error(self, interaction: Interaction, error):
  #   if isinstance(error, commands.BadArgument):
  #     await interaction.followup.send(f"❌ Cannot Play. \nCould not found the track.  \n{error}", ephemeral=True)
  #   elif isinstance(error, AttributeError):
  #     await interaction.followup.send(f"❌ Cannot Play. \nPlease Join Voice channel first!!  \n{error}", ephemeral=True)
  #   else:
  #     print(error)
  #     await interaction.followup.send(f"❌ Cannot Play. \nPlease Join Voice channel first!!", ephemeral=True)

  @join.error
  async def join_error(self, interaction: Interaction, error):
    if isinstance(error, AttributeError):
      return interaction.followup.send(f"❌ Cannot Play. \nPlease Join Voice channel first \n{error}", ephemeral=True)
    await interaction.followup.send(f"❌ Cannot Play. \nPlease Join Voice channel first!!", ephemeral=True)

  # async def cog_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError) -> None:
  #   if isinstance(error, commands.MissingPermissions):
  #     await _handling_error(interaction=interaction, resp='❌ Missing Permission')
  #   else:
  #     await _handling_error(interaction=interaction, resp=f'❌ Uknown error, {Exception(error)}')
  #   return await super().cog_app_command_error(interaction, error)


async def _handling_error(interaction: Interaction, resp: str) -> None:
  if not interaction.response.is_done():
    await interaction.response.send_message(resp, ephemeral=True)
  else:
    await interaction.followup.send(resp, ephemeral=True)


async def setup(bot):
  await bot.add_cog(Player(bot))
