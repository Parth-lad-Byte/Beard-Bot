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
from epicstore_api import EpicGamesStoreAPI
from collections import deque
import googleapiclient.discovery
import os
from disnake import Option
from discord.ext import tasks
from bot.utils.colors import color_map
from disnake.app_commands import OptionType



user_preferences = {}
# Store the currently playing song for each guild
global currently_playing
players = {}
currently_playing = {}
queues = {}
playercontrols = {}
paused_songs = {}
page_data = {}
skip_request = {}


# Set up Spotify API credentials
spotify_credentials = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
spotify = spotipy.Spotify(client_credentials_manager=spotify_credentials)

bot = commands.Bot(command_prefix='/', intents=disnake.Intents.all(), help_command=None)

start_time = datetime.datetime.utcnow()
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def create_source(cls, bot, url, loop, download=False):
        ytdl = youtube_dl.YoutubeDL({'format': 'bestaudio/best', 'noplaylist': 'True'})

        if download:
            ytdl.params['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]

        loop = loop or asyncio.get_event_loop()

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=download))
        if 'entries' in data:
            # If it's a playlist, select the first entry
            data = data['entries'][0]

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn',
        }

        source = await discord.FFmpegPCMAudio(data['url'], **ffmpeg_options)
        return cls(source, data=data)
class Queue:
    def __init__(self):
        self._queue = deque()
        self.current_song = None
        self.is_playing = False

    def add(self, item):
        self._queue.append(item)

    def dequeue(self):
        return self._queue.popleft()

    def remove_song(self, index):
        if 0 <= index < len(self._queue):
            self._queue.pop(index)

    def clear_queue(self):
        self._queue.clear()

    def is_empty(self):
        return not self._queue

    async def play_next_song(self, bot, guild_id):
        if not self.is_empty() and not self.is_playing:
            self.is_playing = True
            next_song = self.dequeue()
            print(f'Playing next song: {next_song}')  # Debug print statement
            self.current_song = next_song

            voice_client = bot.voice_clients[guild_id]
            source = await YTDLSource.create_source(bot, next_song['url'], loop=bot.loop, download=False)

            async def after_playback(error, guild_id):
                if error:
                    print(f"Error in playback: {error}")

                # Check if there was a skip request
                if skip_request.get(guild_id):
                    # Reset the skip request flag
                    skip_request[guild_id] = False
                    return

                # Get the next song to play
                queue = queues.get(guild_id)
                if queue and not queue.is_empty():
                    next_song = queue.dequeue()
                    print(f'Playing next song: {next_song}')  # Debug print statement

                    voice_client = bot.voice_clients[guild_id]
                    source = await YTDLSource.create_source(bot, next_song['url'], loop=bot.loop, download=False)
                    voice_client.play(source, after=lambda e: asyncio.create_task(after_playback(e, guild_id)))

                    # Update the currently playing song
                    queue.current_song = next_song
                else:
                    # No more songs in the queue
                    currently_playing.pop(guild_id, None)
                    playercontrols.pop(guild_id, None)
                    if guild_id in players:
                        players[guild_id].stop()
                        del players[guild_id]
                    queues.pop(guild_id, None)

                    # Remove the currently playing song from the queue
                    queue.current_song = None


    def size(self):
        return len(self._queue)

    @property
    def queue(self):
        return self._queue


class PlayerControls(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="⏯️", custom_id="play_pause"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="⏭️", custom_id="skip"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="💌", custom_id="send_dm"))
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="🗑️", custom_id="clear_chat"))  # Clear button
        self.add_item(disnake.ui.Button(style=disnake.ButtonStyle.red, emoji="📑", custom_id="show_queue"))
class VolumeControl(ui.View):
    def __init__(self):
        super().__init__()

