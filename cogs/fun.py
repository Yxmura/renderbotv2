import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import random
import json
from datetime import datetime


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kiss", description="Kiss another user")
    @app_commands.describe(user="The user to kiss")
    async def kiss(self, interaction, user: discord.Member):
        if user == interaction.user:
            await interaction.response.send_message("You can't kiss yourself!", ephemeral=True)
            return
        elif user.bot:
            await interaction.response.send_message("You can't kiss a bot!", ephemeral=True)
        else:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.otakugifs.xyz/gif?reaction=airkiss') as response:
                    if response.status == 200:
                        data = await response.json()
                        embed = discord.Embed(
                            title=f"{interaction.user.display_name} kissed {user.display_name}!",
                            color=discord.Color.pink()
                        )
                        embed.set_image(url=data['url'])
                        await interaction.response.send_message(content = f"{interaction.user.mention} {user.mention}", embed=embed)


    @app_commands.command(name="meme", description="Get a random meme")
    async def meme(self, interaction):
        async with aiohttp.ClientSession() as session:
            async with session.get('https://meme-api.com/gimme') as response:
                if response.status == 200:
                    data = await response.json()
                    embed = discord.Embed(
                        title=data['title'],
                        url=data['postLink'],
                        color=discord.Color.random()
                    )
                    embed.set_image(url=data['url'])
                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message("Failed to fetch a meme. Try again later.", ephemeral=True)

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a question")
    @app_commands.describe(question="The question to ask")
    async def eight_ball(self, interaction, question: str):
        responses = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes - definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful."
        ]

        embed = discord.Embed(
            title="🎱 Magic 8-Ball",
            description=f"**Question:** {question}\n\n**Answer:** {random.choice(responses)}",
            color=discord.Color.purple()
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roll", description="Roll a dice")
    @app_commands.describe(sides="Number of sides on the dice (default: 6)")
    async def roll(self, interaction, sides: int = 6):
        if sides < 2:
            await interaction.response.send_message("A dice must have at least 2 sides!", ephemeral=True)
            return

        result = random.randint(1, sides)

        embed = discord.Embed(
            title="🎲 Dice Roll",
            description=f"You rolled a **{result}** (1-{sides})",
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="flip", description="Flip a coin")
    async def flip(self, interaction):
        result = random.choice(["Heads", "Tails"])

        embed = discord.Embed(
            title="🪙 Coin Flip",
            description=f"The coin landed on **{result}**!",
            color=discord.Color.gold()
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="joke", description="Get a random joke")
    async def joke(self, interaction):
        async with aiohttp.ClientSession() as session:
            async with session.get('https://official-joke-api.appspot.com/random_joke') as response:
                if response.status == 200:
                    data = await response.json()

                    embed = discord.Embed(
                        title="😂 Random Joke",
                        description=f"**{data['setup']}**\n\n{data['punchline']}",
                        color=discord.Color.brand_green()
                    )

                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message("Failed to fetch a joke. Try again later.", ephemeral=True)

    @app_commands.command(name="fact", description="Get a random fact")
    async def fact(self, interaction):
        async with aiohttp.ClientSession() as session:
            async with session.get('https://uselessfacts.jsph.pl/random.json?language=en') as response:
                if response.status == 200:
                    data = await response.json()

                    embed = discord.Embed(
                        title="🧠 Random Fact",
                        description=data['text'],
                        color=discord.Color.blue()
                    )

                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message("Failed to fetch a fact. Try again later.", ephemeral=True)

    @app_commands.command(name="choose", description="Let the bot choose between multiple options")
    @app_commands.describe(options="Options separated by commas")
    async def choose(self, interaction, options: str):
        choices = [option.strip() for option in options.split(',') if option.strip()]

        if len(choices) < 2:
            await interaction.response.send_message("Please provide at least 2 options separated by commas!",
                                                    ephemeral=True)
            return

        chosen = random.choice(choices)

        embed = discord.Embed(
            title="🤔 Choice Maker",
            description=f"I choose: **{chosen}**",
            color=discord.Color.blue()
        )

        embed.add_field(name="Options", value='\n'.join(f"• {option}" for option in choices))

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))