import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
import re
from datetime import datetime, timedelta
from bot import load_data


# Load data
def load_data(file):
    with open(f'data/{file}.json', 'r') as f:
        return json.load(f)


def save_data(file, data):
    with open(f'data/{file}.json', 'w') as f:
        json.dump(data, f, indent=4)


class PollView(discord.ui.View):
    def __init__(self, poll_id, options):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        self.options = options

        # Add buttons for each option
        for i, option in enumerate(options):
            # Create a button for each option
            button = discord.ui.Button(
                label=option,
                custom_id=f"poll:{poll_id}:{i}",
                style=discord.ButtonStyle.primary
            )
            button.callback = self.vote_callback
            self.add_item(button)

    async def vote_callback(self, interaction):
        # Get the option index from the custom_id
        option_index = int(interaction.data["custom_id"].split(":")[-1])

        # Load poll data
        polls = load_data('polls')
        poll = polls.get(str(self.poll_id))

        if not poll:
            await interaction.response.send_message("This poll no longer exists!", ephemeral=True)
            return

        # Check if poll is closed
        if poll.get("closed", False):
            await interaction.response.send_message("This poll is closed!", ephemeral=True)
            return

        # Check if user has already voted
        user_id = str(interaction.user.id)

        # Remove previous vote if exists
        for votes in poll["votes"].values():
            if user_id in votes:
                votes.remove(user_id)

        # Add new vote
        if str(option_index) not in poll["votes"]:
            poll["votes"][str(option_index)] = []

        poll["votes"][str(option_index)].append(user_id)

        # Save poll data
        save_data('polls', polls)

        # Update poll message
        await self.update_poll_message(interaction)

        # Send confirmation
        await interaction.response.send_message(f"You voted for '{self.options[option_index]}'!", ephemeral=True)

    async def update_poll_message(self, interaction):
        # Load poll data
        polls = load_data('polls')
        poll = polls.get(str(self.poll_id))

        if not poll:
            return

        # Count votes
        total_votes = sum(len(votes) for votes in poll["votes"].values())

        # Create embed with gradient color based on time remaining
        time_color = discord.Color.blue()
        if "end_time" in poll:
            end_time = datetime.fromisoformat(poll["end_time"])
            time_left = (end_time - datetime.now()).total_seconds()
            # Gradient from blue to red as time runs out
            if time_left < 3600:  # < 1 hour
                time_color = discord.Color.red()
            elif time_left < 86400:  # < 1 day
                time_color = discord.Color.orange()

        embed = discord.Embed(
            title=f"📊 {poll['question']}",
            color=time_color
        )
        
        # Add total votes and time remaining to description
        description = f"🗳️ **Total Votes:** {total_votes}\n"
        
        if "end_time" in poll:
            end_time = datetime.fromisoformat(poll["end_time"])
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
            votes = len(poll["votes"].get(str(i), []))
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0

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
                    f"👥 **{votes}** vote{'s' if votes != 1 else ''} • "
                    f"🎯 {percentage:.1f}% of total"
                ),
                inline=False
            )

        # Add end time if set
        if "end_time" in poll:
            end_time = datetime.fromisoformat(poll["end_time"])
            now = datetime.now()

            if end_time > now:
                time_left = end_time - now
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                time_str = f"{time_left.days}d {hours}h {minutes}m {seconds}s"
                embed.set_footer(text=f"Poll ends in: {time_str}")
            else:
                embed.set_footer(text="Poll has ended")

        # Get the message
        try:
            channel = interaction.guild.get_channel(poll["channel_id"])
            message = await channel.fetch_message(poll["message_id"])
            await message.edit(embed=embed)
        except:
            pass  # Message not found or can't be edited


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_polls = {}

        # Start poll end checking task
        self.poll_task = self.bot.loop.create_task(self.check_polls())

    def cog_unload(self):
        # Cancel the task when the cog is unloaded
        self.poll_task.cancel()

    async def check_polls(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                polls = load_data('polls')
                now = datetime.now().isoformat()

                for poll_id, poll in list(polls.items()):
                    if "end_time" in poll and poll["end_time"] <= now and not poll.get("closed", False):
                        # Close the poll
                        poll["closed"] = True
                        save_data('polls', polls)

                        # Send results
                        await self.send_poll_results(poll_id)
            except Exception as e:
                print(f"Error checking polls: {e}")

            # Check every minute
            await asyncio.sleep(60)

    async def send_poll_results(self, poll_id):
        polls = load_data('polls')
        poll = polls.get(str(poll_id))

        if not poll:
            return

        try:
            # Get the channel and message
            channel = self.bot.get_channel(poll["channel_id"])
            if not channel:
                return

            # Count votes
            total_votes = sum(len(votes) for votes in poll["votes"].values())

            # Create results embed with gold color for completed polls
            embed = discord.Embed(
                title=f"🏆 Poll Results: {poll['question']}",
                color=0xf1c40f  # Gold color
            )
            
            # Add total votes and duration to description
            description = f"🗳️ **Total Votes:** {total_votes}\n"
            if "created_at" in poll and "end_time" in poll:
                start = datetime.fromisoformat(poll["created_at"])
                end = datetime.fromisoformat(poll["end_time"])
                duration = end - start
                hours, remainder = divmod(duration.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                duration_str = f"{duration.days}d {hours}h {minutes}m" if duration.days > 0 else f"{hours}h {minutes}m"
                description += f"⏱️ **Duration:** {duration_str}\n"
            
            embed.description = description

            # Define medal emojis for top 3 options
            medals = ["🥇", "🥈", "🥉"]
            
            # Get options sorted by vote count (descending)
            options = poll["options"]
            sorted_options = sorted(
                [(i, len(poll["votes"].get(str(i), []))) for i in range(len(options))],
                key=lambda x: x[1],
                reverse=True
            )
            
            # Add fields for each option in order of votes
            for rank, (i, votes) in enumerate(sorted_options):
                option = options[i]
                percentage = (votes / total_votes * 100) if total_votes > 0 else 0
                
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
                        f"👥 **{votes}** vote{'s' if votes != 1 else ''} • "
                        f"🎯 {percentage:.1f}% of total"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"Poll ID: {poll_id}")

            # Send results
            await channel.send(embed=embed)

            # Update original message
            try:
                message = await channel.fetch_message(poll["message_id"])

                # Create updated embed
                original_embed = message.embeds[0]
                original_embed.title = f"[CLOSED] {original_embed.title}"
                original_embed.set_footer(text="This poll has ended")

                await message.edit(embed=original_embed, view=None)
            except:
                pass  # Message not found or can't be edited

        except Exception as e:
            print(f"Error sending poll results: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent views for active polls
        polls = load_data('polls')

        for poll_id, poll in polls.items():
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
            interaction,
            question: str,
            option1: str,
            option2: str,
            option3: str = None,
            option4: str = None,
            option5: str = None,
            duration: str = None
    ):
        # Parse duration if provided
        duration_minutes = None
        if duration:
            try:
                duration_minutes = self.parse_duration(duration)
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

        # Create a new poll
        polls = load_data('polls')

        # Generate a new poll ID
        poll_id = str(len(polls) + 1)

        # Calculate end time if duration is provided
        end_time = None
        if duration_minutes:
            end_time = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()

        # Create poll view
        view = PollView(poll_id, options)

        # Create initial embed
        embed = discord.Embed(
            title=question,
            description=f"React with the buttons below to vote!",
            color=discord.Color.blue()
        )

        # Add options to embed
        for i, option in enumerate(options):
            embed.add_field(name=f"Option {i + 1}", value=option, inline=False)

        # Add end time if set
        if end_time:
            # Format duration for display
            days = duration_minutes // 1440
            hours = (duration_minutes % 1440) // 60
            minutes = duration_minutes % 60
            
            duration_str = []
            if days > 0:
                duration_str.append(f"{days}d")
            if hours > 0:
                duration_str.append(f"{hours}h")
            if minutes > 0 or not duration_str:  # Show at least minutes if no other units
                duration_str.append(f"{minutes}m")
                
            embed.set_footer(text=f"Poll ends in: {' '.join(duration_str)}")

        # Get poll updates role from config
        config = load_data('config')
        poll_updates_role_id = config.get('polls_role', '')
        
        # Prepare the message content with role mention if configured
        content = None
        if poll_updates_role_id and poll_updates_role_id.isdigit():
            content = f'<@&{poll_updates_role_id}> New poll created!'
        
        # Send poll message with role mention
        await interaction.response.send_message(content=content, embed=embed, view=view)
        message = await interaction.original_response()

        # Save poll data
        polls[poll_id] = {
            "question": question,
            "options": options,
            "votes": {},
            "channel_id": interaction.channel.id,
            "message_id": message.id,
            "created_by": interaction.user.id,
            "created_at": datetime.now().isoformat()
        }

        if end_time:
            polls[poll_id]["end_time"] = end_time

        save_data('polls', polls)

    @app_commands.command(name="endpoll", description="End a poll early")
    @app_commands.describe(message_id="The ID of the poll message")
    async def end_poll(self, interaction, message_id: str):
        # Check if user has permission
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You don't have permission to end polls!", ephemeral=True)
            return

        # Find the poll
        polls = load_data('polls')
        poll_id = None

        for pid, poll in polls.items():
            if str(poll["message_id"]) == message_id:
                poll_id = pid
                break

        if not poll_id:
            await interaction.response.send_message("Poll not found! Make sure you entered the correct message ID.",
                                                    ephemeral=True)
            return

        # Check if poll is already closed
        if polls[poll_id].get("closed", False):
            await interaction.response.send_message("This poll is already closed!", ephemeral=True)
            return

        # Close the poll
        polls[poll_id]["closed"] = True
        polls[poll_id]["end_time"] = datetime.now().isoformat()
        save_data('polls', polls)

        # Send results
        await self.send_poll_results(poll_id)

        await interaction.response.send_message("Poll ended successfully!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Polls(bot))