class ControlsView(PlayerControls):
    def __init__(self):
        super().__init__()
        self.add_item(VolumeButton('-', -25))
        self.add_item(VolumeButton('+', 25))

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

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # Initialize queues at the class level

    async def _play(self, inter, *, song):
        guild_id = inter.guild.id

        if guild_id not in self.queues:
            self.queues[guild_id] = Queue(guild_id)

        if inter.guild.voice_client.is_playing():
            await get_youtube_song(inter, song, add_to_queue=True)  # Add to queue if a song is playing
        else:
            await get_youtube_song(inter, song, add_to_queue=False)  # Play immediately if no song is playing

    async def play_next(self, inter):
        guild_id = inter.guild.id
        if guild_id in self.queues:
            queue = self.queues[guild_id]
            if not queue.is_empty():
                bot_instance = inter.bot
                await queue.play_next_song(bot_instance, guild_id)
                return
        currently_playing.pop(guild_id, None)
        players[guild_id].stop()
        del players[guild_id]
        self.queues.pop(guild_id, None)

    async def play_next_song(self, bot, guild_id):
        if guild_id in self.queues:
            queue = self.queues[guild_id]
            if not queue.is_empty():
                next_song = queue.dequeue()
                queue.current_song = next_song

                voice_client = bot.voice_clients[guild_id]
                source = await YTDLSource.create_source(bot, next_song['url'], loop=bot.loop, download=False)
                voice_client.play(source, after=lambda _: asyncio.ensure_future(asyncio.sleep(1), self.play_next_song(bot, guild_id)))

                # Remove the currently playing song from the queue after starting to play the next song
                queue.current_song = None
            else:
                currently_playing.pop(guild_id, None)
                players[guild_id].stop()
                del players[guild_id]
                self.queues.pop(guild_id, None)
        else:
            currently_playing.pop(guild_id, None)
            players[guild_id].stop()
            del players[guild_id]
            self.queues.pop(guild_id, None)


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

    source = disnake.FFmpegPCMAudio(url, **FFMPEG_OPTIONS, executable='c:/ffmpeg/bin/ffmpeg.exe')
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
    view = ControlsView()
    await ctx.send(embed=embed, view=view)

def get_youtube_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


# Function to fetch playlist information using YouTube Data API
async def fetch_playlist_info(playlist_id):
    api_key = os.getenv('YOUTUBE_API_KEY')  # Replace with your YouTube Data API key

    youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=api_key)
    request = youtube.playlistItems().list(
        part='snippet',
        playlistId=playlist_id,
        maxResults=50  # Adjust the maximum number of results as needed
    )

    try:
        response = await request.execute()
        playlist_info = {
            'tracks': []
        }

        for item in response.get('items', []):
            track_info = item['snippet']
            song = {
                'id': track_info['resourceId']['videoId'],
                'title': track_info['title'],
                'url': f"https://www.youtube.com/watch?v={track_info['resourceId']['videoId']}",
                'thumbnail': track_info['thumbnails']['default']['url'],
                'duration': 'Unknown',  # You can fetch the duration using additional API calls if needed
                'requested_by': 'Unknown'  # Set the requested_by field as needed
            }
            playlist_info['tracks'].append(song)

        return playlist_info

    except googleapiclient.errors.HttpError as e:
        print(f"Error fetching playlist information: {e}")
        return None


async def get_youtube_song(inter, search_query, add_to_queue=True):
    try:
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

        if add_to_queue:
            queues[inter.guild.id].add(info)
            if not inter.guild.voice_client.is_playing() and not inter.guild.voice_client.is_paused():
                await play_song(inter, info)
        else:
            if not inter.guild.voice_client.is_playing() and not inter.guild.voice_client.is_paused():
                await play_song(inter, info)
            else:
                await show_queue(inter.guild.id, inter.channel)  # Show the updated queue

    except Exception as e:
        await inter.send(f"An error occurred while getting the song: {str(e)}")


async def show_queue(guild_id, channel):
    queue = queues[guild_id]
    if not queue.is_empty():
        song_list = [f"{song['title']} - {format_duration(song['duration'])}" for song in queue.get_all()]
        await channel.send("Current Queue:\n" + "\n".join(song_list))
    else:
        await channel.send("The queue is empty.")


