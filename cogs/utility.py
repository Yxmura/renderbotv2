import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
from datetime import datetime


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction):
        latency = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Bot Latency: **{latency}ms**",
            color=discord.Color.green() if latency < 200 else discord.Color.orange() if latency < 500 else discord.Color.red()
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="weather", description="Get weather information for a location")
    @app_commands.describe(location="The city or location to get weather for")
    async def weather(self, interaction, location: str):
        # Note: You would need to sign up for a weather API like OpenWeatherMap
        # This is a placeholder implementation
        api_key = "YOUR_OPENWEATHERMAP_API_KEY"  # Replace with your actual API key

        async with aiohttp.ClientSession() as session:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=metric"

            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        await interaction.response.send_message(f"Couldn't find weather data for '{location}'",
                                                                ephemeral=True)
                        return

                    data = await response.json()

                    weather_main = data["weather"][0]["main"]
                    weather_desc = data["weather"][0]["description"]
                    temp = data["main"]["temp"]
                    feels_like = data["main"]["feels_like"]
                    humidity = data["main"]["humidity"]
                    wind_speed = data["wind"]["speed"]

                    embed = discord.Embed(
                        title=f"Weather in {data['name']}, {data.get('sys', {}).get('country', '')}",
                        description=f"**{weather_main}**: {weather_desc}",
                        color=discord.Color.blue()
                    )

                    embed.add_field(name="Temperature", value=f"{temp}°C", inline=True)
                    embed.add_field(name="Feels Like", value=f"{feels_like}°C", inline=True)
                    embed.add_field(name="Humidity", value=f"{humidity}%", inline=True)
                    embed.add_field(name="Wind Speed", value=f"{wind_speed} m/s", inline=True)

                    # Weather icon
                    icon_id = data["weather"][0]["icon"]
                    embed.set_thumbnail(url=f"http://openweathermap.org/img/wn/{icon_id}@2x.png")

                    await interaction.response.send_message(embed=embed)
            except Exception as e:
                await interaction.response.send_message(f"Error fetching weather data: {str(e)}", ephemeral=True)

    @app_commands.command(name="urban", description="Look up a term in the Urban Dictionary")
    @app_commands.describe(term="The term to look up")
    async def urban(self, interaction, term: str):
        async with aiohttp.ClientSession() as session:
            url = f"https://api.urbandictionary.com/v0/define?term={term}"

            async with session.get(url) as response:
                if response.status != 200:
                    await interaction.response.send_message(f"Couldn't find a definition for '{term}'", ephemeral=True)
                    return

                data = await response.json()

                if not data["list"]:
                    await interaction.response.send_message(f"No definitions found for '{term}'", ephemeral=True)
                    return

                # Get the top definition
                definition = data["list"][0]

                # Clean up the definition text
                def_text = definition["definition"].replace("[", "").replace("]", "")
                example = definition["example"].replace("[", "").replace("]", "")

                if len(def_text) > 1024:
                    def_text = def_text[:1021] + "..."

                if len(example) > 1024:
                    example = example[:1021] + "..."

                embed = discord.Embed(
                    title=f"Urban Dictionary: {term}",
                    url=definition["permalink"],
                    color=discord.Color.dark_purple()
                )

                embed.add_field(name="Definition", value=def_text, inline=False)

                if example:
                    embed.add_field(name="Example", value=example, inline=False)

                embed.add_field(name="👍", value=str(definition["thumbs_up"]), inline=True)
                embed.add_field(name="👎", value=str(definition["thumbs_down"]), inline=True)

                embed.set_footer(text=f"Definition by {definition['author']}")

                await interaction.response.send_message(embed=embed)

    @app_commands.command(name="translate", description="Translate text to another language")
    @app_commands.describe(
        text="The text to translate",
        target="The target language code (e.g., es, fr, de, ja)"
    )
    async def translate(self, interaction, text: str, target: str):
        # Note: You would need to sign up for a translation API like Google Translate
        # This is a placeholder implementation
        await interaction.response.send_message(
            "This is a placeholder for the translate command. To implement this properly, "
            "you would need to sign up for a translation API service.",
            ephemeral=True
        )

    @app_commands.command(name="calculator", description="Perform a simple calculation")
    @app_commands.describe(expression="The mathematical expression to calculate")
    async def calculator(self, interaction, expression: str):
        # Simple and safe evaluation of mathematical expressions
        try:
            # Remove any characters that aren't digits, operators, or decimal points
            sanitized = ''.join(c for c in expression if c.isdigit() or c in '+-*/().^ ')

            # Replace ^ with ** for exponentiation
            sanitized = sanitized.replace('^', '**')

            # Evaluate the expression
            result = eval(sanitized, {"__builtins__": {}})

            embed = discord.Embed(
                title="🧮 Calculator",
                description=f"**Expression:** `{expression}`\n**Result:** `{result}`",
                color=discord.Color.blue()
            )

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"Error calculating result: {str(e)}", ephemeral=True)

    @app_commands.command(name="currency", description="Convert between currencies")
    @app_commands.describe(
        amount="The amount to convert",
        from_currency="The source currency code (e.g., USD, EUR)",
        to_currency="The target currency code (e.g., EUR, GBP)"
    )
    async def currency(self, interaction, amount: float, from_currency: str, to_currency: str):
        # Note: You would need to sign up for a currency conversion API
        # This is a placeholder implementation
        await interaction.response.send_message(
            "This is a placeholder for the currency conversion command. To implement this properly, "
            "you would need to sign up for a currency conversion API service.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Utility(bot))