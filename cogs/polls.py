import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import asyncio
import re
from datetime import datetime, timedelta
from bot import load_data

class ReactionPollView(discord.ui.View):
    def __init__(self, poll_id: str, options: list):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        self.options = options
        self.emojis = ["👍", "👎"] if len(options) == 2 else ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][:len(options)]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

class ReactionPollManager:
    def __init__(self, bot):
        self.bot = bot
        self.polls = {}
        self.load_polls()

    def load_polls(self):
        try:
            with open('data/polls.json', 'r') as f:
                self.polls = json.load(f)
        except FileNotFoundError:
            self.polls = {}

    def save_polls(self):
        with open('data/polls.json', 'w') as f:
            json.dump(self.polls, f, indent=2)

    def create_poll(self, question: str, options: list, duration_minutes: int, channel_id: int, author_id: int) -> str:
        poll_id = str(len(self.polls) + 1)
        end_time = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()
        
        self.polls[poll_id] = {
            "question": question,
            "options": options,
            "votes": {str(i): [] for i in range(len(options))},
            "channel_id": channel_id,
            "message_id": None,
            "author_id": author_id,
            "created_at": datetime.now().isoformat(),
            "end_time": end_time,
            "closed": False,
            "type": "reaction"
        }
        self.save_polls()
        return poll_id

    def get_poll(self, poll_id: str) -> dict:
        return self.polls.get(poll_id)

    def add_vote(self, poll_id: str, option_index: int, user_id: int):
        if poll_id not in self.polls or self.polls[poll_id]["closed"]:
            return False
        
        user_str = str(user_id)
        
        for option_votes in self.polls[poll_id]["votes"].values():
            if user_str in option_votes:
                option_votes.remove(user_str)
        
        self.polls[poll_id]["votes"][str(option_index)].append(user_str)
        self.save_polls()
        return True

    def close_poll(self, poll_id: str):
        if poll_id in self.polls:
            self.polls[poll_id]["closed"] = True
            self.save_polls()

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll_manager = ReactionPollManager(bot)
        self.check_polls.start()

    def cog_unload(self):
        self.check_polls.cancel()

    @tasks.loop(minutes=1)
    async def check_polls(self):
        await self.bot.wait_until_ready()
        
        now = datetime.now()
        for poll_id, poll in list(self.poll_manager.polls.items()):
            if not poll.get("closed", False) and poll.get("end_time"):
                end_time = datetime.fromisoformat(poll["end_time"])
                if now >= end_time:
                    await self.end_poll(poll_id)

    async def end_poll(self, poll_id: str):
        poll = self.poll_manager.get_poll(poll_id)
        if not poll or poll["closed"]:
            return

        self.poll_manager.close_poll(poll_id)
        
        try:
            channel = self.bot.get_channel(poll["channel_id"])
            if not channel:
                return

            message = await channel.fetch_message(poll["message_id"])
            if not message:
                return

            await self.send_poll_results(poll_id, message, poll)
            
            await message.clear_reactions()
            
            embed = discord.Embed(
                title=f"🏆 Poll Ended: {poll['question']}",
                description="This poll has ended. Results are shown below.",
                color=discord.Color.gold()
            )
            await message.edit(embed=embed)

        except Exception as e:
            print(f"Error ending poll {poll_id}: {e}")

    async def send_poll_results(self, poll_id: str, message: discord.Message, poll: dict):
        total_votes = sum(len(votes) for votes in poll["votes"].values())
        
        embed = discord.Embed(
            title=f"🏆 Poll Results: {poll['question']}",
            color=discord.Color.gold()
        )
        
        embed.add_field(name="📊 Total Votes", value=str(total_votes), inline=True)
        
        duration = datetime.fromisoformat(poll["end_time"]) - datetime.fromisoformat(poll["created_at"])
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        duration_str = f"{duration.days}d {hours}h {minutes}m" if duration.days > 0 else f"{hours}h {minutes}m"
        embed.add_field(name="⏱️ Duration", value=duration_str, inline=True)
        
        medals = ["🥇", "🥈", "🥉"]
        sorted_options = sorted(
            [(i, len(poll["votes"][str(i)])) for i in range(len(poll["options"]))],
            key=lambda x: x[1],
            reverse=True
        )
        
        for rank, (option_index, votes) in enumerate(sorted_options):
            option = poll["options"][option_index]
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0
            
            filled_length = int(20 * percentage / 100)
            bar = "█" * filled_length + "░" * (20 - filled_length)
            
            medal = medals[rank] if rank < 3 else "📊"
            
            embed.add_field(
                name=f"{medal} {option}",
                value=f"{bar} **{percentage:.1f}%**\n👥 **{votes}** vote{'s' if votes != 1 else ''}",
                inline=False
            )
        
        embed.set_footer(text=f"Poll ID: {poll_id}")
        await message.channel.send(embed=embed)

    def parse_duration(self, duration_str: str) -> int:
        duration_str = duration_str.lower().replace(' ', '')
        
        patterns = {
            'd': 1440,
            'h': 60,
            'm': 1,
            's': 1/60
        }
        
        match = re.match(r'^(\d+)([dhms])', duration_str)
        if not match:
            raise ValueError("Invalid duration format. Use formats like '2h', '30min', '10s', or '1d'")
            
        value = int(match.group(1))
        unit = match.group(2)
        
        return int(value * patterns[unit])

    @app_commands.command(name="poll", description="Create a reaction-based poll")
    @app_commands.describe(
        question="The poll question",
        option1="First option",
        option2="Second option",
        duration="Poll duration (e.g., '2h', '30min', '10s', '1d')",
        option3="Third option (optional)",
        option4="Fourth option (optional)",
        option5="Fifth option (optional)"
    )
    async def create_poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        duration: str,
        option3: str = None,
        option4: str = None,
        option5: str = None
    ):
        try:
            duration_minutes = self.parse_duration(duration)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        options = [option1, option2]
        if option3:
            options.append(option3)
        if option4:
            options.append(option4)
        if option5:
            options.append(option5)

        if len(options) > 10:
            await interaction.response.send_message("Maximum 5 options allowed for reaction polls.", ephemeral=True)
            return

        poll_id = self.poll_manager.create_poll(question, options, duration_minutes, interaction.channel_id, interaction.user.id)

        embed = discord.Embed(
            title=f"📊 {question}",
            description="React with the corresponding emoji to vote!",
            color=discord.Color.blue()
        )

        emojis = ["👍", "👎"] if len(options) == 2 else ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][:len(options)]

        for i, (emoji, option) in enumerate(zip(emojis, options)):
            embed.add_field(name=f"{emoji} {option}", value="0 votes (0.0%)", inline=False)

        end_time = datetime.fromisoformat(self.poll_manager.polls[poll_id]["end_time"])
        time_left = end_time - datetime.now()
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{time_left.days}d {hours}h {minutes}m" if time_left.days > 0 else f"{hours}h {minutes}m"
        
        embed.set_footer(text=f"Poll ends in: {time_str} • Poll ID: {poll_id}")

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()

        self.poll_manager.polls[poll_id]["message_id"] = message.id
        self.poll_manager.save_polls()

        for emoji in emojis[:len(options)]:
            await message.add_reaction(emoji)

    @app_commands.command(name="endpoll", description="End a poll early")
    @app_commands.describe(message_id="The ID of the poll message")
    async def end_poll(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You don't have permission to end polls!", ephemeral=True)
            return

        poll_id = None
        for pid, poll in self.poll_manager.polls.items():
            if str(poll["message_id"]) == message_id:
                poll_id = pid
                break

        if not poll_id:
            await interaction.response.send_message("Poll not found! Make sure you entered the correct message ID.", ephemeral=True)
            return

        if self.poll_manager.polls[poll_id].get("closed", False):
            await interaction.response.send_message("This poll is already closed!", ephemeral=True)
            return

        await self.end_poll(poll_id)
        await interaction.response.send_message("Poll ended successfully!", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        poll = None
        poll_id = None
        
        for pid, p in self.poll_manager.polls.items():
            if p.get("message_id") == payload.message_id and not p.get("closed", False):
                poll = p
                poll_id = pid
                break
        
        if not poll:
            return

        emojis = ["👍", "👎"] if len(poll["options"]) == 2 else ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][:len(poll["options"])]
        
        if str(payload.emoji) not in emojis:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        message = await channel.fetch_message(payload.message_id)
        if not message:
            return

        await message.remove_reaction(payload.emoji, payload.member)

        option_index = emojis.index(str(payload.emoji))
        self.poll_manager.add_vote(poll_id, option_index, payload.user_id)
        
        await self.update_poll_display(poll_id, message)

    async def update_poll_display(self, poll_id: str, message: discord.Message):
        poll = self.poll_manager.get_poll(poll_id)
        if not poll:
            return

        total_votes = sum(len(votes) for votes in poll["votes"].values())
        emojis = ["👍", "👎"] if len(poll["options"]) == 2 else ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][:len(poll["options"])]

        embed = discord.Embed(
            title=f"📊 {poll['question']}",
            description="React with the corresponding emoji to vote!",
            color=discord.Color.blue()
        )

        for i, (emoji, option) in enumerate(zip(emojis, poll["options"])):
            votes = len(poll["votes"][str(i)])
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0
            
            filled_length = int(10 * percentage / 100)
            bar = "█" * filled_length + "░" * (10 - filled_length)
            
            embed.add_field(
                name=f"{emoji} {option}",
                value=f"{bar} **{percentage:.1f}%** ({votes} votes)",
                inline=False
            )

        end_time = datetime.fromisoformat(poll["end_time"])
        time_left = end_time - datetime.now()
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{time_left.days}d {hours}h {minutes}m" if time_left.days > 0 else f"{hours}h {minutes}m"
        
        embed.set_footer(text=f"Poll ends in: {time_str} • Poll ID: {poll_id}")

        await message.edit(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Reaction Polls cog loaded and ready!")

async def setup(bot):
    await bot.add_cog(Polls(bot))