def format_duration(duration):
    minutes = duration // 60
    seconds = duration % 60
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

async def play_next(inter):
    guild_id = inter.guild.id
    if guild_id in queues:
        queue = queues[guild_id]
        if not queue.is_empty():
            bot_instance = inter.bot
            await queue.play_next_song(bot_instance, guild_id)
            return
    currently_playing.pop(guild_id, None)
    playercontrols.pop(guild_id, None)
    players[guild_id].stop()
    del players[guild_id]
    queues.pop(guild_id, None)





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
    # Check if the user is in a voice channel
    if not inter.author.voice or not inter.author.voice.channel:
        await inter.response.send_message("You need to be in a voice channel to play a song.")
        return

    await inter.response.defer()  # Defer the response

    # Do not clear the queue here; instead, add to it
    # queues[inter.guild.id] = Queue()
    # currently_playing.pop(inter.guild.id, None)

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

    embed = disnake.Embed(title="Now Playing", color=disnake.Color.green())
    embed.add_field(name="Title", value=next_song['title'], inline=False)
    embed.add_field(name="Duration", value=next_song['duration'], inline=False)
    embed.set_thumbnail(url=next_song.get('thumbnail', 'default_thumbnail_url'))
    embed.set_footer(text=f"Requested by: {next_song['requested_by']}")
    view = ControlsView()
    await inter.followup.send(embed=embed, view=view)

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

    if add_to_queue:
        queues[inter.guild.id].add(info)
        if not inter.guild.voice_client.is_playing() and not inter.guild.voice_client.is_paused():
            await play_song(inter, info)
    else:
        if not inter.guild.voice_client.is_playing() and not inter.guild.voice_client.is_paused():
            await play_song(inter, info)
        else:
            await show_queue(inter.guild.id, inter.channel)  # Show the updated queue


def format_duration(duration):
    minutes = duration // 60
    seconds = duration % 60
    return f"{minutes:02d}:{seconds:02d}"

@bot.slash_command(name="show_queue", description="Show the current song queue")
async def _show_queue(inter, page_number: int = 1):
    guild_id = inter.guild.id
    if guild_id in queues and queues[guild_id].size() > 0:
        queue = queues[guild_id]
        queue_items = [song['title'] for song in queue.queue]

        page_size = 10
        page_count = (len(queue_items) + page_size - 1) // page_size  # Calculate total number of pages
        
        if page_number < 1 or page_number > page_count:
            await inter.response.send_message("Invalid page number.")
            return

        start_index = (page_number - 1) * page_size
        end_index = start_index + page_size
        queue_items_page = queue_items[start_index:end_index]

        queue_text = "\n".join([f"`{start_index + i + 1}.` {song}" for i, song in enumerate(queue_items_page)])

        embed = disnake.Embed(
            title="Music Queue",
            description=queue_text,
            color=disnake.Color.blue()
        )
        embed.set_footer(text=f"Page {page_number}/{page_count} | Songs {start_index + 1}-{end_index}/{len(queue_items)} | Requested by: {inter.user.display_name}")


        await inter.response.send_message(embed=embed)
    else:
        await inter.response.send_message("The music queue is currently empty.")

def get_readable_song_name(song_name):
    # Remove special characters and capitalize the first letter of each word
    cleaned_name = ' '.join(word.capitalize() for word in re.findall(r'\w+', song_name))
    
    # Remove unwanted words
    unwanted_words = ['video', 'full', 'song']
    cleaned_name = ' '.join(word for word in cleaned_name.split() if word.lower() not in unwanted_words)
    
    return cleaned_name


@bot.slash_command(name="play_pause", description="Pause or resume the currently playing song")
async def _play_pause(inter):
    guild_id = inter.guild.id
    if guild_id in currently_playing:
        voice_client = inter.guild.voice_client
        if voice_client.is_playing():
            voice_client.pause()
            await inter.response.send_message("Paused the song.")
        else:
            voice_client.resume()
            await inter.response.send_message("Resumed the song.")
    else:
        await inter.response.send_message("No song is currently playing.")
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

