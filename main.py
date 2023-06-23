
from os import getenv, listdir
from dotenv import load_dotenv
from discord import Interaction
from discord.ext import commands
from discord import Embed
from discord import Intents
from discord import Status
import asyncio
import wavelink
from wavelink.ext import spotify
load_dotenv()
MY_ENV_VAR = getenv('TOKEN')
MY_SPOTIFY_CLIENT = getenv('SPOTIFY_CLIENT')
MY_SPOTIFY_SECRET = getenv('SPOTIFY_SECRET')


class Bot(commands.Bot):
  def __init__(self) -> None:
    intents = Intents.all()
    super().__init__(intents=intents, command_prefix='!')

  async def on_ready(self) -> None:
    print(f'Logged in {self.user} | {self.user.id}')
    

  async def setup_hook(self) -> None:
    sc = spotify.SpotifyClient(
      client_id=MY_SPOTIFY_CLIENT,
      client_secret=MY_SPOTIFY_SECRET
    )
    node: wavelink.Node = wavelink.Node(
      uri='http://localhost:2333', password='youshallnotpass')
    await wavelink.NodePool.connect(client=self, nodes=[node], spotify=sc)
    print('successfully connected into', node.id)


bot = Bot()


def embedMain(created_at):
  e = Embed(
    title="Help Commands",
    description="Teheee~ \n\n\n**Anyway here the command list**",
    color=int('E49B0F'.lstrip('#'), 16)
  ).set_thumbnail(
    url="https://i.imgur.com/BAHPJMS.png"
  ).set_author(
      name=bot.user.name,
      icon_url=bot.user.avatar.url
  ).set_footer(
    text=f"© {bot.user.name} | {created_at.strftime('%x')}"
  )
  return e


@bot.tree.command(name="help", description="It might the first thing you wanna see")
async def help(interaction: Interaction):
  embed = embedMain(interaction.created_at)
  embed.add_field(
      name="Slash Command",
      inline=False,
      value='Just try type `/` on your keyboard, and try find me...'
  )
  try:
    return await interaction.response.send_message(embed=embed)
  except Exception as e:
    print(e)


@bot.tree.command(name="music-help", description="All music commands goes here")
async def musichelp(interaction: Interaction):
  embed = embedMain(interaction.created_at)
  embed.add_field(
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
  )
  return await interaction.response.send_message(embed=embed)


async def load():
  for filename in listdir('./cogs'):
    if filename.endswith('.py'):
      await bot.load_extension(f'cogs.{filename[:-3]}')


async def main():
  await load()
  await bot.start(token=MY_ENV_VAR)


asyncio.run(main())
