import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import logging
from datetime import datetime
import random
import time
import platform
import psutil
import asyncio
import re
import math

# Set up logging
logger = logging.getLogger('bot.utility')

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Exchange rates data file
RATES_FILE = 'data/exchange_rates.json'

# Default exchange rates (as of May 2023)
DEFAULT_RATES = {
    "USD": 1.0,
    "EUR": 0.93,
    "GBP": 0.81,
    "JPY": 140.23,
    "CAD": 1.36,
    "AUD": 1.51,
    "CHF": 0.91,
    "CNY": 7.14,
    "INR": 82.74,
    "MXN": 17.61,
    "BRL": 5.01,
    "RUB": 80.84,
    "KRW": 1342.94,
    "TRY": 19.57,
    "ZAR": 19.21,
    "SEK": 10.73,
    "NOK": 10.94,
    "DKK": 6.94,
    "PLN": 4.21,
    "SGD": 1.35,
    "HKD": 7.83,
    "NZD": 1.64,
    "THB": 34.73,
    "IDR": 14950.0,
    "MYR": 4.53,
    "PHP": 55.98,
    "AED": 3.67,
    "SAR": 3.75,
    "ILS": 3.71,
    "EGP": 30.89,
    "BTC": 0.000037
}

def load_rates():
    """Load exchange rates from file or use defaults if file doesn't exist"""
    try:
        with open(RATES_FILE, 'r') as f:
            rates = json.load(f)
            # Check if rates are empty or corrupted
            if not rates or not isinstance(rates, dict):
                return DEFAULT_RATES
            return rates
    except (FileNotFoundError, json.JSONDecodeError):
        # Save default rates to file
        with open(RATES_FILE, 'w') as f:
            json.dump(DEFAULT_RATES, f, indent=4)
        return DEFAULT_RATES