@bot.slash_command(name="skip", description="Skip the currently playing song")
async def _skip(inter):
    guild_id = inter.guild.id
    if guild_id in queues:
        queue = queues[guild_id]
        if not queue.is_empty():
            # Set the skip request flag
            skip_request[guild_id] = True
            
            # Stop the current song
            voice_client = inter.guild.voice_client
            voice_client.stop()
            
            print(f'Skipping song. Queue: {list(queue._queue)}')  # Debug print statement

            await inter.send("Skipping to the next song.")
        else:
            await inter.send("The song queue is empty.")
    else:
        await inter.send("The song queue is empty.")




@bot.slash_command(name="player", description="Manage the music player")
async def _player(ctx):
    guild_id = ctx.guild.id

    if guild_id in currently_playing:
        song = currently_playing[guild_id]
        embed = disnake.Embed(title="Now Playing", color=disnake.Color.green())
        embed.add_field(name="Title", value=f"[{song.title}]({song.youtube_url})", inline=False)
        embed.add_field(name="Duration", value=song.duration, inline=False)
        embed.set_thumbnail(url=song.thumbnail)
        embed.set_footer(text=f"Requested by: {song.requested_by}")
    else:
        embed = disnake.Embed(title="Music Player", description="No song is currently playing.", color=disnake.Color.blue())

    view = PlayerControls()

    if ctx.data.name == "clear":
        # Clear chat and disconnect functionality
        channel = ctx.channel

        # Delete all messages in the channel
        await channel.purge()

        # Disconnect the bot from the voice channel (if connected)
        voice_client = get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

        # Send a response message indicating the chat has been cleared
        embed = disnake.Embed(title="Music Player", description="Chat cleared and bot disconnected.", color=disnake.Color.blue())
        await ctx.send(embed=embed, view=view)
    else:
        await ctx.send(embed=embed, view=view)
@bot.event
async def on_button_click(inter):
    custom_id = inter.data.custom_id

    if custom_id == "skip" or custom_id == "skip_command":
        guild_id = inter.guild.id
        if guild_id in queues:
            queue = queues[guild_id]
            if not queue.is_empty():
                # Set the skip request flag
                skip_request[guild_id] = True

                # Stop the current song
                voice_client = inter.guild.voice_client
                voice_client.stop()

                print(f'Skipping song. Queue: {list(queue._queue)}')  # Debug print statement

                await inter.send("Skipping to the next song.")
            else:
                await inter.send("The song queue is empty.")
        else:
            await inter.send("The song queue is empty.")

    elif custom_id == "play_pause":
        voice_client = inter.guild.voice_client
        if voice_client.is_playing():
            voice_client.pause()
            await inter.message.edit(content="Paused the song.")
        else:
            voice_client.resume()
            await inter.message.edit(content="Resumed the song.")

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
    elif custom_id == "clear_chat":
        channel = inter.channel

        # Delete all messages in the channel
        await channel.purge()

        # Check if the bot is connected to a voice channel
        voice_client = get(bot.voice_clients, guild=inter.guild)
        if voice_client and voice_client.is_connected():
            # Disconnect the bot
            await voice_client.disconnect()

        # Send a response message indicating the chat has been cleared
        await inter.send("Chat cleared and bot disconnected.")

    elif custom_id == "show_queue":
        guild_id = inter.guild.id
        if guild_id in queues:
            queue = queues[guild_id]
            if not queue.is_empty():
                page_number = 1
                page_size = 10
                page_count = (queue.size() + page_size - 1) // page_size

                if page_number < 1 or page_number > page_count:
                    await inter.send("Invalid page number.")
                    return

                start_index = (page_number - 1) * page_size
                end_index = start_index + page_size
                queue_items_page = list(queue._queue)[start_index:end_index]

                queue_text = "\n".join([f"{start_index + i + 1}. {song.title}" if not isinstance(song, dict) else f"{start_index + i + 1}. {song['title']}" for i, song in enumerate(queue_items_page)])

                embed = disnake.Embed(
                    title="Music Queue",
                    description=queue_text,
                    color=disnake.Color.blue()
                )
                embed.set_footer(text=f"Page {page_number}/{page_count} | Songs {start_index + 1}-{end_index}/{queue.size()} | Requested by: {inter.user.display_name}")

                await inter.send(embed=embed)
            else:
                await inter.send("The song queue is empty.")
        else:
            await inter.send("The song queue is empty.")

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
    funny_status = "/help | Report any Issues to @daddylad"
    truncated_status = (funny_status[:46] + "...") if len(funny_status) > 49 else funny_status
    await bot.change_presence(activity=disnake.Activity(type=disnake.ActivityType.listening, name=truncated_status))
    check_for_free_games.start()


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

    # Add music commands
    if music_commands:
        music_commands_text = "\n".join([f"{cmd} - {desc}" for cmd, desc in music_commands])
        embed.add_field(name="Music Commands", value=f"```{music_commands_text}```", inline=False)

    # Add utility commands
    if utility_commands:
        utility_commands_text = "\n".join([f"{cmd} - {desc}" for cmd, desc in utility_commands])
        embed.add_field(name="Utility Commands", value=f"```{utility_commands_text}```", inline=False)

    # Add bot utility commands
    if bot_utility:
        bot_utility_text = "\n".join([f"{cmd} - {desc}" for cmd, desc in bot_utility])
        embed.add_field(name="Bot Utility Commands", value=f"```{bot_utility_text}```", inline=False)

    # Add voice commands
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
        # Disconnect the bot
        await voice_client.disconnect()

    # Send a response message indicating the chat has been cleared
    await inter.edit_original_message(content="Chat cleared and bot disconnected.")

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

