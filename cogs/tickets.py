import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import io
import re
import time
from collections import defaultdict
import hashlib
import base64
from dataclasses import dataclass, asdict
import uuid

logger = logging.getLogger('tickets')
os.makedirs('data', exist_ok=True)

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
            if ticket.get("channel_id") == channel_id and ticket["status"] == "open":
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

class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.blurple, emoji="👤", custom_id="ticket_claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_channel_ticket(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to claim tickets.", ephemeral=True)
            return

        if ticket.get("claimed_by") == interaction.user.id:
            ticket_manager.update_ticket(ticket["ticket_id"], {"claimed_by": None})
            await interaction.response.send_message("You have unclaimed this ticket.", ephemeral=True)
            embed = discord.Embed(description=f"🔓 Ticket unclaimed by {interaction.user.mention}", color=discord.Color.orange())
        else:
            ticket_manager.update_ticket(ticket["ticket_id"], {"claimed_by": interaction.user.id})
            await interaction.response.send_message("You have claimed this ticket!", ephemeral=True)
            embed = discord.Embed(description=f"👤 Ticket claimed by {interaction.user.mention}", color=discord.Color.green())
        
        await interaction.channel.send(embed=embed)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_channel_ticket(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return

        if interaction.user.id != ticket["user_id"] and not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
            return

        modal = CloseReasonModal(ticket["ticket_id"])
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="ticket_add_user")
    async def add_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = ticket_manager.get_channel_ticket(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return

        if not await self.is_admin(interaction):
            await interaction.response.send_message("You don't have permission to add users.", ephemeral=True)
            return

        modal = AddUserModal()
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

        view = CloseConfirmationView(self.ticket_id, self.reason.value, interaction.user.id)
        
        if interaction.user.id == ticket["user_id"]:
            await interaction.response.send_message("Closing ticket...", ephemeral=True)
            await self.close_ticket(ticket, interaction, self.reason.value)
        else:
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
        file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket_{ticket['ticket_id']}_transcript.txt")
        
        ticket_manager.update_ticket(ticket["ticket_id"], {
            "status": "closed",
            "closed_at": datetime.now().isoformat(),
            "closed_by": interaction.user.id,
            "close_reason": reason
        })
        
        await interaction.channel.send("Ticket closed. Transcript attached.", file=file)
        
        config = ConfigManager.load()
        log_channel_id = config.get("ticket_log_channel")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(
                    title="Ticket Closed",
                    description=f"**Ticket:** {ticket['ticket_id']}\n**User:** <@{ticket['user_id']}>\n**Closed by:** {interaction.user.mention}\n**Reason:** {reason}",
                    color=discord.Color.red()
                )
                await log_channel.send(embed=embed)

    async def generate_transcript(self, channel: discord.TextChannel, ticket: Dict[str, Any]) -> str:
        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author.display_name}: {msg.content}")
        
        transcript = f"Ticket {ticket['ticket_id']} Transcript\n"
        transcript += f"User: {ticket['user_name']} ({ticket['user_id']})\n"
        transcript += f"Category: {ticket['category']}\n"
        transcript += f"Created: {ticket['created_at']}\n"
        transcript += "=" * 50 + "\n\n"
        transcript += "\n".join(messages)
        
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

class AddUserModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Add User to Ticket")
        
        self.user_id = discord.ui.TextInput(
            label="User ID",
            placeholder="Enter user ID to add",
            required=True
        )
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = int(self.user_id.value)
            user = interaction.guild.get_member(user_id)
            if not user:
                await interaction.response.send_message("User not found.", ephemeral=True)
                return

            await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
            await interaction.response.send_message(f"Added {user.mention} to the ticket.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid user ID.", ephemeral=True)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_close.start()
        self.user_last_message = {}

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

            if last_user_message and datetime.now() - last_user_message > timedelta(hours=24):
                transcript = await self.generate_transcript(channel, ticket)
                file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket_{ticket['ticket_id']}_transcript.txt")
                
                ticket_manager.update_ticket(ticket["ticket_id"], {
                    "status": "closed",
                    "closed_at": datetime.now().isoformat(),
                    "closed_by": None,
                    "close_reason": "Auto-closed due to 24h user inactivity"
                })
                
                await channel.send("Ticket auto-closed due to 24 hours of inactivity. Transcript attached.", file=file)

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

        config = ConfigManager.load()
        
        embed = discord.Embed(
            title="⚙️ Ticket System Settings",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Support Role", value=config.get("support_role_id", "Not set"), inline=True)
        embed.add_field(name="Auto Close", value=f"{config.get('ticket_auto_close_hours', 24)}h", inline=True)
        embed.add_field(name="Max Tickets/User", value=config.get("max_tickets_per_user", 1), inline=True)
        
        await interaction.response.send_message(embed=embed)

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
            "created_at": datetime.now().isoformat(),
            "claimed_by": None,
            "form_data": form_data,
            "channel_id": None,
            "last_user_message": datetime.now().isoformat()
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
            description=f"**User:** {interaction.user.mention}\n**Status:** Open",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        if isinstance(form_data, dict):
            for key, value in form_data.items():
                if key != "additional_info" or value:
                    embed.add_field(name=key.replace('_', ' ').title(), value=str(value)[:1024], inline=False)

        welcome_message = config.get("welcome_message", "Thank you for creating a ticket! Our staff will assist you shortly.")
        await channel.send(welcome_message, embed=embed)

        controls = TicketControls()
        await channel.send("**Ticket Controls:**", view=controls)

        support_role_id = config.get("support_role_id")
        if support_role_id:
            role = interaction.guild.get_role(int(support_role_id))
            if role:
                await channel.send(f"{role.mention} New ticket created!")

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