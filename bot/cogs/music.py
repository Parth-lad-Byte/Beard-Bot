import disnake
from disnake.ext import commands
from disnake import ButtonStyle, Button, ui
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import requests
from bs4 import BeautifulSoup
import re
import math
import yt_dlp as youtube_dl
import asyncio
import datetime
import psutil
import platform
from disnake.utils import get
from disnake import MessageInteraction, InteractionResponseType
import discord
from discord import VoiceChannel
import time
from collections import deque
from bot.config import TOKEN, SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET
from disnake.ui import View, Button
from typing import Optional
import aiohttp
from disnake import Embed

user_preferences = {}
# Store the currently playing song for each guild

global currently_playing
players = {}
currently_playing = {}
queues = {}
playerconrols = {}
paused_songs = {}


# Set up Spotify API credentials
spotify_credentials = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
spotify = spotipy.Spotify(client_credentials_manager=spotify_credentials)

bot = commands.Bot(command_prefix='/', intents=disnake.Intents.all(), help_command=None)

start_time = datetime.datetime.utcnow()

class Queue:
    def __init__(self):
        self._queue = []
        self.current = None

    def add(self, song):
        self._queue.append(song)

    def get_next(self):
        if self._queue:
            self.current = self._queue.pop(0)
        else:
            self.current = None
        return self.current

    def dequeue(self):
        return self.get_next()

    def is_empty(self):
        return len(self._queue) == 0

    def size(self):
        return len(self._queue)

    @property
    def queue(self):
        return self._queue

class PlayerControls(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="⏮️", custom_id="back"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="⏯️", custom_id="play_pause"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="⏭️", custom_id="next"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="🔁", custom_id="replay"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="💌", custom_id="send_dm"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="🗑️", custom_id="clear"))  # Clear button
        self.add_item(VolumeButton('-', -25))
        self.add_item(VolumeButton('+', 25))