setups = {}

@bot.slash_command(name="setup_role", description="Begin setting up a custom message")
@commands.has_guild_permissions(administrator=True)
async def setup_role(ctx):
    if ctx.guild.id not in setups:
        setups[ctx.guild.id] = []
    setups[ctx.guild.id].append({
        "step": "title",
        "title": "",
        "description": "",
        "roles": [],
        "emojis": [],
        "message_id": None,
        "include_roles": False,
        "color": ""
    })
    await ctx.send("Please enter the title for the message:")

@bot.event
async def on_message(message):
    if message.author == bot.user or message.guild.id not in setups:
        return

    setup = setups[message.guild.id][-1]

    if setup["step"] == "title":
        setup["title"] = message.content
        setup["step"] = "description"
        await message.channel.send("Please enter the description for the message:")
    elif setup["step"] == "description":
        setup["description"] = message.content
        setup["step"] = "color"
        await message.channel.send("Please enter the color name for the embed:")
    elif setup["step"] == "color":
        setup["color"] = message.content.lower()
        setup["step"] = "roles"
        await message.channel.send("Do you want to include role reactions? (yes/no):")
    elif setup["step"] == "roles":
        if message.content.lower() == "yes":
            setup["include_roles"] = True
            setup["step"] = "role_list"
            await message.channel.send("Please mention the roles for the role message (separated by spaces):")
        else:
            setup["include_roles"] = False
            setup["step"] = "channel"
            await message.channel.send("Please mention the channel where you want to post the message, or provide a name for a new channel:")
    elif setup["step"] == "role_list":
        role_order = [int(role_id) for role_id in re.findall(r'<@&(\d+)>', message.content)]
        setup["roles"] = sorted(message.role_mentions, key=lambda r: role_order.index(r.id))
        setup["step"] = "emoji_list"
        await message.channel.send("Please enter the emojis for each role (separated by spaces, in the same order as the roles):")
    elif setup["step"] == "emoji_list":
        setup["emojis"] = message.content.split()
        setup["step"] = "channel"
        await message.channel.send("Please mention the channel where you want to post the message, or provide a name for a new channel:")
    elif setup["step"] == "channel":
        if message.channel_mentions:
            setup_channel = message.channel_mentions[0]
        else:
            overwrites = {
                message.guild.default_role: disnake.PermissionOverwrite(read_messages=False),
                message.guild.me: disnake.PermissionOverwrite(read_messages=True)
            }
            setup_channel = await message.guild.create_text_channel(message.content, overwrites=overwrites)
        setup["step"] = None
        await clear_channel_messages(message.channel)

        color_map = retrieve_color_map()
        color_hex = color_map.get(setup["color"], 0x000000)

        embed = disnake.Embed(title=setup["title"], description=setup["description"], color=color_hex)
        message_sent = await setup_channel.send(embed=embed)
        setup["message_id"] = message_sent.id

        if setup["include_roles"]:
            for emoji in setup["emojis"]:
                await message_sent.add_reaction(emoji)
        else:
            for emoji in setup["emojis"]:
                await message_sent.add_reaction(emoji)

