import discord
from discord import app_commands
from discord.ext import commands
import json
from datetime import datetime

def load_data(file):
    with open(f'data/{file}.json', 'r') as f:
        return json.load(f)

def save_data(file, data):
    with open(f'data/{file}.json', 'w') as f:
        json.dump(data, f, indent=4)

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        config = load_data('config')
        for role_id in config.get("auto_roles", []):
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role assignment")
                except discord.HTTPException:
                    pass
        if config.get("welcome_channel"):
            channel = self.bot.get_channel(int(config["welcome_channel"]))
            if channel:
                try:
                    await channel.edit(name=f"《👋》{member.guild.member_count}")
                except Exception as e:
                    print(f"Failed to update channel name: {e}")
                embed = discord.Embed(
                    title=f"Welcome to {member.guild.name}!",
                    description=f"Welcome to the server! We're now at **{member.guild.member_count}** members!",
                    color=discord.Color.green()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"Joined at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                await channel.send(f"Hey {member.mention}!", embed=embed)

    @commands.Cog.listener()
    async def on_member_boost(self, member, boost_type):
        config = load_data('config')
        if not config.get('boost_channel_id'):
            return
        channel = self.bot.get_channel(int(config['boost_channel_id']))
        if not channel:
            return
        embed = discord.Embed(
            title="✨ Server Boosted! ✨",
            description=(
                f"Thank you {member.mention} for boosting **{member.guild.name}**!\n\n"
                "Your support helps us keep the community running and growing. "
                "As a token of our appreciation, you've received the **Booster** role! 🎉"
            ),
            color=0xFF73FA
        )
        if member.guild.icon:
            embed.set_thumbnail(url=member.guild.icon.url)
        if hasattr(member.guild, 'premium_subscription_count'):
            boost_count = member.guild.premium_subscription_count
            boost_level = member.guild.premium_tier
            level_str = {
                0: "Level 0",
                1: "Level 1 (5+ boosts)",
                2: "Level 2 (15+ boosts)",
                3: "Level 3 (30+ boosts)"
            }.get(boost_level, f"Level {boost_level}")
            embed.add_field(
                name="Server Boost Status",
                value=f"**Boosts:** {boost_count}\n**Boost Level:** {level_str}",
                inline=False
            )
        embed.set_footer(text="Thank you for your support!")
        await channel.send(f"🎉 {member.mention} just boosted the server! 🎉", embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        config = load_data('config')
        if config.get("goodbye_channel"):
            channel = self.bot.get_channel(int(config["goodbye_channel"]))
            if channel:
                try:
                    await channel.edit(name=f"《👋》{member.guild.member_count}")
                except Exception as e:
                    print(f"Failed to update channel name: {e}")
                embed = discord.Embed(
                    title=f"Goodbye!",
                    description=f"{member.name} has left the server. We're now at **{member.guild.member_count}** members.",
                    color=discord.Color.red()
                )
                embed.set_footer(text=f"Left at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                await channel.send(embed=embed)

    @app_commands.command(name="set_welcome_channel", description="Set the welcome message channel")
    @app_commands.describe(channel="The channel for welcome messages")
    async def set_welcome_channel(self, interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to use this command!",
                                                    ephemeral=True)
            return
        config = load_data('config')
        config["welcome_channel"] = str(channel.id)
        save_data('config', config)
        await interaction.response.send_message(f"Welcome channel set to {channel.mention}!", ephemeral=True)

    @app_commands.command(name="set_goodbye_channel", description="Set the goodbye message channel")
    @app_commands.describe(channel="The channel for goodbye messages")
    async def set_goodbye_channel(self, interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to use this command!",
                                                    ephemeral=True)
            return
        config = load_data('config')
        config["goodbye_channel"] = str(channel.id)
        save_data('config', config)
        await interaction.response.send_message(f"Goodbye channel set to {channel.mention}!", ephemeral=True)

    @app_commands.command(name="welcome_test", description="Test the welcome message")
    async def welcome_test(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to use this command!",
                                                    ephemeral=True)
            return
        config = load_data('config')
        if not config.get("welcome_channel"):
            await interaction.response.send_message("Welcome channel is not set! Use `/set_welcome_channel` first.",
                                                    ephemeral=True)
            return
        channel = self.bot.get_channel(int(config["welcome_channel"]))
        if not channel:
            await interaction.response.send_message("Welcome channel not found! It may have been deleted.",
                                                    ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Welcome to {interaction.guild.name}!",
            description=f"Hey {interaction.user.mention}, welcome to the server! We're now at **{interaction.guild.member_count}** members!",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"This is a test message | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Test welcome message sent to {channel.mention}!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Welcome(bot))