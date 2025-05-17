import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
from datetime import datetime


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


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Select ticket category",
        custom_id="ticket_category_select",
        options=[
            discord.SelectOption(label="General Support", description="Get help with general questions", emoji="❓"),
            discord.SelectOption(label="Technical Issue", description="Report a technical problem", emoji="🔧"),
            discord.SelectOption(label="Billing Question", description="Ask about billing or payments", emoji="💰"),
            discord.SelectOption(label="Other", description="Other inquiries", emoji="📝")
        ]
    )
    async def ticket_callback(self, interaction, select):
        # Check if user already has an open ticket
        tickets = load_data('tickets')
        for ticket_id, ticket_data in tickets["tickets"].items():
            if ticket_data["user_id"] == interaction.user.id and ticket_data["status"] == "open":
                await interaction.response.send_message("You already have an open ticket!", ephemeral=True)
                return

        # Create new ticket
        category = select.values[0]
        tickets["counter"] += 1
        ticket_number = tickets["counter"]

        # Create ticket channel
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        # Add admin roles to channel permissions
        config = load_data('config')
        for role_id in config.get("admin_roles", []):
            role = guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # Create the channel
        channel = await guild.create_text_channel(
            f"ticket-{ticket_number}",
            overwrites=overwrites,
            reason=f"Ticket created by {interaction.user}"
        )

        # Save ticket data
        tickets["tickets"][str(ticket_number)] = {
            "id": ticket_number,
            "channel_id": channel.id,
            "user_id": interaction.user.id,
            "category": category,
            "status": "open",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "claimed_by": None
        }
        save_data('tickets', tickets)

        # Send confirmation to user
        await interaction.response.send_message(f"Ticket created! Please check {channel.mention}", ephemeral=True)

        # Send initial message in ticket channel
        embed = discord.Embed(
            title=f"Ticket #{ticket_number} - {category}",
            description=f"Thank you for creating a ticket, {interaction.user.mention}!\nAn admin will be with you shortly.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Category", value=category, inline=True)
        embed.add_field(name="Created", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        # Create ticket management buttons
        ticket_controls = TicketControlsView(ticket_number)
        await channel.send(embed=embed, view=ticket_controls)


class TicketControlsView(discord.ui.View):
    def __init__(self, ticket_id):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, custom_id=f"claim_ticket", emoji="🙋‍♂️")
    async def claim_ticket(self, interaction, button):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to claim tickets!", ephemeral=True)
            return

        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        if ticket_data["claimed_by"]:
            await interaction.response.send_message("This ticket has already been claimed!", ephemeral=True)
            return

        # Update ticket data
        ticket_data["claimed_by"] = interaction.user.id
        save_data('tickets', tickets)

        # Update message
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} - {ticket_data['category']}",
            description=f"This ticket has been claimed by {interaction.user.mention}",
            color=discord.Color.green()
        )

        # Disable claim button
        button.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

        # Notify in channel
        await interaction.followup.send(f"{interaction.user.mention} has claimed this ticket!")

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id=f"close_ticket", emoji="🔒")
    async def close_ticket(self, interaction, button):
        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        # Check permissions (ticket creator or admin)
        if interaction.user.id != ticket_data["user_id"] and not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to close this ticket!", ephemeral=True)
            return

        # Show modal for reason
        await interaction.response.send_modal(CloseTicketModal(self.ticket_id))


class CloseTicketModal(discord.ui.Modal):
    def __init__(self, ticket_id):
        super().__init__(title="Close Ticket")
        self.ticket_id = ticket_id

        self.reason = discord.ui.TextInput(
            label="Reason for closing",
            placeholder="Please provide a reason for closing this ticket...",
            min_length=2,
            max_length=1000,
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction):
        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        # Update ticket data
        ticket_data["status"] = "closed"
        ticket_data["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ticket_data["closed_by"] = interaction.user.id
        ticket_data["close_reason"] = self.reason.value
        save_data('tickets', tickets)

        # Send confirmation
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Closed",
            description=f"This ticket has been closed by {interaction.user.mention}",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=self.reason.value, inline=False)
        embed.set_footer(text=f"Closed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        await interaction.response.send_message(embed=embed)

        # Schedule channel deletion
        await interaction.followup.send("This channel will be deleted in 10 seconds...")
        await asyncio.sleep(10)

        channel = interaction.channel
        try:
            await channel.delete(reason=f"Ticket #{self.ticket_id} closed")
        except:
            await interaction.followup.send("Failed to delete channel. Please delete it manually.")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent views
        self.bot.add_view(TicketView())

        # Register persistent ticket control views for all open tickets
        tickets = load_data('tickets')
        for ticket_id, ticket_data in tickets["tickets"].items():
            if ticket_data["status"] == "open":
                self.bot.add_view(TicketControlsView(int(ticket_id)))

    @app_commands.command(name="setup_tickets", description="Set up the ticket system")
    @app_commands.describe(channel="The channel to set up the ticket system in")
    async def setup_tickets(self, interaction, channel: discord.TextChannel = None):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        target_channel = channel or interaction.channel

        embed = discord.Embed(
            title="🎫 Support Ticket System",
            description="Need help? Create a ticket by selecting a category below!",
            color=discord.Color.blue()
        )

        view = TicketView()
        await target_channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"Ticket system set up in {target_channel.mention}!", ephemeral=True)

    @app_commands.command(name="ticket_stats", description="Show ticket statistics")
    async def ticket_stats(self, interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        tickets = load_data('tickets')

        # Count tickets by status and category
        total_tickets = len(tickets["tickets"])
        open_tickets = sum(1 for t in tickets["tickets"].values() if t["status"] == "open")
        closed_tickets = total_tickets - open_tickets

        categories = {}
        for ticket in tickets["tickets"].values():
            category = ticket["category"]
            if category not in categories:
                categories[category] = 0
            categories[category] += 1

        # Create embed
        embed = discord.Embed(
            title="Ticket Statistics",
            description=f"Total tickets: {total_tickets}",
            color=discord.Color.blue()
        )

        embed.add_field(name="Open Tickets", value=str(open_tickets), inline=True)
        embed.add_field(name="Closed Tickets", value=str(closed_tickets), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for spacing

        for category, count in categories.items():
            embed.add_field(name=category, value=str(count), inline=True)

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Tickets(bot))