import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from supabase_client import get_db
from bot import load_data

# Set up logging
logger = logging.getLogger('bot.polls')

# Initialize database client
db = get_db()


class PollView(discord.ui.View):
    def __init__(self, poll_id: str, options: List[str]):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        self.options = options

        # Add buttons for each option
        for i, option in enumerate(options):
            button = discord.ui.Button(
                label=option,
                custom_id=f"poll:{poll_id}:{i}",
                style=discord.ButtonStyle.primary
            )
            button.callback = self.vote_callback
            self.add_item(button)

    async def vote_callback(self, interaction: discord.Interaction):
        # Get the option index from the custom_id
        option_index = int(interaction.data["custom_id"].split(":")[-1])
        user_id = str(interaction.user.id)

        try:
            # Get the current poll data
            poll = await db.get_poll(self.poll_id)
            if not poll:
                await interaction.response.send_message("This poll no longer exists!", ephemeral=True)
                return

            # Check if poll is closed
            if poll.get("status") == "closed" or poll.get("closed", False):
                await interaction.response.send_message("This poll is closed!", ephemeral=True)
                return

            # Add the vote using Supabase client
            success = await db.add_vote(self.poll_id, option_index, user_id)
            if not success:
                await interaction.response.send_message("Failed to register your vote. Please try again.", ephemeral=True)
                return

            # Update the poll message
            await self.update_poll_message(interaction)
            
            # Send confirmation
            await interaction.response.send_message(
                f"You voted for '{self.options[option_index]}'!", 
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error processing vote: {e}")
            await interaction.response.send_message(
                "An error occurred while processing your vote. Please try again.",
                ephemeral=True
            )

    async def update_poll_message(self, interaction: discord.Interaction):
        """Update the poll message with current vote counts and stats."""
        try:
            # Get the latest poll data from Supabase
            poll = await db.get_poll(self.poll_id)
            if not poll:
                logger.warning(f"Poll {self.poll_id} not found when updating message")
                return

            # Count total votes
            votes = poll.get("votes", {})
            total_votes = sum(len(voters) for voters in votes.values())

            # Create embed with gradient color based on time remaining
            time_color = discord.Color.blue()
            if poll.get("end_time"):
                end_time = datetime.fromisoformat(poll["end_time"]) if isinstance(poll["end_time"], str) else poll["end_time"]
                time_left = (end_time - datetime.now()).total_seconds()
                # Gradient from blue to red as time runs out
                if time_left < 3600:  # < 1 hour
                    time_color = discord.Color.red()
                elif time_left < 86400:  # < 1 day
                    time_color = discord.Color.orange()

            # Create embed
            embed = discord.Embed(
                title=f"📊 {poll['question']}",
                color=time_color
            )
            
            # Add total votes and time remaining to description
            description = f"🗳️ **Total Votes:** {total_votes}\n"
            
            if poll.get("end_time"):
                end_time = datetime.fromisoformat(poll["end_time"]) if isinstance(poll["end_time"], str) else poll["end_time"]
                now = datetime.now()
                if end_time > now:
                    time_left = end_time - now
                    hours, remainder = divmod(time_left.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    time_str = f"{time_left.days}d {hours}h {minutes}m" if time_left.days > 0 else f"{hours}h {minutes}m"
                    description += f"⏳ **Time Remaining:** {time_str}\n"
                else:
                    description += "⏰ **Poll has ended**\n"
            
            embed.description = description

            # Define colors for options based on position
            option_colors = [
                0x3498db,  # Blue
                0x2ecc71,  # Green
                0xe74c3c,  # Red
                0xf1c40f,  # Yellow
                0x9b59b6,  # Purple
                0x1abc9c   # Turquoise
            ]

            # Add fields for each option
            for i, option in enumerate(self.options):
                option_votes = votes.get(str(i), [])
                votes_count = len(option_votes) if isinstance(option_votes, list) else 0
                percentage = (votes_count / total_votes * 100) if total_votes > 0 else 0

                # Create progress bar with emoji
                filled_length = int(10 * percentage / 100)
                bar = "🟦" * filled_length + "⬜" * (10 - filled_length)
                
                # Get color for this option
                color = option_colors[i % len(option_colors)]
                
                # Add field with emoji and formatting
                embed.add_field(
                    name=f"{i+1}. {option}",
                    value=(
                        f"{bar} **{percentage:.1f}%**\n"
                        f"👥 **{votes_count}** vote{'s' if votes_count != 1 else ''} • "
                        f"🎯 {percentage:.1f}% of total"
                    ),
                    inline=False
                )

            # Add end time if set
            if poll.get("end_time"):
                end_time = datetime.fromisoformat(poll["end_time"]) if isinstance(poll["end_time"], str) else poll["end_time"]
                now = datetime.now()

                if end_time > now:
                    time_left = end_time - now
                    hours, remainder = divmod(time_left.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    time_str = f"{time_left.days}d {hours}h {minutes}m {seconds}s"
                    embed.set_footer(text=f"Poll ends in: {time_str}")
                else:
                    embed.set_footer(text="Poll has ended")

            # Get the message and update it
            channel = interaction.guild.get_channel(int(poll["channel_id"]))
            if not channel:
                logger.warning(f"Channel {poll['channel_id']} not found")
                return
                
            message = await channel.fetch_message(int(poll["message_id"]))
            if message:
                await message.edit(embed=embed)

        except Exception as e:
            logger.error(f"Error updating poll message: {e}")
            # Try to send an error message if we can't update the poll
            try:
                await interaction.response.send_message(
                    "Failed to update the poll display. The vote was recorded.",
                    ephemeral=True
                )
            except:
                pass  # If we can't send the message, just log the error


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_polls = {}
        self.poll_task = None
        self._db_initialized = False

    async def cog_load(self):
        """Initialize the cog and start background tasks."""
        await self.initialize_db()
        self.poll_task = self.bot.loop.create_task(self.check_polls())

    async def cog_unload(self):
        """Clean up tasks when the cog is unloaded."""
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass

    async def initialize_db(self):
        """Initialize database connection and verify required tables exist."""
        if self._db_initialized:
            return
            
        try:
            # Test the connection by fetching active polls
            await db.get_active_polls()
            self._db_initialized = True
            logger.info("Database connection for polls initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")
            raise

    async def check_polls(self):
        """Background task to check for and close expired polls."""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                if not self._db_initialized:
                    await self.initialize_db()
                    
                # Get all active polls that should be closed
                now = datetime.utcnow().isoformat()
                active_polls = await db.get_active_polls()
                
                for poll in active_polls:
                    if poll.get("end_time") and poll["end_time"] <= now:
                        try:
                            # Close the poll
                            success = await db.close_poll(str(poll["id"]))
                            if success:
                                logger.info(f"Closed expired poll: {poll['id']}")
                                # Send results
                                await self.send_poll_results(str(poll["id"]))
                            else:
                                logger.error(f"Failed to close expired poll: {poll['id']}")
                        except Exception as e:
                            logger.error(f"Error processing poll {poll.get('id', 'unknown')}: {e}")
                            
            except Exception as e:
                logger.error(f"Error in check_polls task: {e}")
                # If there's a database connection issue, mark as uninitialized to retry
                if "connection" in str(e).lower() or "database" in str(e).lower():
                    self._db_initialized = False
            
            # Check every 30 seconds
            await asyncio.sleep(30)

    async def send_poll_results(self, poll_id: str):
        """Send the final results of a poll to the channel."""
        try:
            # Get poll data from Supabase
            poll = await db.get_poll(poll_id)
            if not poll:
                logger.warning(f"Poll {poll_id} not found when sending results")
                return

            # Get the channel
            try:
                channel_id = int(poll["channel_id"])
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    logger.error(f"Channel {channel_id} not found for poll {poll_id}")
                    return
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid channel ID in poll {poll_id}: {e}")
                return

            # Count total votes
            votes = poll.get("votes", {})
            total_votes = sum(len(voters) for voters in votes.values() if isinstance(voters, list))

            # Create results embed with gold color for completed polls
            embed = discord.Embed(
                title=f"🏆 Poll Results: {poll['question']}",
                color=0xf1c40f  # Gold color
            )
            
            # Add total votes and duration to description
            description = f"🗳️ **Total Votes:** {total_votes}\n"
            
            # Calculate duration if we have both timestamps
            if "created_at" in poll and "end_time" in poll:
                try:
                    start = datetime.fromisoformat(poll["created_at"]) if isinstance(poll["created_at"], str) else poll["created_at"]
                    end = datetime.fromisoformat(poll["end_time"]) if isinstance(poll["end_time"], str) else poll["end_time"]
                    duration = end - start
                    hours, remainder = divmod(duration.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    duration_str = f"{duration.days}d {hours}h {minutes}m" if duration.days > 0 else f"{hours}h {minutes}m"
                    description += f"⏱️ **Duration:** {duration_str}\n"
                except Exception as e:
                    logger.error(f"Error calculating poll duration for {poll_id}: {e}")
            
            embed.description = description

            # Define medal emojis for top 3 options
            medals = ["🥇", "🥈", "🥉"]
            
            # Get options and their vote counts
            options = poll.get("options", [])
            sorted_options = []
            
            # Create list of (option_index, vote_count) tuples
            for i in range(len(options)):
                option_votes = votes.get(str(i), [])
                vote_count = len(option_votes) if isinstance(option_votes, list) else 0
                sorted_options.append((i, vote_count))
            
            # Sort by vote count (descending)
            sorted_options.sort(key=lambda x: x[1], reverse=True)
            
            # Add fields for each option in order of votes
            for rank, (i, votes_count) in enumerate(sorted_options):
                if i >= len(options):
                    continue
                    
                option = options[i]
                percentage = (votes_count / total_votes * 100) if total_votes > 0 else 0
                
                # Create progress bar with emoji
                filled_length = int(10 * percentage / 100)
                bar = "🟨" * filled_length + "⬜" * (10 - filled_length)
                
                # Add medal for top 3
                medal = f"{medals[rank]} " if rank < 3 else ""
                
                # Add field with ranking and formatting
                embed.add_field(
                    name=f"{medal}{option}",
                    value=(
                        f"{bar} **{percentage:.1f}%**\n"
                        f"👥 **{votes_count}** vote{'s' if votes_count != 1 else ''} • "
                        f"🎯 {percentage:.1f}% of total"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"Poll ID: {poll_id}")

            try:
                # Send the results to the channel
                await channel.send(embed=embed)
                
                # Update the original poll message to mark it as closed
                try:
                    message_id = int(poll.get("message_id"))
                    message = await channel.fetch_message(message_id)
                    
                    if message.embeds:
                        # Create updated embed
                        original_embed = message.embeds[0]
                        original_embed.title = f"[CLOSED] {original_embed.title}"
                        original_embed.set_footer(text="This poll has ended")
                        
                        # Remove the view (voting buttons)
                        await message.edit(embed=original_embed, view=None)
                except Exception as e:
                    logger.warning(f"Could not update original poll message {poll_id}: {e}")
                    
            except discord.Forbidden:
                logger.error(f"Missing permissions to send messages in channel {channel.id}")
            except discord.HTTPException as e:
                logger.error(f"Failed to send poll results for {poll_id}: {e}")

        except Exception as e:
            logger.error(f"Unexpected error in send_poll_results for {poll_id}: {e}")
            # Try to send a basic error message if possible
            try:
                await channel.send("❌ An error occurred while processing the poll results.")
            except:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent views for active polls
        active_polls = await db.get_active_polls()
        for poll in active_polls:
            poll_id = poll['id']
            if not poll.get("closed", False):
                view = PollView(poll_id, poll["options"])
                self.bot.add_view(view)

    def parse_duration(self, duration_str: str) -> int:
        """Parse duration string like '2h', '30min', '10s', '1d' into minutes"""
        if not duration_str:
            return None
            
        # Remove any whitespace and convert to lowercase
        duration_str = duration_str.lower().replace(' ', '')
        
        # Define patterns for different time units
        patterns = {
            'd': 1440,  # days to minutes
            'h': 60,    # hours to minutes
            'm': 1,     # minutes
            's': 1/60   # seconds to minutes
        }
        
        # Try to match the pattern
        match = re.match(r'^(\d+)([dhms])', duration_str)
        if not match:
            raise ValueError("Invalid duration format. Use formats like '2h', '30min', '10s', or '1d'")
            
        value = int(match.group(1))
        unit = match.group(2)
        
        # Convert to minutes
        return int(value * patterns[unit])

    async def send_poll_results(self, poll_id: str):
        """Send the final results of a poll to the channel."""
        try:
            # Get poll data from Supabase
            poll = await db.get_poll(poll_id)
            if not poll:
                logger.warning(f"Poll {poll_id} not found when sending results")
                return

            # Get the channel
            try:
                channel_id = int(poll["channel_id"])
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    logger.error(f"Channel {channel_id} not found for poll {poll_id}")
                    return
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid channel ID in poll {poll_id}: {e}")
                return

            # Count total votes
            votes = poll.get("votes", {})
            total_votes = sum(len(voters) for voters in votes.values() if isinstance(voters, list))

            # Create results embed with gold color for completed polls
            embed = discord.Embed(
                title=f"🏆 Poll Results: {poll['question']}",
                color=0xf1c40f  # Gold color
            )
            
            # Add total votes and duration to description
            description = f"🗳️ **Total Votes:** {total_votes}\n"
            
            # Calculate duration if we have both timestamps
            if "created_at" in poll and "end_time" in poll:
                try:
                    start = datetime.fromisoformat(poll["created_at"]) if isinstance(poll["created_at"], str) else poll["created_at"]
                    end = datetime.fromisoformat(poll["end_time"]) if isinstance(poll["end_time"], str) else poll["end_time"]
                    duration = end - start
                    hours, remainder = divmod(duration.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    duration_str = f"{duration.days}d {hours}h {minutes}m" if duration.days > 0 else f"{hours}h {minutes}m"
                    description += f"⏱️ **Duration:** {duration_str}\n"
                except Exception as e:
                    logger.error(f"Error calculating poll duration for {poll_id}: {e}")
            
            embed.description = description

            # Define medal emojis for top 3 options
            medals = ["🥇", "🥈", "🥉"]
            
            # Get options and their vote counts
            options = poll.get("options", [])
            sorted_options = []
            
            # Create list of (option_index, vote_count) tuples
            for i in range(len(options)):
                option_votes = votes.get(str(i), [])
                vote_count = len(option_votes) if isinstance(option_votes, list) else 0
                sorted_options.append((i, vote_count))
            
            # Sort by vote count (descending)
            sorted_options.sort(key=lambda x: x[1], reverse=True)
            
            # Add fields for each option in order of votes
            for rank, (i, votes_count) in enumerate(sorted_options):
                if i >= len(options):
                    continue
                    
                option = options[i]
                percentage = (votes_count / total_votes * 100) if total_votes > 0 else 0
                
                # Create progress bar with emoji
                filled_length = int(10 * percentage / 100)
                bar = "🟨" * filled_length + "⬜" * (10 - filled_length)
                
                # Add medal for top 3
                medal = f"{medals[rank]} " if rank < 3 else ""
                
                # Add field with ranking and formatting
                embed.add_field(
                    name=f"{medal}{option}",
                    value=(
                        f"{bar} **{percentage:.1f}%**\n"
                        f"👥 **{votes_count}** vote{'s' if votes_count != 1 else ''} • "
                        f"🎯 {percentage:.1f}% of total"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"Poll ID: {poll_id}")

            try:
                # Send the results to the channel
                await channel.send(embed=embed)
                
                # Update the original poll message to mark it as closed
                try:
                    message_id = int(poll.get("message_id"))
                    message = await channel.fetch_message(message_id)
                    
                    if message.embeds:
                        # Create updated embed
                        original_embed = message.embeds[0]
                        original_embed.title = f"[CLOSED] {original_embed.title}"
                        original_embed.set_footer(text="This poll has ended")
                        
                        # Remove the view (voting buttons)
                        await message.edit(embed=original_embed, view=None)
                except Exception as e:
                    logger.warning(f"Could not update original poll message {poll_id}: {e}")
                    
            except discord.Forbidden:
                logger.error(f"Missing permissions to send messages in channel {channel.id}")
            except discord.HTTPException as e:
                logger.error(f"Failed to send poll results for {poll_id}: {e}")

        except Exception as e:
            logger.error(f"Unexpected error in send_poll_results for {poll_id}: {e}")
            # Try to send a basic error message if possible
            try:
                await channel.send("❌ An error occurred while processing the poll results.")
            except:
                pass
    @app_commands.command(name="poll", description="Create a poll")
    @app_commands.describe(
        question="The poll question",
        option1="First option",
        option2="Second option",
        option3="Third option (optional)",
        option4="Fourth option (optional)",
        option5="Fifth option (optional)",
        duration="Poll duration (e.g., '2h', '30min', '10s', '1d') (optional, default: no time limit)"
    )
    async def create_poll(
            self,
            interaction: discord.Interaction,
            question: str,
            option1: str,
            option2: str,
            option3: str = None,
            option4: str = None,
            option5: str = None,
            duration: str = None
    ):
        """Create a new poll with the given options."""
        # Ensure database is initialized
        if not self._db_initialized:
            try:
                await self.initialize_db()
            except Exception as e:
                logger.error(f"Database initialization failed: {e}")
                await interaction.response.send_message(
                    "❌ Failed to initialize database connection. Please try again later.",
                    ephemeral=True
                )
                return
    
        # Parse duration if provided
        end_time = None
        if duration:
            try:
                duration_minutes = self.parse_duration(duration)
                end_time = (datetime.utcnow() + timedelta(minutes=duration_minutes)).isoformat()
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return
    
        # Collect options
        options = [option1, option2]
        if option3:
            options.append(option3)
        if option4:
            options.append(option4)
        if option5:
            options.append(option5)

        # Create initial embed with anonymous author
        embed = discord.Embed(
            title=f"📊 {question}",
            description="Cast your vote using the buttons below! 🗳️\n\n**Options:",
            color=discord.Color.blue()
        )
        
        # Add options as fields for better mobile display
        for i, option in enumerate(options, 1):
            embed.add_field(
                name=f"{i}. {option}",
                value="⬜ No votes yet",
                inline=False
            )
            
        # Add footer with duration if applicable
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            now = datetime.utcnow()
            time_left = end_dt - now
            
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            days, hours = divmod(hours, 24)
            minutes = remainder // 60
            
            duration_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"
            embed.set_footer(text=f"⏰ Poll ends in {duration_str}")
        else:
            embed.set_footer(text="No time limit")

        # Get role ID for poll updates from config (if needed)
        # Note: Config handling will need to be updated to use Supabase
        poll_updates_role_id = None  # This will be updated when config is moved to Supabase
        
        # Prepare the message content with role mention if configured
        content = None
        if poll_updates_role_id and str(poll_updates_role_id).isdigit():
            content = f'<@&{poll_updates_role_id}> New poll created!'
        
        # Send the poll message directly
        try:
            # Create the poll view first
            view = PollView("temp", options)  # We'll update this after creating the poll
            
            # Send the poll directly to the channel
            await interaction.response.send_message(content=content, embed=embed, view=view)
            
            # Get the message that was sent
            message = await interaction.channel.fetch_message(interaction.channel.last_message_id)
            
            # Store poll data in Supabase
            poll_data = {
                "question": question,
                "options": options,
                "votes": {},
                "message_id": str(message.id),
                "channel_id": str(interaction.channel.id),
                "user_id": str(interaction.user.id),
                "status": "active",
                "is_anonymous": True,
                "created_at": datetime.utcnow().isoformat(),
            }
            
            if end_time:
                poll_data["end_time"] = end_time
            
            # Create the poll in the database
            created_poll = await db.create_poll(poll_data)
            if not created_poll or "id" not in created_poll:
                raise Exception("Failed to create poll in database")
            
            # Update the view with the correct poll ID
            view = PollView(str(created_poll["id"]), options)
            await message.edit(view=view)
                
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to send messages in that channel.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error creating poll: {e}")
            try:
                await interaction.response.send_message(
                    "❌ An error occurred while creating the poll. Please try again.",
                    ephemeral=True
                )
            except:
                pass

    @app_commands.command(name="endpoll", description="End a poll")
    @app_commands.describe(
        message_id="The message ID of the poll to end"
    )
    async def end_poll(self, interaction: discord.Interaction, message_id: str):
        """End a poll before its scheduled end time."""
        # Check if user has permission
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ You don't have permission to end polls!",
                ephemeral=True
            )
            return

        # Ensure database is initialized
        if not self._db_initialized:
            try:
                await self.initialize_db()
            except Exception as e:
                logger.error(f"Database initialization failed: {e}")
                await interaction.response.send_message(
                    "❌ Failed to initialize database connection. Please try again later.",
                    ephemeral=True
                )
                return

        # Find the poll in the database
        try:
            poll = await db.get_poll_by_message(message_id)
            if not poll:
                await interaction.response.send_message(
                    "❌ Poll not found! Make sure you entered the correct message ID.",
                    ephemeral=True
                )
                return

            # Check if poll is already closed
            if poll.get("status") == "closed":
                await interaction.response.send_message(
                    "❌ This poll is already closed!",
                    ephemeral=True
                )
                return

            # Close the poll in the database
            await db.close_poll(poll["id"])

            # Send results
            await self.send_poll_results(poll["id"])

            await interaction.response.send_message(
                "✅ Poll ended successfully!",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error ending poll: {e}")
            try:
                await interaction.response.send_message(
                    "❌ An error occurred while ending the poll. Please try again.",
                    ephemeral=True
                )
            except:
                pass


async def setup(bot):
    await bot.add_cog(Polls(bot))