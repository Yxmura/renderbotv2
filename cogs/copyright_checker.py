import os
import discord
from discord.ext import commands
from discord import app_commands
from yt_dlp import YoutubeDL
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from googleapiclient.discovery import build
import re
import json
import io
import logging

logger = logging.getLogger('bot.copyright_checker')

# YouTube URL pattern for regex matching
YOUTUBE_URL_PATTERN = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})'


class CopyrightChecker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache_file = 'data/video_cache.json'

        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)

        # Load cached data from the file (if it exists)
        self.cached_info = self.load_cache()

        # YouTube API setup
        youtube_api_key = os.getenv('YOUTUBE_API_KEY')
        if not youtube_api_key:
            logger.warning("YOUTUBE_API_KEY not found in environment variables")
        self.youtube_client = build('youtube', 'v3', developerKey=youtube_api_key) if youtube_api_key else None

        # Spotify API setup
        spotify_client_id = os.getenv('SPOTIFY_CLIENT_ID')
        spotify_client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        if not spotify_client_id or not spotify_client_secret:
            logger.warning("Spotify API credentials not found in environment variables")
            self.spotify = None
        else:
            self.spotify = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
                spotify_client_id, spotify_client_secret))

        # YouTube-DL options
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'extract_flat': 'in_playlist',
            'quiet': True,
            'no_warnings': True,
            'force_generic_extractor': False,
            'cookies': 'cookies.txt' if os.path.exists('cookies.txt') else None
        }

    def load_cache(self):
        """Load the cached video info from a file."""
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_cache(self):
        """Save the cached video info to a file."""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cached_info, f)

    @app_commands.command(name='check', description="Check copyright status of a song by title or YouTube URL")
    @app_commands.describe(query="Song title or YouTube URL to check")
    async def check_copyright(self, interaction: discord.Interaction, query: str):
        """Check copyright status of a song by title or YouTube URL"""
        await interaction.response.defer(thinking=True)
        try:
            if 'youtube.com' in query or 'youtu.be' in query:
                info = await self.get_youtube_info(query)
                if info:
                    embed = await self.create_youtube_embed(info)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(
                        "❌ Couldn't fetch video information. Please make sure the URL is valid.")
            else:
                if not self.spotify:
                    await interaction.followup.send(
                        "❌ Spotify API is not configured. Please use a YouTube URL instead.")
                    return

                results = await self.search_spotify_info(query)
                if results:
                    embed = await self.create_spotify_embed(results)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send("❌ No information found for this song on Spotify.")
        except Exception as e:
            error_msg = f"❌ An error occurred: {str(e)}"
            if "HTTP Error 429" in str(e):
                error_msg = "❌ Rate limit reached. Please try again later."
            elif "This video is unavailable" in str(e):
                error_msg = "❌ This video is unavailable or private."
            await interaction.followup.send(error_msg)
            logger.error(f"Error in check_copyright: {str(e)}")

    async def get_youtube_info(self, url):
        """Get copyright information from YouTube video, using cache if available."""
        if url in self.cached_info:
            return self.cached_info[url]

        with YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                if not info:
                    return None

                license_info = info.get('license', 'Standard YouTube License')
                title = info.get('title', '').lower()
                description = info.get('description', '').lower()
                is_creative_commons = (
                        'creative commons' in description or
                        license_info.lower() == 'creative commons'
                )
                no_copyright_terms = ['no copyright', 'free to use', 'royalty-free', 'copyright free', 'public domain',
                                      'royalty free music']
                contains_no_copyright = any(term in title or term in description for term in no_copyright_terms)
                copyrighted = not (is_creative_commons or contains_no_copyright)

                video_info = {
                    'title': info.get('title', 'Unknown'),
                    'channel': info.get('uploader', 'Unknown'),
                    'license': license_info,
                    'is_copyrighted': copyrighted,
                    'description': info.get('description', 'No description available'),
                    'thumbnail': info.get('thumbnail', None),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', 'Unknown'),
                    'url': info.get('webpage_url', url)
                }

                self.cached_info[url] = video_info
                self.save_cache()
                return video_info

            except Exception as e:
                logger.error(f"Error extracting video info: {str(e)}")
                return None

    async def search_spotify_info(self, query):
        """Search for song information using Spotify"""
        if not self.spotify:
            return None

        try:
            results = self.spotify.search(q=query, type='track', limit=1)
            if results['tracks']['items']:
                track = results['tracks']['items'][0]
                album = self.spotify.album(track['album']['id'])
                copyrighted = True
                if 'copyrights' in album:
                    copyright_text = ' '.join([c['text'].lower() for c in album['copyrights']])
                    if any(term in copyright_text for term in ['creative commons', 'public domain', 'cc0']):
                        copyrighted = False
                return {
                    'title': track['name'],
                    'artist': ", ".join(artist['name'] for artist in track['artists']),
                    'album': track['album']['name'],
                    'release_date': track['album']['release_date'],
                    'spotify_url': track['external_urls']['spotify'],
                    'thumbnail': track['album']['images'][0]['url'] if track['album']['images'] else None,
                    'is_copyrighted': copyrighted,
                    'copyright_text': album.get('copyrights', [{'text': 'No copyright information available'}])[0][
                        'text']
                }
            return None
        except Exception as e:
            logger.error(f"Error fetching song info from Spotify: {str(e)}")
            return None

    async def create_spotify_embed(self, info):
        """Create Discord embed for Spotify track info"""
        copyright_status = "🔒 Likely Copyrighted" if info['is_copyrighted'] else "⚠️ Potentially Not Copyrighted"
        embed = discord.Embed(
            title="Spotify Track Information",
            description=f"[Listen on Spotify]({info['spotify_url']})",
            color=discord.Color.green()
        )
        embed.add_field(name="Title", value=info['title'], inline=False)
        embed.add_field(name="Artist(s)", value=info['artist'], inline=True)
        embed.add_field(name="Album", value=info['album'], inline=True)
        embed.add_field(name="Release Date", value=info['release_date'], inline=True)
        embed.add_field(name="Estimated Status", value=copyright_status, inline=False)
        embed.add_field(name="Copyright Info", value=info['copyright_text'], inline=False)
        embed.add_field(name="⚠️ Important Note", value=(
            "Spotify Search Results Are Not Accurate! Use YouTube Search Instead."
        ), inline=False)
        if info['thumbnail']:
            embed.set_thumbnail(url=info['thumbnail'])
        return embed

    async def create_youtube_embed(self, info):
        """Create Discord embed for YouTube video info"""
        copyright_status = "🔒 Copyrighted" if info['is_copyrighted'] else "✔️ Public Domain / Creative Commons"
        embed = discord.Embed(
            title="YouTube Video Information",
            description=f"[Watch on YouTube]({info.get('url')})",
            color=discord.Color.red()
        )
        embed.add_field(name="Title", value=info['title'], inline=False)
        embed.add_field(name="Channel", value=info['channel'], inline=True)
        embed.add_field(name="License", value=info['license'], inline=True)
        embed.add_field(name="Status", value=copyright_status, inline=True)
        embed.add_field(name="Note",
                        value="This check is based on video license information, title, and description analysis.",
                        inline=True)
        embed.add_field(name="Note For Epidemic Music",
                        value="If you are checking a music Epidemic Music Which Says That It is Royalty Free, That Does Not Mean You Can Use it you have to buy a subscription from Epidemic.",
                        inline=True)
        embed.set_footer(text="Learn About Copyright, types, symbols and much more. Visit Gappa Wiki Now!")

        if info['thumbnail']:
            embed.set_thumbnail(url=info['thumbnail'])
        return embed

    @app_commands.command(name="fetch", description="Fetch detailed information about a YouTube video")
    @app_commands.describe(url="YouTube video URL to fetch information for")
    async def fetch_video_info(self, interaction: discord.Interaction, url: str):
        """Fetch detailed information about a YouTube video"""
        if not self.youtube_client:
            await interaction.response.send_message("❌ YouTube API is not configured.")
            return

        await interaction.response.defer(thinking=True)
        try:
            video_info = self.get_video_info(url)
            embed = discord.Embed(
                title=video_info['title'],
                description=video_info['description'][:200] + "..." if len(video_info['description']) > 200 else
                video_info['description'],
                color=discord.Color.red(),
                url=url
            )
            embed.set_author(name=video_info['channel_title'])
            embed.add_field(name="Published on", value=video_info['publish_date'], inline=True)
            embed.add_field(name="Views", value=f"{int(video_info['views']):,}", inline=True)
            embed.add_field(name="Likes", value=f"{int(video_info['likes']):,}", inline=True)
            embed.add_field(name="Comments", value=f"{int(video_info['comments']):,}", inline=True)
            embed.add_field(name="Duration", value=self.format_duration(video_info['duration']), inline=True)
            embed.add_field(name="Channel Subscribers", value=f"{int(video_info['channel_subscribers']):,}",
                            inline=True)
            embed.add_field(name="Total Videos", value=f"{int(video_info['channel_videos']):,}", inline=True)
            if 'thumbnail' in video_info and video_info['thumbnail']:
                embed.set_thumbnail(url=video_info['thumbnail'])
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {str(e)}")
            logger.error(f"Error in fetch_video_info: {str(e)}")

    def format_duration(self, duration):
        """Convert ISO 8601 duration to a more readable format"""
        duration = duration.replace('PT', '')
        hours = 0
        minutes = 0
        seconds = 0
        if 'H' in duration:
            hours, duration = duration.split('H')
            hours = int(hours)
        if 'M' in duration:
            minutes, duration = duration.split('M')
            minutes = int(minutes)
        if 'S' in duration:
            seconds = int(duration.replace('S', ''))
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

    def get_video_info(self, video_url):
        """Get detailed information about a YouTube video"""
        if not self.youtube_client:
            raise Exception("YouTube API is not configured.")

        # Extract video ID from URL
        match = re.search(YOUTUBE_URL_PATTERN, video_url)
        if not match:
            raise Exception("Invalid YouTube URL")

        video_id = match.group(1)

        video_request = self.youtube_client.videos().list(
            part="snippet,contentDetails,statistics",
            id=video_id
        )
        video_response = video_request.execute()
        if not video_response['items']:
            raise Exception("Invalid YouTube video link or video not found.")
        video_data = video_response["items"][0]
        channel_id = video_data["snippet"]["channelId"]
        channel_request = self.youtube_client.channels().list(
            part="snippet,statistics",
            id=channel_id
        )
        channel_response = channel_request.execute()
        channel_data = channel_response["items"][0]
        thumbnail = video_data["snippet"]["thumbnails"]["high"]["url"] if "thumbnails" in video_data[
            "snippet"] else None
        return {
            "title": video_data["snippet"]["title"],
            "description": video_data["snippet"]["description"],
            "channel_title": video_data["snippet"]["channelTitle"],
            "publish_date": video_data["snippet"]["publishedAt"],
            "views": video_data["statistics"].get("viewCount", "0"),
            "likes": video_data["statistics"].get("likeCount", "0"),
            "comments": video_data["statistics"].get("commentCount", "0"),
            "duration": video_data["contentDetails"]["duration"],
            "channel_subscribers": channel_data["statistics"].get("subscriberCount", "0"),
            "channel_videos": channel_data["statistics"].get("videoCount", "0"),
            "thumbnail": thumbnail
        }

    @app_commands.command(name='youtube', description="Get detailed statistics for a YouTube channel")
    @app_commands.describe(channel_id="YouTube channel ID to get statistics for")
    async def youtube_stats(self, interaction: discord.Interaction, channel_id: str):
        """Get detailed statistics for a YouTube channel"""
        if not self.youtube_client:
            await interaction.response.send_message("❌ YouTube API is not configured.")
            return

        await interaction.response.defer(thinking=True)
        try:
            stats = self.get_channel_details(channel_id)
            latest_video = self.get_latest_video(channel_id)
            top_video = self.get_top_video(channel_id)
            if stats:
                embed = discord.Embed(
                    title=f"{stats['title']} - YouTube Channel Stats",
                    description=stats['description'][:200] + "..." if len(stats['description']) > 200 else stats[
                        'description'],
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url=stats["profile_pic"])
                if stats["banner_url"]:
                    embed.set_image(url=stats["banner_url"])
                embed.add_field(name="Subscribers", value=stats['subscribers'], inline=True)
                embed.add_field(name="Total Views", value=stats['views'], inline=True)
                embed.add_field(name="Total Videos", value=stats['videos'], inline=True)
                embed.add_field(name="Watch Hours (estimated)", value=stats['watch_hours'], inline=True)
                embed.add_field(name="Channel Created", value=stats['created_at'], inline=True)
                if latest_video:
                    embed.add_field(
                        name="Latest Video",
                        value=f"[{latest_video['title']}](https://www.youtube.com/watch?v={latest_video['video_id']})"
                    )
                if top_video:
                    embed.add_field(
                        name="Top Video",
                        value=f"[{top_video['title']}](https://www.youtube.com/watch?v={top_video['video_id']})"
                    )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("Channel not found!")
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {str(e)}")
            logger.error(f"Error in youtube_stats: {str(e)}")

    def get_channel_details(self, channel_id):
        """Get detailed information about a YouTube channel"""
        if not self.youtube_client:
            return None

        request = self.youtube_client.channels().list(
            part="snippet,statistics,brandingSettings,contentDetails",
            id=channel_id
        )
        response = request.execute()
        if "items" in response and len(response["items"]) > 0:
            channel = response["items"][0]
            statistics = channel["statistics"]
            snippet = channel["snippet"]
            branding = channel["brandingSettings"]
            return {
                "title": snippet["title"],
                "description": snippet.get("description", "No description"),
                "subscribers": statistics.get("subscriberCount", "N/A"),
                "views": statistics.get("viewCount", "N/A"),
                "videos": statistics.get("videoCount", "N/A"),
                "watch_hours": round(int(statistics.get("viewCount", 0)) / 1000, 2)*12,
                "created_at": snippet["publishedAt"],
                "profile_pic": snippet["thumbnails"]["high"]["url"],
                "banner_url": branding["image"].get("bannerExternalUrl", None) if "image" in branding else None,
            }
        else:
            return None

    def get_latest_video(self, channel_id):
        """Get the latest video from a YouTube channel"""
        if not self.youtube_client:
            return None

        request = self.youtube_client.search().list(
            part="snippet",
            channelId=channel_id,
            order="date",
            maxResults=1,
            type="video"
        )
        response = request.execute()

        if response["items"]:
            video = response["items"][0]
            return {
                "title": video["snippet"]["title"],
                "video_id": video["id"]["videoId"],
                "published_at": video["snippet"]["publishedAt"]
            }
        return None

    def get_top_video(self, channel_id):
        """Get the top video from a YouTube channel by view count"""
        if not self.youtube_client:
            return None

        request = self.youtube_client.search().list(
            part="snippet",
            channelId=channel_id,
            order="viewCount",
            maxResults=1,
            type="video"
        )
        response = request.execute()

        if response["items"]:
            video = response["items"][0]
            return {
                "title": video["snippet"]["title"],
                "video_id": video["id"]["videoId"]
            }
        return None

    @app_commands.command(name="getid", description="Fetches the YouTube channel ID from a given handle")
    @app_commands.describe(handle="YouTube channel handle (with or without @)")
    async def getid(self, interaction: discord.Interaction, handle: str):
        """Fetches the YouTube channel ID from a given handle"""
        if not self.youtube_client:
            await interaction.response.send_message("❌ YouTube API is not configured.")
            return

        await interaction.response.defer(thinking=True)
        try:
            handle = handle.lstrip('@')

            request = self.youtube_client.channels().list(
                part="id,snippet",
                forUsername=handle
            )
            response = request.execute()
            if not response.get("items"):
                search_request = self.youtube_client.search().list(
                    part="id,snippet",
                    q=handle,
                    type="channel",
                    maxResults=1
                )
                search_response = search_request.execute()
                if search_response.get("items"):
                    channel_id = search_response["items"][0]["id"]["channelId"]
                    channel_name = search_response["items"][0]["snippet"]["title"]
                else:
                    await interaction.followup.send(
                        f"No channel found for `{handle}`. The handle might be incorrect or the channel might not exist.")
                    return
            else:
                channel_id = response["items"][0]["id"]
                channel_name = response["items"][0]["snippet"]["title"]
            embed = discord.Embed(
                title="YouTube Channel ID",
                description=f"Channel ID for `{handle}`",
                color=discord.Color.red()
            )
            embed.add_field(name="Channel Name", value=channel_name, inline=False)
            embed.add_field(name="Channel ID", value=channel_id, inline=False)
            embed.add_field(name="Note", value="The searches may sometimes be inaccurate. Please verify the results.",
                            inline=False)

            # Create a view with a button to get channel stats
            view = discord.ui.View(timeout=180)  # 3 minute timeout
            button = discord.ui.Button(style=discord.ButtonStyle.green, label="Get Channel Stats")

            async def button_callback(button_interaction):
                if button_interaction.user.id != interaction.user.id:
                    await button_interaction.response.send_message("This button is not for you!", ephemeral=True)
                    return
                await button_interaction.response.defer(thinking=True)

                # Call the youtube_stats command with the channel ID
                try:
                    stats = self.get_channel_details(channel_id)
                    latest_video = self.get_latest_video(channel_id)
                    top_video = self.get_top_video(channel_id)

                    if stats:
                        desc = stats['description'][:200] + "..." if len(stats['description']) > 200 else stats['description']
                        stats_embed = discord.Embed(
                            title=f"{stats['title']} - YouTube Channel Stats",

                            description=f'```{desc}```'
                            ,
                            color=discord.Color.red()
                        )
                        stats_embed.set_thumbnail(url=stats["profile_pic"])
                        if stats["banner_url"]:
                            stats_embed.set_image(url=stats["banner_url"])
                        stats_embed.add_field(name="Subscribers", value=stats['subscribers'], inline=True)
                        stats_embed.add_field(name="Total Views", value=stats['views'], inline=True)
                        stats_embed.add_field(name="Total Videos", value=stats['videos'], inline=True)
                        stats_embed.add_field(name="Watch Hours (estimated)", value=stats['watch_hours'], inline=True)
                        stats_embed.add_field(name="Channel Created", value=stats['created_at'], inline=True)
                        if latest_video:
                            stats_embed.add_field(
                                name="Latest Video",
                                value=f"[{latest_video['title']}](https://www.youtube.com/watch?v={latest_video['video_id']})"
                            )
                        if top_video:
                            stats_embed.add_field(
                                name="Top Video",
                                value=f"[{top_video['title']}](https://www.youtube.com/watch?v={top_video['video_id']})"
                            )
                        await button_interaction.followup.send(embed=stats_embed)
                    else:
                        await button_interaction.followup.send("Channel not found!")
                except Exception as e:
                    await button_interaction.followup.send(f"An error occurred: {str(e)}")
                    logger.error(f"Error in button callback: {str(e)}")

            button.callback = button_callback
            view.add_item(button)

            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            error_message = f"An error occurred: {str(e)}"
            if "quota" in str(e).lower():
                error_message += "\nIt seems the YouTube API quota has been exceeded. Please try again later."
            await interaction.followup.send(error_message)
            logger.error(f"Error in getid: {str(e)}")

    @app_commands.command(name='thumb', description="Get the HD thumbnail of a YouTube video")
    @app_commands.describe(url="YouTube video URL to get thumbnail for")
    async def thumb(self, interaction: discord.Interaction, url: str):
        """Get the HD thumbnail of a YouTube video"""
        await interaction.response.defer(thinking=True)
        match = re.match(YOUTUBE_URL_PATTERN, url)
        if match:
            video_id = match.group(1)
            thumbnail_url = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'

            embed = discord.Embed(
                title='YouTube Thumbnail',
                description='Here is the HD thumbnail of the provided video:',
                color=discord.Color.blue()
            )
            embed.set_image(url=thumbnail_url)
            embed.set_footer(text='Requested by ' + interaction.user.name)

            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send('Please provide a valid YouTube link!')

    from discord import app_commands

    @app_commands.command(name='extract', description="Extract audio from a YouTube video")
    @app_commands.describe(
        url="YouTube video URL to extract audio from",
        quality="Audio quality: low (64kbps), medium (192kbps), or high (320kbps)"
    )
    async def extract(self, interaction: discord.Interaction, url: str, quality: str = 'medium'):
        """Extract audio from a YouTube video"""

        if not url:
            await interaction.response.send_message("Please provide a YouTube link.")
            return
        if "youtube.com" not in url and "youtu.be" not in url:
            await interaction.response.send_message("Please provide a valid YouTube link.")
            return

        await interaction.response.defer(thinking=True)
        output_filename = "downloaded_audio.mp3"

        quality_map = {
            "low": "64",
            "medium": "192",
            "high": "320"
        }
        preferred_quality = quality_map.get(quality.lower(), "192")

        try:
            await interaction.followup.send(f"Downloading audio at **{quality}** quality... This may take a moment.")
            ydl_opts = {
                'format': 'bestaudio',
                'outtmpl': 'downloaded_audio.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': preferred_quality
                }]
            }
            with YoutubeDL(ydl_opts) as ydl:
                await asyncio.to_thread(ydl.extract_info, url, download=True)

            if os.path.exists(output_filename):
                file_size = os.path.getsize(output_filename) / (1024 * 1024)  # MB
                if file_size > 8:
                    await interaction.followup.send(
                        f"⚠️ The audio file is too large ({file_size:.1f} MB). Discord has an 8MB file size limit.")
                    os.remove(output_filename)
                    return

                await interaction.followup.send("✅ Audio extracted successfully!", file=discord.File(output_filename))
                os.remove(output_filename)
            else:
                await interaction.followup.send("❌ Failed to extract audio. The file was not created.")
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred while extracting audio: {str(e)}")
            logger.error(f"Error in extract: {str(e)}")
            if os.path.exists(output_filename):
                os.remove(output_filename)

    @app_commands.command(name='download', description="Download a YouTube video in 720p (medium quality)")
    @app_commands.describe(url="YouTube video URL to download")
    async def download_video(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(thinking=True)
        try:
            self.video_ydl_opts = {
                'format': 'bestvideo[height=720]+bestaudio/best[height=720]/best[height=720]',
                'outtmpl': 'data/%(title)s.%(ext)s',
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'cookies': 'cookies.txt' if os.path.exists('cookies.txt') else None,
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferredformat': 'mp4'
                }]
            }

            os.makedirs('downloads', exist_ok=True)

            with YoutubeDL(self.ydl_opts) as ydl:
                info_dict = await asyncio.to_thread(ydl.extract_info, url, download=True)
                file_path = ydl.prepare_filename(info_dict).replace('.webm', '.mp4')  # handle container fallback
                if not os.path.exists(file_path):
                    raise Exception("Failed to download video.")

            file = discord.File(file_path, filename=os.path.basename(file_path))
            await interaction.followup.send(content=f"🎬 Downloaded: **{info_dict.get('title', 'Video')}**", file=file)

            # Optionally delete the file after sending
            os.remove(file_path)

        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            await interaction.followup.send(f"❌ Failed to download video. Error: {str(e)}")

    @app_commands.command(name='copyright_help', description="Show help for copyright checker commands")
    async def copyright_help(self, interaction: discord.Interaction):
        """Show help for copyright checker commands"""
        embed = discord.Embed(
            title="Copyright Checker Commands",
            description="Here are the available commands:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="/check",
            value="Check the copyright status of a song or YouTube video.",
            inline=False
        )
        embed.add_field(
            name="/fetch",
            value="Fetch detailed information about a YouTube video.",
            inline=False
        )
        embed.add_field(
            name="/thumb",
            value="Get the HD thumbnail of a YouTube video.",
            inline=False
        )
        embed.add_field(
            name="/youtube",
            value="Get detailed statistics for a YouTube channel.",
            inline=False
        )
        embed.add_field(
            name="/getid",
            value="Get the channel ID for a given YouTube handle (with or without '@').",
            inline=False
        )
        embed.add_field(
            name="/extract",
            value="Extract audio from a YouTube video and send it as an MP3 file.",
            inline=False
        )
        embed.add_field(
            name="/copyright_help",
            value="Show this help message.",
            inline=False
        )
        embed.set_footer(
            text="Learn About Copyright, types, symbols and much more. Click the Button Below To Start Learning!")

        view = discord.ui.View()
        button = discord.ui.Button(style=discord.ButtonStyle.green, label="Learn About Copyright",
                                   url="https://gappa-web.pages.dev/wiki/wiki")
        view.add_item(button)

        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(CopyrightChecker(bot))