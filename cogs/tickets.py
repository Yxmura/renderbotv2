import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
from typing import Optional, Dict, Any
import io
import re
import textwrap
from datetime import datetime, timedelta
import logging
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict, field
import uuid
from bot import load_data, save_data

logger = logging.getLogger('bot.tickets')
os.makedirs('data', exist_ok=True)

class TicketManager:
    @staticmethod
    def load_tickets():
        return load_data('tickets')
    
    @staticmethod
    def save_tickets(tickets_data):
        save_data('tickets', tickets_data)
    
    @staticmethod
    def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
        tickets = TicketManager.load_tickets()
        return tickets["tickets"].get(ticket_id)
    
    @staticmethod
    def update_ticket(ticket_id: str, ticket_data: Dict[str, Any]):
        tickets = TicketManager.load_tickets()
        tickets["tickets"][ticket_id] = ticket_data
        TicketManager.save_tickets(tickets)
    
    @staticmethod
    def create_ticket(ticket_data: Dict[str, Any]) -> str:
        tickets = TicketManager.load_tickets()
        tickets["counter"] += 1
        ticket_id = f"T{tickets['counter']:04d}"
        ticket_data["ticket_id"] = ticket_id
        tickets["tickets"][ticket_id] = ticket_data
        TicketManager.save_tickets(tickets)
        return ticket_id
    
    @staticmethod
    def delete_ticket(ticket_id: str):
        tickets = TicketManager.load_tickets()
        if ticket_id in tickets["tickets"]:
            del tickets["tickets"][ticket_id]
            TicketManager.save_tickets(tickets)
    
    @staticmethod
    def get_user_open_tickets(user_id: int) -> List[Dict[str, Any]]:
        tickets = TicketManager.load_tickets()
        return [t for t in tickets["tickets"].values() 
                if t["user_id"] == user_id and t["status"] == "open"]

