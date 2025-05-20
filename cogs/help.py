import discord
from discord import app_commands
from discord.ext import commands

CATEGORIES = {
    "Ticket System": [
        ("/setup_tickets", "Set up the ticket system"),
        ("/ticket_stats", "Show ticket statistics")
    ],
    "Fun Commands": [
        ("/meme", "Get a random meme"),
        ("/8ball", "Ask the magic 8-ball a question"),
        ("/roll", "Roll a dice"),
        ("/flip", "Flip a coin"),
        ("/joke", "Get a random joke"),
        ("/fact", "Get a random fact"),
        ("/choose", "Let the bot choose between options")
    ],
    "Utility Commands": [
        ("/ping", "Check the bot's latency"),
        ("/weather", "Get weather information"),
        ("/urban", "Look up a term in Urban Dictionary"),
        ("/calculator", "Perform a simple calculation")
    ],
    "Admin Commands": [
        ("/set_admin_role", "Set admin roles for ticket management"),
        ("/create_embed", "Create a custom embed"),
        ("/set_auto_role", "Set a role to be automatically assigned"),
        ("/purge", "Delete a specified number of messages"),
        ("/announce", "Make an announcement")
    ],
    "Welcome System": [
        ("/set_welcome_channel", "Set the welcome message channel"),
        ("/set_goodbye_channel", "Set the goodbye message channel"),
        ("/welcome_test", "Test the welcome message")
    ],
    "Info Commands": [
        ("/serverinfo", "Get information about the server"),
        ("/userinfo", "Get information about a user"),
        ("/avatar", "Get a user's avatar"),
        ("/roleinfo", "Get information about a role")
    ],
    "Poll System": [
        ("/poll", "Create a poll"),
        ("/endpoll", "End a poll early")
    ],
    "Reminder System": [
        ("/remind", "Set a reminder"),
        ("/reminders", "List your active reminders"),
        ("/cancelreminder", "Cancel a reminder")
    ]
}

class HelpMenu(discord.ui.View):
    def __init__(self, category: str):
        super().__init__(timeout=60)
        self.category = category
        self.current_page = 0
        self.commands = CATEGORIES[category]
        self.max_per_page = 6

        for name in CATEGORIES:
            self.add_item(HelpButton(name, self))

        if len(self.commands) > self.max_per_page:
            self.add_item(NextPageButton())
            self.add_item(PrevPageButton())

    def get_embed(self):
        start = self.current_page * self.max_per_page
        end = start + self.max_per_page
        cmd_page = self.commands[start:end]

        embed = discord.Embed(
            title=f"Renderbot Help - {self.category}",
            description="List of commands available in Renderbot",
            color=discord.Color.purple()
        )
        for cmd, desc in cmd_page:
            embed.add_field(name=cmd, value=desc, inline=False)

        total_pages = (len(self.commands) - 1) // self.max_per_page + 1
        embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages}")
        return embed

class HelpButton(discord.ui.Button):
    def __init__(self, category: str, menu: HelpMenu):
        super().__init__(label=category, style=discord.ButtonStyle.secondary)
        self.category = category
        self.menu = menu

    async def callback(self, interaction: discord.Interaction):
        self.menu.category = self.category
        self.menu.commands = CATEGORIES[self.category]
        self.menu.current_page = 0
        await interaction.response.edit_message(embed=self.menu.get_embed(), view=self.menu)

class NextPageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="▶", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: HelpMenu = self.view
        max_page = (len(view.commands) - 1) // view.max_per_page
        if view.current_page < max_page:
            view.current_page += 1
            await interaction.response.edit_message(embed=view.get_embed(), view=view)

class PrevPageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: HelpMenu = self.view
        if view.current_page > 0:
            view.current_page -= 1
            await interaction.response.edit_message(embed=view.get_embed(), view=view)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Get help with the bot commands")
    async def help(self, interaction: discord.Interaction):
        default_category = list(CATEGORIES.keys())[0]
        view = HelpMenu(default_category)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=False)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Help cog loaded.")

async def setup(bot):
    await bot.add_cog(Help(bot))