class VolumeControl(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
class ControlsView(PlayerControls, VolumeControl):
    def __init__(self):
        super().__init__()

class VolumeButton(ui.Button):
    def __init__(self, label, volume_delta):
        super().__init__(style=ButtonStyle.secondary, label=label)
        self.volume_delta = volume_delta

    async def callback(self, interaction: disnake.MessageInteraction):
        # Defer the interaction
        await interaction.response.defer()

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.source:
            new_volume = voice_client.source.volume + self.volume_delta / 100
            new_volume = max(0, min(new_volume, 2))  # Ensure the volume is between 0 and 2
            voice_client.source.volume = new_volume
            try:
                await interaction.edit_original_message(content=f"Volume: {new_volume * 100:.0f}%")
            except disnake.errors.InteractionResponded:
                pass
        else:
            try:
                await interaction.response.send_message("Nothing is playing right now.")
            except disnake.errors.InteractionResponded:
                pass

# Initialize song queues for different servers
class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # Initialize queues at the class level

    async def _play(self, inter, *, song):
        if inter.guild.voice_client.is_playing():
            await get_youtube_song(inter, song, add_to_queue=True)  # Add to queue if a song is playing
        else:
            await get_youtube_song(inter, song, add_to_queue=False)  # Play immediately if no song is playing



    @commands.command()
    async def join(self, ctx):
        channel = ctx.author.voice.channel
        voice_client = disnake.utils.get(ctx.bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_connected():
            await voice_client.move_to(channel)
        else:
            voice_client = await channel.connect()

        # Ensure the bot is self-deafened
        await ctx.guild.change_voice_state(channel=channel, self_deaf=True)

        await ctx.send(f'Joined {channel}')

# Function to join the voice channel the user is in
async def join_voice_channel(inter):
    channel = inter.author.voice.channel
    guild_id = inter.guild.id
    voice_client = disnake.utils.get(bot.voice_clients, guild=inter.guild)

    if voice_client:
        if voice_client.is_connected():
            await voice_client.move_to(channel)
        else:
            await channel.connect()
            voice_client = disnake.utils.get(bot.voice_clients, guild=inter.guild)
    else:
        await channel.connect()
        voice_client = disnake.utils.get(bot.voice_clients, guild=inter.guild)

    if voice_client and voice_client.is_playing():
        voice_client.stop()  # Stop the currently playing audio before setting the volume

    voice_client.volume = 20  # Set the default user volume to 20

class VolumeButton(ui.Button):
    def __init__(self, label, volume_delta):
        super().__init__(style=ButtonStyle.secondary, label=label)
        self.volume_delta = volume_delta

    async def callback(self, interaction: disnake.MessageInteraction):
        # Defer the interaction
        await interaction.response.defer()

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.source:
            new_volume = voice_client.source.volume + self.volume_delta / 100
            new_volume = max(0, min(new_volume, 2))  # Ensure the volume is between 0 and 2
            voice_client.source.volume = new_volume
            try:
                await interaction.edit_original_message(content=f"Volume: {new_volume * 100:.0f}%")
            except disnake.errors.InteractionResponded:
                pass
        else:
            try:
                await interaction.response.send_message("Nothing is playing right now.")
            except disnake.errors.InteractionResponded:
                pass

# Set the default volume to 25
default_volume = 25 / 100  # Convert to a decimal value between 0 and 1

# Create an instance of the VolumeButton with the default volume
volume_button = VolumeButton(label="Volume", volume_delta=default_volume)

# Function to get the command signature for a given command
def get_command_signature(command: commands.Command):
    return f'/{command.name} {command.signature}'

async def play_song(ctx, info):
    if info is None:
        await ctx.send("Error: Unable to fetch the song URL.")
        return

    url = info['url']
    title = info['title']
    youtube_url = get_youtube_url(info['id'])
    thumbnail = info['thumbnail']
    duration = format_duration(info['duration'])
    requested_by = ctx.author.name

    print(f"Attempting to play URL: {url}")  # Debugging

    voice_client = ctx.guild.voice_client

    if voice_client.is_playing():
        voice_client.stop()

    FFMPEG_OPTIONS = {
        'options': '-vn',
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    }

    source = disnake.FFmpegPCMAudio(url, **FFMPEG_OPTIONS, executable='C:\\ffmpeg\\bin\\ffmpeg.exe')
    volume_transformer = disnake.PCMVolumeTransformer(source)
    
    # After the current song ends, it will play the next song in the queue.
    voice_client.play(volume_transformer, after=lambda e: bot.loop.create_task(play_next_song(ctx)))

    # Create the Song object
    song = Song(info['id'], title, youtube_url, thumbnail, duration, requested_by)

    # Update the currently playing song
    currently_playing[ctx.guild.id] = song

    # Store the message view
    embed = disnake.Embed(title="Now Playing", color=disnake.Color.green())
    embed.add_field(name="Title", value=f"[{title}]({youtube_url})", inline=False)
    embed.add_field(name="Duration", value=duration, inline=False)
    embed.set_thumbnail(url=thumbnail)
    embed.set_footer(text=f"Requested by: {requested_by}")
    row = PlayerControls()
    volume_control = VolumeControl()
    view = disnake.ui.View()
    for item in volume_control.children:
        view.add_item(item)
    for item in row.children:
        view.add_item(item)
    message = await ctx.send(embed=embed, view=view)

    volume_control.message = message

def get_youtube_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"

def format_duration(duration):
    total_seconds = int(duration)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"

@bot.slash_command(name="replay", description="Replay the last song")
async def _replay(inter):
    global queues

    if inter.guild.id not in queues or len(queues[inter.guild.id]) == 0:
        await inter.response.send_message("No song has been played yet to replay.")
        return

    song = queues[inter.guild.id].replay_song()
    if song is None:
        await inter.response.send_message("No song has been played yet to replay.")
        return

    await play_song(inter, song)

# Function to play the next song in the queue
async def play_next(inter):
    guild_id = inter.guild.id
    if guild_id in queues:
        queue = queues[guild_id]
        if not queue.is_empty():
            queue.dequeue()

@bot.slash_command(name="play_next", description="Skip to the next song in the queue")
async def _play_next(inter):
    await play_next(inter)

# Slash command to join the voice channel
@bot.slash_command(name="join", description="Join the voice channel")
async def _join(inter):
    await join_voice_channel(inter)
    await inter.response.send_message("Joined the voice channel.")

@bot.slash_command(name="play", description="Play a song from YouTube or Spotify")
async def _play(inter: disnake.CommandInteraction, song_url: str):
    await inter.response.defer()  # Defer the response

    # Do not clear the queue here; instead, add to it
    #queues[inter.guild.id] = Queue()
    #currently_playing.pop(inter.guild.id, None)

    # Create the queue for the guild if it doesn't exist
    if inter.guild.id not in queues:
        queues[inter.guild.id] = Queue()

    # Join the voice channel
    await join_voice_channel(inter)

    if 'spotify.com' in song_url:
        if 'playlist' in song_url:
            playlist = spotify.playlist_items(song_url)
            for item in playlist['items']:
                track = item['track']
                song_name = track['name']
                song_artist = track['artists'][0]['name']
                search_query = f"{song_name} {song_artist}"
                await get_youtube_song(inter, search_query, add_to_queue=True)
        else:
            track = spotify.track(song_url)
            song_name = track['name']
            song_artist = track['artists'][0]['name']
            search_query = f"{song_name} {song_artist}"
            await get_youtube_song(inter, search_query, add_to_queue=True)
    else:
        await get_youtube_song(inter, song_url, add_to_queue=True)

    # Play the song if nothing is currently playing
    if not inter.guild.voice_client.is_playing():
        await play_next_song(inter)


async def play_next_song(inter):
    # Check if there are any songs in the queue
    if not queues[inter.guild.id].is_empty():
        # Get the next song
        next_song = queues[inter.guild.id].dequeue()

        # Play the song
        await play_song(inter, next_song)

        # Create the "Now Playing" message
        embed = disnake.Embed(title="Now Playing", color=disnake.Color.green())
        embed.add_field(name="Title", value=next_song.title, inline=False)
        embed.add_field(name="Duration", value=next_song.duration, inline=False)
        embed.set_thumbnail(url=next_song.thumbnail)
        embed.set_footer(text=f"Requested by: {next_song.requested_by}")
        row = PlayerControls()
        await inter.followup.send(embed=embed, components=[row])

# ...

async def get_youtube_song(inter, search_query, add_to_queue=True):
    ydl_opts = {
        'format': 'bestaudio/best',
        'default_search': 'ytsearch:',
        'extractor_args': {
            'youtube': {'noplaylist': True},
            'soundcloud': {},
        },
    }

    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_query, download=False)
        if 'entries' in info:
            info = info['entries'][0]

    if info is None:
        await inter.send("Error: Unable to fetch the song URL.")
        return

    queues[inter.guild.id].add(info)

    if add_to_queue:
        # If adding to queue, just send the "Added to Queue" message
        embed = disnake.Embed(title="Added to Queue", color=disnake.Color.green())
        await inter.followup.send(embed=embed)
    else:
        # If not adding to queue, start playing immediately only if a song is not currently playing
        if not inter.guild.voice_client.is_playing() and not inter.guild.voice_client.is_paused():
            await play_song(inter, info)
            embed = disnake.Embed(title="Now Playing", color=disnake.Color.green())
            row = PlayerControls()
            await inter.followup.send(embed=embed, components=[row])

# ...

def format_duration(duration):
    minutes = duration // 60
    seconds = duration % 60
    return f"{minutes:02d}:{seconds:02d}"

async def show_queue(guild_id, channel):
    if guild_id in queues and queues[guild_id].size() > 0:
        queue = queues[guild_id]
        queue_list = [f"{i + 1}. {song['title']} - Duration: {song['duration']}" for i, song in enumerate(queue.queue)]
        queue_text = "\n".join(queue_list)
        embed = disnake.Embed(
            title="Music Queue",
            description=queue_text,
            color=disnake.Color.blue()
        )
        await channel.send(embed=embed)
    else:
        await channel.send("The music queue is currently empty.")


# Slash command to pause the currently playing song
@bot.slash_command(name="pause", description="Pause the currently playing song")
async def _pause(inter):
    voice_client = inter.guild.voice_client
    if voice_client.is_playing():
        paused_songs[inter.guild.id] = voice_client.source
        voice_client.pause()
        await inter.response.send_message("Paused the song.")
    else:
        await inter.response.send_message("Nothing is playing to pause.")

# Slash command to resume the paused song
@bot.slash_command(name="resume", description="Resume the paused song")
async def _resume(inter):
    voice_client = inter.guild.voice_client
    if inter.guild.id in paused_songs:
        voice_client.play(paused_songs[inter.guild.id])
        del paused_songs[inter.guild.id]
        await inter.response.send_message("Resumed the song.")
    else:
        await inter.response.send_message("No song is paused to resume.")

# Slash command to stop the currently playing song
@bot.slash_command(name="stop", description="Stop the currently playing song")
async def _stop(inter):
    voice_client = inter.guild.voice_client
    if voice_client.is_playing() or voice_client.is_paused():
        if inter.guild.id in paused_songs:
            del paused_songs[inter.guild.id]
        voice_client.stop()
        await inter.response.send_message("Stopped the song.")
    else:
        await inter.response.send_message("Nothing is playing to stop.")

# Slash command to skip to the next song in the queue
@bot.slash_command(name="next", description="Skip to the next song in the queue")
async def _next(inter):
    await play_next(inter)

# Slash command to show the current song queue
@bot.slash_command(name="queue", description="Show the current song queue")
async def _queue(inter, page: int = 1):
    if inter.guild.id in queues and len(queues[inter.guild.id]) > 0:
        max_page = math.ceil(len(queues[inter.guild.id]) / 10)
        page = max(1, min(page, max_page))
        start = (page - 1) * 10
        end = start + 10

        embed = disnake.Embed(title="Song Queue", color=disnake.Color.blue())
        for idx, song in enumerate(queues[inter.guild.id].queue[start:end], start=start+1):
            title = song['title']
            if len(title) > 50:
                title = title[:50] + "..."
            embed.add_field(name=f"Song {idx}", value=title, inline=False)
        embed.set_footer(text=f"Page {page} of {max_page}")

        control_view = QueueControl(page, max_page)
        await inter.response.send_message(embed=embed, view=control_view)
    else:
        await inter.response.send_message("The song queue is currently empty.")

class Song:
    def __init__(self, song_id, title, youtube_url, thumbnail, duration, requested_by):
        self.song_id = song_id
        self.title = title
        self.youtube_url = youtube_url
        self.thumbnail = thumbnail
        self.duration = duration
        self.requested_by = requested_by

# Function to add a song to the queue
async def add_to_queue(inter, song_info):
    song = Song(song_info['id'], song_info['title'])

    guild_id = inter.guild.id
    if guild_id not in queues:
        queues[guild_id] = Queue()

    queues[guild_id].enqueue(song)

    if queues[guild_id].size() > 1:
        await inter.followup.send(f"Added to queue: {song.title}")
    else:
        await play_song(inter, song_info)
        await inter.followup.send(f"Now playing: {song.title}")

@bot.event
async def on_button_click(inter):
    custom_id = inter.data.custom_id

    if custom_id == "play_pause":
        voice_client = inter.guild.voice_client
        if voice_client.is_playing():
            voice_client.pause()
            await inter.message.edit(content="Paused the song.")
        else:
            voice_client.resume()
            await inter.message.edit(content="Resumed the song.")
    elif custom_id == "back":
        await inter.message.edit(content="Back functionality not implemented yet.")
    elif custom_id == "next":
        await play_next(inter)
        await inter.message.edit(content="Playing next song in the queue.")
    elif custom_id == "stop":
        inter.guild.voice_client.stop()
        await inter.message.edit(content="Stopped the song.")
    elif custom_id == "send_dm":
        if inter.guild.id in currently_playing:
            song = currently_playing[inter.guild.id]
            message = f"Here is the song you liked:\nView on YouTube: {song.youtube_url}"
            await inter.user.send(message)
        else:
            await inter.message.edit(content="No song has been played yet.")
    elif custom_id == "clear":
        # Clear chat and disconnect functionality
        channel = inter.channel

        # Delete all messages in the channel
        await channel.purge()

        # Disconnect the bot from the voice channel (if connected)
        voice_client = get(bot.voice_clients, guild=inter.guild)
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

        # Send a response message indicating the chat has been cleared
        await inter.edit_origin(content="Chat cleared and bot disconnected.")


class QueueControl(ui.View):
    def __init__(self, page, max_page):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.blurple, emoji="◀️", custom_id="queue_back", disabled=page==1))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.blurple, emoji="▶️", custom_id="queue_next", disabled=page==max_page))

    async def on_timeout(self):
        # Remove the view after timeout
        for child in self.children:
            child.disabled = True
        await asyncio.sleep(5)  # Wait for 5 seconds
        self.stop()
