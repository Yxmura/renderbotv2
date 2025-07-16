import discord
from discord.ext import commands
import os
import json
import asyncio
import logging
from datetime import datetime
import dotenv

dotenv.load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot")

# Bot configuration
intents = discord.Intents.default()
intents.members = True
intents.message_content = True


class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!',
            intents=intents,
            application_id=os.getenv('APPLICATION_ID')  # Optional: Set your application ID
        )
        self.initial_extensions = [
            'cogs.tickets',
            'cogs.fun',
            'cogs.utility',
            'cogs.admin',
            'cogs.welcome',
            'cogs.info',
            'cogs.polls',
            'cogs.reminders',
            'cogs.giveaways',
            'cogs.copyright_checker',
            'cogs.help',
            'cogs.rules',
            'cogs.roles'
        ]

    async def setup_hook(self):
        # Load extensions
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                logger.info(f"Loaded extension {extension}")
            except Exception as e:
                logger.error(f"Failed to load extension {extension}: {e}")

        # Ensure data directories exist
        self.ensure_data_directories()

    def ensure_data_directories(self):
        # Create data directory if it doesn't exist
        if not os.path.exists('data'):
            os.makedirs('data')
            logger.info("Created data directory")

        # Create default data files if they don't exist
        default_files = {
            'tickets.json': {"tickets": {}, "counter": 0},
            'config.json': {
                "ticket_categories": ["General Support", "Technical Issue", "Billing Question", "Other"],
                "admin_roles": [],
                "welcome_channel": None,
                "goodbye_channel": None,
                "auto_roles": []
            },
            'reminders.json': [],
            'polls.json': {},
            'giveaways.json': {}  # Add default giveaways file
        }

        for filename, default_data in default_files.items():
            filepath = f'data/{filename}'
            if not os.path.exists(filepath):
                with open(filepath, 'w') as f:
                    json.dump(default_data, f, indent=4)
                logger.info(f"Created default {filepath}")

    async def on_ready(self):
        logger.info(f'Logged in as {self.user.name} ({self.user.id})')
        logger.info('------')

        # Sync commands
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

        # Setup activity
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Renderdragon.org | /help"
        ))


# Helper functions for data management
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


# Run the bot
if __name__ == "__main__":
    bot = TicketBot()
    bot.run(DISCORD_TOKEN)