async def clear_channel_messages(channel):
    async for message in channel.history(limit=100):
        try:
            await message.delete()
        except:
            pass

def retrieve_color_map():
    return color_map

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot or payload.guild_id not in setups:
        return

    for setup in setups[payload.guild_id]:
        if setup['message_id'] != payload.message_id:
            continue

        emoji = str(payload.emoji)
        if emoji in setup["emojis"]:
            idx = setup["emojis"].index(emoji)
            role = disnake.utils.get(payload.member.guild.roles, id=setup["roles"][idx].id)
            if role in payload.member.roles:
                await payload.member.remove_roles(role)
            else:
                await payload.member.add_roles(role)
            break

@bot.event
async def on_raw_reaction_remove(payload):
    guild = bot.get_guild(payload.guild_id)
    if guild is None or payload.guild_id not in setups:
        return

    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return

    for setup in setups[payload.guild_id]:
        if setup['message_id'] != payload.message_id:
            continue

        emoji = str(payload.emoji)
        if emoji in setup["emojis"]:
            idx = setup["emojis"].index(emoji)
            role = disnake.utils.get(guild.roles, id=setup["roles"][idx].id)
            if role in member.roles:
                await member.remove_roles(role)
            break


#Random commands that are use full


@bot.slash_command(description='Show color information.', options=[
    disnake.Option(name='color_name', description='Enter a color name', type=OptionType.string, required=True)
])
async def color(inter: disnake.ApplicationCommandInteraction, color_name: str):
    color_name = color_name.lower()
    if color_name not in color_map:
        await inter.response.send_message("Please provide a valid color name.")
        return

    color_hex_value = color_map[color_name]
    color_embed = disnake.Embed(title=f"Color: {color_name.capitalize()}", 
                                description=f"HEX: #{color_hex_value:06X}\nRGB: ({color_hex_value>>16}, {(color_hex_value>>8)&0xFF}, {color_hex_value&0xFF})",
                                color=color_hex_value)
    await inter.response.send_message(embed=color_embed)


@bot.slash_command(name="avatar", description="Get a user's avatar", 
                   options=[Option("user", "The user to get the avatar of", type=6, required=False)])
async def avatar(ctx, user: disnake.User = None):
    if user is None:  # if no member is mentioned
        user = ctx.author  # set member as the author

    embed = disnake.Embed(
        title = f"{user.name}'s avatar",
        color = disnake.Color.blue()
    )
    embed.set_image(url=user.display_avatar.url)
    await ctx.send(embed=embed)

