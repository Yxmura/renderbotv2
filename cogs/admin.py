import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
from supabase import create_client, Client
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Supabase client
try:
    supabase: Client = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_KEY')
    )
    logging.info("Supabase client initialized successfully")
except Exception as e:
    logging.error(f"Failed to initialize Supabase client: {e}")
    supabase = None


# Load data
def load_data(file):
    with open(f'data/{file}.json', 'r') as f:
        return json.load(f)


def save_data(file, data):
    with open(f'data/{file}.json', 'w') as f:
        json.dump(data, f, indent=4)


# Check if user has admin role
def is_admin(interaction):
    config = load_data('config')
    admin_roles = config.get("admin_roles", [])

    if not admin_roles:  # If no admin roles set, default to administrator permission
        return interaction.user.guild_permissions.administrator

    for role_id in admin_roles:
        role = interaction.guild.get_role(int(role_id))
        if role and role in interaction.user.roles:
            return True

    return interaction.user.guild_permissions.administrator


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supabase = supabase

    @app_commands.command(name="set_admin_role", description="Set admin roles for ticket management")
    @app_commands.describe(role="The role to add as admin")
    async def set_admin_role(self, interaction, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to use this command!",
                                                    ephemeral=True)
            return

        config = load_data('config')
        if "admin_roles" not in config:
            config["admin_roles"] = []

        role_id = str(role.id)
        if role_id in config["admin_roles"]:
            config["admin_roles"].remove(role_id)
            await interaction.response.send_message(f"Removed {role.mention} from admin roles!", ephemeral=True)
        else:
            config["admin_roles"].append(role_id)
            await interaction.response.send_message(f"Added {role.mention} to admin roles!", ephemeral=True)

        save_data('config', config)

    @app_commands.command(name="create_embed", description="Create a custom embed")
    @app_commands.describe(
        channel="The channel to send the embed to",
        title="The title of the embed",
        description="The description of the embed",
        color="The color of the embed (hex code like #FF0000)",
        image_url="Optional: URL of an image to include"
    )
    async def create_embed(
            self,
            interaction,
            channel: discord.TextChannel,
            title: str,
            description: str,
            color: str = "#0099ff",
            image_url: str = None
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        # Parse color
        try:
            if color.startswith('#'):
                color = color[1:]
            color_value = int(color, 16)
        except ValueError:
            await interaction.response.send_message("Invalid color format! Use hex code like #FF0000", ephemeral=True)
            return

        # Create embed
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color(color_value)
        )

        if image_url:
            embed.set_image(url=image_url)

        embed.set_footer(text=f"Created by {interaction.user}")

        # Send embed
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}!", ephemeral=True)

    @app_commands.command(name="set_auto_role", description="Set a role to be automatically assigned to new members")
    @app_commands.describe(role="The role to automatically assign")
    async def set_auto_role(self, interaction, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to use this command!",
                                                    ephemeral=True)
            return

        config = load_data('config')
        if "auto_roles" not in config:
            config["auto_roles"] = []

        role_id = str(role.id)
        if role_id in config["auto_roles"]:
            config["auto_roles"].remove(role_id)
            await interaction.response.send_message(f"Removed {role.mention} from auto-roles!", ephemeral=True)
        else:
            config["auto_roles"].append(role_id)
            await interaction.response.send_message(
                f"Added {role.mention} to auto-roles! New members will receive this role.", ephemeral=True)

        save_data('config', config)

    @app_commands.command(name="purge", description="Delete a specified number of messages")
    @app_commands.describe(amount="The number of messages to delete (1-100)")
    async def purge(self, interaction, amount: int):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        if amount < 1 or amount > 100:
            await interaction.response.send_message("Please specify a number between 1 and 100!", ephemeral=True)
            return

        # Need to defer because deletion might take some time
        await interaction.response.defer(ephemeral=True)

        # Delete messages
        deleted = await interaction.channel.purge(limit=amount)

        await interaction.followup.send(f"Successfully deleted {len(deleted)} messages!", ephemeral=True)

    @app_commands.command(name="announce", description="Make an announcement in a channel")
    @app_commands.describe(
        channel="The channel to send the announcement to",
        title="The title of the announcement",
        message="The announcement message",
        ping_everyone="Whether to ping @updates (default: False)"
    )
    async def announce(
            self,
            interaction,
            channel: discord.TextChannel,
            title: str,
            message: str,
            ping_everyone: bool = False
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        # Create embed
        embed = discord.Embed(
            title=title,
            description=message,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Announcement from {interaction.guild.name}",
                         icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

        # Send announcement
        content = "<@&1330576797267660841>" if ping_everyone else None
        await channel.send(content=content, embed=embed)

        await interaction.response.send_message(f"Announcement sent to {channel.mention}!", ephemeral=True)
        
    @app_commands.command(name="test_db", description="Test the database connection")
    async def test_db(self, interaction: discord.Interaction):
        """Test the Supabase database connection"""
        await interaction.response.defer(ephemeral=True)
        
        if not self.supabase:
            await interaction.followup.send("❌ Supabase client not initialized. Check your environment variables.")
            return
            
        try:
            # Test connection by listing tables
            response = self.supabase.table('tickets').select("*").limit(1).execute()
            
            if hasattr(response, 'error') and response.error:
                await interaction.followup.send(f"❌ Database error: {response.error}")
                return
                
            # Check if tickets table exists
            tables = self.supabase.table('pg_tables').select("tablename").execute()
            table_names = [table['tablename'] for table in tables.data] if hasattr(tables, 'data') else []
            
            embed = discord.Embed(
                title="✅ Database Connection Test",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Connection Status",
                value="✅ Successfully connected to Supabase",
                inline=False
            )
            
            embed.add_field(
                name="Tables in Database",
                value="\n".join(table_names) if table_names else "No tables found",
                inline=False
            )
            
            embed.add_field(
                name="Tickets Table Status",
                value="✅ Found" if 'tickets' in table_names else "❌ Not found",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Database Test Failed",
                description=f"Error: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed)


async def setup(bot):
    await bot.add_cog(Admin(bot))