# |----------------------------------------------------------------------------------------------|
#other shit

# Event that triggers when the bot is ready
@bot.event
async def on_ready():
    print(f"Bot is ready: {bot.user.name}")
    funny_status = "with your mom!"
    await bot.change_presence(activity=disnake.Game(name=funny_status))

# Function to get the command signature for a given command
def get_command_signature(command: commands.Command):
    return f'/{command.name} {command.signature}'

# Slash command to show available commands
@bot.slash_command(name="help", description="Show available commands")
async def _help(inter):
    music_commands = [
        ("/play", "Play a song from YouTube or Spotify"),
        ("/stop", "Stop the currently playing song"),
        ("/next", "Skip to the next song in the queue"),
        ("/queue", "Show the current song queue"),
    ]
    
    utility_commands = [
        ("/clear", "Clear all messages in the chat"),
        ("/join", "Join the voice channel"),
        ("/info", "Show bot information"),
        ("/ping", "Check the bot's latency"),
        ("/clear_chat", "Clear all messages in text chat and bot dissconnects"),
    ]

    bot_utility = [
        ("/setup_role", "Setup a role Reaction"),
        ("/setup_serverstats", "Setup server statistics")
    ]
    
    voice_commands = [
        ("/Move", "Move users in a voice channel to another voice channel"),
    ]


    embed = disnake.Embed(title="Help", description="List of available commands", color=disnake.Color.blue())
    
    # Add fields for each command category
    if music_commands:
        music_commands_text = "\n".join([f"{cmd} - {desc}" for cmd, desc in music_commands])
        embed.add_field(name="Music Commands", value=f"```{music_commands_text}```", inline=False)
    
    if utility_commands:
        utility_commands_text = "\n".join([f"{cmd} - {desc}" for cmd, desc in utility_commands])
        embed.add_field(name="Utility Commands", value=f"```{utility_commands_text}```", inline=False)
    
    if voice_commands:
        voice_commands_text = "\n".join([f"{cmd} - {desc}" for cmd, desc in voice_commands])
        embed.add_field(name="Voice Commands", value=f"```{voice_commands_text}```", inline=False)

    # Add a blank field to separate the commands from the footer
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    embed.set_footer(text="Made with ❤️ by Parth")
    embed.add_field(name="Support Me", value="[Buy Me a Coffee](https://www.buymeacoffee.com/parthlad)", inline=False)
    embed.add_field(name="Your support means the world to me! ❤️", value="\u200b")
  


    # Send the embed as a response
    await inter.response.send_message(embed=embed)


