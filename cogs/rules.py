import discord
from discord import app_commands
from discord.ext import commands

class RulesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # Add Donate button
        self.add_item(discord.ui.Button(
            label="💖 Donate",
            url="https://ko-fi.com/renderdragon",
            style=discord.ButtonStyle.link
        ))
        
        # Add Website button
        self.add_item(discord.ui.Button(
            label="🌐 Visit Website",
            url="https://renderdragon.org",
            style=discord.ButtonStyle.link
        ))

class Rules(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(RulesView())  # This makes the view persistent

    @app_commands.command(name="rules", description="Display the server rules")
    @app_commands.checks.has_permissions(administrator=True)
    async def rules(self, interaction: discord.Interaction):
        """Display a beautiful rules embed with action buttons"""
        embed = discord.Embed(
            title="📜 Server Rules & Information",
            color=discord.Color.blue(),
            description=(
                "Welcome to our community! Please read the rules below to ensure a great experience for everyone.\n\n"
                "**1️⃣ Be Respectful**\n"
                "Treat all members with kindness and respect. No harassment, hate speech, or discrimination will be tolerated.\n\n"
                "**2️⃣ Keep it Clean**\n"
                "No NSFW content, excessive swearing, or inappropriate language. Keep discussions family-friendly.\n\n"
                "**3️⃣ No Spamming**\n"
                "Avoid excessive messaging, mentions, or any form of spam. This includes text walls and emoji spam.\n\n"
                "**4️⃣ Stay On Topic**\n"
                "Keep discussions relevant to the channel topic. Use appropriate channels for off-topic discussions.\n\n"
                "**5️⃣ No Self-Promotion**\n"
                "Do not advertise your own content without permission from staff. This includes DM advertising.\n\n"
                "**6️⃣ Follow Discord's TOS**\n"
                "You must follow [Discord's Terms of Service](https://discord.com/terms) and [Community Guidelines](https://discord.com/guidelines).\n\n"
                "**7️⃣ Listen to Staff**\n"
                "Follow instructions from staff members. If you have an issue, discuss it respectfully in DMs.\n\n"
                "**Need Help?**\n"
                "If you have any questions or need assistance, feel free to contact a staff member!"
            )
        )
        
        # Add footer with server info
        embed.set_footer(
            text=f"{interaction.guild.name} • Last Updated",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )
        embed.timestamp = discord.utils.utcnow()
        
        # Add thumbnail if server has an icon
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        # Send the message with the view containing buttons
        await interaction.response.send_message(embed=embed, view=RulesView())

async def setup(bot):
    await bot.add_cog(Rules(bot))
