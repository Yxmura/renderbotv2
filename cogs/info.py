import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="serverinfo", description="Get information about the server")
    async def serverinfo(self, interaction):
        guild = interaction.guild

        # Get counts
        total_members = guild.member_count
        online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        roles = len(guild.roles)
        emojis = len(guild.emojis)

        # Create embed
        embed = discord.Embed(
            title=f"{guild.name} Server Information",
            description=guild.description or "No description",
            color=discord.Color.blue()
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        # General info
        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="Created On", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Server ID", value=guild.id, inline=True)

        # Member info
        embed.add_field(name="Members", value=f"Total: {total_members}\nOnline: {online_members}", inline=True)

        # Channel info
        embed.add_field(
            name="Channels",
            value=f"Categories: {categories}\nText: {text_channels}\nVoice: {voice_channels}",
            inline=True
        )

        # Other info
        embed.add_field(name="Roles", value=str(roles), inline=True)
        embed.add_field(name="Emojis", value=str(emojis), inline=True)

        # Server features
        if guild.features:
            embed.add_field(
                name="Features",
                value="\n".join(f"• {feature.replace('_', ' ').title()}" for feature in guild.features),
                inline=False
            )

        embed.set_footer(text=f"Requested by {interaction.user}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Get information about a user")
    @app_commands.describe(user="The user to get information about (defaults to yourself)")
    async def userinfo(self, interaction, user: discord.Member = None):
        # Default to the command user if no user is specified
        target = user or interaction.user

        # Create embed
        embed = discord.Embed(
            title=f"User Information - {target.display_name}",
            color=target.color if target.color != discord.Color.default() else discord.Color.blue()
        )

        embed.set_thumbnail(url=target.display_avatar.url)

        # User information
        embed.add_field(name="Username", value=str(target), inline=True)
        embed.add_field(name="User ID", value=target.id, inline=True)
        embed.add_field(name="Bot", value="Yes" if target.bot else "No", inline=True)

        # Dates
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(target.created_at.timestamp())}:R>",
            inline=True
        )
        embed.add_field(
            name="Joined Server",
            value=f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "Unknown",
            inline=True
        )

        # Status and activity
        status_emoji = {
            discord.Status.online: "🟢",
            discord.Status.idle: "🟡",
            discord.Status.dnd: "🔴",
            discord.Status.offline: "⚫"
        }

        status = f"{status_emoji.get(target.status, '⚪')} {str(target.status).title()}"
        embed.add_field(name="Status", value=status, inline=True)

        # Roles
        roles = [role.mention for role in target.roles if role.name != "@everyone"]
        roles.reverse()  # Show highest roles first

        if roles:
            # Limit to first 10 roles to avoid hitting embed field limits
            roles_value = " ".join(roles[:10])
            if len(target.roles) > 11:  # +1 for @everyone
                roles_value += f" (+{len(target.roles) - 11} more)"

            embed.add_field(name=f"Roles [{len(roles)}]", value=roles_value, inline=False)

        # Permissions
        key_permissions = []
        permissions = target.guild_permissions

        if permissions.administrator:
            key_permissions.append("Administrator")
        else:
            if permissions.manage_guild:
                key_permissions.append("Manage Server")
            if permissions.ban_members:
                key_permissions.append("Ban Members")
            if permissions.kick_members:
                key_permissions.append("Kick Members")
            if permissions.manage_channels:
                key_permissions.append("Manage Channels")
            if permissions.manage_messages:
                key_permissions.append("Manage Messages")
            if permissions.manage_roles:
                key_permissions.append("Manage Roles")

        if key_permissions:
            embed.add_field(name="Key Permissions", value=", ".join(key_permissions), inline=False)

        embed.set_footer(text=f"Requested by {interaction.user}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Get a user's avatar")
    @app_commands.describe(user="The user to get the avatar of (defaults to yourself)")
    async def avatar(self, interaction, user: discord.Member = None):
        # Default to the command user if no user is specified
        target = user or interaction.user

        embed = discord.Embed(
            title=f"{target.display_name}'s Avatar",
            color=discord.Color.blue()
        )

        embed.set_image(url=target.display_avatar.url)
        embed.set_footer(text=f"Requested by {interaction.user}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roleinfo", description="Get information about a role")
    @app_commands.describe(role="The role to get information about")
    async def roleinfo(self, interaction, role: discord.Role):
        # Create embed
        embed = discord.Embed(
            title=f"Role Information - {role.name}",
            color=role.color
        )

        # Role information
        embed.add_field(name="Name", value=role.name, inline=True)
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color).upper(), inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        embed.add_field(name="Created On", value=role.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Member Count", value=str(len(role.members)), inline=True)

        # Key permissions
        permissions = []

        if role.permissions.administrator:
            permissions.append("Administrator")
        else:
            permission_mapping = {
                "manage_guild": "Manage Server",
                "ban_members": "Ban Members",
                "kick_members": "Kick Members",
                "manage_channels": "Manage Channels",
                "manage_messages": "Manage Messages",
                "manage_roles": "Manage Roles",
                "mention_everyone": "Mention Everyone",
                "manage_webhooks": "Manage Webhooks",
                "manage_emojis": "Manage Emojis"
            }

            for perm_name, display_name in permission_mapping.items():
                if getattr(role.permissions, perm_name):
                    permissions.append(display_name)

        if permissions:
            embed.add_field(name="Key Permissions", value=", ".join(permissions), inline=False)

        embed.set_footer(text=f"Requested by {interaction.user}")

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Info(bot))