async def clear_messages(channel):
    await channel.purge(limit=100)

@bot.slash_command(name="clear", description="Clear all messages in the chat")
async def _clear(inter):
    await clear_messages(inter.channel)
    await inter.response.send_message("Cleared all messages in the chat.", ephemeral=True)


@bot.slash_command(name="ping", description="Check the bot's latency")
async def ping(inter):
    ping_value = round(bot.latency * 1000)

    # Create the embed
    embed = disnake.Embed(title="Pong! :ping_pong:", color=disnake.Color.green())
    embed.add_field(name="Latency", value=f"{ping_value}ms", inline=False)

    # Set the footer with library information
    # Add a blank field to separate the commands from the footer
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    embed.set_footer(text="Made with ❤️ by Parth")
    embed.add_field(name="Support Me", value="[Buy Me a Coffee](https://www.buymeacoffee.com/parthlad)", inline=False)
    embed.add_field(name="Your support means the world to me! ❤️", value="\u200b")
  



    # Send the embed as a response
    await inter.response.send_message(embed=embed)


@bot.slash_command(name="info", description="Show bot information")
async def show_info(inter):
    bot_name = bot.user.name
    api_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uptime = datetime.datetime.utcnow() - start_time
    uptime_str = str(uptime).split(".")[0]
    bot_stats = f"Bot Name: {bot_name}\nAPI Time: {api_time}\nRuntime: {uptime_str}"

    cpu_usage = psutil.cpu_percent()
    memory_usage = psutil.virtual_memory().percent
    system_stats = f"OS: {platform.system()}\nUptime: {uptime}\nRAM: {memory_usage} MB"

    # Calculate ping value
    ping_value = round(bot.latency * 1000)

    # Create the embed
    embed = disnake.Embed(title="The Gaming Parlor Bot (/) Information", color=disnake.Color.blue())


    # Add bot stats information
    bot_stats_box = f"```\n{bot_stats}\n```"
    embed.add_field(name="Bot Stats", value=bot_stats_box, inline=False)

    # Add ping information
    ping_box = f"```\nPing: {ping_value}ms\n```"
    embed.add_field(name="Ping", value=ping_box, inline=False)

    # Add system stats information
    system_stats_box = f"```\n{system_stats}\n```"
    embed.add_field(name="System Stats", value=system_stats_box, inline=False)

    # Set the footer with library information
   # Add a blank field to separate the commands from the footer
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    embed.set_footer(text="Made with ❤️ by Parth")
    embed.add_field(name="Support Me", value="[Buy Me a Coffee](https://www.buymeacoffee.com/parthlad)", inline=False)
    embed.add_field(name="Your support means the world to me! ❤️", value="\u200b")
  


    # Send the embed as a response
    await inter.response.send_message(embed=embed)