def save_rates(rates):
    """Save exchange rates to file"""
    with open(RATES_FILE, 'w') as f:
        json.dump(rates, f, indent=4)

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rates = load_rates()
        self.start_time = datetime.now()
    
    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        """Check the bot's latency"""
        start_time = time.time()
        await interaction.response.defer(ephemeral=True)
        end_time = time.time()
        
        api_latency = round((end_time - start_time) * 1000)
        websocket_latency = round(self.bot.latency * 1000)
        
        embed = discord.Embed(
            title="🏓 Pong!",
            description="Here are the current latency statistics:",
            color=discord.Color.green()
        )
        
        embed.add_field(name="API Latency", value=f"{api_latency}ms", inline=True)
        embed.add_field(name="WebSocket Latency", value=f"{websocket_latency}ms", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="stats", description="Show bot statistics")
    async def stats(self, interaction: discord.Interaction):
        """Show bot statistics"""
        await interaction.response.defer()
        
        # Calculate uptime
        uptime = datetime.now() - self.start_time
        days, remainder = divmod(int(uptime.total_seconds()), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        
        # Get system info
        cpu_usage = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        memory_used = memory.used / (1024 ** 2)  # Convert to MB
        memory_total = memory.total / (1024 ** 2)  # Convert to MB
        
        # Get bot info
        guild_count = len(self.bot.guilds)
        user_count = sum(guild.member_count for guild in self.bot.guilds)
        channel_count = sum(len(guild.channels) for guild in self.bot.guilds)
        command_count = len(self.bot.tree.get_commands())
        
        # Create embed
        embed = discord.Embed(
            title="Bot Statistics",
            description="Here are the current statistics for the bot:",
            color=discord.Color.blue()
        )
        
        # Bot info
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Guilds", value=str(guild_count), inline=True)
        embed.add_field(name="Users", value=str(user_count), inline=True)
        embed.add_field(name="Channels", value=str(channel_count), inline=True)
        embed.add_field(name="Commands", value=str(command_count), inline=True)
        embed.add_field(name="Library", value=f"discord.py {discord.__version__}", inline=True)
        
        # System info
        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
        embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
        embed.add_field(name="Memory Usage", value=f"{memory_usage}% ({memory_used:.1f}MB / {memory_total:.1f}MB)", inline=True)
        embed.add_field(name="Platform", value=platform.system(), inline=True)
        
        # Set footer
        embed.set_footer(text=f"Bot started on {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="calculate", description="Calculate a mathematical expression")
    @app_commands.describe(expression="The mathematical expression to calculate")
    async def calculate(self, interaction: discord.Interaction, expression: str):
        """Calculate a mathematical expression"""
        await interaction.response.defer()
        
        # Sanitize the expression to prevent code execution
        sanitized = re.sub(r'[^0-9+\-*/().%^ ]', '', expression)
        
        # Replace ^ with ** for exponentiation
        sanitized = sanitized.replace('^', '**')
        
        try:
            # Evaluate the expression
            result = eval(sanitized, {"__builtins__": {}}, {"math": math})
            
            # Create embed
            embed = discord.Embed(
                title="Calculator",
                description=f"Expression: `{expression}`",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Result", value=str(result), inline=False)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error calculating expression: {str(e)}")
    
    @app_commands.command(name="roll_dice_utility", description="Roll dice (e.g., 2d6, 1d20)")
    @app_commands.describe(dice="Dice notation (e.g., 2d6, 1d20)")
    async def roll(self, interaction: discord.Interaction, dice: str):
        """Roll dice (e.g., 2d6, 1d20)"""
        await interaction.response.defer()
        
        # Parse dice notation
        match = re.match(r'^(\d+)d(\d+)$', dice.lower())
        if not match:
            await interaction.followup.send("Invalid dice notation. Use format like `2d6` or `1d20`.")
            return
        
        num_dice = int(match.group(1))
        num_sides = int(match.group(2))
        
        # Validate input
        if num_dice <= 0 or num_sides <= 0:
            await interaction.followup.send("Number of dice and sides must be positive.")
            return
        
        if num_dice > 100:
            await interaction.followup.send("Cannot roll more than 100 dice at once.")
            return
        
        if num_sides > 1000:
            await interaction.followup.send("Dice cannot have more than 1000 sides.")
            return
        
        # Roll the dice
        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        total = sum(rolls)
        
        # Create embed
        embed = discord.Embed(
            title="🎲 Dice Roll",
            description=f"Rolling {dice}",
            color=discord.Color.green()
        )
        
        embed.add_field(name="Rolls", value=str(rolls), inline=False)
        embed.add_field(name="Total", value=str(total), inline=False)
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="convert", description="Convert currency without using an API")
    @app_commands.describe(
        amount="Amount to convert",
        from_currency="Currency to convert from (e.g., USD, EUR, GBP)",
        to_currency="Currency to convert to (e.g., USD, EUR, GBP)"
    )
    async def convert(self, interaction: discord.Interaction, amount: float, from_currency: str, to_currency: str):
        """Convert currency without using an API"""
        await interaction.response.defer()
        
        try:
            # Normalize currency codes
            from_currency = from_currency.upper()
            to_currency = to_currency.upper()
            
            # Check if currencies exist in our rates
            if from_currency not in self.rates:
                raise ValueError(f"Currency '{from_currency}' not found in exchange rates")
            if to_currency not in self.rates:
                raise ValueError(f"Currency '{to_currency}' not found in exchange rates")
            
            # Convert to USD first (our base currency)
            amount_in_usd = amount / self.rates[from_currency]
            
            # Convert from USD to target currency
            result = amount_in_usd * self.rates[to_currency]
            
            # Create embed
            embed = discord.Embed(
                title="Currency Conversion",
                description=f"{amount:,.2f} {from_currency} = {result:,.2f} {to_currency}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            # Add exchange rate info
            rate = self.rates[to_currency] / self.rates[from_currency]
            embed.add_field(name="Exchange Rate", value=f"1 {from_currency} = {rate:,.4f} {to_currency}", inline=False)
            
            # Add note about rates
            embed.set_footer(text="Note: Exchange rates are approximate and may not reflect current market values")
            
            await interaction.followup.send(embed=embed)
            
        except ValueError as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")
        except Exception as e:
            logger.error(f"Error in convert command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while converting currency")
    
    @app_commands.command(name="currencies", description="List all available currencies")
    async def list_currencies(self, interaction: discord.Interaction):
        """List all available currencies"""
        await interaction.response.defer()
        
        # Create embed
        embed = discord.Embed(
            title="Available Currencies",
            description="Here are all the currencies available for conversion:",
            color=discord.Color.blue()
        )
        
        # Sort currencies alphabetically
        currencies = sorted(self.rates.keys())
        
        # Split currencies into multiple fields (Discord has a limit of 25 fields)
        chunks = [currencies[i:i+15] for i in range(0, len(currencies), 15)]
        
        for i, chunk in enumerate(chunks):
            embed.add_field(
                name=f"Currencies {i+1}",
                value="\n".join(chunk),
                inline=True
            )
        
        embed.set_footer(text="Use /convert to convert between these currencies")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="update_rate", description="Update an exchange rate (Admin only)")
    @app_commands.describe(
        currency="Currency code to update (e.g., USD, EUR, GBP)",
        rate="New exchange rate relative to USD (1 USD = X Currency)"
    )
    async def update_rate(self, interaction: discord.Interaction, currency: str, rate: float):
        """Update an exchange rate (Admin only)"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Normalize currency code
            currency = currency.upper()
            
            # Update rate
            old_rate = self.rates.get(currency, None)
            self.rates[currency] = rate
            save_rates(self.rates)
            
            if old_rate:
                await interaction.followup.send(f"✅ Updated exchange rate for {currency}: {old_rate} → {rate}", ephemeral=True)
            else:
                await interaction.followup.send(f"✅ Added new currency {currency} with rate {rate}", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in update_rate command: {str(e)}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="add_currency", description="Add a new currency (Admin only)")
    @app_commands.describe(
        currency="Currency code to add (e.g., USD, EUR, GBP)",
        rate="Exchange rate relative to USD (1 USD = X Currency)"
    )
    async def add_currency(self, interaction: discord.Interaction, currency: str, rate: float):
        """Add a new currency (Admin only)"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Normalize currency code
            currency = currency.upper()
            
            # Check if currency already exists
            if currency in self.rates:
                await interaction.followup.send(f"❌ Currency {currency} already exists. Use /update_rate to update it.", ephemeral=True)
                return
            
            # Add new currency
            self.rates[currency] = rate
            save_rates(self.rates)
            
            await interaction.followup.send(f"✅ Added new currency {currency} with rate {rate}", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in add_currency command: {str(e)}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="remove_currency", description="Remove a currency (Admin only)")
    @app_commands.describe(currency="Currency code to remove (e.g., EUR, GBP)")
    async def remove_currency(self, interaction: discord.Interaction, currency: str):
        """Remove a currency (Admin only)"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Normalize currency code
            currency = currency.upper()
            
            # Check if currency exists
            if currency not in self.rates:
                await interaction.followup.send(f"❌ Currency {currency} not found", ephemeral=True)
                return
            
            # Prevent removing USD (base currency)
            if currency == "USD":
                await interaction.followup.send("❌ Cannot remove USD as it is the base currency", ephemeral=True)
                return
            
            # Remove currency
            del self.rates[currency]
            save_rates(self.rates)
            
            await interaction.followup.send(f"✅ Removed currency {currency}", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in remove_currency command: {str(e)}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="random", description="Generate a random number")
    @app_commands.describe(
        min_value="Minimum value (default: 1)",
        max_value="Maximum value (default: 100)"
    )
    async def random_number(self, interaction: discord.Interaction, min_value: int = 1, max_value: int = 100):
        """Generate a random number"""
        await interaction.response.defer()
        
        try:
            # Validate input
            if min_value >= max_value:
                await interaction.followup.send("Minimum value must be less than maximum value.")
                return
            
            # Generate random number
            result = random.randint(min_value, max_value)
            
            # Create embed
            embed = discord.Embed(
                title="🎲 Random Number",
                description=f"Generated a random number between {min_value} and {max_value}",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Result", value=str(result), inline=False)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error generating random number: {str(e)}")
    
    @app_commands.command(name="choose", description="Choose a random option from a list")
    @app_commands.describe(options="Options to choose from, separated by commas")
    async def choose(self, interaction: discord.Interaction, options: str):
        """Choose a random option from a list"""
        await interaction.response.defer()
        
        # Split options by commas
        option_list = [opt.strip() for opt in options.split(',') if opt.strip()]
        
        if not option_list:
            await interaction.followup.send("Please provide at least one option.")
            return
        
        if len(option_list) == 1:
            await interaction.followup.send("Please provide more than one option.")
            return
        
        # Choose a random option
        chosen = random.choice(option_list)
        
        # Create embed
        embed = discord.Embed(
            title="🎯 Random Choice",
            description=f"I've chosen from {len(option_list)} options",
            color=discord.Color.purple()
        )
        
        embed.add_field(name="Options", value=", ".join(option_list), inline=False)
        embed.add_field(name="Result", value=chosen, inline=False)
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="coinflip", description="Flip a coin")
    async def coinflip(self, interaction: discord.Interaction):
        """Flip a coin"""
        await interaction.response.defer()
        
        # Flip the coin
        result = random.choice(["Heads", "Tails"])
        
        # Create embed
        embed = discord.Embed(
            title="🪙 Coin Flip",
            description="Flipping a coin...",
            color=discord.Color.gold()
        )
        
        embed.add_field(name="Result", value=result, inline=False)
        
        # Add coin image
        if result == "Heads":
            embed.set_thumbnail(url="https://i.imgur.com/HAvGDNJ.png")  # Heads image
        else:
            embed.set_thumbnail(url="https://i.imgur.com/XnAHEFT.png")  # Tails image
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Utility(bot))
