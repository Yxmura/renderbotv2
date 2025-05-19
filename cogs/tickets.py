import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
import io
import re
import textwrap
from datetime import datetime, timedelta
import logging
import os

# Set up logging
logger = logging.getLogger('bot.tickets')

# Ensure data directory exists
os.makedirs('data', exist_ok=True)


# Load data
def load_data(file):
    try:
        with open(f'data/{file}.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Create default data structure if file doesn't exist
        if file == 'tickets':
            default_data = {"counter": 0, "tickets": {}}
        elif file == 'config':
            default_data = {
                "admin_roles": [],
                "ticket_categories": [
                    {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
                    {"name": "Technical Issue", "emoji": "🔧", "description": "Report a technical problem"},
                    {"name": "Billing Question", "emoji": "💰", "description": "Ask about billing or payments"},
                    {"name": "Other", "emoji": "📝", "description": "Other inquiries"}
                ],
                "ticket_category_id": "",
                "ticket_log_channel": "",
                "ticket_auto_close_hours": 0
            }
        else:
            default_data = {}

        with open(f'data/{file}.json', 'w') as f:
            json.dump(default_data, f, indent=4)

        return default_data


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


# Ticket category select menu
class TicketView(discord.ui.View):
    def __init__(self, categories=None):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect(categories))


class TicketCategorySelect(discord.ui.Select):
    def __init__(self, categories=None):
        # Load default categories if none provided
        if not categories:
            config = load_data('config')
            categories = config.get("ticket_categories", [
                {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
                {"name": "Technical Issue", "emoji": "🔧", "description": "Report a technical problem"},
                {"name": "Billing Question", "emoji": "💰", "description": "Ask about billing or payments"},
                {"name": "Other", "emoji": "📝", "description": "Other inquiries"}
            ])

        # Create options from categories
        options = []
        for category in categories:
            options.append(
                discord.SelectOption(
                    label=category["name"],
                    description=category.get("description", f"Create a {category['name']} ticket"),
                    emoji=category.get("emoji", "🎫"),
                    value=category["name"]
                )
            )

        super().__init__(
            placeholder="Select ticket category",
            custom_id="ticket_category_select",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # Check if user already has an open ticket
        tickets = load_data('tickets')
        for ticket_id, ticket_data in tickets["tickets"].items():
            if ticket_data["user_id"] == interaction.user.id and ticket_data["status"] == "open":
                await interaction.response.send_message("You already have an open ticket!", ephemeral=True)
                return

        # Create new ticket
        category = self.values[0]
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

        # Get ticket category if set
        category_channel = None
        if config.get("ticket_category_id"):
            category_channel = guild.get_channel(int(config["ticket_category_id"]))

        # Create the channel
        try:
            channel = await guild.create_text_channel(
                f"ticket-{ticket_number}",
                overwrites=overwrites,
                category=category_channel,
                reason=f"Ticket created by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to create channels!", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Failed to create ticket channel: {str(e)}", ephemeral=True)
            return

        # Save ticket data
        tickets["tickets"][str(ticket_number)] = {
            "id": ticket_number,
            "channel_id": channel.id,
            "user_id": interaction.user.id,
            "category": category,
            "status": "open",
            "priority": "normal",
            "created_at": datetime.now().isoformat(),
            "claimed_by": None,
            "last_activity": datetime.now().isoformat(),
            "messages": []
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
        embed.add_field(name="Created", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(name="Priority", value="Normal", inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        # Create ticket management buttons
        ticket_controls = TicketControlsView(ticket_number)
        await channel.send(embed=embed, view=ticket_controls)

        # Log ticket creation to log channel
        await self.log_ticket_creation(interaction, ticket_number, category, channel)

        # Log ticket creation
        logger.info(
            f"Ticket #{ticket_number} created by {interaction.user} (ID: {interaction.user.id}) in category {category}")

    async def log_ticket_creation(self, interaction, ticket_number, category, channel):
        """Log ticket creation to the configured log channel"""
        config = load_data('config')
        if not config.get("ticket_log_channel"):
            return

        try:
            log_channel = interaction.guild.get_channel(int(config["ticket_log_channel"]))
            if not log_channel:
                return

            log_embed = discord.Embed(
                title=f"Ticket #{ticket_number} Created",
                description=f"A new ticket has been created",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            log_embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.name})", inline=True)
            log_embed.add_field(name="Category", value=category, inline=True)
            log_embed.add_field(name="Channel", value=channel.mention, inline=True)
            log_embed.set_footer(text=f"User ID: {interaction.user.id}")

            await log_channel.send(embed=log_embed)
        except Exception as e:
            logger.error(f"Failed to log ticket creation: {e}")


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
        ticket_data["last_activity"] = datetime.now().isoformat()
        save_data('tickets', tickets)

        # Update message
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} - {ticket_data['category']}",
            description=f"This ticket has been claimed by {interaction.user.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Category", value=ticket_data['category'], inline=True)
        embed.add_field(name="Created",
                        value=f"<t:{int(datetime.fromisoformat(ticket_data['created_at']).timestamp())}:R>",
                        inline=True)
        embed.add_field(name="Priority", value=ticket_data.get('priority', 'Normal').capitalize(), inline=True)
        embed.set_footer(text=f"User ID: {ticket_data['user_id']}")

        # Disable claim button
        button.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

        # Notify in channel
        await interaction.followup.send(f"{interaction.user.mention} has claimed this ticket!")

        # Log ticket claim
        logger.info(f"Ticket #{self.ticket_id} claimed by {interaction.user} (ID: {interaction.user.id})")

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

    @discord.ui.button(label="Set Priority", style=discord.ButtonStyle.secondary, custom_id=f"priority_ticket",
                       emoji="🔖")
    async def set_priority(self, interaction, button):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to set ticket priority!", ephemeral=True)
            return

        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        # Show priority selection
        await interaction.response.send_message(
            "Select a priority level for this ticket:",
            view=TicketPriorityView(self.ticket_id),
            ephemeral=True
        )

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, custom_id=f"transcript_ticket",
                       emoji="📝")
    async def create_transcript(self, interaction, button):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to create transcripts!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.followup.send("This ticket no longer exists!", ephemeral=True)
            return

        # Generate transcript
        transcript = await self.generate_transcript(interaction.channel, ticket_data)

        # Create file
        transcript_file = discord.File(
            io.BytesIO(transcript.encode('utf-8')),
            filename=f"ticket-{self.ticket_id}-transcript.txt"
        )

        # Send transcript
        await interaction.followup.send(
            "Here's the transcript for this ticket:",
            file=transcript_file,
            ephemeral=True
        )

    async def generate_transcript(self, channel, ticket_data):
        # Fetch messages
        messages = []
        async for message in channel.history(limit=500, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)

        # Format transcript
        transcript = f"Transcript for Ticket #{self.ticket_id}\n"
        transcript += f"Category: {ticket_data['category']}\n"
        transcript += f"Created: {ticket_data['created_at']}\n"
        transcript += f"Creator: {channel.guild.get_member(ticket_data['user_id'])}\n"
        if ticket_data.get('claimed_by'):
            claimer = channel.guild.get_member(ticket_data['claimed_by'])
            transcript += f"Claimed by: {claimer}\n" if claimer else f"Claimed by: Unknown (ID: {ticket_data['claimed_by']})\n"
        transcript += f"Status: {ticket_data['status']}\n"
        transcript += f"Priority: {ticket_data.get('priority', 'normal')}\n\n"
        transcript += "=" * 50 + "\n\n"

        # Add messages
        for message in messages:
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author_name = message.author.display_name

            transcript += f"[{timestamp}] {author_name}: "

            # Handle embeds
            if message.embeds:
                for embed in message.embeds:
                    if embed.title:
                        transcript += f"\n[Embed] {embed.title}"
                    if embed.description:
                        transcript += f"\n{embed.description}"
                    for field in embed.fields:
                        transcript += f"\n{field.name}: {field.value}"

            # Handle regular content
            if message.content:
                transcript += f"{message.content}"

            # Handle attachments
            if message.attachments:
                transcript += f"\n[Attachments: {', '.join([a.filename for a in message.attachments])}]"

            transcript += "\n\n"

        return transcript


class TicketPriorityView(discord.ui.View):
    def __init__(self, ticket_id):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Low", style=discord.ButtonStyle.secondary, custom_id="priority_low")
    async def priority_low(self, interaction, button):
        await self.set_priority(interaction, "low", discord.Color.green())

    @discord.ui.button(label="Normal", style=discord.ButtonStyle.primary, custom_id="priority_normal")
    async def priority_normal(self, interaction, button):
        await self.set_priority(interaction, "normal", discord.Color.blue())

    @discord.ui.button(label="High", style=discord.ButtonStyle.danger, custom_id="priority_high")
    async def priority_high(self, interaction, button):
        await self.set_priority(interaction, "high", discord.Color.orange())

    @discord.ui.button(label="Urgent", style=discord.ButtonStyle.danger, custom_id="priority_urgent")
    async def priority_urgent(self, interaction, button):
        await self.set_priority(interaction, "urgent", discord.Color.red())

    async def set_priority(self, interaction, priority, color):
        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        # Update ticket data
        ticket_data["priority"] = priority
        ticket_data["last_activity"] = datetime.now().isoformat()
        save_data('tickets', tickets)

        # Update channel name to reflect priority
        channel = interaction.channel
        try:
            # Only update if the name doesn't already have a priority prefix
            if not re.match(r'^\[(low|normal|high|urgent)\]', channel.name, re.IGNORECASE):
                await channel.edit(name=f"[{priority.upper()}] {channel.name}")
        except discord.Forbidden:
            pass  # Ignore if we can't edit the channel

        # Send confirmation
        await interaction.response.send_message(f"Ticket priority set to **{priority.capitalize()}**", ephemeral=True)

        # Send notification in channel
        embed = discord.Embed(
            title=f"Priority Updated",
            description=f"This ticket's priority has been set to **{priority.capitalize()}**",
            color=color
        )
        embed.set_footer(text=f"Updated by {interaction.user}")

        await interaction.channel.send(embed=embed)

        # Log priority change
        logger.info(
            f"Ticket #{self.ticket_id} priority set to {priority} by {interaction.user} (ID: {interaction.user.id})")


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

        # Get the ticket creator
        user_id = ticket_data["user_id"]
        user = interaction.guild.get_member(user_id)

        # Check if admin or ticket creator
        is_admin_user = is_admin(interaction)
        is_ticket_creator = interaction.user.id == user_id

        # Send confirmation message with buttons
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Close Request",
            description=f"This ticket has been requested to be closed by {interaction.user.mention}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reason", value=self.reason.value, inline=False)
        embed.set_footer(text=f"Requested at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Create confirmation view
        view = TicketCloseConfirmView(self.ticket_id, self.reason.value, interaction.user.id)

        # Send the message and ping the user outside the embed
        if user:
            await interaction.response.send_message(f"{user.mention}", embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

        # Log the close request
        logger.info(
            f"Ticket #{self.ticket_id} close requested by {interaction.user} (ID: {interaction.user.id}) with reason: {self.reason.value}")

    async def generate_transcript(self, channel, ticket_data):
        # Fetch messages
        messages = []
        async for message in channel.history(limit=500, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)

        # Format transcript
        transcript = f"Transcript for Ticket #{self.ticket_id}\n"
        transcript += f"Category: {ticket_data['category']}\n"
        transcript += f"Created: {ticket_data['created_at']}\n"
        transcript += f"Creator: {channel.guild.get_member(ticket_data['user_id'])}\n"
        if ticket_data.get('claimed_by'):
            claimer = channel.guild.get_member(ticket_data['claimed_by'])
            transcript += f"Claimed by: {claimer}\n" if claimer else f"Claimed by: Unknown (ID: {ticket_data['claimed_by']})\n"
        transcript += f"Status: {ticket_data['status']}\n"
        transcript += f"Priority: {ticket_data.get('priority', 'normal')}\n\n"
        transcript += "=" * 50 + "\n\n"

        # Add messages
        for message in messages:
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author_name = message.author.display_name

            transcript += f"[{timestamp}] {author_name}: "

            # Handle embeds
            if message.embeds:
                for embed in message.embeds:
                    if embed.title:
                        transcript += f"\n[Embed] {embed.title}"
                    if embed.description:
                        transcript += f"\n{embed.description}"
                    for field in embed.fields:
                        transcript += f"\n{field.name}: {field.value}"

            # Handle regular content
            if message.content:
                transcript += f"{message.content}"

            # Handle attachments
            if message.attachments:
                transcript += f"\n[Attachments: {', '.join([a.filename for a in message.attachments])}]"

            transcript += "\n\n"

        return transcript


class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, ticket_id, reason, closer_id):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.ticket_id = ticket_id
        self.reason = reason
        self.closer_id = closer_id

    @discord.ui.button(label="Confirm Close", style=discord.ButtonStyle.green, custom_id="confirm_close")
    async def confirm_close(self, interaction, button):
        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        # Check if user is the ticket creator
        if interaction.user.id != ticket_data["user_id"] and not is_admin(interaction):
            await interaction.response.send_message(
                "Only the ticket creator or an admin can confirm closing the ticket!", ephemeral=True)
            return

        await self.close_ticket(interaction, "confirmed by user")

    @discord.ui.button(label="Deny Close", style=discord.ButtonStyle.red, custom_id="deny_close")
    async def deny_close(self, interaction, button):
        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        # Check if user is the ticket creator
        if interaction.user.id != ticket_data["user_id"] and not is_admin(interaction):
            await interaction.response.send_message("Only the ticket creator or an admin can deny closing the ticket!",
                                                    ephemeral=True)
            return

        # Update the message to show denial
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Close Request Denied",
            description=f"The request to close this ticket has been denied by {interaction.user.mention}",
            color=discord.Color.red()
        )

        # Disable all buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        # Log the denial
        logger.info(f"Ticket #{self.ticket_id} close request denied by {interaction.user} (ID: {interaction.user.id})")

    @discord.ui.button(label="Force Close", style=discord.ButtonStyle.danger, custom_id="force_close")
    async def force_close(self, interaction, button):
        if not is_admin(interaction):
            await interaction.response.send_message("Only admins can force close tickets!", ephemeral=True)
            return

        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.response.send_message("This ticket no longer exists!", ephemeral=True)
            return

        await self.close_ticket(interaction, "force closed by admin")

    async def close_ticket(self, interaction, close_type):
        await interaction.response.defer()

        tickets = load_data('tickets')
        ticket_data = tickets["tickets"].get(str(self.ticket_id))

        if not ticket_data:
            await interaction.followup.send("This ticket no longer exists!")
            return

        # Update ticket data
        ticket_data["status"] = "closed"
        ticket_data["closed_at"] = datetime.now().isoformat()
        ticket_data["closed_by"] = interaction.user.id
        ticket_data["close_reason"] = self.reason
        ticket_data["close_type"] = close_type
        save_data('tickets', tickets)

        # Generate transcript before closing
        transcript = await self.generate_transcript(interaction.channel, ticket_data)

        # Create transcript file
        transcript_file = discord.File(
            io.BytesIO(transcript.encode('utf-8')),
            filename=f"ticket-{self.ticket_id}-transcript.txt"
        )

        # Send confirmation
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Closed",
            description=f"This ticket has been {close_type}",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=self.reason, inline=False)
        embed.set_footer(text=f"Closed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Disable all buttons in the view
        for child in self.children:
            child.disabled = True

        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(file=transcript_file)

        # Log transcript to log channel if configured
        await self.log_ticket_closure(interaction, ticket_data, transcript)

        # Schedule channel deletion
        await interaction.followup.send("This channel will be deleted in 10 seconds...")
        await asyncio.sleep(10)

        channel = interaction.channel
        try:
            await channel.delete(reason=f"Ticket #{self.ticket_id} closed")
        except Exception as e:
            await interaction.followup.send(f"Failed to delete channel: {e}. Please delete it manually.")

        # Log ticket closure
        logger.info(
            f"Ticket #{self.ticket_id} closed by {interaction.user} (ID: {interaction.user.id}) with reason: {self.reason}")

    async def log_ticket_closure(self, interaction, ticket_data, transcript):
        """Log ticket closure to the configured log channel"""
        config = load_data('config')
        if not config.get("ticket_log_channel"):
            return

        try:
            log_channel = interaction.guild.get_channel(int(config["ticket_log_channel"]))
            if not log_channel:
                return

            # Create log embed
            log_embed = discord.Embed(
                title=f"Ticket #{self.ticket_id} Closed",
                description=f"Ticket created by <@{ticket_data['user_id']}> has been closed",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            log_embed.add_field(name="Category", value=ticket_data["category"], inline=True)
            log_embed.add_field(name="Closed by", value=f"<@{interaction.user.id}>", inline=True)
            log_embed.add_field(name="Close type", value=ticket_data.get("close_type", "closed"), inline=True)
            log_embed.add_field(name="Reason", value=self.reason, inline=False)

            # Send log with transcript
            await log_channel.send(
                embed=log_embed,
                file=discord.File(
                    io.BytesIO(transcript.encode('utf-8')),
                    filename=f"ticket-{self.ticket_id}-transcript.txt"
                )
            )
        except Exception as e:
            logger.error(f"Failed to log ticket closure: {e}")

    async def generate_transcript(self, channel, ticket_data):
        # Fetch messages
        messages = []
        async for message in channel.history(limit=500, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)

        # Format transcript
        transcript = f"Transcript for Ticket #{self.ticket_id}\n"
        transcript += f"Category: {ticket_data['category']}\n"
        transcript += f"Created: {ticket_data['created_at']}\n"

        creator = channel.guild.get_member(ticket_data['user_id'])
        transcript += f"Creator: {creator}\n" if creator else f"Creator: Unknown (ID: {ticket_data['user_id']})\n"

        if ticket_data.get('claimed_by'):
            claimer = channel.guild.get_member(ticket_data['claimed_by'])
            transcript += f"Claimed by: {claimer}\n" if claimer else f"Claimed by: Unknown (ID: {ticket_data['claimed_by']})\n"

        transcript += f"Status: {ticket_data['status']}\n"
        transcript += f"Priority: {ticket_data.get('priority', 'normal')}\n"
        transcript += f"Close Reason: {self.reason}\n\n"
        transcript += "=" * 50 + "\n\n"

        # Add messages
        for message in messages:
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author_name = message.author.display_name

            transcript += f"[{timestamp}] {author_name}: "

            # Handle embeds
            if message.embeds:
                for embed in message.embeds:
                    if embed.title:
                        transcript += f"\n[Embed] {embed.title}"
                    if embed.description:
                        transcript += f"\n{embed.description}"
                    for field in embed.fields:
                        transcript += f"\n{field.name}: {field.value}"

            # Handle regular content
            if message.content:
                transcript += f"{message.content}"

            # Handle attachments
            if message.attachments:
                transcript += f"\n[Attachments: {', '.join([a.filename for a in message.attachments])}]"

            transcript += "\n\n"

        return transcript


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Start auto-close task
        self.auto_close_task = self.bot.loop.create_task(self.check_inactive_tickets())

    def cog_unload(self):
        # Cancel the task when the cog is unloaded
        self.auto_close_task.cancel()

    async def check_inactive_tickets(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                config = load_data('config')
                auto_close_hours = config.get("ticket_auto_close_hours", 0)

                # Skip if auto-close is disabled
                if auto_close_hours <= 0:
                    await asyncio.sleep(3600)  # Check once per hour
                    continue

                tickets = load_data('tickets')
                now = datetime.now()

                for ticket_id, ticket_data in list(tickets["tickets"].items()):
                    if ticket_data["status"] == "open":
                        last_activity = datetime.fromisoformat(ticket_data["last_activity"])
                        inactive_time = now - last_activity

                        # Auto-close if inactive for the configured time
                        if inactive_time.total_seconds() > auto_close_hours * 3600:
                            await self.auto_close_ticket(ticket_id, ticket_data)
            except Exception as e:
                logger.error(f"Error checking inactive tickets: {e}")

            # Check every hour
            await asyncio.sleep(3600)

    async def auto_close_ticket(self, ticket_id, ticket_data):
        # Update ticket data
        ticket_data["status"] = "closed"
        ticket_data["closed_at"] = datetime.now().isoformat()
        ticket_data["closed_by"] = self.bot.user.id
        ticket_data["close_reason"] = "Automatically closed due to inactivity"
        ticket_data["close_type"] = "auto-closed due to inactivity"

        tickets = load_data('tickets')
        tickets["tickets"][ticket_id] = ticket_data
        save_data('tickets', tickets)

        # Try to get the channel
        channel = self.bot.get_channel(ticket_data["channel_id"])
        if not channel:
            return

        # Generate transcript
        transcript = await self.generate_transcript(channel, ticket_data)

        # Send closure message
        embed = discord.Embed(
            title=f"Ticket #{ticket_id} Auto-Closed",
            description="This ticket has been automatically closed due to inactivity.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Closed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            await channel.send(
                embed=embed,
                file=discord.File(
                    io.BytesIO(transcript.encode('utf-8')),
                    filename=f"ticket-{ticket_id}-transcript.txt"
                )
            )
        except:
            pass

        # Log transcript to log channel if configured
        await self.log_ticket_closure(channel.guild, ticket_id, ticket_data, transcript)

        # Delete the channel
        try:
            await asyncio.sleep(10)
            await channel.delete(reason=f"Ticket #{ticket_id} auto-closed due to inactivity")
        except:
            pass

        # Log ticket auto-closure
        logger.info(f"Ticket #{ticket_id} auto-closed due to inactivity")

    async def log_ticket_closure(self, guild, ticket_id, ticket_data, transcript):
        """Log ticket closure to the configured log channel"""
        config = load_data('config')
        if not config.get("ticket_log_channel"):
            return

        try:
            log_channel = guild.get_channel(int(config["ticket_log_channel"]))
            if not log_channel:
                return

            # Create log embed
            log_embed = discord.Embed(
                title=f"Ticket #{ticket_id} Auto-Closed",
                description=f"Ticket created by <@{ticket_data['user_id']}> was automatically closed due to inactivity",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            log_embed.add_field(name="Category", value=ticket_data["category"], inline=True)

            # Send log with transcript
            await log_channel.send(
                embed=log_embed,
                file=discord.File(
                    io.BytesIO(transcript.encode('utf-8')),
                    filename=f"ticket-{ticket_id}-transcript.txt"
                )
            )
        except Exception as e:
            logger.error(f"Failed to log auto-closed ticket: {e}")

    async def generate_transcript(self, channel, ticket_data):
        # Fetch messages
        messages = []
        try:
            async for message in channel.history(limit=500, oldest_first=True):
                if not message.author.bot or (message.author.bot and message.embeds):
                    messages.append(message)
        except:
            # If we can't fetch history, return a basic transcript
            return f"Transcript for Ticket #{ticket_data['id']}\nCould not fetch message history."

        # Format transcript
        transcript = f"Transcript for Ticket #{ticket_data['id']}\n"
        transcript += f"Category: {ticket_data['category']}\n"
        transcript += f"Created: {ticket_data['created_at']}\n"

        creator = channel.guild.get_member(ticket_data['user_id'])
        transcript += f"Creator: {creator}\n" if creator else f"Creator: Unknown (ID: {ticket_data['user_id']})\n"

        if ticket_data.get('claimed_by'):
            claimer = channel.guild.get_member(ticket_data['claimed_by'])
            transcript += f"Claimed by: {claimer}\n" if claimer else f"Claimed by: Unknown (ID: {ticket_data['claimed_by']})\n"

        transcript += f"Status: {ticket_data['status']}\n"
        transcript += f"Priority: {ticket_data.get('priority', 'normal')}\n\n"
        transcript += "=" * 50 + "\n\n"

        # Add messages
        for message in messages:
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author_name = message.author.display_name

            transcript += f"[{timestamp}] {author_name}: "

            # Handle embeds
            if message.embeds:
                for embed in message.embeds:
                    if embed.title:
                        transcript += f"\n[Embed] {embed.title}"
                    if embed.description:
                        transcript += f"\n{embed.description}"
                    for field in embed.fields:
                        transcript += f"\n{field.name}: {field.value}"

            # Handle regular content
            if message.content:
                transcript += f"{message.content}"

            # Handle attachments
            if message.attachments:
                transcript += f"\n[Attachments: {', '.join([a.filename for a in message.attachments])}]"

            transcript += "\n\n"

        return transcript

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent views
        self.bot.add_view(TicketView())

        # Register persistent ticket control views for all open tickets
        tickets = load_data('tickets')
        for ticket_id, ticket_data in tickets["tickets"].items():
            if ticket_data["status"] == "open":
                self.bot.add_view(TicketControlsView(int(ticket_id)))

    @commands.Cog.listener()
    async def on_message(self, message):
        # Update last activity for tickets
        if message.author.bot:
            return

        # Check if message is in a ticket channel
        if not message.guild:
            return

        tickets = load_data('tickets')
        for ticket_id, ticket_data in tickets["tickets"].items():
            if ticket_data["channel_id"] == message.channel.id and ticket_data["status"] == "open":
                # Update last activity
                ticket_data["last_activity"] = datetime.now().isoformat()

                # Store message in ticket data (limited to 100 messages)
                if "messages" not in ticket_data:
                    ticket_data["messages"] = []

                ticket_data["messages"].append({
                    "author_id": message.author.id,
                    "content": message.content,
                    "timestamp": message.created_at.isoformat()
                })

                # Keep only the last 100 messages
                if len(ticket_data["messages"]) > 100:
                    ticket_data["messages"] = ticket_data["messages"][-100:]

                save_data('tickets', tickets)
                break

    @app_commands.command(name="setup_tickets", description="Set up the ticket system")
    @app_commands.describe(channel="The channel to set up the ticket system in")
    async def setup_tickets(self, interaction, channel: discord.TextChannel = None):
        # Defer response to prevent timeout
        await interaction.response.defer(ephemeral=True)

        if not is_admin(interaction):
            await interaction.followup.send("You don't have permission to use this command!", ephemeral=True)
            return

        target_channel = channel or interaction.channel

        embed = discord.Embed(
            title="🎫 Support Ticket System",
            description="Need help? Create a ticket by selecting a category below!",
            color=discord.Color.blue()
        )

        view = TicketView()
        await target_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"Ticket system set up in {target_channel.mention}!", ephemeral=True)

        # Log setup
        logger.info(
            f"Ticket system set up in channel {target_channel.id} by {interaction.user} (ID: {interaction.user.id})")

    @app_commands.command(name="ticket_panel", description="Create a customized ticket panel")
    @app_commands.describe(
        channel="The channel to set up the ticket panel in",
        title="The title for the ticket panel",
        description="The description for the ticket panel",
        color="The color for the embed (hex code like #FF0000)"
    )
    async def ticket_panel(
            self,
            interaction,
            channel: discord.TextChannel = None,
            title: str = "🎫 Support Ticket System",
            description: str = "Need help? Create a ticket by selecting a category below!",
            color: str = "#3498db"
    ):
        # Defer response to prevent timeout
        await interaction.response.defer(ephemeral=True)

        if not is_admin(interaction):
            await interaction.followup.send("You don't have permission to use this command!", ephemeral=True)
            return

        target_channel = channel or interaction.channel

        # Parse color
        try:
            if color.startswith('#'):
                color = color[1:]
            color_value = int(color, 16)
        except ValueError:
            await interaction.followup.send("Invalid color format! Use hex code like #FF0000", ephemeral=True)
            return

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color(color_value)
        )

        embed.set_footer(text=f"Created by {interaction.user}")

        view = TicketView()
        await target_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"Custom ticket panel created in {target_channel.mention}!", ephemeral=True)

        # Log setup
        logger.info(
            f"Custom ticket panel created in channel {target_channel.id} by {interaction.user} (ID: {interaction.user.id})")

    @app_commands.command(name="ticket_categories", description="Customize ticket categories")
    async def ticket_categories(self, interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        # Show modal for category customization
        await interaction.response.send_modal(TicketCategoriesModal())

    @app_commands.command(name="ticket_settings", description="Configure ticket system settings")
    async def ticket_settings(self, interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        # Show modal for settings
        await interaction.response.send_modal(TicketSettingsModal(self.bot))

    @app_commands.command(name="ticket_stats", description="Show ticket statistics")
    async def ticket_stats(self, interaction):
        # Defer response to prevent timeout
        await interaction.response.defer(ephemeral=True)

        if not is_admin(interaction):
            await interaction.followup.send("You don't have permission to use this command!", ephemeral=True)
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

        # Count tickets by priority
        priorities = {
            "low": 0,
            "normal": 0,
            "high": 0,
            "urgent": 0
        }

        for ticket in tickets["tickets"].values():
            priority = ticket.get("priority", "normal").lower()
            if priority in priorities:
                priorities[priority] += 1

        # Create embed
        embed = discord.Embed(
            title="Ticket Statistics",
            description=f"Total tickets: {total_tickets}",
            color=discord.Color.blue()
        )

        embed.add_field(name="Open Tickets", value=str(open_tickets), inline=True)
        embed.add_field(name="Closed Tickets", value=str(closed_tickets), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for spacing

        # Add categories
        categories_text = ""
        for category, count in categories.items():
            categories_text += f"**{category}**: {count}\n"

        if categories_text:
            embed.add_field(name="Categories", value=categories_text, inline=False)

        # Add priorities
        priorities_text = ""
        for priority, count in priorities.items():
            if count > 0:
                priorities_text += f"**{priority.capitalize()}**: {count}\n"

        if priorities_text:
            embed.add_field(name="Priorities", value=priorities_text, inline=False)

        # Add recent activity
        recent_tickets = sorted(
            [t for t in tickets["tickets"].values() if t["status"] == "open"],
            key=lambda t: datetime.fromisoformat(t["last_activity"]),
            reverse=True
        )[:5]

        if recent_tickets:
            recent_text = ""
            for ticket in recent_tickets:
                last_activity = datetime.fromisoformat(ticket["last_activity"])
                recent_text += f"**Ticket #{ticket['id']}** - <t:{int(last_activity.timestamp())}:R>\n"

            embed.add_field(name="Recent Activity", value=recent_text, inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ticket_help", description="Get help with the ticket system")
    async def ticket_help(self, interaction):
        embed = discord.Embed(
            title="Ticket System Help",
            description="Here's how to use the ticket system:",
            color=discord.Color.blue()
        )

        # User commands
        embed.add_field(
            name="For Users",
            value=(
                "1. Click on the dropdown menu in the ticket panel\n"
                "2. Select the appropriate category for your issue\n"
                "3. A new ticket channel will be created for you\n"
                "4. Explain your issue in the ticket channel\n"
                "5. Wait for a staff member to assist you\n"
                "6. When your issue is resolved, you can close the ticket"
            ),
            inline=False
        )

        # Admin commands
        if is_admin(interaction):
            embed.add_field(
                name="For Admins",
                value=(
                    "`/setup_tickets [channel]` - Create a basic ticket panel\n"
                    "`/ticket_panel [channel] [title] [description] [color]` - Create a customized ticket panel\n"
                    "`/ticket_categories` - Customize ticket categories\n"
                    "`/ticket_settings` - Configure ticket system settings\n"
                    "`/ticket_stats` - View ticket statistics"
                ),
                inline=False
            )

            embed.add_field(
                name="In Ticket Channels",
                value=(
                    "• Click 'Claim Ticket' to assign yourself to a ticket\n"
                    "• Click 'Set Priority' to change the ticket's priority\n"
                    "• Click 'Transcript' to generate a transcript of the ticket\n"
                    "• Click 'Close Ticket' to close and delete the ticket\n"
                    "• The ticket will be automatically deleted 10 seconds after closing"
                ),
                inline=False
            )

            embed.add_field(
                name="Auto-Close Feature",
                value=(
                    "Tickets can be automatically closed after a period of inactivity.\n"
                    "Use `/ticket_settings` to configure the auto-close time in hours.\n"
                    "Set to 0 to disable auto-closing."
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="close_all_tickets", description="Close all open tickets (Admin only)")
    async def close_all_tickets(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to use this command!",
                                                    ephemeral=True)
            return

        # Confirm action
        embed = discord.Embed(
            title="⚠️ Close All Tickets",
            description="Are you sure you want to close ALL open tickets? This action cannot be undone.",
            color=discord.Color.red()
        )

        await interaction.response.send_message(embed=embed, view=CloseAllTicketsView(), ephemeral=True)


class TicketCategoriesModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Customize Ticket Categories")

        # Load current categories
        config = load_data('config')
        categories = config.get("ticket_categories", [
            {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
            {"name": "Technical Issue", "emoji": "🔧", "description": "Report a technical problem"},
            {"name": "Billing Question", "emoji": "💰", "description": "Ask about billing or payments"},
            {"name": "Other", "emoji": "📝", "description": "Other inquiries"}
        ])

        # Format categories for display
        categories_text = ""
        for category in categories:
            categories_text += f"{category['name']},{category.get('emoji', '🎫')},{category.get('description', '')}\n"

        self.categories = discord.ui.TextInput(
            label="Categories (name,emoji,description)",
            placeholder="General Support,❓,Get help with general questions\nTechnical Issue,🔧,Report a technical problem",
            required=True,
            style=discord.TextStyle.paragraph,
            default=categories_text.strip()
        )
        self.add_item(self.categories)

    async def on_submit(self, interaction):
        # Parse categories
        categories = []
        for line in self.categories.value.split('\n'):
            if not line.strip():
                continue

            parts = line.split(',', 2)
            if len(parts) >= 1:
                category = {"name": parts[0].strip()}
                if len(parts) >= 2:
                    category["emoji"] = parts[1].strip()
                if len(parts) >= 3:
                    category["description"] = parts[2].strip()

                categories.append(category)

        if not categories:
            await interaction.response.send_message("You must specify at least one category!", ephemeral=True)
            return

        # Save categories
        config = load_data('config')
        config["ticket_categories"] = categories
        save_data('config', config)

        # Send confirmation
        categories_text = "\n".join([f"• {c['name']} {c.get('emoji', '')}" for c in categories])

        embed = discord.Embed(
            title="Ticket Categories Updated",
            description=f"The following categories have been set:\n\n{categories_text}",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Log category update
        logger.info(f"Ticket categories updated by {interaction.user} (ID: {interaction.user.id})")


class TicketSettingsModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Ticket System Settings")
        self.bot = bot

        # Load current settings
        config = load_data('config')

        self.category_id = discord.ui.TextInput(
            label="Ticket Category ID (optional)",
            placeholder="ID of the category to create tickets in",
            required=False,
            default=config.get("ticket_category_id", "")
        )
        self.add_item(self.category_id)

        self.log_channel_id = discord.ui.TextInput(
            label="Log Channel ID (optional)",
            placeholder="ID of the channel to log ticket transcripts",
            required=False,
            default=config.get("ticket_log_channel", "")
        )
        self.add_item(self.log_channel_id)

        self.auto_close_hours = discord.ui.TextInput(
            label="Auto-close Hours (0 to disable)",
            placeholder="Number of hours of inactivity before auto-closing",
            required=False,
            default=str(config.get("ticket_auto_close_hours", "0"))
        )
        self.add_item(self.auto_close_hours)

    async def on_submit(self, interaction):
        # Validate inputs
        config = load_data('config')

        # Category ID
        if self.category_id.value:
            try:
                category_id = int(self.category_id.value)
                category = interaction.guild.get_channel(category_id)
                if not category or not isinstance(category, discord.CategoryChannel):
                    await interaction.response.send_message(
                        "Invalid category ID! Please provide a valid category channel ID.", ephemeral=True)
                    return

                config["ticket_category_id"] = str(category_id)
            except ValueError:
                await interaction.response.send_message("Invalid category ID! Please provide a valid number.",
                                                        ephemeral=True)
                return
        else:
            config["ticket_category_id"] = ""

        # Log channel ID
        if self.log_channel_id.value:
            try:
                log_channel_id = int(self.log_channel_id.value)
                log_channel = interaction.guild.get_channel(log_channel_id)
                if not log_channel or not isinstance(log_channel, discord.TextChannel):
                    await interaction.response.send_message(
                        "Invalid log channel ID! Please provide a valid text channel ID.", ephemeral=True)
                    return

                config["ticket_log_channel"] = str(log_channel_id)
            except ValueError:
                await interaction.response.send_message("Invalid log channel ID! Please provide a valid number.",
                                                        ephemeral=True)
                return
        else:
            config["ticket_log_channel"] = ""

        # Auto-close hours
        if self.auto_close_hours.value:
            try:
                auto_close_hours = int(self.auto_close_hours.value)
                if auto_close_hours < 0:
                    await interaction.response.send_message("Auto-close hours must be 0 or greater!", ephemeral=True)
                    return

                config["ticket_auto_close_hours"] = auto_close_hours
            except ValueError:
                await interaction.response.send_message("Invalid auto-close hours! Please provide a valid number.",
                                                        ephemeral=True)
                return
        else:
            config["ticket_auto_close_hours"] = 0

        # Save settings
        save_data('config', config)

        # Create confirmation embed
        embed = discord.Embed(
            title="Ticket Settings Updated",
            color=discord.Color.green()
        )

        if config.get("ticket_category_id"):
            category = interaction.guild.get_channel(int(config["ticket_category_id"]))
            embed.add_field(name="Ticket Category", value=category.mention if category else "Invalid Category",
                            inline=False)

        if config.get("ticket_log_channel"):
            log_channel = interaction.guild.get_channel(int(config["ticket_log_channel"]))
            embed.add_field(name="Log Channel", value=log_channel.mention if log_channel else "Invalid Channel",
                            inline=False)

        auto_close_hours = config.get("ticket_auto_close_hours", 0)
        if auto_close_hours > 0:
            embed.add_field(name="Auto-close", value=f"After {auto_close_hours} hours of inactivity", inline=False)
        else:
            embed.add_field(name="Auto-close", value="Disabled", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Log settings update
        logger.info(f"Ticket settings updated by {interaction.user} (ID: {interaction.user.id})")


class CloseAllTicketsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, close all tickets", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        tickets = load_data('tickets')
        open_tickets = {tid: t for tid, t in tickets["tickets"].items() if t["status"] == "open"}

        if not open_tickets:
            await interaction.followup.send("There are no open tickets to close!", ephemeral=True)
            return

        # Close all open tickets
        closed_count = 0
        for ticket_id, ticket_data in open_tickets.items():
            # Update ticket data
            ticket_data["status"] = "closed"
            ticket_data["closed_at"] = datetime.now().isoformat()
            ticket_data["closed_by"] = interaction.user.id
            ticket_data["close_reason"] = "Mass closure by administrator"
            ticket_data["close_type"] = "mass closed by administrator"

            # Try to delete the channel
            channel = interaction.guild.get_channel(ticket_data["channel_id"])
            if channel:
                try:
                    await channel.delete(reason=f"Mass ticket closure by {interaction.user}")
                    closed_count += 1
                except:
                    pass

        # Save updated ticket data
        save_data('tickets', tickets)

        # Send confirmation
        await interaction.followup.send(f"Successfully closed {closed_count} tickets!", ephemeral=True)

        # Log mass closure
        logger.info(
            f"Mass ticket closure: {closed_count} tickets closed by {interaction.user} (ID: {interaction.user.id})")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.send_message("Action cancelled.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))