# Drag Members to Different Voice Channel
@bot.slash_command(name="move", description="Move specific users in a voice channel to another voice channel")
async def drag_users(inter, from_channel: disnake.VoiceChannel, to_channel: disnake.VoiceChannel, members: str):
    await inter.response.defer()  # Add a deferral to the response

    member_mentions = re.findall(r"<@!?(\d+)>", members)
    members_to_drag = []
    for member in from_channel.members:
        if str(member.id) in member_mentions:
            members_to_drag.append(member)
    if str(inter.author.id) in member_mentions:
        members_to_drag.append(inter.author)  # Add author of command to members to drag
    elif not members_to_drag:
        await inter.edit_original_message(content="No valid member mentions were provided or no members found in the specified voice channel.")  # Edit the deferred response
        return

    for member in members_to_drag:
        try:
            await member.move_to(to_channel)
        except disnake.HTTPException as e:
            if e.status == 429:
                # If rate limited, wait for the specified time before trying again
                await asyncio.sleep(int(e.headers["Retry-After"]))
                await member.move_to(to_channel)
            else:
                raise e
        await asyncio.sleep(1)  # Add a 1-second delay between commands
    await inter.edit_original_message(content=f"Moved  members.")  # Edit the deferred response

@bot.slash_command(name="clear_chat", description="Clear all messages in the chat and disconnect the bot")
async def clear_chat(inter):
    await inter.response.defer()
    channel = inter.channel

    # Delete all messages in the channel
    await channel.purge()

    # Check if the bot is connected to a voice channel
    voice_client = get(bot.voice_clients, guild=inter.guild)
    if voice_client and voice_client.is_connected():
        # Check if the user who triggered the command is in a voice channel
        voice_state = inter.author.voice
        if voice_state and voice_state.channel:
            # Disconnect the bot only if the user is not in the same voice channel
            if voice_state.channel != voice_client.channel:
                await voice_client.disconnect()

    # Send a response message indicating the chat has been cleared
    await inter.edit_original_message(content="Chat cleared and bot disconnected.", ephemeral=True)




