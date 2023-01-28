
from os import getenv, listdir
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import wavelink
from wavelink.ext import spotify
load_dotenv()
MY_ENV_VAR = getenv('TOKEN')

intents = discord.Intents.all()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)




# #connecting to wavelinkz
@bot.event
async def on_ready():
  bot.loop.create_task(connect_nodes())
  await bot.tree.sync()

async def connect_nodes():
  await bot.wait_until_ready()
  await wavelink.NodePool.create_node(
    bot=bot,
    host='lavalink',
    port=2333,
    password='youshallnotpass',
    spotify_client=spotify.SpotifyClient(client_id=getenv('SPOTIFY_CLIENT'), client_secret=getenv('SPOTIFY_SECRET'))
  )

@bot.event
async def on_wavelink_node_ready(node: wavelink.Node):
  print(f'Node: <<{node.identifier}>> is ready!')  

# @bot.event
# async def on_wavelink_track_start(player: CustomPlayer, track: wavelink.Track):
  
@bot.tree.command(name="help", description="It might the first thing you wanna see")
async def help(interaction:discord.Interaction):
  e = discord.Embed(
      title="Help Commands",
      description="Teheee~ \n\n\n**Anyway here the command list**",
      color=int('E49B0F'.lstrip('#'), 16)
  ).set_thumbnail(url="https://i.imgur.com/BAHPJMS.png"
                  ).add_field(
      name="`/musichelp`",
      inline=False,
      value='This bot feature currently only supporting music player for Youtube/Spotify. \n So, if you want to go check the available command just type that'
  ).add_field(
      name="Slash Command",
      inline=False,
      value='Just try type `/` on your keyboard, and try find me...'
  ).set_author(
      name=bot.user.name,
      icon_url=bot.user.avatar.url
  ).set_footer(text=f"© {bot.user.name} | {interaction.created_at.strftime('%x')}")
  return await interaction.response.send_message(embed=e)


@bot.tree.command(name="music-help", description="All music commands goes here")
async def musichelp(interaction: discord.Interaction):
  e = discord.Embed(
      title="Music Commands",
      description="Teheee~ \n\n\n**Anyway here the command list**",
      color=int('E49B0F'.lstrip('#'), 16)
  ).set_thumbnail(url="https://i.imgur.com/BAHPJMS.png"
                  ).add_field(
      name="`/join`",
      value='To join an voice channel',
      inline=False
  ).add_field(
      name="`/play`",
      inline=False,
      value='Play anything from youtube/spotify'
  ).add_field(
      name="`/search`",
      inline=False,
      value='Search anything from youtube/spotify, then type 1-10 from the list'
  ).add_field(
      name="`/queue`",
      inline=False,
      value='List of songs that will played'
  ).add_field(
      name="`/skip`",
      value='Skip song'
  ).add_field(
      name="`/clear`",
      value='Clear queue'
  ).add_field(
      name="`/shuffle`",
      value='Shuffle queue'
  ).add_field(
      name="`/np`",
      inline=False,
      value='Now playing song'
  ).set_author(
      name=bot.user.name,
      icon_url=bot.user.avatar.url
  ).set_footer(text=f"© {bot.user.name} | {interaction.created_at.strftime('%x')}")
  return await interaction.response.send_message(embed=e)


async def load():
  for filename in listdir('./cogs'):
    if filename.endswith('.py'):
      await bot.load_extension(f'cogs.{filename[:-3]}')


async def main():
  await load()
  await bot.start(token=MY_ENV_VAR)


asyncio.run(main())
