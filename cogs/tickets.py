import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
from datetime import datetime, timedelta, timezone
import asyncio
from typing import Optional, Dict, Any, List, Tuple
import requests
from PIL import Image, ImageDraw, ImageFont
import textwrap
import os

class TicketData:
    @staticmethod
    def load(filename: str) -> Dict[str, Any]:
        try:
            with open(f'data/{filename}.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            if filename == 'tickets':
                return {"tickets": {}, "reaction_roles": {}, "blacklist": [], "templates": {}, "webhooks": {}}
            return {}

    @staticmethod
    def save(filename: str, data: Dict[str, Any]) -> None:
        with open(f'data/{filename}.json', 'w') as f:
            json.dump(data, f, indent=2)

class TicketManager:
    def __init__(self):
        self.data = TicketData.load('tickets')
        self.counter = self._get_next_counter()

    def _get_next_counter(self) -> int:
        if not self.data["tickets"]:
            return 1
        max_num = 0
        for ticket_id in self.data["tickets"].keys():
            if ticket_id.startswith("T") and ticket_id[1:].isdigit():
                max_num = max(max_num, int(ticket_id[1:]))
        return max_num + 1

    def create_ticket(self, ticket_data: Dict[str, Any]) -> str:
        ticket_id = f"T{self.counter:04d}"
        self.counter += 1
        ticket_data["ticket_id"] = ticket_id
        self.data["tickets"][ticket_id] = ticket_data
        TicketData.save('tickets', self.data)
        return ticket_id

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        return self.data["tickets"].get(ticket_id)

    def get_channel_ticket(self, channel_id: int) -> Optional[Dict[str, Any]]:
        for ticket in self.data["tickets"].values():
            if ticket.get("channel_id") == channel_id:
                return ticket
        return None

    def get_user_tickets(self, user_id: int) -> List[Dict[str, Any]]:
        return [t for t in self.data["tickets"].values() 
                if t["user_id"] == user_id and t["status"] == "open"]

    def get_all_tickets(self) -> Dict[str, Dict[str, Any]]:
        return self.data["tickets"]

    def update_ticket(self, ticket_id: str, updates: Dict[str, Any]) -> None:
        if ticket_id in self.data["tickets"]:
            self.data["tickets"][ticket_id].update(updates)
            TicketData.save('tickets', self.data)

    def delete_ticket(self, ticket_id: str) -> None:
        if ticket_id in self.data["tickets"]:
            del self.data["tickets"][ticket_id]
            TicketData.save('tickets', self.data)

    def add_to_blacklist(self, user_id: int):
        if "blacklist" not in self.data:
            self.data["blacklist"] = []
        if user_id not in self.data["blacklist"]:
            self.data["blacklist"].append(user_id)
            TicketData.save('tickets', self.data)

    def remove_from_blacklist(self, user_id: int):
        if "blacklist" in self.data and user_id in self.data["blacklist"]:
            self.data["blacklist"].remove(user_id)
            TicketData.save('tickets', self.data)

    def is_blacklisted(self, user_id: int) -> bool:
        return user_id in self.data.get("blacklist", [])

ticket_manager = TicketManager()

class ConfigManager:
    @staticmethod
    def load() -> Dict[str, Any]:
        config = TicketData.load('config')
        if not config:
            config = {
                "admin_roles": [],
                "ticket_categories": [
                    {"name": "General Support", "emoji": "❓", "description": "Get help with general questions", "color": "blue"},
                    {"name": "Resource Issue", "emoji": "⚠️", "description": "Report a problem with a resource", "color": "yellow"},
                    {"name": "Partner/Sponsor", "emoji": "💰", "description": "Partner or sponsorship inquiries", "color": "green"},
                    {"name": "Staff Application", "emoji": "🔒", "description": "Apply to join our staff team", "color": "purple"},
                    {"name": "Other", "emoji": "📝", "description": "Other inquiries", "color": "grey"}
                ],
                "ticket_category_id": "",
                "ticket_log_channel": "",
                "ticket_auto_close_hours": 24,
                "support_role_id": "",
                "welcome_message": "Thank you for creating a ticket! Our staff will assist you shortly.",
                "max_tickets_per_user": 1,
                "enable_rating": True,
                "enable_archiving": True,
                "archive_category_id": "",
                "enable_logging": True
            }
            TicketData.save('config', config)
        return config

    @staticmethod
    def save(config: Dict[str, Any]) -> None:
        TicketData.save('config', config)

class CategoryModal(discord.ui.Modal):
    def __init__(self, category: str):
        super().__init__(title=f"{category} Ticket")
        self.category = category
        
        if category == "General Support":
            self.short_desc = discord.ui.TextInput(label="What do you need help with?", placeholder="Brief description", max_length=100, required=True)
            self.details = discord.ui.TextInput(label="Detailed description", placeholder="Please provide details", style=discord.TextStyle.paragraph, max_length=1000, required=True)
        elif category == "Resource Issue":
            self.short_desc = discord.ui.TextInput(label="Resource name", placeholder="Name of the resource", max_length=100, required=True)
            self.details = discord.ui.TextInput(label="Issue description", placeholder="Describe the problem", style=discord.TextStyle.paragraph, max_length=1000, required=True)
        elif category == "Partner/Sponsor":
            self.short_desc = discord.ui.TextInput(label="Company/Organization", placeholder="Your company name", max_length=100, required=True)
            self.details = discord.ui.TextInput(label="Partnership details", placeholder="Describe your partnership proposal", style=discord.TextStyle.paragraph, max_length=1000, required=True)
        elif category == "Staff Application":
            self.short_desc = discord.ui.TextInput(label="Position applying for", placeholder="Staff position", max_length=100, required=True)
            self.details = discord.ui.TextInput(label="Experience", placeholder="Your relevant experience", style=discord.TextStyle.paragraph, max_length=1000, required=True)
        else:
            self.short_desc = discord.ui.TextInput(label="Subject", placeholder="Brief subject", max_length=100, required=True)
            self.details = discord.ui.TextInput(label="Details", placeholder="Please provide details", style=discord.TextStyle.paragraph, max_length=1000, required=True)
        
        self.add_item(self.short_desc)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_cog = interaction.client.get_cog('Tickets')
        if ticket_cog:
            await ticket_cog.create_ticket_channel(interaction, self.category, {
                "short_desc": self.short_desc.value,
                "details": self.details.value
            })

class StaffApplicationModal(discord.ui.Modal):
    def __init__(self, position: str):
        super().__init__(title=f"Staff Application - {position}")
        self.position = position
        
        self.q1 = discord.ui.TextInput(label="Why do you want to join our staff?", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.q2 = discord.ui.TextInput(label="Previous experience", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.q3 = discord.ui.TextInput(label="Availability per week", style=discord.TextStyle.short, max_length=50, required=True)
        self.q4 = discord.ui.TextInput(label="Timezone", style=discord.TextStyle.short, max_length=50, required=True)
        self.q5 = discord.ui.TextInput(label="Additional information", style=discord.TextStyle.paragraph, max_length=500, required=False)
        
        self.add_item(self.q1)
        self.add_item(self.q2)
        self.add_item(self.q3)
        self.add_item(self.q4)
        self.add_item(self.q5)

class PrioritySelect(discord.ui.Select):
    def __init__(self, ticket_id: str):
        options = [
            discord.SelectOption(label="Urgent", value="urgent", emoji="🔴", description="Critical issue requiring immediate attention"),
            discord.SelectOption(label="High", value="high", emoji="🟠", description="Important issue to address soon"),
            discord.SelectOption(label="Normal", value="normal", emoji="🟡", description="Standard priority"),
            discord.SelectOption(label="Low", value="low", emoji="🔵", description="Minor issue or suggestion")
        ]
        super().__init__(placeholder="Select priority...", min_values=1, max_values=1, options=options)
        self.ticket_id = ticket_id

    async def callback(self, interaction: discord.Interaction):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to change priority.", ephemeral=True)
            return

        priority = self.values[0]
        ticket_manager.update_ticket(self.ticket_id, {"priority": priority})
        
        channel = interaction.client.get_channel(ticket["channel_id"])
        if channel:
            embed = discord.Embed(
                description=f"🎯 Priority changed to **{priority.upper()}** by {interaction.user.mention}",
                color=discord.Color.orange()
            )
            await channel.send(embed=embed)
        
        await interaction.response.send_message(f"Priority set to {priority.upper()}", ephemeral=True)

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        config = ConfigManager.load()
        admin_roles = config.get("admin_roles", [])
        
        if not admin_roles:
            return interaction.user.guild_permissions.administrator
        
        for role_id in admin_roles:
            role = interaction.guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                return True
        
        return interaction.user.guild_permissions.administrator

class TicketControls(discord.ui.View):
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.blurple, emoji="👤", custom_id="ticket_claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to claim tickets.", ephemeral=True)
            return

        if ticket.get("claimed_by") == interaction.user.id:
            ticket_manager.update_ticket(self.ticket_id, {"claimed_by": None})
            await interaction.response.send_message("You have unclaimed this ticket.", ephemeral=True)
            embed = discord.Embed(description=f"🔓 Ticket unclaimed by {interaction.user.mention}", color=discord.Color.orange())
        else:
            ticket_manager.update_ticket(self.ticket_id, {"claimed_by": interaction.user.id})
            await interaction.response.send_message("You have claimed this ticket!", ephemeral=True)
            embed = discord.Embed(description=f"👤 Ticket claimed by {interaction.user.mention}", color=discord.Color.green())
        
        await interaction.channel.send(embed=embed)

    @discord.ui.button(label="Priority", style=discord.ButtonStyle.secondary, emoji="🎯", custom_id="ticket_priority")
    async def priority_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to change priority.", ephemeral=True)
            return

        view = discord.ui.View()
        view.add_item(PrioritySelect(self.ticket_id))
        await interaction.response.send_message("Select priority:", view=view, ephemeral=True)

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="ticket_add_user")
    async def add_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to add users.", ephemeral=True)
            return

        await interaction.response.send_message("Please mention the user you want to add to this ticket.", ephemeral=True)

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await interaction.client.wait_for('message', check=check, timeout=30)
            if msg.mentions:
                user = msg.mentions[0]
                try:
                    await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
                    await interaction.channel.send(f"✅ Added {user.mention} to the ticket.")
                except discord.Forbidden:
                    await interaction.channel.send("❌ I don't have permission to add users to this channel.")
                await msg.delete()
            else:
                await interaction.channel.send("❌ Please mention a valid user.")
        except asyncio.TimeoutError:
            await interaction.channel.send("❌ User addition timed out.")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if interaction.user.id != ticket["user_id"] and not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
            return

        modal = CloseReasonModal(self.ticket_id)
        await interaction.response.send_modal(modal)

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        config = ConfigManager.load()
        admin_roles = config.get("admin_roles", [])
        
        if not admin_roles:
            return interaction.user.guild_permissions.administrator
        
        for role_id in admin_roles:
            role = interaction.guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                return True
        
        return interaction.user.guild_permissions.administrator

class CloseReasonModal(discord.ui.Modal):
    def __init__(self, ticket_id: str):
        super().__init__(title="Close Ticket")
        self.ticket_id = ticket_id
        
        self.reason = discord.ui.TextInput(
            label="Reason for closing",
            placeholder="Enter reason...",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if interaction.user.id == ticket["user_id"]:
            await self.close_ticket(ticket, interaction, self.reason.value)
        else:
            view = CloseConfirmationView(self.ticket_id, self.reason.value, interaction.user.id)
            user = interaction.guild.get_member(ticket["user_id"])
            if user:
                embed = discord.Embed(
                    title="Close Ticket Confirmation",
                    description=f"{interaction.user.mention} wants to close your ticket.\n**Reason:** {self.reason.value}",
                    color=discord.Color.orange()
                )
                await interaction.channel.send(content=user.mention, embed=embed, view=view)
                await interaction.response.send_message("Close request sent to user.", ephemeral=True)

    async def close_ticket(self, ticket: Dict[str, Any], interaction: discord.Interaction, reason: str):
        transcript = await self.generate_transcript(interaction.channel, ticket)
        
        ticket_manager.update_ticket(ticket["ticket_id"], {
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "closed_by": interaction.user.id,
            "close_reason": reason
        })
        
        config = ConfigManager.load()
        log_channel_id = config.get("ticket_log_channel")
        
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if log_channel:
                file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket_{ticket['ticket_id']}_transcript.txt")
                
                embed = discord.Embed(
                    title="🗂️ Ticket Closed",
                    description=f"**Ticket:** {ticket['ticket_id']}\n**User:** <@{ticket['user_id']}>\n**Closed by:** {interaction.user.mention}\n**Reason:** {reason}",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                
                await log_channel.send(embed=embed, file=file)
        
        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description=f"This ticket has been closed by {interaction.user.mention}\n**Reason:** {reason}",
            color=discord.Color.red()
        )
        
        await interaction.channel.send(embed=embed)
        
        try:
            await interaction.channel.edit(name=f"{interaction.channel.name}-closed")
        except:
            pass

    async def generate_transcript(self, channel: discord.TextChannel, ticket: Dict[str, Any]) -> str:
        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author.display_name} ({msg.author.id}): {msg.content}")
        
        transcript = f"{'='*60}\n"
        transcript += f"TICKET TRANSCRIPT - {ticket['ticket_id']}\n"
        transcript += f"{'='*60}\n"
        transcript += f"User: {ticket['user_name']} ({ticket['user_id']})\n"
        transcript += f"Category: {ticket['category']}\n"
        transcript += f"Created: {ticket['created_at']}\n"
        transcript += f"Status: {ticket['status']}\n"
        transcript += f"{'='*60}\n\n"
        
        for msg in messages:
            transcript += f"{msg}\n"
        
        transcript += f"\n{'='*60}\n"
        transcript += f"END OF TRANSCRIPT\n"
        transcript += f"{'='*60}"
        
        return transcript

class CloseConfirmationView(discord.ui.View):
    def __init__(self, ticket_id: str, reason: str, closer_id: int):
        super().__init__(timeout=300)
        self.ticket_id = ticket_id
        self.reason = reason
        self.closer_id = closer_id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message("You can only confirm your own ticket.", ephemeral=True)
            return

        modal = CloseReasonModal(self.ticket_id)
        await modal.close_ticket(ticket, interaction, self.reason)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, emoji="❌")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message("You can only decline your own ticket.", ephemeral=True)
            return

        await interaction.response.send_message("Ticket close cancelled.", ephemeral=True)

    @discord.ui.button(label="Force Close", style=discord.ButtonStyle.danger, emoji="⚡")
    async def force_close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to force close tickets.", ephemeral=True)
            return

        modal = CloseReasonModal(self.ticket_id)
        await modal.close_ticket(ticket, interaction, f"Force closed: {self.reason}")

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        config = ConfigManager.load()
        admin_roles = config.get("admin_roles", [])
        
        if not admin_roles:
            return interaction.user.guild_permissions.administrator
        
        for role_id in admin_roles:
            role = interaction.guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                return True
        
        return interaction.user.guild_permissions.administrator