# Server stats
server_stats_settings = {}

@bot.slash_command(
    name="setup_serverstats",
    description="Set up server stats"
)
async def setup_serverstats(ctx: disnake.ApplicationCommandInteraction):
    server_id = ctx.guild.id

    # Check if the server has already been set up
    if server_id in server_stats_settings:
        await ctx.send("Server stats are already set up for this server.")
        return

    # Prompt the user for the desired settings
    await ctx.send("Let's set up the server stats display.")
    await ctx.send("Please select your preference for server stats:\n1. Voice Chat\n2. Text Chat")

    def check(message):
        return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

    try:
        preference_message = await bot.wait_for('message', timeout=60.0, check=check)
    except asyncio.TimeoutError:
        await ctx.send("Timeout. Please try again.")
        return

    preference = preference_message.content.lower()

    if preference not in ['1', '2']:
        await ctx.send("Invalid preference. Please select either '1' or '2'.")
        return

    # Create new channels based on the preference
    member_channel = None
    bot_channel = None
    total_channel = None
    category = None
    if preference == '1':
        # Voice Chat
        category = await ctx.guild.create_category("📊 ▬ SERVER STATS ▬ 📊")
        member_channel = await ctx.guild.create_voice_channel(f"Members-{ctx.guild.member_count}", category=category)
        bot_channel = await ctx.guild.create_voice_channel(f"Bots-{sum(member.bot for member in ctx.guild.members)}", category=category)
        total_channel = await ctx.guild.create_voice_channel(f"Total-{ctx.guild.member_count + sum(member.bot for member in ctx.guild.members)}", category=category)
    elif preference == '2':
        # Text Chat
        category = await ctx.guild.create_category("📊 ▬ SERVER STATS ▬ 📊")
        member_channel = await ctx.guild.create_text_channel(f"Members-{ctx.guild.member_count}", category=category)
        bot_channel = await ctx.guild.create_text_channel(f"Bots-{sum(member.bot for member in ctx.guild.members)}", category=category)
        total_channel = await ctx.guild.create_text_channel(f"Total-{ctx.guild.member_count + sum(member.bot for member in ctx.guild.members)}", category=category)

    if not member_channel or not bot_channel or not total_channel:
        await ctx.send("Failed to create the channels. Please make sure the bot has the required permissions.")
        return

    # Set channel permissions to lock them
    overwrites = {
        ctx.guild.default_role: disnake.PermissionOverwrite(connect=False)  # Lock the channels
    }
    await member_channel.edit(overwrites=overwrites)
    await bot_channel.edit(overwrites=overwrites)
    await total_channel.edit(overwrites=overwrites)

    # Store the server stats settings
    server_stats_settings[server_id] = {
        'category_id': category.id,
        'member_channel_id': member_channel.id,
        'bot_channel_id': bot_channel.id,
        'total_channel_id': total_channel.id
    }


    await ctx.send(f"Server stats have been set up successfully. Channels created: {member_channel.mention}, {bot_channel.mention}, {total_channel.mention}")