@bot.slash_command(description='Check user info and ban history')
@disnake.ext.commands.has_permissions(administrator=True)
async def userinfo(ctx: disnake.ApplicationCommandInteraction, member: disnake.Member):
    # Get user info
    created_at = member.created_at.strftime('%a, %b %d, %Y %I:%M %p')
    joined_at = member.joined_at.strftime('%a, %b %d, %Y %I:%M %p')
    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]

    # Get user's key permissions
    key_permissions = {'kick_members', 'ban_members', 'administrator', 'manage_channels', 'manage_guild',
                    'view_audit_log', 'manage_messages', 'mention_everyone', 'manage_roles', 'manage_webhooks',
                    'manage_emojis'}

    # Get user's key permissions, only if they are in the set defined above
    permissions = [perm[0].replace("_", " ").title() for perm in member.guild_permissions if perm[1] and perm[0] in key_permissions]

    # Get ban history
    async for ban_entry in ctx.guild.bans():
        if ban_entry.user.id == member.id:
            break
    else:
        ban_entry = None

    if ban_entry:
        ban_info = f'Banned at: {ban_entry.created_at}\nReason: {ban_entry.reason}'
    else:
        ban_info = 'No ban history found'

    # Create embed
    embed = disnake.Embed(color=disnake.Color.blue())
    
    # Show avatar and username#discriminator
    if member.avatar:
        embed.set_author(name=f'{member}', icon_url=member.avatar.url)
    else:
        embed.set_author(name=f'{member}')
    embed.set_thumbnail(url=member.avatar.url)
    embed.add_field(name='Joined', value=f'{joined_at}', inline=True)
    embed.add_field(name='Registered', value=f'{created_at}', inline=True)
    embed.add_field(name=f'Roles [{len(roles)}]', value=', '.join(roles) or "None", inline=False)
    
    # Add Key Permissions field if there are any
    if permissions:
        embed.add_field(name='Key Permissions', value=', '.join(permissions), inline=False)
    
    embed.add_field(name='Ban History', value=ban_info, inline=False)
    
    # Add Acknowledgements field if member is server owner
    if member == ctx.guild.owner:
        embed.add_field(name='Acknowledgements', value='Server Owner', inline=False)

    # Footer with ID, Requested by and Requested at
    embed.set_footer(text=f'ID: {member.id} | Requested by {ctx.author.name} | {datetime.datetime.now().strftime("Today at %I:%M %p")}')
    
    await ctx.response.send_message(embed=embed)

