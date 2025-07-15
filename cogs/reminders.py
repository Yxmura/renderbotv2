import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
from datetime import datetime, timedelta


# Load data
def load_data(file):
    with open(f'data/{file}.json', 'r') as f:
        return json.load(f)


def save_data(file, data):
    with open(f'data/{file}.json', 'w') as f:
        json.dump(data, f, indent=4)


class Reminders(commands.Cog):  # Changed from 'Polls' to 'Reminders'
    def __init__(self, bot):
        self.bot = bot
        self.reminder_task = self.bot.loop.create_task(self.check_reminders())

    def cog_unload(self):
        self.reminder_task.cancel()

    async def check_reminders(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                reminders = load_data('reminders')
                now = datetime.now()

                # Check for reminders that need to be sent
                to_remove = []
                for i, reminder in enumerate(reminders):
                    reminder_time = datetime.fromisoformat(reminder["time"])

                    if reminder_time <= now:
                        # Send the reminder
                        await self.send_reminder(reminder)
                        to_remove.append(i)

                # Remove sent reminders
                for i in sorted(to_remove, reverse=True):
                    reminders.pop(i)

                save_data('reminders', reminders)
            except Exception as e:
                print(f"Error checking reminders: {e}")

            # Check every 30 seconds
            await asyncio.sleep(30)

    async def send_reminder(self, reminder):
        try:
            # Get the user
            user = self.bot.get_user(reminder["user_id"])
            if not user:
                user = await self.bot.fetch_user(reminder["user_id"])

            # Create embed
            embed = discord.Embed(
                title="⏰ Reminder",
                description=reminder["message"],
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            embed.set_footer(text=f"Reminder set on {reminder['created_at']}")

            # Send DM
            await user.send(embed=embed)

            # If channel_id is set, also send to channel
            if reminder.get("channel_id"):
                channel = self.bot.get_channel(reminder["channel_id"])
                if channel:
                    await channel.send(f"{user.mention}, here's your reminder:", embed=embed)
        except Exception as e:
            print(f"Error sending reminder: {e}")

    @app_commands.command(name="remind", description="Set a reminder")
    @app_commands.describe(
        time="Time until reminder (e.g. 1h30m, 2d, 30m)",
        message="The reminder message",
        channel="Whether to send the reminder in this channel as well (default: False)"
    )
    async def remind(self, interaction, time: str, message: str, channel: bool = False):
        # Parse time string
        total_seconds = 0
        time_str = time.lower()

        # Extract days, hours, minutes
        import re
        days = re.search(r'(\d+)d', time_str)
        hours = re.search(r'(\d+)h', time_str)
        minutes = re.search(r'(\d+)m', time_str)
        seconds = re.search(r'(\d+)s', time_str)

        if days:
            total_seconds += int(days.group(1)) * 86400
        if hours:
            total_seconds += int(hours.group(1)) * 3600
        if minutes:
            total_seconds += int(minutes.group(1)) * 60
        if seconds:
            total_seconds += int(seconds.group(1))

        if total_seconds == 0:
            await interaction.response.send_message("Invalid time format! Use format like 1h30m, 2d, 30m",
                                                    ephemeral=True)
            return

        # Calculate reminder time
        reminder_time = datetime.now() + timedelta(seconds=total_seconds)

        # Create reminder
        reminder = {
            "user_id": interaction.user.id,
            "message": message,
            "time": reminder_time.isoformat(),
            "created_at": datetime.now().isoformat()
        }

        if channel:
            reminder["channel_id"] = interaction.channel.id

        # Save reminder
        reminders = load_data('reminders')
        reminders.append(reminder)
        save_data('reminders', reminders)

        # Format time for display
        time_parts = []
        days = total_seconds // 86400
        if days > 0:
            time_parts.append(f"{days} day{'s' if days != 1 else ''}")

        hours = (total_seconds % 86400) // 3600
        if hours > 0:
            time_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")

        minutes = (total_seconds % 3600) // 60
        if minutes > 0:
            time_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

        seconds = total_seconds % 60
        if seconds > 0:
            time_parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

        time_display = ", ".join(time_parts)

        # Send confirmation
        embed = discord.Embed(
            title="⏰ Reminder Set",
            description=f"I'll remind you in **{time_display}**.",
            color=discord.Color.green()
        )

        embed.add_field(name="Message", value=message, inline=False)
        embed.add_field(name="Time", value=f"<t:{int(reminder_time.timestamp())}:F>", inline=False)

        if channel:
            embed.add_field(name="Channel", value=f"I'll also remind you in {interaction.channel.mention}",
                            inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="reminders", description="List your active reminders")
    async def list_reminders(self, interaction):
        reminders = load_data('reminders')

        # Filter reminders for this user
        user_reminders = [r for r in reminders if r["user_id"] == interaction.user.id]

        if not user_reminders:
            await interaction.response.send_message("You don't have any active reminders!", ephemeral=True)
            return

        # Create embed
        embed = discord.Embed(
            title="Your Reminders",
            description=f"You have {len(user_reminders)} active reminder{'s' if len(user_reminders) != 1 else ''}.",
            color=discord.Color.blue()
        )

        # Add fields for each reminder
        for i, reminder in enumerate(user_reminders):
            reminder_time = datetime.fromisoformat(reminder["time"])
            time_left = reminder_time - datetime.now()

            if time_left.total_seconds() <= 0:
                time_str = "Any moment now..."
            else:
                days = time_left.days
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                time_parts = []
                if days > 0:
                    time_parts.append(f"{days}d")
                if hours > 0:
                    time_parts.append(f"{hours}h")
                if minutes > 0:
                    time_parts.append(f"{minutes}m")
                if seconds > 0:
                    time_parts.append(f"{seconds}s")

                time_str = " ".join(time_parts) if time_parts else "Any moment now..."

            embed.add_field(
                name=f"Reminder #{i + 1} (in {time_str})",
                value=f"**Message:** {reminder['message']}\n**Time:** <t:{int(reminder_time.timestamp())}:F>",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cancelreminder", description="Cancel a reminder")
    @app_commands.describe(index="The reminder number (from /reminders list)")
    async def cancel_reminder(self, interaction, index: int):
        reminders = load_data('reminders')

        # Filter reminders for this user
        user_reminders = [r for r in reminders if r["user_id"] == interaction.user.id]

        if not user_reminders:
            await interaction.response.send_message("You don't have any active reminders!", ephemeral=True)
            return

        if index < 1 or index > len(user_reminders):
            await interaction.response.send_message(
                f"Invalid reminder number! You have {len(user_reminders)} reminder(s).", ephemeral=True)
            return

        # Get the reminder to cancel
        target_reminder = user_reminders[index - 1]

        # Remove from the list
        reminders.remove(target_reminder)
        save_data('reminders', reminders)

        # Send confirmation
        embed = discord.Embed(
            title="Reminder Cancelled",
            description=f"Your reminder has been cancelled.",
            color=discord.Color.red()
        )

        embed.add_field(name="Message", value=target_reminder["message"], inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Reminders(bot))