class TicketFormModal(discord.ui.Modal):    
    def __init__(self, category: str, *args, **kwargs):
        super().__init__(title=f"{category} - Ticket Details", *args, **kwargs)
        self.category = category
        self.form_data = {}
    
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {}
        for child in self.children:
            if isinstance(child, discord.ui.TextInput):
                if child.value:
                    self.form_data[child.label] = child.value
        
        form_embed = self.format_embed(interaction)
        await interaction.response.defer(ephemeral=True)
        
        ticket_view = TicketCategorySelect()
        result = await ticket_view.create_ticket_channel(interaction, self)
        
        if not result:
            return
            
        channel, ticket_id = result
            
        await ticket_view.send_ticket_created_message(
            interaction,
            channel,
            ticket_id,
            self.category,
            form_embed=form_embed
        )
        
        await interaction.followup.send(
            f"Ticket created! Please check {channel.mention}", 
            ephemeral=True
        )
    
    def format_embed(self, interaction: discord.Interaction) -> discord.Embed:
        embed = discord.Embed(
            title=f"Ticket Details - {self.category}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        
        for field_name, value in self.form_data.items():
            if value:
                embed.add_field(name=field_name, value=value[:1024], inline=False)
        
        return embed

class GeneralSupportModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("General Support", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.question = discord.ui.TextInput(
            label="How can we help you?",
            placeholder="Describe your question or issue...",
            required=True,
            max_length=1000
        )
        self.add_item(self.question)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {"Short Description": self.short_desc.value, "Question": self.question.value}
        await super().on_submit(interaction)

class ResourceIssueModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Resource Issue", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.resource_title = discord.ui.TextInput(
            label="Resource Title (Optional)",
            placeholder="Name of the resource with the issue",
            required=False,
            max_length=100
        )
        self.add_item(self.resource_title)
        self.issue_description = discord.ui.TextInput(
            label="Issue Description",
            placeholder="Please describe the issue in detail...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.issue_description)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {"Short Description": self.short_desc.value}
        if self.resource_title.value:
            self.form_data["Resource Title"] = self.resource_title.value
        self.form_data["Issue Description"] = self.issue_description.value
        await super().on_submit(interaction)

class PartnerSponsorModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Partner- or sponsorship", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.organization = discord.ui.TextInput(
            label="Organization/Channel Name",
            placeholder="Your organization or channel name",
            required=True,
            max_length=100
        )
        self.add_item(self.organization)
        self.link = discord.ui.TextInput(
            label="Discord/YouTube/Twitch Link",
            placeholder="https://discord.gg/... or https://youtube.com/... or https://twitch.tv/...",
            required=True,
            max_length=200
        )
        self.add_item(self.link)
        self.details = discord.ui.TextInput(
            label="Partnership/Sponsorship Details",
            placeholder="Tell us about your proposal...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.details)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {
            "Short Description": self.short_desc.value,
            "Organization/Channel Name": self.organization.value,
            "Link": f"[Click here]({self.link.value})" if self.link.value.startswith(('http://', 'https://')) else self.link.value,
            "Details": self.details.value
        }
        await super().on_submit(interaction)

class StaffApplicationModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Staff Application - if open", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.name = discord.ui.TextInput(
            label="Full Name",
            placeholder="Your full name",
            required=True,
            max_length=100
        )
        self.add_item(self.name)
        self.age = discord.ui.TextInput(
            label="Age",
            placeholder="Your age",
            required=True,
            max_length=3
        )
        self.add_item(self.age)
        self.timezone = discord.ui.TextInput(
            label="Timezone",
            placeholder="Example: EST, PST, GMT+2, etc.",
            required=True,
            max_length=50
        )
        self.add_item(self.timezone)
        self.experience = discord.ui.TextInput(
            label="Previous Experience",
            placeholder="Any previous staff experience (Discord or other platforms)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.experience)
        self.why_join = discord.ui.TextInput(
            label="Why do you want to join our staff team?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.why_join)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {
            "Short Description": self.short_desc.value,
            "Full Name": self.name.value,
            "Age": self.age.value,
            "Timezone": self.timezone.value,
            "Previous Experience": self.experience.value,
            "Why do you want to join our staff team?": self.why_join.value
        }
        await super().on_submit(interaction)

class BugReportModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Bug Report", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.page = discord.ui.TextInput(
            label="On what page did the bug occur?",
            placeholder="e.g. /dashboard, /login, ...",
            required=True,
            max_length=100
        )
        self.add_item(self.page)
        self.browser = discord.ui.TextInput(
            label="What browser are you using?",
            placeholder="e.g. Chrome, Firefox, Safari, ...",
            required=True,
            max_length=100
        )
        self.add_item(self.browser)
        self.steps = discord.ui.TextInput(
            label="Steps to Reproduce",
            placeholder="Describe the steps to reproduce the bug...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.steps)
        self.expected = discord.ui.TextInput(
            label="Expected Behavior",
            placeholder="What did you expect to happen?",
            required=True,
            max_length=500
        )
        self.add_item(self.expected)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {
            "Short Description": self.short_desc.value,
            "Page": self.page.value,
            "Browser": self.browser.value,
            "Steps to Reproduce": self.steps.value,
            "Expected Behavior": self.expected.value
        }
        await super().on_submit(interaction)

class ContentCreatorModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Content Creator", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.channel_name = discord.ui.TextInput(
            label="Channel Name",
            placeholder="Your channel name",
            required=True,
            max_length=100
        )
        self.add_item(self.channel_name)
        self.channel_url = discord.ui.TextInput(
            label="Channel URL",
            placeholder="https://youtube.com/... or https://twitch.tv/...",
            required=True,
            max_length=200
        )
        self.add_item(self.channel_url)
        self.subscriber_count = discord.ui.TextInput(
            label="Subscriber/Followers Count",
            placeholder="Example: 10K",
            required=True,
            max_length=50
        )
        self.add_item(self.subscriber_count)
        self.last_video_views = discord.ui.TextInput(
            label="Last Video View Count (Optional)",
            placeholder="Example: 5K",
            required=False,
            max_length=50
        )
        self.add_item(self.last_video_views)
        self.collab_ideas = discord.ui.TextInput(
            label="Collaboration Ideas",
            placeholder="What kind of collaboration are you interested in?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.collab_ideas)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {
            "Short Description": self.short_desc.value,
            "Channel Name": self.channel_name.value,
            "Channel URL": f"[Click here]({self.channel_url.value})" if self.channel_url.value.startswith(('http://', 'https://')) else self.channel_url.value,
            "Subscriber/Followers Count": self.subscriber_count.value,
            "Collaboration Ideas": self.collab_ideas.value
        }
        if self.last_video_views.value:
            self.form_data["Last Video View Count"] = self.last_video_views.value
        await super().on_submit(interaction)

class OtherInquiryModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Other", *args, **kwargs)
        self.short_desc = discord.ui.TextInput(
            label="Short Description",
            placeholder="Briefly describe the reason for your ticket...",
            required=True,
            max_length=200
        )
        self.add_item(self.short_desc)
        self.subject = discord.ui.TextInput(
            label="Subject",
            placeholder="Briefly describe what this is about",
            required=True,
            max_length=200
        )
        self.add_item(self.subject)
        self.details = discord.ui.TextInput(
            label="Details",
            placeholder="Please provide more details about your inquiry...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.details)
    async def on_submit(self, interaction: discord.Interaction):
        self.form_data = {
            "Short Description": self.short_desc.value,
            "Subject": self.subject.value,
            "Details": self.details.value
        }
        await super().on_submit(interaction)

def load_config():
    try:
        with open('data/config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        default_config = {
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
        os.makedirs('data', exist_ok=True)
        with open('data/config.json', 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config

def save_config(config):
    os.makedirs('data', exist_ok=True)
    with open('data/config.json', 'w') as f:
        json.dump(config, f, indent=4)

async def is_admin(interaction: discord.Interaction) -> bool:
    config = load_config()
    admin_roles = config.get("admin_roles", [])
    return any(role.id in admin_roles for role in interaction.user.roles)

class TicketCategorySelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.select(
        placeholder="Choose a category...",
        options=[
            discord.SelectOption(label="General Support", emoji="❓", description="Get help with general questions"),
            discord.SelectOption(label="Resource Issue", emoji="📁", description="Report issues with resources"),
            discord.SelectOption(label="Partner- or sponsorship", emoji="🤝", description="Partnership or sponsorship inquiries"),
            discord.SelectOption(label="Staff Application - if open", emoji="👥", description="Apply to join our staff team"),
            discord.SelectOption(label="Bug Report", emoji="🐛", description="Report bugs or technical issues"),
            discord.SelectOption(label="Content Creator", emoji="🎥", description="Content creator collaboration"),
            discord.SelectOption(label="Other", emoji="📝", description="Other inquiries")
        ]
    )
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        
        modal_map = {
            "General Support": GeneralSupportModal,
            "Resource Issue": ResourceIssueModal,
            "Partner- or sponsorship": PartnerSponsorModal,
            "Staff Application - if open": StaffApplicationModal,
            "Bug Report": BugReportModal,
            "Content Creator": ContentCreatorModal,
            "Other": OtherInquiryModal
        }
        
        modal = modal_map[category]()
        await interaction.response.send_modal(modal)

    async def create_ticket_channel(self, interaction: discord.Interaction, modal) -> Optional[tuple]:
        config = load_config()
        category_id = config.get("ticket_category_id") or config.get("ticket_category")
        if not category_id:
            await interaction.followup.send("Ticket category is not configured. Please contact an admin.", ephemeral=True)
            return None
        
        category = interaction.guild.get_channel(int(category_id))
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("Configured ticket category is invalid. Please contact an admin.", ephemeral=True)
            return None
        
        open_tickets = TicketManager.get_user_open_tickets(interaction.user.id)
        if open_tickets:
            channel = interaction.guild.get_channel(open_tickets[0]["channel_id"])
            if channel:
                await interaction.followup.send(f"You already have an open ticket: {channel.mention}", ephemeral=True)
                return None
        
        def sanitize(text):
            return re.sub(r'[^a-z0-9-]', '-', text.lower().replace(' ', '-'))
        
        username = sanitize(interaction.user.display_name)
        catname = sanitize(modal.category)
        ticket_id = TicketManager.create_ticket({
            "user_id": interaction.user.id,
            "category": modal.category,
            "status": "open",
            "priority": "normal",
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "form_data": getattr(modal, 'form_data', {})
        })
        
        channel_name = f"{username}-{catname}-{ticket_id.lower()}"
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_roles=True)
        }
        
        admin_role_mentions = []
        for role_id in config.get("admin_roles", []):
            role = interaction.guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                admin_role_mentions.append(role.mention)
        
        channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=ticket_id
        )
        
        ticket_data = TicketManager.get_ticket(ticket_id)
        ticket_data["channel_id"] = channel.id
        TicketManager.update_ticket(ticket_id, ticket_data)
        
        if admin_role_mentions:
            await channel.send(' '.join(admin_role_mentions))
        
        await log_ticket_action(interaction.guild, "Created", ticket_data, f"Created by: {interaction.user.mention}")
        return channel, ticket_id

    async def send_ticket_created_message(self, interaction, channel, ticket_id, category, form_embed=None):
        embed = discord.Embed(
            title=f"🎫 Ticket Created: {category}",
            description=f"Thank you for opening a ticket! Our team will assist you shortly.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Ticket ID", value=ticket_id, inline=True)
        embed.add_field(name="Status", value="🟢 Open", inline=True)
        embed.add_field(name="Category", value=category, inline=True)
        if form_embed:
            embed.add_field(name="Details", value="See below for your submitted details.", inline=False)
        
        await channel.send(content=f"{interaction.user.mention}", embed=embed, view=TicketControlsView(ticket_id))
        if form_embed:
            await channel.send(embed=form_embed)
        
        config = load_config()
        staff_ping = config.get("ticket_staff_ping")
        if staff_ping:
            await channel.send(staff_ping)

