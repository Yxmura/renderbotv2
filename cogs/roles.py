import discord
from discord import app_commands
from discord.ext import commands

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roles", description="View information about server roles and their perks")
    async def show_roles(self, interaction: discord.Interaction):
        """Display information about server roles and their perks"""
        # Create the main embed
        embed = discord.Embed(
            title="🎭 Server Roles & Perks",
            description=(
                "Below you'll find information about the special roles available in our community "
                "and how to obtain them.\n\n"
                "*Note: Some roles are automatically assigned based on your server activity and support!*"
            ),
            color=0x5865F2  # Blurple color
        )
        
        # Add server icon if available
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        # Add role sections
        roles_info = [
            {
                "emoji": "🐣",
                "name": "Babydragon",
                "description": "Supporters who've made a donation to the project — thank you!",
                "perks": [
                    "Custom nickname",
                    "Embed links (GIF perms)",
                    "Unique role color & name flair"
                ]
            },
            {
                "emoji": "🔥",
                "name": "Flamewing (5+ USD Donation)",
                "description": "You've gone above and beyond with your support!",
                "perks": [
                    "All Babydragon perks",
                    "Exclusive Flamewing flair"
                ]
            },
            {
                "emoji": "🐲",
                "name": "Ancient Guardian (10+ USD Donation)",
                "description": "A legendary supporter!",
                "perks": [
                    "All Flamewing perks",
                    "Prestigious role styling and recognition"
                ]
            },
            {
                "emoji": "🎥",
                "name": "Content Creator",
                "description": "Have 1,000+ subscribers? Open a ticket to request this role!",
                "perks": [
                    "Perfect for creators in the Minecraft space",
                    "Stand out and connect with other content creators"
                ]
            },
            {
                "emoji": "📢",
                "name": "Updates",
                "description": "Want to stay in the loop?",
                "perks": [
                    "Get pings for Renderdragon updates, tools, and content creation resources",
                    "No spam — just useful news and releases!"
                ]
            },
            {
                "emoji": "🛡️",
                "name": "Team Member",
                "description": "Official staff of the server and Renderdragon project.",
                "perks": [
                    "Moderation powers",
                    "Here to help and keep things running smoothly!"
                ]
            },
            {
                "emoji": "💎",
                "name": "Booster",
                "description": "For everyone who boosts our Discord server",
                "perks": [
                    "Stand out and be appreciated"
                ]
            }
        ]

        # Add each role to the embed
        for role in roles_info:
            perks_text = "\n".join([f"➤ {perk}" for perk in role["perks"]])
            embed.add_field(
                name=f"{role['emoji']} {role['name']}",
                value=f"{role['description']}\n{perks_text}",
                inline=False
            )
        
        # Add footer with instructions
        embed.set_footer(
            text=(
                "🔧 To claim a donation-based role, please contact staff or use the ticket system.\n"
                "📨 For Content Creator access, provide proof via a support ticket."
            )
        )
        
        # Send the embed
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Roles(bot))
