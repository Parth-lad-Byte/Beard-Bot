import disnake
from disnake.ext import commands
from bot.config import TOKEN

intents = disnake.Intents.default()
intents.voice_states = True
intents.messages = True
intents.guilds = True
intents.members = True
intents.reactions = True
intents.presences = True
intents.typing = False  # Set to True if you need typing events
intents.message_content = True  # Set to True to enable message content intent

class MyBot(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # Add custom bot functionality here

# Create an instance of MyBot
bot = MyBot(command_prefix='/', intents=intents, help_command=None)
bot.token = TOKEN

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