class TicketControlsView(discord.ui.View):
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.add_item(self.ClaimButton(ticket_id))
        self.add_item(self.PriorityButton(ticket_id))
        self.add_item(self.CloseButton(ticket_id))
        self.add_item(self.TranscriptButton(ticket_id))

    class ClaimButton(discord.ui.Button):
        def __init__(self, ticket_id):
            super().__init__(label="Claim/Unclaim", style=discord.ButtonStyle.primary, emoji="🙋", row=0)
            self.ticket_id = ticket_id
        async def callback(self, interaction: discord.Interaction):
            ticket_data = TicketManager.get_ticket(self.ticket_id)
            if not ticket_data:
                await interaction.response.send_message("Could not find ticket.", ephemeral=True)
                return
            
            if ticket_data.get('claimed_by') == interaction.user.id:
                ticket_data['claimed_by'] = None
                await interaction.response.send_message("You have unclaimed this ticket.", ephemeral=True)
                await log_ticket_action(interaction.guild, "Unclaim", ticket_data, f"By: {interaction.user.mention}")
            else:
                ticket_data['claimed_by'] = interaction.user.id
                await interaction.response.send_message("You have claimed this ticket!", ephemeral=True)
                await log_ticket_action(interaction.guild, "Claim", ticket_data, f"By: {interaction.user.mention}")
            
            ticket_data['last_activity'] = datetime.now().isoformat()
            TicketManager.update_ticket(self.ticket_id, ticket_data)

    class PriorityButton(discord.ui.Button):
        def __init__(self, ticket_id):
            super().__init__(label="Set Priority", style=discord.ButtonStyle.secondary, emoji="🔖", row=0)
            self.ticket_id = ticket_id
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_message(
                "Select a new priority:",
                view=TicketControlsView.PrioritySelectView(self.ticket_id),
                ephemeral=True
            )

    class PrioritySelectView(discord.ui.View):
        def __init__(self, ticket_id):
            super().__init__(timeout=60)
            self.add_item(TicketControlsView.PrioritySelect(ticket_id))

    class PrioritySelect(discord.ui.Select):
        def __init__(self, ticket_id):
            options = [
                discord.SelectOption(label="Urgent", value="urgent", emoji="🔴"),
                discord.SelectOption(label="High", value="high", emoji="🟠"),
                discord.SelectOption(label="Normal", value="normal", emoji="🟡"),
                discord.SelectOption(label="Low", value="low", emoji="🔵")
            ]
            super().__init__(placeholder="Choose priority...", min_values=1, max_values=1, options=options)
            self.ticket_id = ticket_id
        async def callback(self, interaction: discord.Interaction):
            ticket_data = TicketManager.get_ticket(self.ticket_id)
            if not ticket_data:
                await interaction.response.send_message("Could not find ticket.", ephemeral=True)
                return
            
            priority = self.values[0]
            ticket_data['priority'] = priority
            ticket_data['last_activity'] = datetime.now().isoformat()
            TicketManager.update_ticket(self.ticket_id, ticket_data)
            
            await log_ticket_action(interaction.guild, "Priority Change", ticket_data, f"Set to: {priority.capitalize()} by {interaction.user.mention}")
            await interaction.response.edit_message(content=f"Priority set to {priority.capitalize()}!", view=None)

    class CloseButton(discord.ui.Button):
        def __init__(self, ticket_id):
            super().__init__(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", row=1)
            self.ticket_id = ticket_id
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_modal(CloseTicketModal(self.ticket_id))

    class TranscriptButton(discord.ui.Button):
        def __init__(self, ticket_id):
            super().__init__(label="Transcript", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
            self.ticket_id = ticket_id
        async def callback(self, interaction: discord.Interaction):
            ticket_data = TicketManager.get_ticket(self.ticket_id)
            if not ticket_data:
                await interaction.response.send_message("Could not find ticket.", ephemeral=True)
                return
            
            if interaction.user.id != ticket_data.get('user_id') and not await is_admin(interaction):
                await interaction.response.send_message("You do not have permission to generate a transcript.", ephemeral=True)
                return
            
            channel = interaction.guild.get_channel(ticket_data["channel_id"])
            if not channel:
                await interaction.response.send_message("Could not find ticket channel.", ephemeral=True)
                return
            
            transcript = await TicketCloseConfirmView(self.ticket_id, "", interaction.user.id).generate_transcript(channel, ticket_data)
            transcript_file = discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{self.ticket_id}-transcript.txt")
            await interaction.response.send_message("Here is the transcript:", file=transcript_file, ephemeral=True)
            await log_ticket_action(interaction.guild, "Transcript", ticket_data, f"Generated by: {interaction.user.mention}")

class CloseTicketModal(discord.ui.Modal):
    def __init__(self, ticket_id: str):
        super().__init__(title="Close Ticket")
        self.ticket_id = ticket_id
        
        self.reason = discord.ui.TextInput(
            label="Reason for closing",
            placeholder="Enter the reason for closing this ticket...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.reason)
        
        self.close_type = discord.ui.TextInput(
            label="Close type",
            placeholder="resolved, cancelled, etc.",
            required=True,
            max_length=100
        )
        self.add_item(self.close_type)

    async def on_submit(self, interaction: discord.Interaction):
        ticket_data = TicketManager.get_ticket(self.ticket_id)
        if not ticket_data:
            await interaction.response.send_message("Could not find ticket.", ephemeral=True)
            return
        
        view = TicketCloseConfirmView(self.ticket_id, self.reason.value, interaction.user.id, self.close_type.value)
        await interaction.response.send_message(
            f"Are you sure you want to close ticket {self.ticket_id}?",
            view=view,
            ephemeral=True
        )

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, ticket_id: str, reason: str, closer_id: int, close_type: str = "closed"):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.reason = reason
        self.closer_id = closer_id
        self.close_type = close_type

    @discord.ui.button(label="Yes, close ticket", style=discord.ButtonStyle.danger)
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_data = TicketManager.get_ticket(self.ticket_id)
        if not ticket_data:
            await interaction.response.send_message("Could not find ticket.", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(ticket_data["channel_id"])
        
        ticket_data["status"] = "closed"
        ticket_data["closed_at"] = datetime.now().isoformat()
        ticket_data["closed_by"] = self.closer_id
        ticket_data["close_reason"] = self.reason
        ticket_data["close_type"] = self.close_type
        ticket_data["last_activity"] = datetime.now().isoformat()
        TicketManager.update_ticket(self.ticket_id, ticket_data)
        
        transcript = await self.generate_transcript(channel, ticket_data)
        
        if channel:
            try:
                await channel.delete(reason=f"Ticket closed by {interaction.user}")
            except:
                pass
        
        config = load_config()
        log_channel_id = config.get("ticket_log_channel")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(
                    title=f"Ticket Closed: {ticket_data['category']}",
                    description=f"**Ticket ID:** {self.ticket_id}\n**User:** <@{ticket_data['user_id']}>\n**Closed by:** <@{self.closer_id}>\n**Reason:** {self.reason}\n**Type:** {self.close_type}",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                
                transcript_file = discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{self.ticket_id}-transcript.txt")
                await log_channel.send(embed=embed, file=transcript_file)
        
        await interaction.response.send_message(f"Ticket {self.ticket_id} has been closed.", ephemeral=True)
        await log_ticket_action(interaction.guild, "Close", ticket_data, f"By: <@{self.closer_id}> - {self.reason}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Ticket closure cancelled.", ephemeral=True)

    async def generate_transcript(self, channel, ticket_data):
        if not channel:
            return f"Transcript for ticket {self.ticket_id}\nChannel was deleted.\n"
        
        transcript = f"Ticket Transcript - {self.ticket_id}\n"
        transcript += f"Category: {ticket_data['category']}\n"
        transcript += f"User: {ticket_data['user_id']} (<@{ticket_data['user_id']}>)\n"
        transcript += f"Created: {ticket_data['created_at']}\n"
        transcript += f"Status: {ticket_data['status']}\n"
        if ticket_data.get('claimed_by'):
            transcript += f"Claimed by: {ticket_data['claimed_by']} (<@{ticket_data['claimed_by']}>)\n"
        transcript += f"Priority: {ticket_data.get('priority', 'normal')}\n"
        transcript += "=" * 50 + "\n\n"
        
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                content = message.content
                if message.embeds:
                    for embed in message.embeds:
                        content += f"\n[Embed: {embed.title or 'No title'}]"
                if message.attachments:
                    for attachment in message.attachments:
                        content += f"\n[Attachment: {attachment.filename}]"
                
                messages.append(f"[{message.created_at}] {message.author.display_name}: {content}")
            
            transcript += "\n".join(messages)
        except:
            transcript += "Could not retrieve messages from channel."
        
        return transcript

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(TicketCategorySelect())

    @app_commands.command(name="ticketpanel", description="Create a ticket panel")
    @app_commands.check(is_admin)
    async def ticketpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Create a Ticket",
            description="Click the button below to create a new ticket. Please select the appropriate category for your inquiry.",
            color=discord.Color.blue()
        )
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Create Ticket",
            style=discord.ButtonStyle.primary,
            emoji="🎫",
            custom_id="create_ticket"
        ))
        
        await interaction.response.send_message(embed=embed, view=view)

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="create_ticket")
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TicketCategorySelect()
        await interaction.response.send_message(
            "Please select a category for your ticket:",
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="close", description="Close the current ticket")
    async def close(self, interaction: discord.Interaction):
        ticket_data = None
        for ticket_id, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id and data["status"] == "open":
                ticket_data = data
                ticket_id_to_close = ticket_id
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not an open ticket channel.", ephemeral=True)
            return
        
        if not await is_admin(interaction) and interaction.user.id != ticket_data["user_id"]:
            await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
            return
        
        await interaction.response.send_modal(CloseTicketModal(ticket_id_to_close))

    @app_commands.command(name="adduser", description="Add a user to the ticket")
    @app_commands.describe(user="The user to add to the ticket")
    async def adduser(self, interaction: discord.Interaction, user: discord.Member):
        ticket_data = None
        for ticket_id, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id and data["status"] == "open":
                ticket_data = data
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not an open ticket channel.", ephemeral=True)
            return
        
        if not await is_admin(interaction):
            await interaction.response.send_message("You don't have permission to add users to this ticket.", ephemeral=True)
            return
        
        channel = interaction.channel
        await channel.set_permissions(user, read_messages=True, send_messages=True)
        
        embed = discord.Embed(
            description=f"✅ {user.mention} has been added to the ticket.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removeuser", description="Remove a user from the ticket")
    @app_commands.describe(user="The user to remove from the ticket")
    async def removeuser(self, interaction: discord.Interaction, user: discord.Member):
        ticket_data = None
        for ticket_id, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id and data["status"] == "open":
                ticket_data = data
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not an open ticket channel.", ephemeral=True)
            return
        
        if not await is_admin(interaction):
            await interaction.response.send_message("You don't have permission to remove users from this ticket.", ephemeral=True)
            return
        
        channel = interaction.channel
        await channel.set_permissions(user, read_messages=False, send_messages=False)
        
        embed = discord.Embed(
            description=f"✅ {user.mention} has been removed from the ticket.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rename", description="Rename the ticket channel")
    @app_commands.describe(new_name="The new name for the channel")
    async def rename(self, interaction: discord.Interaction, new_name: str):
        ticket_data = None
        for ticket_id, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id:
                ticket_data = data
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return
        
        if not await is_admin(interaction):
            await interaction.response.send_message("You don't have permission to rename this ticket.", ephemeral=True)
            return
        
        channel = interaction.channel
        await channel.edit(name=new_name)
        
        embed = discord.Embed(
            description=f"✅ Channel renamed to: **{new_name}**",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="claim", description="Claim or unclaim the current ticket")
    async def claim(self, interaction: discord.Interaction):
        ticket_data = None
        ticket_id = None
        for tid, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id and data["status"] == "open":
                ticket_data = data
                ticket_id = tid
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not an open ticket channel.", ephemeral=True)
            return
        
        if ticket_data.get('claimed_by') == interaction.user.id:
            ticket_data['claimed_by'] = None
            await interaction.response.send_message("You have unclaimed this ticket.", ephemeral=True)
            await log_ticket_action(interaction.guild, "Unclaim", ticket_data, f"By: {interaction.user.mention}")
        else:
            ticket_data['claimed_by'] = interaction.user.id
            await interaction.response.send_message("You have claimed this ticket!", ephemeral=True)
            await log_ticket_action(interaction.guild, "Claim", ticket_data, f"By: {interaction.user.mention}")
        
        ticket_data['last_activity'] = datetime.now().isoformat()
        TicketManager.update_ticket(ticket_id, ticket_data)

    @app_commands.command(name="priority", description="Set the priority of the current ticket")
    @app_commands.describe(priority="The priority level")
    async def priority(self, interaction: discord.Interaction, priority: str):
        ticket_data = None
        ticket_id = None
        for tid, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id and data["status"] == "open":
                ticket_data = data
                ticket_id = tid
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not an open ticket channel.", ephemeral=True)
            return
        
        if not await is_admin(interaction):
            await interaction.response.send_message("You don't have permission to change the priority.", ephemeral=True)
            return
        
        if priority.lower() not in ["urgent", "high", "normal", "low"]:
            await interaction.response.send_message("Invalid priority. Use: urgent, high, normal, or low.", ephemeral=True)
            return
        
        ticket_data['priority'] = priority.lower()
        ticket_data['last_activity'] = datetime.now().isoformat()
        TicketManager.update_ticket(ticket_id, ticket_data)
        
        await interaction.response.send_message(f"Priority set to {priority.capitalize()}!", ephemeral=True)
        await log_ticket_action(interaction.guild, "Priority Change", ticket_data, f"Set to: {priority.capitalize()} by {interaction.user.mention}")

    @app_commands.command(name="transcript", description="Generate a transcript of the current ticket")
    async def transcript(self, interaction: discord.Interaction):
        ticket_data = None
        ticket_id = None
        for tid, data in TicketManager.load_tickets()["tickets"].items():
            if data["channel_id"] == interaction.channel_id:
                ticket_data = data
                ticket_id = tid
                break
        
        if not ticket_data:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return
        
        if interaction.user.id != ticket_data.get('user_id') and not await is_admin(interaction):
            await interaction.response.send_message("You do not have permission to generate a transcript.", ephemeral=True)
            return
        
        transcript = await TicketCloseConfirmView(ticket_id, "", interaction.user.id).generate_transcript(interaction.channel, ticket_data)
        transcript_file = discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{ticket_id}-transcript.txt")
        await interaction.response.send_message("Here is the transcript:", file=transcript_file, ephemeral=True)
        await log_ticket_action(interaction.guild, "Transcript", ticket_data, f"Generated by: {interaction.user.mention}")

    @app_commands.command(name="tickets", description="View all tickets")
    @app_commands.check(is_admin)
    async def tickets(self, interaction: discord.Interaction):
        tickets = TicketManager.load_tickets()
        
        if not tickets["tickets"]:
            embed = discord.Embed(
                title="📋 All Tickets",
                description="No tickets found.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        open_tickets = [t for t in tickets["tickets"].values() if t["status"] == "open"]
        closed_tickets = [t for t in tickets["tickets"].values() if t["status"] == "closed"]
        
        embed = discord.Embed(
            title="📋 Ticket Overview",
            description=f"**Open:** {len(open_tickets)} | **Closed:** {len(closed_tickets)} | **Total:** {len(tickets['tickets'])}",
            color=discord.Color.blue()
        )
        
        if open_tickets:
            open_list = []
            for ticket in open_tickets[:10]:
                channel = interaction.guild.get_channel(ticket["channel_id"])
                channel_mention = channel.mention if channel else f"Channel {ticket['channel_id']}"
                claimed = f" (Claimed by <@{ticket['claimed_by']}>)" if ticket.get('claimed_by') else ""
                open_list.append(f"• **{ticket['ticket_id']}** - {ticket['category']} - <@{ticket['user_id']}> - {channel_mention}{claimed}")
            
            if len(open_tickets) > 10:
                open_list.append(f"... and {len(open_tickets) - 10} more")
            
            embed.add_field(name="Open Tickets", value="\n".join(open_list), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ticketsettings", description="Configure ticket system settings")
    @app_commands.check(is_admin)
    async def ticketsettings(self, interaction: discord.Interaction):
        modal = TicketSettingsModal(self.bot)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="setcategory", description="Set ticket categories")
    @app_commands.check(is_admin)
    async def setcategory(self, interaction: discord.Interaction):
        modal = TicketCategoryModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="closealltickets", description="Close all open tickets")
    @app_commands.check(is_admin)
    async def closealltickets(self, interaction: discord.Interaction):
        view = CloseAllTicketsView()
        await interaction.response.send_message(
            "⚠️ **Warning: This will close ALL open tickets!**\n\nThis action cannot be undone.",
            view=view,
            ephemeral=True
        )

class TicketCategoryModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Set Ticket Categories")
        
        config = load_data('config')
        current_categories = "\n".join([
            f"{c['name']}, {c.get('emoji', '')}, {c.get('description', '')}".rstrip(", ")
            for c in config.get("ticket_categories", [])
        ])
        
        self.categories = discord.ui.TextInput(
            label="Categories (one per line)",
            placeholder="Format: Name, Emoji, Description",
            style=discord.TextStyle.paragraph,
            required=True,
            default=current_categories,
            max_length=1000
        )
        self.add_item(self.categories)

    async def on_submit(self, interaction):
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

        config = load_data('config')
        config["ticket_categories"] = categories
        save_data('config', config)

        categories_text = "\n".join([f"• {c['name']} {c.get('emoji', '')}" for c in categories])

        embed = discord.Embed(
            title="Ticket Categories Updated",
            description=f"The following categories have been set:\n\n{categories_text}",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Ticket categories updated by {interaction.user} (ID: {interaction.user.id})")

class TicketSettingsModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Ticket System Settings")
        self.bot = bot

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
        config = load_data('config')

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

        save_data('config', config)

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
        logger.info(f"Ticket settings updated by {interaction.user} (ID: {interaction.user.id})")

class CloseAllTicketsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, close all tickets", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        tickets = TicketManager.load_tickets()
        open_tickets = {tid: t for tid, t in tickets["tickets"].items() if t["status"] == "open"}

        if not open_tickets:
            await interaction.followup.send("There are no open tickets to close!", ephemeral=True)
            return

        closed_count = 0
        for ticket_id, ticket_data in open_tickets.items():
            ticket_data["status"] = "closed"
            ticket_data["closed_at"] = datetime.now().isoformat()
            ticket_data["closed_by"] = interaction.user.id
            ticket_data["close_reason"] = "Mass closure by administrator"
            ticket_data["close_type"] = "mass closed by administrator"

            channel = interaction.guild.get_channel(ticket_data["channel_id"])
            if channel:
                try:
                    await channel.delete(reason=f"Mass ticket closure by {interaction.user}")
                    closed_count += 1
                except:
                    pass

        TicketManager.save_tickets(tickets)

        await interaction.followup.send(f"Successfully closed {closed_count} tickets!", ephemeral=True)
        logger.info(
            f"Mass ticket closure: {closed_count} tickets closed by {interaction.user} (ID: {interaction.user.id})")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.send_message("Action cancelled.", ephemeral=True)

async def log_ticket_action(guild, action: str, ticket_data: dict, extra: str = ""):
    try:
        config = load_data('config')
        log_channel_id = config.get("ticket_log_channel")
        if not log_channel_id:
            return
        log_channel = guild.get_channel(int(log_channel_id))
        if not log_channel:
            return
        embed = discord.Embed(
            title=f"[Ticket] {action}",
            description=f"Ticket ID: {ticket_data.get('ticket_id')}\nUser: <@{ticket_data.get('user_id')}>\nCategory: {ticket_data.get('category')}\nStatus: {ticket_data.get('status')}\n{extra}",
            color=discord.Color.blurple(),
            timestamp=datetime.now()
        )
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to log ticket action: {e}")

async def setup(bot):
    await bot.add_cog(Tickets(bot))