class SettingsView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild
        self.config = ConfigManager.load()

    @discord.ui.select(
        placeholder="Select setting to configure",
        options=[
            discord.SelectOption(label="Ticket Categories", value="categories", emoji="📋", description="Manage ticket categories"),
            discord.SelectOption(label="Support Role", value="support_role", emoji="👥", description="Set support role"),
            discord.SelectOption(label="Log Channel", value="log_channel", emoji="📝", description="Set log channel"),
            discord.SelectOption(label="Auto Close Hours", value="auto_close", emoji="⏰", description="Set auto-close time"),
            discord.SelectOption(label="Welcome Message", value="welcome", emoji="👋", description="Set welcome message"),
            discord.SelectOption(label="Admin Roles", value="admin_roles", emoji="🔧", description="Manage admin roles"),
            discord.SelectOption(label="Max Tickets/User", value="max_tickets", emoji="🔢", description="Set max tickets per user"),
            discord.SelectOption(label="Archive Category", value="archive", emoji="📁", description="Set archive category")
        ]
    )
    async def settings_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        setting = select.values[0]
        
        if setting == "categories":
            await self.show_categories_menu(interaction)
        elif setting == "support_role":
            await self.show_role_select(interaction, "support_role")
        elif setting == "log_channel":
            await self.show_channel_select(interaction, "log_channel")
        elif setting == "auto_close":
            await self.show_auto_close_modal(interaction)
        elif setting == "welcome":
            await self.show_welcome_modal(interaction)
        elif setting == "admin_roles":
            await self.show_admin_roles_menu(interaction)
        elif setting == "max_tickets":
            await self.show_max_tickets_modal(interaction)
        elif setting == "archive":
            await self.show_channel_select(interaction, "archive_category_id")

    async def show_categories_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📋 Ticket Categories",
            description="Current categories:\n" + "\n".join([f"• {cat['name']} {cat['emoji']}" for cat in self.config["ticket_categories"]]),
            color=discord.Color.blue()
        )
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Add Category", style=discord.ButtonStyle.success, emoji="➕"))
        view.add_item(discord.ui.Button(label="Remove Category", style=discord.ButtonStyle.danger, emoji="➖"))
        view.add_item(discord.ui.Button(label="Edit Category", style=discord.ButtonStyle.primary, emoji="✏️"))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def show_role_select(self, interaction: discord.Interaction, setting: str):
        roles = [r for r in interaction.guild.roles if not r.is_default()]
        
        options = [discord.SelectOption(label=role.name, value=str(role.id)) for role in roles[:25]]
        
        select = discord.ui.Select(placeholder="Select role...", options=options)
        
        async def role_callback(interaction: discord.Interaction):
            role_id = select.values[0]
            self.config[setting] = role_id
            ConfigManager.save(self.config)
            await interaction.response.send_message(f"✅ {setting.replace('_', ' ').title()} set to <@&{role_id}>", ephemeral=True)
        
        select.callback = role_callback
        view = discord.ui.View()
        view.add_item(select)
        
        await interaction.response.send_message("Select a role:", view=view, ephemeral=True)

    async def show_channel_select(self, interaction: discord.Interaction, setting: str):
        channels = [c for c in interaction.guild.channels if isinstance(c, discord.TextChannel)]
        
        options = [discord.SelectOption(label=channel.name, value=str(channel.id)) for channel in channels[:25]]
        
        select = discord.ui.Select(placeholder="Select channel...", options=options)
        
        async def channel_callback(interaction: discord.Interaction):
            channel_id = select.values[0]
            self.config[setting] = channel_id
            ConfigManager.save(self.config)
            await interaction.response.send_message(f"✅ {setting.replace('_', ' ').title()} set to <#{channel_id}>", ephemeral=True)
        
        select.callback = channel_callback
        view = discord.ui.View()
        view.add_item(select)
        
        await interaction.response.send_message("Select a channel:", view=view, ephemeral=True)

    async def show_auto_close_modal(self, interaction: discord.Interaction):
        modal = discord.ui.Modal(title="Auto Close Settings")
        
        hours = discord.ui.TextInput(
            label="Hours until auto-close",
            placeholder="Enter number of hours (1-168)",
            default_value=str(self.config.get("ticket_auto_close_hours", 24)),
            max_length=3,
            required=True
        )
        modal.add_item(hours)
        
        async def modal_callback(interaction: discord.Interaction):
            try:
                value = int(hours.value)
                if 1 <= value <= 168:
                    self.config["ticket_auto_close_hours"] = value
                    ConfigManager.save(self.config)
                    await interaction.response.send_message(f"✅ Auto-close set to {value} hours", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Please enter a value between 1 and 168", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)
        
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    async def show_welcome_modal(self, interaction: discord.Interaction):
        modal = discord.ui.Modal(title="Welcome Message")
        
        message = discord.ui.TextInput(
            label="Welcome message",
            placeholder="Enter welcome message...",
            default_value=self.config.get("welcome_message", "Thank you for creating a ticket!"),
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True
        )
        modal.add_item(message)
        
        async def modal_callback(interaction: discord.Interaction):
            self.config["welcome_message"] = message.value
            ConfigManager.save(self.config)
            await interaction.response.send_message("✅ Welcome message updated", ephemeral=True)
        
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    async def show_max_tickets_modal(self, interaction: discord.Interaction):
        modal = discord.ui.Modal(title="Max Tickets Per User")
        
        max_tickets = discord.ui.TextInput(
            label="Maximum tickets per user",
            placeholder="Enter number (1-10)",
            default_value=str(self.config.get("max_tickets_per_user", 1)),
            max_length=2,
            required=True
        )
        modal.add_item(max_tickets)
        
        async def modal_callback(interaction: discord.Interaction):
            try:
                value = int(max_tickets.value)
                if 1 <= value <= 10:
                    self.config["max_tickets_per_user"] = value
                    ConfigManager.save(self.config)
                    await interaction.response.send_message(f"✅ Max tickets per user set to {value}", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Please enter a value between 1 and 10", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)
        
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    async def show_admin_roles_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔧 Admin Roles",
            description="Current admin roles:\n" + "\n".join([f"<@&{role_id}>" for role_id in self.config.get("admin_roles", [])]),
            color=discord.Color.blue()
        )
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Add Role", style=discord.ButtonStyle.success, emoji="➕"))
        view.add_item(discord.ui.Button(label="Remove Role", style=discord.ButtonStyle.danger, emoji="➖"))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_close.start()

    def cog_unload(self):
        self.auto_close.cancel()

    @tasks.loop(minutes=5)
    async def auto_close(self):
        tickets = ticket_manager.get_all_tickets()
        for ticket in tickets.values():
            if ticket["status"] != "open":
                continue
            
            channel = self.bot.get_channel(ticket["channel_id"])
            if not channel:
                continue

            last_user_message = None
            async for msg in channel.history(limit=50):
                if msg.author.id == ticket["user_id"]:
                    last_user_message = msg.created_at
                    break

            if last_user_message and datetime.now(timezone.utc) - last_user_message > timedelta(hours=24):
                transcript = await self.generate_transcript(channel, ticket)
                
                config = ConfigManager.load()
                log_channel_id = config.get("ticket_log_channel")
                
                if log_channel_id:
                    log_channel = self.bot.get_channel(int(log_channel_id))
                    if log_channel:
                        file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket_{ticket['ticket_id']}_transcript.txt")
                        
                        embed = discord.Embed(
                            title="🗂️ Auto-Closed Ticket",
                            description=f"**Ticket:** {ticket['ticket_id']}\n**User:** <@{ticket['user_id']}>\n**Reason:** 24h user inactivity",
                            color=discord.Color.red(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        
                        await log_channel.send(embed=embed, file=file)
                
                ticket_manager.update_ticket(ticket["ticket_id"], {
                    "status": "closed",
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                    "closed_by": None,
                    "close_reason": "Auto-closed due to 24h user inactivity"
                })
                
                try:
                    await channel.edit(name=f"{channel.name}-closed")
                except:
                    pass

    @auto_close.before_loop
    async def before_auto_close(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="ticket", description="Ticket management commands")
    @app_commands.choices(action=[
        app_commands.Choice(name="panel", value="panel"),
        app_commands.Choice(name="stats", value="stats"),
        app_commands.Choice(name="settings", value="settings"),
        app_commands.Choice(name="close", value="close"),
        app_commands.Choice(name="reopen", value="reopen")
    ])
    async def ticket_command(self, interaction: discord.Interaction, action: str):
        if action == "panel":
            await self.create_panel(interaction)
        elif action == "stats":
            await self.show_stats(interaction)
        elif action == "settings":
            await self.show_settings(interaction)
        elif action == "close":
            await self.close_ticket_cmd(interaction)
        elif action == "reopen":
            await self.reopen_ticket_cmd(interaction)

    async def create_panel(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to create panels.", ephemeral=True)
            return

        config = ConfigManager.load()
        categories = config.get("ticket_categories", [])
        
        embed = discord.Embed(
            title="🎫 Create a Ticket",
            description="Choose a category below to create a new ticket",
            color=discord.Color.blue()
        )
        
        view = discord.ui.View()
        
        for cat in categories:
            color_map = {
                "blue": discord.ButtonStyle.blurple,
                "yellow": discord.ButtonStyle.secondary,
                "green": discord.ButtonStyle.success,
                "purple": discord.ButtonStyle.primary,
                "grey": discord.ButtonStyle.grey
            }
            
            button = discord.ui.Button(
                label=cat["name"],
                emoji=cat.get("emoji", "🎫"),
                style=color_map.get(cat.get("color", "blue"), discord.ButtonStyle.blurple)
            )
            button.callback = lambda i, c=cat["name"]: self.handle_category_select(i, c)
            view.add_item(button)
        
        await interaction.response.send_message(embed=embed, view=view)

    async def handle_category_select(self, interaction: discord.Interaction, category: str):
        if ticket_manager.is_blacklisted(interaction.user.id):
            await interaction.response.send_message("You are blacklisted from creating tickets.", ephemeral=True)
            return

        user_tickets = ticket_manager.get_user_tickets(interaction.user.id)
        if user_tickets:
            await interaction.response.send_message("You already have an open ticket. Please close it first.", ephemeral=True)
            return

        if category == "Staff Application":
            await self.start_staff_application(interaction)
        else:
            modal = CategoryModal(category)
            await interaction.response.send_modal(modal)

    async def start_staff_application(self, interaction: discord.Interaction):
        questions = [
            "What is your Discord username and tag?",
            "How old are you?",
            "What timezone are you in?",
            "How many hours per week can you dedicate to this role?",
            "Do you have any previous moderation experience? If yes, please describe.",
            "Why do you want to join our staff team?",
            "What skills do you bring to the team?",
            "How would you handle a user who is being disruptive?",
            "What is your availability schedule?",
            "Any additional information you'd like to share?"
        ]
        
        answers = []
        
        try:
            await interaction.response.send_message("Starting staff application in DMs...", ephemeral=True)
            
            dm_channel = await interaction.user.create_dm()
            await dm_channel.send("**Staff Application Started**\nYou have 5 minutes per question. Type 'cancel' to stop.")
            
            for i, question in enumerate(questions, 1):
                await dm_channel.send(f"**Question {i}/10:** {question}")
                
                def check(m):
                    return m.author == interaction.user and m.channel == dm_channel
                
                try:
                    msg = await self.bot.wait_for('message', check=check, timeout=300)
                    if msg.content.lower() == 'cancel':
                        await dm_channel.send("Application cancelled.")
                        return
                    answers.append(msg.content)
                except asyncio.TimeoutError:
                    await dm_channel.send("Application timed out. Please restart if you wish to apply.")
                    return
            
            application_data = {
                "discord_username": answers[0],
                "age": answers[1],
                "timezone": answers[2],
                "hours_per_week": answers[3],
                "experience": answers[4],
                "motivation": answers[5],
                "skills": answers[6],
                "disruption_handling": answers[7],
                "availability": answers[8],
                "additional_info": answers[9]
            }
            
            await self.create_ticket_channel(interaction, "Staff Application", application_data)
            await dm_channel.send("✅ Staff application submitted! A ticket has been created for review.")
            
        except discord.Forbidden:
            await interaction.followup.send("I cannot DM you. Please enable DMs from server members.", ephemeral=True)

    async def show_stats(self, interaction: discord.Interaction):
        tickets = ticket_manager.get_all_tickets()
        
        open_tickets = [t for t in tickets.values() if t["status"] == "open"]
        closed_tickets = [t for t in tickets.values() if t["status"] == "closed"]
        
        embed = discord.Embed(
            title="📊 Ticket Statistics",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Total Tickets", value=len(tickets), inline=True)
        embed.add_field(name="Open", value=len(open_tickets), inline=True)
        embed.add_field(name="Closed", value=len(closed_tickets), inline=True)
        
        await interaction.response.send_message(embed=embed)

    async def show_settings(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to view settings.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚙️ Ticket System Settings",
            description="Use the dropdown below to configure ticket system settings",
            color=discord.Color.blue()
        )
        
        view = SettingsView(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def close_ticket_cmd(self, interaction: discord.Interaction):
        ticket = ticket_manager.get_channel_ticket(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return

        if interaction.user.id != ticket["user_id"] and not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
            return

        modal = CloseReasonModal(ticket["ticket_id"])
        await interaction.response.send_modal(modal)

    async def reopen_ticket_cmd(self, interaction: discord.Interaction):
        ticket = next((t for t in ticket_manager.get_all_tickets().values() 
                      if t.get("channel_id") == interaction.channel_id), None)
        
        if not ticket:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return

        if interaction.user.id != ticket["user_id"] and not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to reopen this ticket.", ephemeral=True)
            return

        if ticket["status"] != "closed":
            await interaction.response.send_message("This ticket is not closed.", ephemeral=True)
            return

        ticket_manager.update_ticket(ticket["ticket_id"], {"status": "open"})
        
        try:
            await interaction.channel.edit(name=interaction.channel.name.replace("-closed", ""))
        except:
            pass
        
        await interaction.response.send_message("✅ Ticket reopened.", ephemeral=True)

    async def create_ticket_channel(self, interaction: discord.Interaction, category: str, form_data: Dict[str, Any]):
        config = ConfigManager.load()
        category_id = config.get("ticket_category_id")
        
        if not category_id:
            await interaction.followup.send("Ticket system not configured. Please contact an administrator.", ephemeral=True)
            return

        category_channel = interaction.guild.get_channel(int(category_id))
        if not category_channel or not isinstance(category_channel, discord.CategoryChannel):
            await interaction.followup.send("Invalid ticket category configuration.", ephemeral=True)
            return

        ticket_id = ticket_manager.create_ticket({
            "user_id": interaction.user.id,
            "user_name": interaction.user.display_name,
            "category": category,
            "status": "open",
            "priority": "normal",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "claimed_by": None,
            "form_data": form_data,
            "channel_id": None,
            "last_user_message": datetime.now(timezone.utc).isoformat()
        })

        channel_name = f"{category.lower().replace(' ', '-')}-{ticket_id.lower()}"
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        channel = await category_channel.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=f"Ticket {ticket_id} - {category}"
        )

        ticket_manager.update_ticket(ticket_id, {"channel_id": channel.id})

        embed = discord.Embed(
            title=f"🎫 {category} - {ticket_id}",
            description=f"**User:** {interaction.user.mention}\n**Status:** Open\n**Priority:** Normal",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        if isinstance(form_data, dict):
            for key, value in form_data.items():
                if key != "additional_info" or value:
                    embed.add_field(name=key.replace('_', ' ').title(), value=str(value)[:1024], inline=False)

        welcome_message = config.get("welcome_message", "Thank you for creating a ticket! Our staff will assist you shortly.")
        
        mentions = []
        support_role_id = config.get("support_role_id")
        if support_role_id:
            role = interaction.guild.get_role(int(support_role_id))
            if role:
                mentions.append(role.mention)
        
        admin_roles = config.get("admin_roles", [])
        for role_id in admin_roles:
            role = interaction.guild.get_role(int(role_id))
            if role:
                mentions.append(role.mention)
        
        mentions.append(interaction.user.mention)
        
        await channel.send(" ".join(mentions), embed=embed)
        
        controls = TicketControls(ticket_id)
        await channel.send("**Ticket Controls:**", view=controls)
        
        if hasattr(interaction, 'followup'):
            await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)

    async def generate_transcript(self, channel: discord.TextChannel, ticket: Dict[str, Any]) -> str:
        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author.display_name} ({msg.author.id}): {msg.content}")
        
        transcript = f"{'='*60}\n"
        transcript += f"TICKET TRANSCRIPT - {ticket['ticket_id']}\n"
        transcript += f"{'='*60}\n"
        transcript += f"User: {ticket['user_name']} ({ticket['user_id']})\n"
        transcript += f"Category: {ticket['category']}\n"
        transcript += f"Created: {ticket['created_at']}\n"
        transcript += f"Status: {ticket['status']}\n"
        transcript += f"{'='*60}\n\n"
        
        for msg in messages:
            transcript += f"{msg}\n"
        
        transcript += f"\n{'='*60}\n"
        transcript += f"END OF TRANSCRIPT\n"
        transcript += f"{'='*60}"
        
        return transcript

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        config = ConfigManager.load()
        admin_roles = config.get("admin_roles", [])
        
        if not admin_roles:
            return interaction.user.guild_permissions.administrator
        
        for role_id in admin_roles:
            role = interaction.guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                return True
        
        return interaction.user.guild_permissions.administrator

async def setup(bot):
    await bot.add_cog(Tickets(bot))