@userinfo.error
async def userinfo_error(ctx, error):
    if isinstance(error, disnake.commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")
    else:
        raise error










#Ban command 
@bot.slash_command(description='Ban a user from the server.')
@commands.has_permissions(administrator=True)
async def ban(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member, reason: str = "No reason provided."):
    await user.ban(reason=reason)
    await inter.response.send_message(f'{user.name} has been banned from the server. Reason: {reason}')

#kick command 
@bot.slash_command(description='Kick a user from the server.')
@commands.has_permissions(administrator=True)
async def kick(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member, reason: str = "No reason provided."):
    await user.kick(reason=reason)
    await inter.response.send_message(f'{user.name} has been kicked from the server. Reason: {reason}')
#Mute command 
@bot.slash_command(description='Mute a user in the server.')
@commands.has_permissions(administrator=True)
async def mute(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member, duration: str, reason: str = "No reason provided."):
    # Mute the user by assigning the "Muted" role or applying necessary permission changes
    # Adjust the implementation based on your bot's mute functionality

    await inter.response.send_message(f'{user.name} has been muted for {duration}. Reason: {reason}')

#Unmute 
@bot.slash_command(description='Unmute a previously muted user.')
@commands.has_permissions(administrator=True)
async def unmute(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member):
    # Unmute the user by removing the "Muted" role or reverting the necessary permission changes
    # Adjust the implementation based on your bot's mute functionality

    await inter.response.send_message(f'{user.name} has been unmuted.')
#Manage Role
@bot.slash_command(description='Manage roles within the server.')
@commands.has_permissions(administrator=True)
async def role(self, inter: disnake.ApplicationCommandInteraction, action: str, user: disnake.Member, role: disnake.Role):
    if action == 'add':
        await user.add_roles(role)
        await inter.response.send_message(f'{user.name} has been given the role: {role.name}')
    elif action == 'remove':
        await user.remove_roles(role)
        await inter.response.send_message(f'{user.name} no longer has the role: {role.name}')
    else:
        await inter.response.send_message('Invalid action. Please provide either "add" or "remove".')

    

#agem patch  
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

api = EpicGamesStoreAPI()
FREE_GAMES_CHANNEL = None

sent_free_games = set()

@tasks.loop(minutes=5)
async def check_for_free_games():
    global FREE_GAMES_CHANNEL
    if FREE_GAMES_CHANNEL is None:
        return

    free_games_promotions = api.get_free_games()
    free_games = []
    for game in free_games_promotions['data']['Catalog']['searchStore']['elements']:
        if game['promotions'] and game['promotions']['promotionalOffers']:
            free_games.append(game)
            title = game['title']
            if title in sent_free_games:
                continue
            sent_free_games.add(title)
            url = f"https://www.epicgames.com/store/en-US/p/{game['productSlug']}"
            image_url = game['keyImages'][0]['url']
            original_price = game['price']['totalPrice']['fmtPrice']['originalPrice']
            price = game['price']['totalPrice']['fmtPrice']['discountPrice']
            game_info = {
                'title': title,
                'url': url,
                'image_url': image_url,
                'original_price': original_price,
                'price': price if price != '0' else 'Free',  # set price to 'Free' if the discount price is '0'
                'platform': 'PC',
                'store': 'Epic Games Store',
            }

            embed = disnake.Embed(title=game_info['title'], url=game_info['url'])
            embed.set_image(url=game_info['image_url'])
            embed.add_field(name='Store', value=game_info['store'], inline=True)
            embed.add_field(name='Platform', value=game_info['platform'], inline=True)
            original_price_with_strike = f'~~{game_info["original_price"]}~~'
            price = f'{original_price_with_strike} - {game_info["price"]}'  # Add strikethrough to original price
            embed.add_field(name='Price', value=price, inline=False)

            await FREE_GAMES_CHANNEL.send(embed=embed)

@bot.slash_command(
    name='setup',
    description='Set up the channel for free games notifications',
    options=[
        disnake.Option(
            name='channel',
            description='The channel to receive free games notifications',
            type=disnake.OptionType.channel,
            required=True
        )
    ]
)
async def setup(ctx, channel: disnake.TextChannel):
    global FREE_GAMES_CHANNEL
    FREE_GAMES_CHANNEL = channel
    await ctx.send(f'Set up the free games notifications channel to {channel.mention}.')

@bot.slash_command(
    name='freegames',
    description='Fetch and display free games'
)
async def freegames(ctx):
    global FREE_GAMES_CHANNEL
    if FREE_GAMES_CHANNEL is None:
        await ctx.send('The free games channel has not been set up. Please run the /setup command to set up the channel.')
        return

    free_games_promotions = api.get_free_games()
    free_games = []
    for game in free_games_promotions['data']['Catalog']['searchStore']['elements']:
        if game['promotions'] and game['promotions']['promotionalOffers']:
            free_games.append(game)
            title = game['title']
            url = f"https://www.epicgames.com/store/en-US/p/{game['productSlug']}"
            image_url = game['keyImages'][0]['url']
            original_price = game['price']['totalPrice']['fmtPrice']['originalPrice']
            price = game['price']['totalPrice']['fmtPrice']['discountPrice']
            game_info = {
                'title': title,
                'url': url,
                'image_url': image_url,
                'original_price': original_price,
                'price': price if price != '0' else 'Free',  # set price to 'Free' if the discount price is '0'
                'platform': 'PC',
                'store': 'Epic Games Store',
            }

            embed = disnake.Embed(title=game_info['title'], url=game_info['url'])
            embed.set_image(url=game_info['image_url'])
            embed.add_field(name='Store', value=game_info['store'], inline=True)
            embed.add_field(name='Platform', value=game_info['platform'], inline=True)
            original_price_with_strike = f'~~{game_info["original_price"]}~~'
            price = f'{original_price_with_strike} - {game_info["price"]}'  # Add strikethrough to original price
            embed.add_field(name='Price', value=price, inline=False)

            await FREE_GAMES_CHANNEL.send(embed=embed)
    else:
        await ctx.send("No free games available.")

# Run the bot
bot.run(TOKEN)
