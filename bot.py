import discord
from discord.ext import commands
import json
import os
import logging
from datetime import datetime
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Load configuration
def load_data(filename):
    """Load data from JSON file"""
    try:
        with open(f'data/{filename}.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def save_data(filename, data):
    """Save data to JSON file"""
    with open(f'data/{filename}.json', 'w') as f:
        json.dump(data, f, indent=4)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Load cogs
    await load_cogs()

async def load_cogs():
    """Load all cogs from the cogs directory"""
    cogs_dir = 'cogs'
    if not os.path.exists(cogs_dir):
        return
    
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and not filename.startswith('__'):
            cog_name = filename[:-3]
            try:
                await bot.load_extension(f'cogs.{cog_name}')
                print(f"Loaded cog: {cog_name}")
            except Exception as e:
                print(f"Failed to load cog {cog_name}: {e}")

@bot.command()
@commands.is_owner()
async def reload(ctx, cog_name: str):
    """Reload a specific cog"""
    try:
        await bot.reload_extension(f'cogs.{cog_name}')
        await ctx.send(f"✅ Reloaded cog: {cog_name}")
    except Exception as e:
        await ctx.send(f"❌ Failed to reload cog: {e}")

@bot.command()
@commands.is_owner()
async def load(ctx, cog_name: str):
    """Load a cog"""
    try:
        await bot.load_extension(f'cogs.{cog_name}')
        await ctx.send(f"✅ Loaded cog: {cog_name}")
    except Exception as e:
        await ctx.send(f"❌ Failed to load cog: {e}")

@bot.command()
@commands.is_owner()
async def unload(ctx, cog_name: str):
    """Unload a cog"""
    try:
        await bot.unload_extension(f'cogs.{cog_name}')
        await ctx.send(f"✅ Unloaded cog: {cog_name}")
    except Exception as e:
        await ctx.send(f"❌ Failed to unload cog: {e}")

@bot.command()
@commands.is_owner()
async def cogs(ctx):
    """List all loaded cogs"""
    loaded_cogs = list(bot.cogs.keys())
    embed = discord.Embed(
        title="Loaded Cogs",
        description=f"**{len(loaded_cogs)} cogs loaded**",
        color=discord.Color.blue()
    )
    
    for cog_name in loaded_cogs:
        embed.add_field(name=cog_name, value="✅ Active", inline=True)
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    # Try to get token from environment variable first
    token = os.getenv('DISCORD_TOKEN')
    
    # Fallback to config.json if not found in .env
    if not token:
        config = load_data('config')
        token = config.get('token')
    
    if not token:
        print("Error: No token found in .env (DISCORD_TOKEN) or data/config.json")
        print("Please add your bot token to .env file as DISCORD_TOKEN=your_token_here")
    else:
        bot.run(token)
