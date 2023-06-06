import disnake
from disnake.ext import commands
from bot.config import TOKEN
from bot.bot import MyBot
import bot.config
import asyncio

intents = disnake.Intents.all()

intents = disnake.Intents.default()
intents.voice_states = True
intents.messages = True
intents.guilds = True
intents.members = True
intents.reactions = True
intents.presences = True
intents.typing = False
intents.message_content = True

bot = MyBot(command_prefix='/', intents=intents, help_command=None)
bot.token = TOKEN



# Load the cogs
bot.load_extension('bot.cogs.music')


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

async def main():
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

# Run the bot
bot.run(TOKEN)