@bot.event
async def on_member_join(member):
    guild = member.guild
    server_id = guild.id

    if server_id in server_stats_settings:
        category_id = server_stats_settings[server_id]['category_id']
        member_channel_id = server_stats_settings[server_id]['member_channel_id']
        bot_channel_id = server_stats_settings[server_id]['bot_channel_id']
        total_channel_id = server_stats_settings[server_id]['total_channel_id']

        category = guild.get_channel(category_id)
        member_channel = guild.get_channel(member_channel_id)
        bot_channel = guild.get_channel(bot_channel_id)
        total_channel = guild.get_channel(total_channel_id)

        if member_channel and bot_channel and total_channel and category:
            member_count = guild.member_count
            bot_count = sum(member.bot for member in guild.members)
            total_count = member_count + bot_count

            # Edit the channel names with the updated counts
            await member_channel.edit(name=f"Members-{member_count}")
            await bot_channel.edit(name=f"Bots-{bot_count}")
            await total_channel.edit(name=f"Total-{total_count}")

            member_embed = disnake.Embed(title="Member Count", color=disnake.Color.blurple())
            member_embed.add_field(name="Count", value=str(member_count))

            bot_embed = disnake.Embed(title="Bot Count", color=disnake.Color.blurple())
            bot_embed.add_field(name="Count", value=str(bot_count))

            total_embed = disnake.Embed(title="Total Count", color=disnake.Color.blurple())
            total_embed.add_field(name="Count", value=str(total_count))

            await member_channel.send(embed=member_embed)
            await bot_channel.send(embed=bot_embed)
            await total_channel.send(embed=total_embed)


@bot.slash_command(
    name="serverstats",
    description="Display server statistics"
)
async def serverstats(ctx: disnake.ApplicationCommandInteraction):
    guild = ctx.guild
    member_count = guild.member_count
    bot_count = sum(member.bot for member in guild.members)
    total_count = member_count + bot_count

    cpu_usage = psutil.cpu_percent()
    memory_usage = psutil.virtual_memory().percent

    embed = disnake.Embed(title="📊 ▬ SERVER STATS ▬ 📊", color=disnake.Color.blurple())
    embed.add_field(name="Member Count", value=str(member_count))
    embed.add_field(name="Bot Count", value=str(bot_count))
    embed.add_field(name="Total Count", value=str(total_count))
    embed.add_field(name="Text Channels", value=str(len(guild.text_channels)))
    embed.add_field(name="Voice Channels", value=str(len(guild.voice_channels)))
    embed.add_field(name="CPU Usage", value=f"{cpu_usage}%")
    embed.add_field(name="Memory Usage", value=f"{memory_usage}%")

    await ctx.send(embed=embed)


# Role Reactions 
class RoleView(ui.View):
    def __init__(self, roles, emojis):
        super().__init__(timeout=None)
        self.roles = roles
        self.emojis = emojis
        self.dropdown = ui.Select(placeholder="Select a role...", options=[
            ui.SelectOption(label=emoji, description=role.name, value=str(idx))
            for idx, (role, emoji) in enumerate(zip(roles, emojis))
        ])
        self.add_item(self.dropdown)

    async def interaction_check(self, interaction: MessageInteraction) -> bool:
        role_id = int(interaction.data['values'][0])
        role = self.roles[role_id]
        member = interaction.user

        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"Removed {role.name} from {member.mention}", ephemeral=True)
        else:
          await member.add_roles(role)
          await interaction.response.send_message(f"Added {role.name} to {member.mention}", ephemeral=True)

        return True


    async def assign_role(self, interaction, role):
        member = interaction.user
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"Removed {role.name} from {member.mention}", ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"Added {role.name} to {member.mention}", ephemeral=True)


setup_step = None
setup_title = ""
setup_description = ""
setup_roles = []
setup_emojis = []
setup_include_roles = False
setup_color = 0


@bot.slash_command(name="setup_role", description="Begin setting up a custom message")
@commands.has_guild_permissions(administrator=True)
async def setup_role(ctx):
    global setup_step
    setup_step = "title"
    await ctx.send("Please enter the title for the message:")

