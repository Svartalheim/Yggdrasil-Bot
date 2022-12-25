import discord
from discord import app_commands
from discord.ext import commands
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
  sec = round(sec)
  m, s = divmod(sec, 60)
  h, m = divmod(m, 60)
  if sec > 3600:
    return f'{h:d}h {m:02d}m {s:02d}s'
  else:
    return f'{m:02d}m {s:02d}s'


class CustomPlayer(wavelink.Player):
  pass


class Player(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot
    self.guild_id = {}
    self.message_id = {}
    self.now_playing_id = 0
    self.synced = False
    super().__init__()

  Response_color = {
    'success': '198754',
    'failed': 'CA0B00',
    'queue': '0E86D4',
    'play': 'E49B0F'
  }

  URL_REGEX = re.compile(
    r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)+(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"
  )

  @commands.Cog.listener()
  async def on_wavelink_track_start(self, player: wavelink.Player, track: wavelink.Track):
    channel = self.bot.get_channel(self.guild_id[player.guild.id])
    embed = discord.Embed(
      title="Now Playing",
      color=int(self.Response_color['play'].lstrip('#'), 16),
      description=f"**[{track.title}]({track.uri}) - {parseSec(track.duration)}**"
    )
    get_id = await channel.send(embed=embed)
    self.message_id[player.guild.id] = get_id.id
    # setattr(player, 'message_id', get_id.id)
    # player.message_id = get_id.id

  @commands.Cog.listener()
  async def on_wavelink_track_end(self, player: wavelink.Player, track: wavelink.Track, reason):
    channel = self.bot.get_channel(self.guild_id[player.guild.id])
    msg = await channel.fetch_message(self.message_id[player.guild.id])
    await msg.delete()
    if not player.queue.is_empty:
      next_track = player.queue.get()
      await player.play(next_track)

  @commands.Cog.listener()
  async def on_ready(self):
    if not self.synced:
      await self.bot.tree.sync()
      self.synced = True
    print('bot ready')

  @commands.command()
  async def ping(self, ctx):
    # await self.bot.tree.sync()
    await ctx.send('Pong! {0} ms'.format(round(self.bot.latency * 1000, 1)))

  @app_commands.command(name="join", description="Join an voice channel")
  async def join(self, interaction: discord.Interaction):
    vc = interaction.user.guild.voice_client
    try:
      channel: wavelink.Player = interaction.user.voice.channel
      self.id = interaction.channel_id
    except:
      return await interaction.response.send_message("❌ Cannot Join. \nPlease Join Voice channel first!!", ephemeral=True)
    self.guild_id[interaction.guild_id] = interaction.channel_id
    if not vc:
      await channel.connect(cls=wavelink.Player)
      await interaction.response.send_message(f"Joined")
    else:
      await interaction.response.send_message("❌ Cannot Join. \nThe bot is already connected to a voice channel!!", ephemeral=True)

  @app_commands.command(name="play", description='Play a song from youtube')
  @app_commands.describe(query="Link youtube / keyword")
  async def play(self, interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    if not interaction.user.guild.voice_client:
      vc: wavelink.Player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
    else:
      vc: wavelink.Player = interaction.user.guild.voice_client


    self.guild_id[interaction.guild_id] = interaction.channel_id

    search = ''
    embed = discord.Embed(
        color=int(self.Response_color['success'].lstrip('#'), 16),
        timestamp=datetime.datetime.now(pytz.timezone('Asia/Jakarta'))
      ).set_footer(
        text=f'From {interaction.user} \u200b',
        icon_url=interaction.user.display_avatar
      )

    if query.startswith("https://"):
      if "playlist?" in query:
        playlist = await wavelink.YouTubePlaylist.search(query=query)
        for search in playlist.tracks:
          await vc.queue.put_wait(search)
        if not vc.is_playing():
          search = await vc.queue.get_wait()
          await vc.play(search)
        embed.description = f"✅ Queued - {len(playlist.tracks)} tracks from ** [{playlist.name}]({query})**"
        return await interaction.followup.send(embed=embed)
      elif "open.spotify" in query:
        decoded = spotify.decode_url(query)
        # print(decoded['type'], decoded['id'])
        if decoded and decoded['type'] is spotify.SpotifySearchType.track:
          search = await spotify.SpotifyTrack.search(query=decoded["id"], type=decoded["type"], return_first=True)
        elif decoded and decoded['type'] is spotify.SpotifySearchType.playlist:
          info_playlist = await spotify_http.get_playlist(decoded['id'])
          length = 0
          async for partial in spotify.SpotifyTrack.iterator(query=query, partial_tracks=True):
            await vc.queue.put_wait(partial)
            length += 1
          if not vc.is_playing():
            search = await vc.queue.get_wait()
            await vc.play(search)
          embed.description = f"✅ Queued - {length} tracks from ** [{info_playlist['name']}]({info_playlist['external_urls']['spotify']})**"
          return await interaction.followup.send(embed=embed)
        elif decoded and decoded['type'] is spotify.SpotifySearchType.album:
          info_playlist = await spotify_client.get_album(decoded['id'])
          length = 0
          async for partial in spotify.SpotifyTrack.iterator(query=query):
            await vc.queue.put_wait(partial)
            length += 1
          if not vc.is_playing():
            search = await vc.queue.get_wait()
            await vc.play(search)
          embed.description = f"✅ Queued - {length} tracks from ** [{info_playlist.name}]({info_playlist.url})**"
          return await interaction.followup.send(embed=embed)
      else:
        # search = await vc.node.get_tracks(query=query, cls=wavelink.Track)
        search = await wavelink.NodePool.get_node().get_tracks(wavelink.YouTubeTrack, query)
        search = search[0]
    else:
      search = await wavelink.YouTubeTrack.search(query=query, return_first=True)

    if vc.is_playing():
      await vc.queue.put_wait(item=search)
      # if len(search.title) > 36:
      #   embed.description = f"✅ Queued - **[{search.title[:40]}]({search.uri})...**"
      # else:
      embed.description = f"✅ Queued - **[{search.title}]({search.uri})**"
      await interaction.followup.send(embed=embed)
    else:
      await vc.play(search)
      # if len(vc.source.title) > 36:
      #   embed.description = f"🎶 Playing - **[{vc.source.title[:40]}]({search.uri})...**"
      # else:
      embed.description = f"🎶 Playing - **[{vc.source.title}]({search.uri})**"
      await interaction.followup.send(embed=embed)

  @app_commands.command(name="search", description='Search a song/playlist from youtube')
  @app_commands.describe(query="Link youtube / keyword")
  async def search(self, interaction: discord.Interaction, query: str):
    embedSearch = discord.Embed(
        color=int(self.Response_color['play'].lstrip('#'), 16),
      )
    search = await wavelink.YouTubeTrack.search(query=query)
    if self.URL_REGEX.match(query):
      search = await wavelink.NodePool.get_node().get_tracks(wavelink.YouTubeTrack, query)
    iterate = 1
    queue = ''
    for a in search:
      if iterate > 10:
        break
      # if len(a.info['title']) > 40:
      #   queue += f"{iterate}. **[{a.info['title'][:36]}]({a.info['uri']})...** - {parseSec(a.duration) }\n"
      # else:
      queue += f"{iterate}. **[{a.info['title']}]({a.info['uri']})** - {parseSec(a.duration) }\n"
      iterate += 1
    embedSearch.description = queue
    embedSearch.set_footer(
      text="Type 1-10 from the list above that you want to play. \nThis message will disappear in 30 seconds"
    )

    await interaction.response.send_message(embed=embedSearch)
    user_id = interaction.user.id

    def check(m):
      return user_id == m.author.id and m.content.isnumeric()

    try:
      msg = await self.bot.wait_for('message', check=check, timeout=30.0)
    except TimeoutError:
      await interaction.delete_original_response()

    option = int(msg.content)

    if not interaction.user.guild.voice_client:
      vc: wavelink.Player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
    else:
      vc: wavelink.Player = interaction.user.guild.voice_client
    id = interaction.channel_id
    self.guild_id[interaction.guild_id] = interaction.channel_id
    embed = discord.Embed(
        color=int(self.Response_color['success'].lstrip('#'), 16),
        timestamp=datetime.datetime.now(pytz.timezone('Asia/Jakarta'))
      ).set_footer(
        text=f'From {interaction.user} \u200b',
        icon_url=interaction.user.display_avatar
      )

    channel = self.bot.get_channel(id)
    msg_del = await channel.fetch_message(msg.id)
    await msg_del.delete()

    search = search[option - 1]
    # print(search, 'search')
    try:
      # print(search[0].info)
      if vc.is_playing():
        await vc.queue.put_wait(item=search)
        # if len(search.title) > 36:
        #   embed.description = f"✅ Queued - **[{search.info['title'][:40]}]({search.info['uri']})...**"
        # else:
        embed.description = f"✅ Queued - **[{search.info['title']}]({search.info['uri']})**"
        await interaction.edit_original_response(embed=embed)
      else:
        await vc.play(search)
        # if len(vc.source.title) > 36:
        #   embed.description = f"🎶 Playing - **[{vc.source.title[:40]}]({vc.source.info['uri']})...**"
        # else:
        embed.description = f"🎶 Playing - **[{vc.source.title}]({vc.source.info['uri']})**"
        await interaction.edit_original_response(embed=embed)
    except Exception as e:
      print(e)

  @app_commands.command(name="queue", description="Song queue")
  async def queue(self, interaction: discord.Interaction):
    await interaction.response.defer()
    player: wavelink.Player = interaction.user.guild.voice_client
    queue = ""
    embed = discord.Embed(
        title="Queue",
        color=int(self.Response_color['queue'].lstrip('#'), 16)
    )
    iterate = 10
    # print(list(enumerate(player.queue)))

    try:
      # print(player.queue.count)
      # print(len(player.queue))
      for count, ele in enumerate(player.queue):
        # if ele.info:
        #   print(ele.info)
        if count == iterate:
          break
        try:
          isClass = str(type(ele)).split(".")[0]
          if isClass == "<class 'wavelink":
            ele = await ele._search()
        except:
          pass
        # if len(ele.info['title']) > 24:
        #   queue += f"{count+1}. **[{ele.info['title'][:26]}]({ele.info['uri']})...** - {parseSec(ele.duration) }\n"
        # else:
        queue += f"{count+1}. **[{ele.info['title']}]({ele.info['uri']})** - {parseSec(ele.duration) }\n"
        # print(ele.info['title'])

      if queue:
        embed.description = queue
        if player.queue.count > 10:
          embed.description += f"\n and {len(player.queue) - 10} more..."
        return await interaction.followup.send(embed=embed)
      else:
        embed.description = "No music queued"
        embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
        await interaction.followup.send(embed=embed)
    except:
      embed.description = "No music queued"
      embed.color = int(self.Response_color['failed'].lstrip('#'), 16)
      await interaction.followup.send(embed=embed)

  @app_commands.command(name="skip", description="Skip song")
  async def skip(self, interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
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
      await vc.seek(vc.track.length * 1000)
      if vc.is_paused():
        await vc.resume()
    else:
      await interaction.followup.send("The bot is not connected to a voice channel")

  @app_commands.command(name="clear", description="Clear queue")
  async def clear(self, interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
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

  @app_commands.command(name="shuffle", description="Shuffle song")
  async def shuffle(self, interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
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

  @app_commands.command(name="np", description="Now playing song")
  async def np(self, interaction: discord.Interaction):
    await interaction.response.defer()
    vc: wavelink.Player = interaction.user.guild.voice_client

    # print(vc.source.info)
    # print(vc.track.info)
    embed = discord.Embed(
      title="Now Playing",
      description=f"**[{vc.source.title}]({vc.source.info['uri']}) - {parseSec(vc.source.duration)}**",
      color=int(self.Response_color['play'].lstrip('#'), 16)
    )
    vc: wavelink.Player = interaction.user.guild.voice_client
    if interaction.user.guild.voice_client:
      if vc.is_playing:
        await interaction.followup.send(embed=embed)
      else:
        return await interaction.followup.send("Nothing is playing")
    else:
      await interaction.followup.send("The bot is not connected to a voice channel", ephemeral=True)

  @app_commands.command(name="pause", description="Pause song")
  async def pause(self, interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
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

  @app_commands.command(name="resume", description="Resume song")
  async def resume(self, interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
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

  @app_commands.command(name="leave", description="Leave the voice channel")
  async def leave(self, interaction: discord.Interaction):
    channel = interaction.user.guild.voice_client
    if not channel:
      await interaction.response.send_message("❌ Not joined a voice channel", ephemeral=True)
    await channel.disconnect()

    del self.guild_id[interaction.guild.id]
    
    del self.message_id[interaction.guild.id]
    print(self.guild_id, self.message_id)
    await interaction.response.send_message("✅ Succesfully Disconnected ")

  @play.error
  async def play_error(self, interaction: discord.Interaction, error):
    if isinstance(error, commands.BadArgument):
      await interaction.followup.send("❌ Cannot Play. \nCould not found the track.", ephemeral=True)
    else:
      print(error)
      await interaction.followup.send("❌ Cannot Join. \nPlease Join Voice channel first!!", ephemeral=True)


async def setup(bot):
  await bot.add_cog(Player(bot))