@bot.event
async def on_message(message):
    global setup_step, setup_title, setup_description, setup_roles, setup_include_roles, setup_color, setup_emojis
    
    # Ignore bot's own messages
    if message.author == bot.user:
        return

    if setup_step == "title":
        setup_title = message.content
        setup_step = "description"
        await message.channel.send("Please enter the description for the message:")
    elif setup_step == "description":
        setup_description = message.content
        setup_step = "color"
        await message.channel.send("Please enter the color for the embed (in hex format, e.g. #123456):")
    elif setup_step == "color":
        setup_color = int(message.content.replace("#", ""), 16)  # Convert hex color to integer
        setup_step = "roles"
        await message.channel.send("Do you want to include role reactions? (yes/no):")
    elif setup_step == "roles":
        if message.content.lower() == "yes":
            setup_include_roles = True
            setup_step = "role_list"
            await message.channel.send("Please mention the roles for the role message (separated by spaces):")
        else:
            setup_include_roles = False
            setup_step = "channel"  # If no role reactions, ask for the channel to send the message to
            await message.channel.send("Please mention the channel where you want to post the message, or provide a name for a new channel:")
    elif setup_step == "role_list":
        # Get the order of role mentions in the message content
        role_order = [int(role_id) for role_id in re.findall(r'<@&(\d+)>', message.content)]
        # Sort role_mentions based on their order in the message content
        setup_roles = sorted(message.role_mentions, key=lambda r: role_order.index(r.id))
        setup_step = "emoji_list"
        await message.channel.send("Please enter the emojis for each role (separated by spaces, in the same order as the roles):")
    elif setup_step == "emoji_list":
        setup_emojis = message.content.split()  # Split by whitespace to get each emoji
        setup_step = "channel"
        await message.channel.send("Please mention the channel where you want to post the message, or provide a name for a new channel:")
    elif setup_step == "channel":
        if message.channel_mentions:  # If there's a channel mention in the message
            setup_channel = message.channel_mentions[0]  # Use the first mentioned channel
        else:  # If there's no channel mention, create a new channel
            overwrites = {
                message.guild.default_role: disnake.PermissionOverwrite(read_messages=False),
                message.guild.me: disnake.PermissionOverwrite(read_messages=True)
            }
            setup_channel = await message.guild.create_text_channel(message.content, overwrites=overwrites)
        setup_step = None
        await clear_messages(message.channel)  # Clear messages in channel
        embed = disnake.Embed(title=setup_title, description=setup_description, color=setup_color)
        message_sent = await setup_channel.send(embed=embed)
        if setup_include_roles:
            for emoji in setup_emojis:
                await message_sent.add_reaction(emoji)
        else:
            for emoji in setup_emojis:
                await message_sent.add_reaction(emoji)  # Add reactions even if there's no roles associated
    elif setup_step == "emoji_list":
        setup_emojis = message.content.split()  # Split by whitespace to get each emoji
        setup_step = None
        print(f"Roles: {setup_roles}")  # Debug: print roles
        print(f"Emojis: {setup_emojis}")  # Debug: print emojis
        await clear_messages(message.channel)  # Clear messages in channel
        embed = disnake.Embed(title=setup_title, description=setup_description, color=setup_color)
        message_sent = await message.channel.send(embed=embed)
    if setup_include_roles:
        for emoji in setup_emojis:
            await message_sent.add_reaction(emoji)
    else:
        for emoji in setup_emojis:
            await message_sent.add_reaction(emoji)  # Add reactions even if there's no roles associated


async def clear_channel_messages(channel):
    async for message in channel.history(limit=100):
        try:
            await message.delete()
        except:
            pass

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot:
        pass
    else:
        emoji = str(payload.emoji)
        if emoji in setup_emojis:
            idx = setup_emojis.index(emoji)
            role = disnake.utils.get(payload.member.guild.roles, id=setup_roles[idx].id)
            if role in payload.member.roles:
                await payload.member.remove_roles(role)  # Remove role if member already has it
            else:
                await payload.member.add_roles(role)  # Add role if member doesn't have it



@bot.event
async def on_raw_reaction_remove(payload):
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return

    emoji = str(payload.emoji)
    if emoji in setup_emojis:
        idx = setup_emojis.index(emoji)
        role = disnake.utils.get(guild.roles, id=setup_roles[idx].id)
        if role in member.roles:
            await member.remove_roles(role)

if bot.get_command("play"):
    bot.remove_command("play")
    bot.load_extension('bot.cogs.music')



@bot.slash_command()
async def set_patch_notes_channel(ctx, channel: disnake.TextChannel):
    # Save the chosen channel in bot's storage
    bot.patch_notes_channel = channel
    await ctx.send(f"Patch notes channel set to {channel.mention}")


@bot.slash_command()
async def check_patch_notes(ctx):
    url = 'https://playvalorant.com/en-us/news/game-updates/'
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            soup = BeautifulSoup(await response.text(), 'html.parser')
    
    latest_patch = soup.find('a', {"data-testid": "card-1"})
    
    if latest_patch is not None:
        patch_title = latest_patch.find('h3').text.strip()
        patch_link = 'https://playvalorant.com' + latest_patch['href']
        patch_description = latest_patch.find('p').text.strip()
        patch_image_url = latest_patch.find('img')['src']

        embed = Embed(title=patch_title, url=patch_link, description=patch_description)
        embed.set_image(url=patch_image_url)
        channel = bot.patch_notes_channel  # Get the saved channel
        if channel:
            await channel.send(embed=embed)  # Send the embed to the specified channel
            await ctx.send("Patch notes sent successfully!")
        else:
            await ctx.send("Please set the patch notes channel using the `/set_patch_notes_channel` command.")
    else:
        await ctx.send("Couldn't find the latest patch.")




def setup(bot):
    bot.add_cog(Music(bot))

# Run the bot
bot.run(TOKEN)