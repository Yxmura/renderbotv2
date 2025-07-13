import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
from typing import Optional, Dict, Any, List
import io
import re
import textwrap
from datetime import datetime, timedelta
import logging
import os
from dataclasses import dataclass, asdict, field
import uuid
from bot import load_data, save_data
from supabase_client import get_db


# Set up logging
logger = logging.getLogger('bot.tickets')

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# --- Discord-Native Metadata Utilities ---

async def get_metadata_from_channel(channel: discord.TextChannel) -> Optional[dict]:
    """Fetches and parses ticket metadata from a message in the channel."""
    if not channel.topic or not channel.topic.isdigit():
        return None
    try:
        message_id = int(channel.topic)
        metadata_msg = await channel.fetch_message(message_id)
        if not metadata_msg.embeds:
            return None
        
        # Find the JSON in the embed's description or a field
        json_str = None
        if "```json" in metadata_msg.embeds[0].description:
            json_str = metadata_msg.embeds[0].description.split('```json\n')[1].split('```')[0]
        else:
            for field in metadata_msg.embeds[0].fields:
                if field.name == "Metadata":
                    json_str = field.value.split('```json\n')[1].split('```')[0]
                    break
        
        if json_str:
            return json.loads(json_str)
    except (discord.NotFound, json.JSONDecodeError, IndexError):
        return None
    return None

async def update_metadata_message(channel: discord.TextChannel, new_metadata: dict):
    """Updates the metadata message in the channel."""
    if not channel.topic or not channel.topic.isdigit():
        return
    try:
        message_id = int(channel.topic)
        metadata_msg = await channel.fetch_message(message_id)
        
        embed = metadata_msg.embeds[0]
        embed.description = f"```json\n{json.dumps(new_metadata, indent=2)}```"
        await metadata_msg.edit(embed=embed)
    except (discord.NotFound, IndexError):
        pass # Or handle error appropriately

async def create_metadata_message(channel: discord.TextChannel, metadata: dict):
    """Creates a new metadata message in the channel."""
    embed = discord.Embed(title="Ticket Metadata", description=f"```json\n{json.dumps(metadata, indent=2)}```")
    metadata_msg = await channel.send(embed=embed)
    await channel.edit(topic=str(metadata_msg.id))

# Base form modal for ticket creation
class TicketFormModal(discord.ui.Modal):    
    def __init__(self, category: str, *args, **kwargs):
        super().__init__(title=f"{category} - Ticket Details", *args, **kwargs)
        self.category = category
        self.form_data = {}
    
    async def on_submit(self, interaction: discord.Interaction):
        # Store the form data
        self.form_data = {}
        for child in self.children:
            if isinstance(child, discord.ui.TextInput):
                if child.value:  # Only store non-empty values
                    self.form_data[child.label] = child.value
        
        # Format the data into a nice embed
        form_embed = self.format_embed(interaction)
        
        # Acknowledge the modal submission
        await interaction.response.defer(ephemeral=True)
        
        # Create the ticket channel
        ticket_view = TicketCategorySelect()  # Get an instance to access helper methods
        result = await ticket_view.create_ticket_channel(interaction, self)
        
        if not result:
            return  # Error already handled in create_ticket_channel
            
        channel, metadata = result
        
        # Send the ticket created message with form data
        await ticket_view.send_ticket_created_message(
            interaction,
            channel,
            self.ticket_id,
            self.category,
            form_embed=form_embed
        )
        
        # Send confirmation to user
        await interaction.followup.send(
            f"Ticket created! Please check {channel.mention}", 
            ephemeral=True
        )
    
    def format_embed(self, interaction: discord.Interaction) -> discord.Embed:
        """Format the form data into an embed for the ticket channel."""
        embed = discord.Embed(
            title=f"Ticket Details - {self.category}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        # Add user info
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        
        # Add form fields
        for field_name, value in self.form_data.items():
            if value:  # Only add non-empty fields
                embed.add_field(name=field_name, value=value[:1024], inline=False)
        
        return embed


class ResourceIssueModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Resource Issue", *args, **kwargs)
        
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
        # Store the form data
        self.form_data = {}
        if self.resource_title.value:
            self.form_data["Resource Title"] = self.resource_title.value
        self.form_data["Issue Description"] = self.issue_description.value
        
        # Call parent's on_submit to handle the rest
        await super().on_submit(interaction)


class PartnerSponsorModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Partner/Sponsor Inquiry", *args, **kwargs)
        
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
        # Store the form data
        self.form_data = {
            "Organization/Channel Name": self.organization.value,
            "Link": f"[Click here]({self.link.value})" if self.link.value.startswith(('http://', 'https://')) else self.link.value,
            "Details": self.details.value
        }
        
        # Call parent's on_submit to handle the rest
        await super().on_submit(interaction)


class StaffApplicationModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Staff Application", *args, **kwargs)
        
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
        # Store the form data
        self.form_data = {
            "Full Name": self.name.value,
            "Age": self.age.value,
            "Timezone": self.timezone.value,
            "Previous Experience": self.experience.value,
            "Why do you want to join our staff team?": self.why_join.value
        }
        
        # Call parent's on_submit to handle the rest
        await super().on_submit(interaction)


class ContentCreatorModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Content Creator Application", *args, **kwargs)
        
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
        # Store the form data
        self.form_data = {
            "Channel Name": self.channel_name.value,
            "Channel URL": f"[Click here]({self.channel_url.value})" if self.channel_url.value.startswith(('http://', 'https://')) else self.channel_url.value,
            "Subscriber/Followers Count": self.subscriber_count.value,
            "Collaboration Ideas": self.collab_ideas.value
        }
        
        # Add optional fields if provided
        if self.last_video_views.value:
            self.form_data["Last Video View Count"] = self.last_video_views.value
            
        # Call parent's on_submit to handle the rest
        await super().on_submit(interaction)


class OtherInquiryModal(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Other Inquiry", *args, **kwargs)
        
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
        # Store the form data
        self.form_data = {
            "Subject": self.subject.value,
            "Details": self.details.value
        }
        
        # Call parent's on_submit to handle the rest


@dataclass
class TicketMetadata:
    """Class to handle ticket metadata and database operations."""
    def __init__(self, **kwargs):
        self.ticket_id = kwargs.get('ticket_id', str(uuid.uuid4()))
        self.user_id = kwargs.get('user_id')
        self.category = kwargs.get('category')
        self.status = kwargs.get('status', 'open')
        self.priority = kwargs.get('priority', 'normal')
        self.created_at = kwargs.get('created_at', datetime.now().isoformat())
        self.claimed_by = kwargs.get('claimed_by')
        self.last_activity = kwargs.get('last_activity', datetime.now().isoformat())
        self.closed_at = kwargs.get('closed_at')
        self.closed_by = kwargs.get('closed_by')
        self.close_reason = kwargs.get('close_reason')
        self.close_type = kwargs.get('close_type')
        self.channel_id = kwargs.get('channel_id')
        self.guild_id = kwargs.get('guild_id')

    @classmethod
    def from_topic(cls, topic: Optional[str]) -> Optional['TicketMetadata']:
        """Create TicketMetadata from channel topic."""
        if not topic:
            return None
            
        try:
            data = json.loads(topic)
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Error parsing ticket metadata: {e}")
            return None
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TicketMetadata':
        """Create TicketMetadata from dictionary."""
        return cls(**data)
    
    @classmethod
    async def from_channel(cls, channel: discord.TextChannel) -> Optional['TicketMetadata']:
        """Load ticket metadata from database using channel."""
        if not channel.topic or not channel.topic.isdigit():
            return None
            
        try:
            ticket_id = channel.topic
            db = get_db()
            ticket_data = await db.tickets.get_ticket(ticket_id)
            if not ticket_data:
                return None
                
            return cls.from_dict(ticket_data)
        except Exception as e:
            logger.error(f"Error loading ticket from database: {e}")
            return None
            
    async def save(self):
        """Save ticket metadata to database."""
        try:
            data = self.to_dict()
            db = get_db()
            
            # Check if ticket exists
            existing_ticket = await db.tickets.get_ticket(self.ticket_id)
            
            if existing_ticket:
                # Update existing ticket
                return await db.tickets.update_ticket(self.ticket_id, data)
            else:
                # Insert new ticket
                ticket_id = await db.tickets.create_ticket(data)
                return ticket_id is not None
        except Exception as e:
            logger.error(f"Error saving ticket to database: {e}")
            return False
    
    def to_topic(self) -> str:
        """Convert metadata to channel topic string."""
        return self.ticket_id
        
    def to_dict(self) -> dict:
        """Convert metadata to dictionary."""
        return {
            'ticket_id': self.ticket_id,
            'user_id': self.user_id,
            'category': self.category,
            'status': self.status,
            'priority': self.priority,
            'created_at': self.created_at,
            'claimed_by': self.claimed_by,
            'last_activity': self.last_activity,
            'closed_at': self.closed_at,
            'closed_by': self.closed_by,
            'close_reason': self.close_reason,
            'close_type': self.close_type,
            'channel_id': self.channel_id,
            'guild_id': self.guild_id
        }
        
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now().isoformat()
        
    async def close(self, closer_id: int, reason: str, close_type: str):
        """Close the ticket."""
        self.status = "closed"
        self.closed_by = closer_id
        self.close_reason = reason
        self.close_type = close_type
        self.closed_at = datetime.now().isoformat()
        self.update_activity()
        await self.save()
    
    async def set_priority(self, priority: str):
        """Set ticket priority."""
        self.priority = priority
        self.update_activity()
        await self.save()
    
    async def claim(self, user_id: int):
        """Claim ticket for a user."""
        self.claimed_by = user_id
        self.update_activity()
        await self.save()
    
    async def unclaim(self):
        """Unclaim ticket."""
        self.claimed_by = None
        self.update_activity()
        await self.save()

# Load config (only config, not tickets)
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
    """Save config to file."""
    os.makedirs('data', exist_ok=True)
    with open('data/config.json', 'w') as f:
        json.dump(config, f, indent=4)


async def is_admin(interaction: discord.Interaction) -> bool:
    """Check if the user has admin permissions.
    
    Args:
        interaction: The Discord interaction object
        
    Returns:
        bool: True if user has admin permissions, False otherwise
    """
    # Check if user has administrator permission
    if interaction.user.guild_permissions.administrator:
        return True
        
    # Check if user has any admin roles
    config = load_data('config')
    admin_roles = config.get("admin_roles", [])
    
    # If no admin roles are set, only server admins can use admin commands
    if not admin_roles:
        return False
        
    # Check if user has any of the admin roles
    user_role_ids = [str(role.id) for role in interaction.user.roles]
    return any(role_id in user_role_ids for role_id in admin_roles)


class TicketCategoryButton(discord.ui.Button):
    def __init__(self, category, row=0):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=category["name"],
            emoji=category.get("emoji", "🎫"),
            custom_id=f"ticket_{category['name'].lower().replace(' ', '_')}",
            row=row
        )
        self.category = category
        
    async def callback(self, interaction: discord.Interaction):
        # Defer to prevent interaction timeout
        await interaction.response.defer(ephemeral=True)
        
        # Check if user already has an open ticket
        guild = interaction.guild
        for channel in guild.channels:
            if not isinstance(channel, discord.TextChannel):
                continue
                
            # Check if channel is a ticket channel for this user
            metadata = TicketMetadata.from_topic(channel.topic)
            if (metadata and 
                metadata.user_id == interaction.user.id and 
                metadata.status == "open"):
                await interaction.followup.send(
                    f"You already have an open ticket: {channel.mention}", 
                    ephemeral=True
                )
                return

        # Create new ticket
        ticket_id = str(uuid.uuid4())[:8]
        category_name = self.category["name"]
        
        # Show the appropriate modal based on the selected category
        modal = None
        if "Resource Issue" in category_name:
            modal = ResourceIssueModal()
        elif "Partner" in category_name or "Sponsor" in category_name:
            modal = PartnerSponsorModal()
        elif "Staff" in category_name or "Application" in category_name:
            modal = StaffApplicationModal()
        elif "Content" in category_name or "Creator" in category_name:
            modal = ContentCreatorModal()
        else:  # General Support, Other, or any other category
            modal = OtherInquiryModal()
        
        # Store the ticket creation context on the modal
        modal.ticket_id = ticket_id
        modal.category = category_name
        modal.guild = guild
        modal.interaction = interaction
        modal.overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                manage_channels=True,
                manage_roles=True
            )
        }
        
        # Add admin roles to channel permissions
        config = load_config()
        for role_id in config.get("admin_roles", []):
            role = guild.get_role(int(role_id))
            if role:
                modal.overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True
                )
        
        # Show the modal to the user
        await interaction.followup.send_modal(modal)


class TicketView(discord.ui.View):
    def __init__(self, categories=None):
        super().__init__(timeout=None)
        if not categories:
            try:
                # Load categories from config.json
                with open('data/config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                categories = config.get('ticket_categories', [
                    {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
                    {"name": "Resource Issue", "emoji": "⚠️", "description": "Report a problem with a resource"},
                    {"name": "Partner/Sponsor", "emoji": "💰", "description": "Partner or sponsorship inquiries"},
                    {"name": "Staff Application", "emoji": "🔒", "description": "Request for staff application"},
                    {"name": "Content Creator", "emoji": "📷", "description": "Content creator application"},
                    {"name": "Other", "emoji": "📝", "description": "Other inquiries"}
                ])
                logger.info(f"Loaded {len(categories)} ticket categories from config")
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                categories = [
                    {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
                    {"name": "Resource Issue", "emoji": "⚠️", "description": "Report a problem with a resource"},
                    {"name": "Partner/Sponsor", "emoji": "💰", "description": "Partner or sponsorship inquiries"},
                    {"name": "Staff Application", "emoji": "🔒", "description": "Request for staff application"},
                    {"name": "Content Creator", "emoji": "📷", "description": "Content creator application"},
                    {"name": "Other", "emoji": "📝", "description": "Other inquiries"}
                ]
        
        # Add buttons in rows of 2
        row = 0
        for i, category in enumerate(categories):
            if i > 0 and i % 2 == 0:
                row += 1
            try:
                self.add_item(TicketCategoryButton(category, row=row))
                logger.debug(f"Added button for category: {category.get('name')}")
            except Exception as e:
                logger.error(f"Error adding button for category {category.get('name', 'unknown')}: {e}")


# Ticket category button panel
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(
        label="General Support", 
        style=discord.ButtonStyle.primary, 
        emoji="❓",
        custom_id="ticket_general_support",
        row=0
    )
    async def general_support_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction, "General Support")
    
    @discord.ui.button(
        label="Resource Issue", 
        style=discord.ButtonStyle.danger, 
        emoji="⚠️",
        custom_id="ticket_resource_issue",
        row=0
    )
    async def resource_issue_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction, "Resource Issue")
    
    @discord.ui.button(
        label="Partner/Sponsor", 
        style=discord.ButtonStyle.success, 
        emoji="💰",
        custom_id="ticket_partner_sponsor",
        row=1
    )
    async def partner_sponsor_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction, "Partner/Sponsor")
    
    @discord.ui.button(
        label="Staff Application", 
        style=discord.ButtonStyle.secondary, 
        emoji="🔒",
        custom_id="ticket_staff_application",
        row=1
    )
    async def staff_application_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction, "Staff Application")
    
    @discord.ui.button(
        label="Content Creator", 
        style=discord.ButtonStyle.primary, 
        emoji="📷",
        custom_id="ticket_content_creator",
        row=2
    )
    async def content_creator_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction, "Content Creator")
    
    @discord.ui.button(
        label="Other", 
        style=discord.ButtonStyle.secondary, 
        emoji="📝",
        custom_id="ticket_other",
        row=2
    )
    async def other_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction, "Other")
    
    async def handle_ticket_creation(self, interaction: discord.Interaction, category_name: str):
        # Defer to prevent interaction timeout
        await interaction.response.defer(ephemeral=True)
        
        # Check if user already has an open ticket
        guild = interaction.guild
        for channel in guild.channels:
            if not isinstance(channel, discord.TextChannel):
                continue
                
            # Check if channel is a ticket channel for this user
            metadata = TicketMetadata.from_topic(channel.topic)
            if (metadata and 
                metadata.user_id == interaction.user.id and 
                metadata.status == "open"):
                await interaction.followup.send(
                    f"You already have an open ticket: {channel.mention}", 
                    ephemeral=True
                )
                return

        # Create new ticket
        ticket_id = str(uuid.uuid4())[:8]
        
        # Show the appropriate modal based on the selected category
        modal = None
        if "Resource Issue" in category_name:
            modal = ResourceIssueModal()
        elif "Partner" in category_name or "Sponsor" in category_name:
            modal = PartnerSponsorModal()
        elif "Staff" in category_name or "Application" in category_name:
            modal = StaffApplicationModal()
        elif "Content" in category_name or "Creator" in category_name:
            modal = ContentCreatorModal()
        else:  # General Support, Other, or any other category
            modal = OtherInquiryModal()
        
        # Store the ticket creation context on the modal
        modal.ticket_id = ticket_id
        modal.category = category_name
        modal.guild = guild
        modal.interaction = interaction
        modal.overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                manage_channels=True,
                manage_roles=True
            )
        }
        
        # Add admin roles to channel permissions
        config = load_config()
        for role_id in config.get("admin_roles", []):
            role = guild.get_role(int(role_id))
            if role:
                modal.overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True
                )
        
        # Show the modal to the user
        await interaction.followup.send_modal(modal)

    async def callback(self, interaction: discord.Interaction):
        # Check if user already has an open ticket
        guild = interaction.guild
        for channel in guild.channels:
            if not isinstance(channel, discord.TextChannel):
                continue
                
            # Check if channel is a ticket channel for this user
            metadata = TicketMetadata.from_topic(channel.topic)
            if (metadata and 
                metadata.user_id == interaction.user.id and 
                metadata.status == "open"):
                await interaction.response.send_message(
                    f"You already have an open ticket: {channel.mention}", 
                    ephemeral=True
                )
        # Create ticket ID and store context on the modal
        ticket_id = str(uuid.uuid4())
        modal.ticket_id = ticket_id
        modal.category = category_name
        modal.guild = guild
        modal.interaction = interaction
        modal.overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
                manage_roles=True
            )
        }
        
        # Add admin roles to channel permissions
        config = load_config()
        for role_id in config.get("admin_roles", []):
            role = guild.get_role(int(role_id))
            if role:
                modal.overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True
                )
        
        # Show the modal to the user
        await interaction.followup.send_modal(modal)

    async def create_ticket_channel(self, interaction: discord.Interaction, modal: TicketFormModal):
        """Helper method to create the ticket channel after form submission."""
        try:
            # Get the ticket category from config
            config = load_config()
            category_id = config.get('ticket_category_id')
            if not category_id:
                await interaction.followup.send(
                    "Ticket category not configured. Please contact an admin.",
                    ephemeral=True
                )
                return None
                
            # Create ticket channel
            guild = interaction.guild
            ticket_id = modal.ticket_id
            ticket_channel_name = f"ticket-{ticket_id[:8]}"
            
            # Get the category
            category = guild.get_channel(int(category_id))
            if not category:
                await interaction.followup.send(
                    "Ticket category not found. Please contact an admin.",
                    ephemeral=True
                )
                return None
            
            # Create the ticket channel with permissions
            ticket_channel = await guild.create_text_channel(
                name=ticket_channel_name,
                category=category,
                overwrites=modal.overwrites,
                reason=f"Ticket created by {interaction.user}"
            )
            
            # Create ticket metadata
            metadata = TicketMetadata(
                ticket_id=ticket_id,
                user_id=interaction.user.id,
                category=modal.category,
                guild_id=guild.id,
                channel_id=ticket_channel.id,
                created_at=datetime.now().isoformat(),
                last_activity=datetime.now().isoformat()
            )
            
            # Save ticket to database
            if not await metadata.save():
                logger.error("Failed to save ticket to database")
                await ticket_channel.delete(reason="Failed to save ticket data")
                await interaction.followup.send(
                    "An error occurred while creating the ticket. Please try again.",
                    ephemeral=True
                )
                return None
            
            # Set the channel topic to the ticket ID for reference
            await ticket_channel.edit(topic=metadata.to_topic())
            
            # Create initial message with ticket info
            embed = discord.Embed(
                title=f"Ticket: {modal.category}",
                description=(
                    f"Thank you for creating a ticket, {interaction.user.mention}!\n"
                    f"A staff member will be with you shortly.\n\n"
                    f"**Ticket ID:** `{ticket_id}`\n"
                    f"**Category:** {modal.category}\n"
                    f"**Status:** Open\n"
                    f"**Created:** <t:{int(datetime.now().timestamp())}:R>"
                ),
                color=discord.Color.blue()
            )
            
            # Add form data to embed if any
            if hasattr(modal, 'form_data') and modal.form_data:
                form_text = "\n".join([f"**{k}:** {v}" for k, v in modal.form_data.items()])
                embed.add_field(name="Details", value=form_text, inline=False)
            
            # Add controls
            controls = TicketControlsView(ticket_id)
            
            # Create ticket channel
            guild = interaction.guild
            ticket_channel_name = f"ticket-{ticket_id[:8]}"
                
            # Get the category
            category = guild.get_channel(int(category_id))
            if not category:
                await interaction.followup.send(
                    "Ticket category not found. Please contact an admin.",
                    ephemeral=True
                )
                return None
                
            # Create the ticket channel with permissions
            ticket_channel = await guild.create_text_channel(
                name=ticket_channel_name,
                category=category,
                overwrites=modal.overwrites,
                reason=f"Ticket created by {interaction.user}"
            )
                
            # Create ticket metadata
            metadata = {
                'ticket_id': ticket_id,
                'user_id': interaction.user.id,
                'category': modal.category,
                'guild_id': guild.id,
                'channel_id': ticket_channel.id,
                'created_at': datetime.utcnow().isoformat(),
                'last_activity': datetime.utcnow().isoformat(),
                'status': 'open',
                'priority': 'normal'
            }
            
            # Save ticket to Supabase
            try:
                result = supabase.table('tickets').insert(metadata).execute()
                if not result.data:
                    raise Exception("No data returned from Supabase")
            except Exception as e:
                logger.error(f"Failed to save ticket to Supabase: {e}")
                try:
                    await ticket_channel.delete(reason="Failed to save ticket data")
                except Exception as delete_error:
                    logger.error(f"Failed to delete channel after save error: {delete_error}")
                
                await interaction.followup.send(
                    "An error occurred while creating the ticket. Please try again.",
                    ephemeral=True
                )
                return None
            
            # Set the channel topic to the ticket ID for reference
            await ticket_channel.edit(topic=f"ticket:{ticket_id}")
                
            # Create initial message with ticket info
            embed = discord.Embed(
                title=f"Ticket: {modal.category}",
                description=(
                    f"Thank you for creating a ticket, {interaction.user.mention}!\n"
                    f"A staff member will be with you shortly.\n\n"
                    f"**Ticket ID:** `{ticket_id}`\n"
                    f"**Category:** {modal.category}\n"
                    f"**Status:** Open\n"
                    f"**Created:** <t:{int(datetime.utcnow().timestamp())}:R>"
                ),
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
                
            # Add form data to embed if any
            if hasattr(modal, 'form_data') and modal.form_data:
                form_text = "\n".join([f"**{k}:** {v}" for k, v in modal.form_data.items()])
                embed.add_field(name="Details", value=form_text, inline=False)
                
            # Add controls
            controls = TicketControlsView(ticket_id)
                
            # Send the initial message
            await ticket_channel.send(embed=embed, view=controls)
                
            # Send confirmation to user (ephemeral)
            await interaction.followup.send(
                f"Your ticket has been created: {ticket_channel.mention}",
                ephemeral=True
            )
            
            # Log ticket creation
            log_channel_id = config.get('log_channel_id')
            if log_channel_id:
                try:
                    log_channel = guild.get_channel(int(log_channel_id))
                    if log_channel:
                        log_embed = discord.Embed(
                            title="🎫 Ticket Created",
                            description=(
                                f"**Ticket ID:** `{ticket_id}`\n"
                                f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                                f"**Category:** {modal.category}\n"
                                f"**Channel:** {ticket_channel.mention}"
                            ),
                            color=discord.Color.green(),
                            timestamp=datetime.utcnow()
                        )
                        log_embed.set_footer(text=f"User ID: {interaction.user.id}")
                        
                        # Add form data to log if it exists
                        if hasattr(modal, 'form_data') and modal.form_data:
                            form_text = "\n".join([f"**{k}:** {v}" for k, v in modal.form_data.items()])
                            log_embed.add_field(name="Form Data", value=form_text, inline=False)
                        
                        # Send as a webhook if configured for better formatting
                        webhook_url = config.get('log_webhook_url')
                        if webhook_url:
                            try:
                                webhook = discord.SyncWebhook.from_url(webhook_url)
                                webhook.send(embed=log_embed, username=f"Ticket System - {guild.name}")
                            except Exception as e:
                                logger.error(f"Failed to send webhook log: {e}")
                                await log_channel.send(embed=log_embed)
                        else:
                            await log_channel.send(embed=log_embed)
                except Exception as e:
                    logger.error(f"Error logging ticket creation: {e}")
                    # Continue with ticket creation even if logging fails
        
            return ticket_channel
            
        except discord.Forbidden as e:
            logger.error(f"Bot lacks permissions to create ticket channel: {e}")
            try:
                await interaction.followup.send(
                    "I don't have permission to create channels in this server. "
                    "Please check my permissions and try again.",
                    ephemeral=True
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")
            return None
            
        except discord.HTTPException as e:
            logger.error(f"Discord HTTP error creating ticket: {e}")
            try:
                await interaction.followup.send(
                    "An error occurred while creating the ticket. Please try again later.",
                    ephemeral=True
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error in create_ticket_channel: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "An unexpected error occurred. Please try again or contact an admin.",
                    ephemeral=True
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")
            return None

async def log_ticket_creation(self, interaction, ticket_id, category, channel):
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


class AssignTicketButton(discord.ui.Button):
    """Button for claiming/unclaiming a ticket."""
    
    def __init__(self, ticket_id: str, is_assigned: bool = False):
        self.ticket_id = ticket_id
        self.is_assigned = is_assigned
        
        # Set button style and label based on assignment state
        style = discord.ButtonStyle.success if not is_assigned else discord.ButtonStyle.danger
        label = "Claim Ticket" if not is_assigned else "Unassign"
        emoji = "🙋" if not is_assigned else "✖️"
        
        super().__init__(
            style=style,
            label=label,
            emoji=emoji,
            custom_id=f"ticket_assign_{ticket_id}",
            row=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle button click to claim or unassign the ticket."""
        # Defer the interaction first
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # Get the parent view
        view = self.view
        if not hasattr(view, 'ticket_id'):
            await interaction.followup.send("❌ Could not process this action. Please try again.", ephemeral=True)
            return
        
        # Get ticket metadata
        metadata = await view.get_ticket_metadata(interaction)
        if not metadata:
            await interaction.followup.send("❌ Could not find ticket metadata.", ephemeral=True)
            return
        
        # Toggle assignment
        if self.is_assigned:
            # Unassign the ticket
            updates = {
                'assigned_to': None,
                'assigned_at': None,
                'assigned_by': None
            }
            success = await view.update_ticket_metadata(interaction, updates)
            if success:
                await interaction.followup.send("✅ You have unassigned this ticket.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to unassign the ticket.", ephemeral=True)
        else:
            # Assign the ticket to the user
            updates = {
                'assigned_to': interaction.user.id,
                'assigned_at': datetime.now().isoformat(),
                'assigned_by': interaction.user.id
            }
            success = await view.update_ticket_metadata(interaction, updates)
            if success:
                await interaction.followup.send("✅ You have claimed this ticket!", ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to claim the ticket.", ephemeral=True)


class PrioritySelect(discord.ui.Select):
    """Select menu for setting ticket priority."""
    
    def __init__(self, ticket_id: str, current_priority: str = 'normal'):
        self.ticket_id = ticket_id
        
        # Define priority options
        options = [
            discord.SelectOption(
                label="Urgent",
                description="Critical issue requiring immediate attention",
                emoji="🔴",
                value="urgent",
                default=(current_priority == 'urgent')
            ),
            discord.SelectOption(
                label="High",
                description="Important issue that should be addressed soon",
                emoji="🟠",
                value="high",
                default=(current_priority == 'high')
            ),
            discord.SelectOption(
                label="Normal",
                description="Standard priority issue",
                emoji="🟡",
                value="normal",
                default=(current_priority == 'normal')
            ),
            discord.SelectOption(
                label="Low",
                description="Minor issue that can wait",
                emoji="🔵",
                value="low",
                default=(current_priority == 'low')
            )
        ]
        
        super().__init__(
            placeholder=f"Set priority (Current: {current_priority.capitalize()})",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"ticket_priority_{ticket_id}",
            row=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle priority selection."""
        # Defer the interaction first
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # Get the selected priority
        priority = self.values[0].lower()
        
        # Get the parent view
        view = self.view
        if not hasattr(view, 'ticket_id'):
            await interaction.followup.send("❌ Could not process this action. Please try again.", ephemeral=True)
            return
        
        # Update the ticket metadata
        updates = {'priority': priority}
        success = await view.update_ticket_metadata(interaction, updates)
        
        if success:
            # Update the select menu to show the new priority
            self.placeholder = f"Set priority (Current: {priority.capitalize()})"
            for option in self.options:
                option.default = (option.value == priority)
            
            await interaction.message.edit(view=view)
            await interaction.followup.send(f"✅ Priority set to **{priority.capitalize()}**", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to update ticket priority.", ephemeral=True)


class AssignTicketButton(discord.ui.Button):
    def __init__(self, ticket_id: str, assigned: bool = False):
        self.ticket_id = ticket_id
        self.assigned = assigned
        super().__init__(
            style=discord.ButtonStyle.success if not assigned else discord.ButtonStyle.danger,
            label="Claim Ticket" if not assigned else "Unassign",
            emoji="👤" if not assigned else "❌",
            custom_id=f"ticket_assign_{ticket_id}",
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction):
        # Get the ticket metadata
        metadata = await self.view.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message("❌ Could not find ticket metadata.", ephemeral=True)
            return
        
        # If unassigning
        if self.assigned:
            metadata['assigned_to'] = None
            metadata['assigned_at'] = None
            metadata['assigned_by'] = None
            await interaction.response.send_message(embed=self.view.get_assignment_embed(None, interaction.user))
        else:
            # Assign to the user who clicked
            metadata['assigned_to'] = interaction.user.id
            metadata['assigned_at'] = datetime.now().isoformat()
            metadata['assigned_by'] = interaction.user.id
            await interaction.response.send_message(embed=self.view.get_assignment_embed(interaction.user, interaction.user))
        
        # Update the message with the new view
        await self.view.update_controls(interaction.message, metadata)
        await update_metadata_message(interaction.channel, metadata)

class PrioritySelect(discord.ui.Select):
    def __init__(self, ticket_id: str, current_priority: str = "normal"):
        self.ticket_id = ticket_id
        options = [
            discord.SelectOption(label="🔴 Urgent", value="urgent", description="Critical issue requiring immediate attention", emoji="🔴"),
            discord.SelectOption(label="🟠 High", value="high", description="Important issue that needs prompt attention", emoji="🟠"),
            discord.SelectOption(label="🟡 Normal", value="normal", description="Standard priority", emoji="🟡", default=True),
            discord.SelectOption(label="🔵 Low", value="low", description="Minor issue or question", emoji="🔵")
        ]
        
        # Set the default option
        for option in options:
            option.default = (option.value == current_priority)
        
        super().__init__(
            placeholder="Set priority...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"ticket_priority_{ticket_id}",
            row=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        priority = self.values[0]
        metadata = await self.view.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message("❌ Could not find ticket metadata.", ephemeral=True)
            return
        
        metadata['priority'] = priority
        await update_metadata_message(interaction.channel, metadata)
        
        # Get priority color
        priority_colors = {
            'urgent': 0xff0000,  # Red
            'high': 0xff6b00,    # Orange
            'normal': 0xffff00,  # Yellow
            'low': 0x00a2ff     # Blue
        }
        
        embed = discord.Embed(
            title=f"Priority Updated: {priority.title()}",
            description=f"Ticket priority has been updated by {interaction.user.mention}",
            color=priority_colors.get(priority, 0x00a2ff)
        )
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.config = load_config()
        
        # Add control buttons
        self.add_item(AssignTicketButton(ticket_id, is_assigned=False))
        self.add_item(PrioritySelect(ticket_id, 'normal'))
        
        # Add close and transcript buttons
        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="Close Ticket",
            emoji="🔒",
            custom_id=f"ticket_close_{ticket_id}",
            row=2
        ))
        
        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Transcript",
            emoji="📝",
            custom_id=f"ticket_transcript_{ticket_id}",
            row=2
        ))
    
    def load_config(self):
        """Load the bot configuration."""
        self.config = load_config()
        return self.config
    
    async def get_ticket_metadata(self, interaction: discord.Interaction) -> Optional[dict]:
        """Get the ticket metadata from the channel's metadata message."""
        try:
            # Try to find the metadata message in the channel
            async for message in interaction.channel.history(limit=50):
                if message.embeds and message.embeds[0].title == "📝 Ticket Metadata":
                    # Parse the metadata from the embed
                    embed = message.embeds[0]
                    metadata_str = embed.description.strip('```json\n').strip('\n```')
                    return json.loads(metadata_str)
            return None
        except Exception as e:
            logger.error(f"Error getting ticket metadata: {e}")
            await interaction.followup.send("❌ Failed to get ticket metadata.", ephemeral=True)
            return None
            
    async def update_control_message(self, interaction: discord.Interaction) -> None:
        """Update the control message with current ticket state."""
        metadata = await self.get_ticket_metadata(interaction)
        if not metadata:
            return
            
        # Get the control message
        control_message_id = metadata.get('control_message_id')
        if not control_message_id:
            return
            
        try:
            control_message = await interaction.channel.fetch_message(control_message_id)
            if not control_message:
                return
                
            # Get the current embed
            if not control_message.embeds:
                return
                
            embed = control_message.embeds[0]
            
            # Update status and priority in the embed
            status = metadata.get('status', 'open')
            priority = metadata.get('priority', 'normal')
            
            # Update the description
            description = embed.description
            description = re.sub(r'\*\*Status:\*\* .*\n', f'**Status:** 🟢 Open\n' if status == 'open' else '**Status:** 🔴 Closed\n', description)
            description = re.sub(r'\*\*Priority:\*\* .*\n', f'**Priority:** {self.get_priority_emoji(priority)} {priority.capitalize()}\n', description)
            
            # Update assigned user if available
            assigned_to = metadata.get('assigned_to')
            if assigned_to:
                member = interaction.guild.get_member(assigned_to)
                if member:
                    description = re.sub(r'\*\*Assigned to:\*\* .*\n', f'**Assigned to:** {member.mention}\n', description)
            
            # Update the embed
            embed.description = description
            await control_message.edit(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"Error updating control message: {e}")
            
    def get_priority_emoji(self, priority: str) -> str:
        """Get the emoji for a priority level."""
        emojis = {
            'urgent': '🔴',
            'high': '🟠',
            'normal': '🟡',
            'low': '🔵'
        }
        return emojis.get(priority.lower(), '⚪')
    
    async def update_ticket_metadata(self, interaction: discord.Interaction, updates: dict) -> bool:
        """Update the ticket metadata with the given updates."""
        try:
            # Find and update the metadata message
            async for message in interaction.channel.history(limit=50):
                if message.embeds and message.embeds[0].title == "📝 Ticket Metadata":
                    # Get current metadata
                    embed = message.embeds[0]
                    metadata_str = embed.description.strip('```json\n').strip('\n```')
                    metadata = json.loads(metadata_str)
                    
                    # Update with new values
                    metadata.update(updates)
                    metadata['last_activity'] = datetime.now().isoformat()
                    
                    # Update the embed
                    new_embed = discord.Embed(
                        title=embed.title,
                        description=f"```json\n{json.dumps(metadata, indent=2)}\n```",
                        color=embed.color
                    )
                    await message.edit(embed=new_embed)
                    
                    # Update the channel topic if ticket_id is in updates
                    if 'ticket_id' in updates:
                        await interaction.channel.edit(topic=f"ticket_{updates['ticket_id']}_{message.id}")
                    
                    # Update the control message
                    await self.update_control_message(interaction)
                    
                    # Log the update
                    if 'status' in updates:
                        status = updates['status']
                        log_msg = f"Ticket {self.ticket_id} marked as {status}"
                        if status == 'closed' and 'closed_by' in updates:
                            closer = interaction.guild.get_member(updates['closed_by'])
                            if closer:
                                log_msg += f" by {closer.mention}"
                        await interaction.channel.send(log_msg)
                    
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating ticket metadata: {e}")
            await interaction.followup.send("❌ Failed to update ticket metadata.", ephemeral=True)
            return False
        
    def get_assignment_embed(self, assigned_to: Optional[discord.Member] = None, assigned_by: Optional[discord.Member] = None) -> discord.Embed:
        """Create an embed for ticket assignment."""
        embed = discord.Embed(
            title="🎫 Ticket Assigned" if assigned_to else "🎫 Ticket Unassigned",
            color=discord.Color.blue() if assigned_to else discord.Color.orange()
        )
        if assigned_to:
            embed.description = f"This ticket has been assigned to {assigned_to.mention}"
            if assigned_by and assigned_by.id != assigned_to.id:
                embed.description += f" by {assigned_by.mention}"
            embed.set_footer(text=f"Assigned at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            embed.description = "This ticket is now unassigned"
            if assigned_by:
                embed.description += f" by {assigned_by.mention}"
        return embed
        
    async def update_controls(self, message: discord.Message, metadata: dict):
        """Update the control message with current ticket state."""
        # Clear existing items
        self.clear_items()
        
        # Get the guild and members
        guild = message.guild
        assigned_to = None
        if metadata.get('assigned_to'):
            assigned_to = guild.get_member(metadata['assigned_to'])
        
        # Add assign/unassign button
        is_assigned = bool(assigned_to)
        self.add_item(AssignTicketButton(self.ticket_id, is_assigned))
        
        # Add priority selector
        current_priority = metadata.get('priority', 'normal')
        self.add_item(PrioritySelect(self.ticket_id, current_priority))
        
        # Add close button
        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="Close Ticket",
            emoji="🔒",
            custom_id=f"ticket_close_{self.ticket_id}",
            row=2
        ))
        
        # Add transcript button
        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Generate Transcript",
            emoji="📋",
            custom_id=f"ticket_transcript_{self.ticket_id}",
            row=2
        ))
        
        # Update the message with the new view
        try:
            await message.edit(view=self)
        except discord.NotFound:
            logger.warning(f"Could not update ticket controls: message not found")
        except discord.HTTPException as e:
            logger.error(f"Failed to update ticket controls: {e}")
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[dict]:
        """Get ticket metadata from the metadata message in the channel."""
        metadata = await get_metadata_from_channel(channel)
        if not metadata or metadata.get('ticket_id') != self.ticket_id:
            return None
        return metadata
    
    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, custom_id="claim_ticket", emoji="🙋‍♂️")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Claim the ticket for handling."""
        if not await is_admin(interaction):
            await interaction.response.send_message("You don't have permission to claim tickets!", ephemeral=True)
            return

        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message("This ticket is invalid!", ephemeral=True)
            return

        if metadata.get('claimed_by'):
            claimer = interaction.guild.get_member(metadata['claimed_by'])
            await interaction.response.send_message(f"Ticket already claimed by {claimer.mention if claimer else 'a staff member'}!", ephemeral=True)
            return

        # Update metadata
        metadata['claimed_by'] = interaction.user.id
        metadata['status'] = 'claimed'
        await update_metadata_message(interaction.channel, metadata)

        # Update the main ticket message embed
        try:
            ticket_message = await interaction.channel.fetch_message(metadata['main_ticket_message_id'])
            embed = ticket_message.embeds[0]
            embed.color = discord.Color.orange()
            # Find and update status field or add it
            status_updated = False
            for i, field in enumerate(embed.fields):
                if field.name.lower() in ["status", "👤 user"]:
                    embed.set_field_at(i, name="🔒 Claimed by", value=interaction.user.mention, inline=True)
                    status_updated = True
                    break
            if not status_updated: # Fallback
                 embed.add_field(name="🔒 Claimed by", value=interaction.user.mention, inline=True)

            button.disabled = True
            await ticket_message.edit(embed=embed, view=self)
            await interaction.response.send_message(f"You have claimed this ticket!", ephemeral=True)
            logger.info(f"Ticket #{self.ticket_id} claimed by {interaction.user.name}")
        except (discord.NotFound, IndexError):
            await interaction.response.send_message("Claimed, but failed to update the main ticket message.", ephemeral=True)
    
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Initiate ticket closure."""
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message("This ticket is invalid!", ephemeral=True)
            return

        # Check permissions
        is_creator = interaction.user.id == metadata.get('user_id')
        if not (is_creator or await is_admin(interaction)):
            await interaction.response.send_message("Only the ticket creator or an admin can close this ticket!", ephemeral=True)
            return

        await interaction.response.send_modal(CloseTicketModal(self.ticket_id))
    
    @discord.ui.button(label="Set Priority", style=discord.ButtonStyle.secondary, custom_id="set_priority", emoji="🔖")
    async def set_priority(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set ticket priority."""
        if not await is_admin(interaction):
            await interaction.response.send_message("You don't have permission to set ticket priority!", ephemeral=True)
            return

        await interaction.response.send_message(
            "Please select a new priority for this ticket:",
            view=TicketPriorityView(self.ticket_id),
            ephemeral=True
        )

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, custom_id="transcript", emoji="📝")
    async def create_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Generate a transcript of the ticket."""
        # Check admin permissions
        if not await is_admin(interaction):
            await interaction.response.send_message(
                "You don't have permission to create transcripts!",
                ephemeral=True
            )
            return
            
        await interaction.response.defer(ephemeral=True)
        
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.followup.send(
                "This ticket no longer exists or is invalid!",
                ephemeral=True
            )
            return
            
        # Generate transcript
        try:
            transcript = await self.generate_transcript(interaction.channel, metadata)
            
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
            
        except Exception as e:
            logger.error(f"Failed to generate transcript: {e}")
            await interaction.followup.send(
                "Failed to generate transcript. Please try again later.",
                ephemeral=True
            )
    
    async def generate_transcript(self, channel: discord.TextChannel, metadata: dict) -> str:
        """Generate a text transcript of the ticket."""
        # Format transcript header with metadata
        transcript = f"""
        {'='*60}
        TICKET TRANSCRIPT - {metadata.get('ticket_id', 'UNKNOWN')}
        {'='*60}
        
        TICKET INFORMATION:
        {'-'*60}
        Ticket ID:    {metadata.get('ticket_id', 'N/A')}
        Category:     {metadata.get('category', 'N/A')}
        Status:       {metadata.get('status', 'N/A').upper()}
        Created:      {metadata.get('created_at', 'N/A')}
        Created By:   {metadata.get('user_id', 'N/A')}
        Assigned To:  {metadata.get('assigned_to', 'Unassigned')}
        Priority:     {metadata.get('priority', 'Normal').capitalize()}
        
        CLOSURE INFORMATION:
        {'-'*60}
        Closed:       {metadata.get('closed_at', 'N/A')}
        Closed By:    {metadata.get('closed_by', 'N/A')}
        Close Type:   {metadata.get('close_type', 'N/A').capitalize() if metadata.get('close_type') else 'N/A'}
        Close Reason: {metadata.get('close_reason', 'No reason provided')}
        
        MESSAGES:
        {'-'*60}
        """
        
        # Fetch and format messages
        messages = []
        try:
            async for message in channel.history(limit=1000, oldest_first=True):
                # Skip system messages and empty messages
                if message.type != discord.MessageType.default or not message.content and not message.attachments and not message.embeds:
                    continue
                    
                # Format message timestamp
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
                author = f"{message.author.name}#{message.author.discriminator}"
                
                # Format message content
                content = message.clean_content.replace('\n', '\n                    ')
                
                # Add attachment info if present
                if message.attachments:
                    attachments = ' '.join(f'[Attachment: {a.filename}]' for a in message.attachments)
                    content = f"{content} {attachments}".strip()
                
                # Add embed info if present
                if message.embeds:
                    embed_count = len(message.embeds)
                    content = f"{content} [Embed: {embed_count} embed{'s' if embed_count > 1 else ''}]".strip()
                
                # Format the message line
                msg_line = f"[{timestamp}] {author}: {content}"
                messages.append(msg_line)
                
        except Exception as e:
            logger.error(f"Error fetching messages for transcript: {e}")
            transcript += "\n[Error: Could not fetch all messages for transcript]\n"
        
        # Add messages to transcript
        transcript += '\n'.join(messages)
        transcript += f"\n\n{'='*60}\nEND OF TRANSCRIPT\n{'='*60}"
        
        # Clean up any excessive whitespace
        transcript = '\n'.join(line.strip() for line in transcript.split('\n') if line.strip())
        
        return transcript
        creator = channel.guild.get_member(metadata['user_id'])
        transcript += f"Creator: {creator} (ID: {metadata['user_id']}) \n"
        
        if metadata.get('claimed_by'):
            claimer = channel.guild.get_member(metadata['claimed_by'])
            claimer_info = f"{claimer} (ID: {metadata['claimed_by']})" if claimer else f"User ID: {metadata['claimed_by']}"
            transcript += f"Claimed by: {claimer_info}\n"
        
        transcript += f"Status: {metadata['status'].capitalize()}\n"
        transcript += f"Priority: {metadata['priority'].capitalize()}\n"
        created_dt = datetime.fromisoformat(metadata['created_at'])
        transcript += f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if metadata.get('closed_at') and metadata.get('closed_by'):
            closed_dt = datetime.fromisoformat(metadata['closed_at'])
            closer = channel.guild.get_member(metadata['closed_by'])
            closer_info = f"{closer} (ID: {metadata['closed_by']})" if closer else f"User ID: {metadata['closed_by']}"
            transcript += f"Closed: {closed_dt.strftime('%Y-%m-%d %H:%M:%S')} by {closer_info}\n"
            if metadata.get('close_reason'):
                transcript += f"Close Reason: {metadata['close_reason']}\n"
        transcript += "\n" + "=" * 50 + "\n\n"
        
        # Add messages
        for message in messages:
            # Skip system messages
            if message.is_system():
                continue
                
            # Format timestamp
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            
            # Format author
            if message.author.bot:
                author = f"[BOT] {message.author.display_name}"
            else:
                author = f"{message.author.display_name} ({message.author.id})"
            
            # Add message header
            transcript += f"[{timestamp}] {author}\n"
            
            # Add message content
            if message.content:
                transcript += f"{message.content}\n"
            
            # Add attachments
            if message.attachments:
                transcript += "Attachments:\n"
                for attachment in message.attachments:
                    transcript += f"- {attachment.filename} ({attachment.size} bytes)\n"
            # Add embeds
            if message.embeds:
                transcript += "Embeds:\n"
                for embed in message.embeds:
                    if embed.title:
                        transcript += f"Title: {embed.title}\n"
                    if embed.description:
                        transcript += f"Description: {embed.description}\n"
                    for field in embed.fields:
                        transcript += f"{field.name}: {field.value}\n"
                    if embed.footer:
                        transcript += f"Footer: {embed.footer.text}\n"
            transcript += "\n" + ("-" * 50) + "\n\n"
        
        return transcript


class TicketPriorityView(discord.ui.View):
    """View for setting ticket priority."""
    
    def __init__(self, ticket_id: str):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id

    async def update_priority_and_respond(self, interaction: discord.Interaction, priority: str):
        """Helper to update priority and edit messages."""
        metadata = await get_metadata_from_channel(interaction.channel)
        if not metadata or metadata.get('ticket_id') != self.ticket_id:
            await interaction.response.edit_message(content="This ticket is invalid!", view=None)
            return

        old_priority = metadata.get('priority', 'normal')
        if old_priority.lower() == priority.lower():
            await interaction.response.edit_message(content=f"Priority is already **{priority}**.", view=None)
            return

        # Update metadata
        metadata['priority'] = priority.lower()
        await update_metadata_message(interaction.channel, metadata)

        # Update the main ticket embed
        try:
            ticket_message = await interaction.channel.fetch_message(metadata['main_ticket_message_id'])
            embed = ticket_message.embeds[0]
            embed.color = self.get_priority_color(priority)

            # Find and update priority field
            priority_updated = False
            for i, field in enumerate(embed.fields):
                if field.name.lower() == 'priority':
                    embed.set_field_at(i, name="Priority", value=priority.capitalize(), inline=True)
                    priority_updated = True
                    break
            if not priority_updated:
                embed.add_field(name="Priority", value=priority.capitalize(), inline=True)

            await ticket_message.edit(embed=embed)
            await interaction.response.edit_message(content=f"Priority set to **{priority}**.", view=None)
            logger.info(f"Ticket #{self.ticket_id} priority set to {priority} by {interaction.user.name}")
        except (discord.NotFound, IndexError):
            await interaction.response.edit_message(content="Priority updated, but failed to edit the main ticket message.", view=None)

    def get_priority_color(self, priority: str) -> discord.Color:
        return {
            "low": discord.Color.blue(),
            "normal": discord.Color.green(),
            "high": discord.Color.orange(),
            "urgent": discord.Color.red()
        }.get(priority.lower(), discord.Color.default())

    @discord.ui.button(label="Low", style=discord.ButtonStyle.primary, custom_id="priority_low")
    async def low(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_priority_and_respond(interaction, "Low")

    @discord.ui.button(label="Normal", style=discord.ButtonStyle.success, custom_id="priority_normal")
    async def normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_priority_and_respond(interaction, "Normal")

    @discord.ui.button(label="High", style=discord.ButtonStyle.secondary, custom_id="priority_high")
    async def high(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_priority_and_respond(interaction, "High")

    @discord.ui.button(label="Urgent", style=discord.ButtonStyle.danger, custom_id="priority_urgent")
    async def urgent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_priority_and_respond(interaction, "Urgent")
            
        # Get the ticket channel
        ticket_channel = interaction.channel
        if not isinstance(ticket_channel, discord.TextChannel):
            await interaction.response.send_message(
                "This command can only be used in a ticket channel.",
                ephemeral=True
            )
            return
        
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(ticket_channel)
        if not metadata:
            await interaction.response.send_message(
                "This ticket no longer exists or is invalid!",
                ephemeral=True
            )
            return
        
        # Update priority in metadata
        old_priority = metadata.priority
        metadata.priority = priority
        metadata.update_activity()
        
        # Save changes
        await self.update_ticket_metadata(ticket_channel, metadata)
        
        # Find and update the main ticket message
        ticket_message = None
        try:
            async for message in ticket_channel.history(limit=50):
                if message.embeds and f"Ticket #{self.ticket_id}" in message.embeds[0].title:
                    ticket_message = message
                    break
        except Exception as e:
            logger.error(f"Error finding ticket message: {e}")
        
        if ticket_message and ticket_message.embeds:
            try:
                # Update the embed with new priority
                embed = ticket_message.embeds[0]
                
                # Update priority field
                for i, field in enumerate(embed.fields):
                    if field.name.lower() == "priority":
                        embed.set_field_at(i, name="Priority", value=priority.capitalize(), inline=True)
                        break
                
                # Update color based on priority
                embed.color = color
                
                # Update the message
                view = TicketControlsView(self.ticket_id)
                await ticket_message.edit(embed=embed, view=view)
                
                # Send confirmation
                await interaction.response.edit_message(
                    content=f"✅ Ticket priority changed from **{old_priority.capitalize()}** to **{priority.capitalize()}**",
                    embed=None,
                    view=None
                )
                
                # Notify in the ticket channel
                priority_colors = {
                    "low": "🟢 Low",
                    "normal": "🔵 Normal",
                    "high": "🟠 High",
                    "urgent": "🔴 Urgent"
                }
                
                priority_emoji = priority_colors.get(priority, "")
                await ticket_channel.send(
                    f"{interaction.user.mention} set the ticket priority to {priority_emoji}"
                )
                
            except Exception as e:
                logger.error(f"Error updating ticket message: {e}")
                await interaction.response.send_message(
                    "✅ Priority updated, but there was an error updating the ticket message.",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                f"✅ Priority set to **{priority.capitalize()}** (could not update ticket message)",
                ephemeral=True
            )


class CloseTicketModal(discord.ui.Modal):
    """Modal for entering a reason to close a ticket."""
    
    def __init__(self, ticket_id: str):
        super().__init__(title="Close Ticket")
        self.ticket_id = ticket_id

        # Reason text input
        self.reason = discord.ui.TextInput(
            label="Reason for closing",
            placeholder="Please provide a reason for closing this ticket...",
            min_length=2,
            max_length=1000,
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.reason)
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[dict]:
        """Get ticket metadata from the metadata message in the channel."""
        metadata = await get_metadata_from_channel(channel)
        if not metadata or metadata.get('ticket_id') != self.ticket_id:
            return None
        return metadata
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle form submission."""
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a ticket channel.", ephemeral=True)
            return

        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message("This ticket is invalid!", ephemeral=True)
            return

        # Check permissions
        is_creator = interaction.user.id == metadata.get('user_id')
        if not (is_creator or await is_admin(interaction)):
            await interaction.response.send_message("Only the ticket creator or an admin can close this ticket!", ephemeral=True)
            return

        # Build confirmation embed
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Close Request",
            description=f"Requested by {interaction.user.mention}\n\n**Reason:** {self.reason.value}",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )

        creator = interaction.guild.get_member(metadata.get('user_id'))
        embed.add_field(name="Creator", value=creator.mention if creator else "N/A", inline=True)
        embed.add_field(name="Category", value=metadata.get('category', 'N/A'), inline=True)

        if metadata.get('claimed_by'):
            claimer = interaction.guild.get_member(metadata['claimed_by'])
            embed.add_field(name="Claimed By", value=claimer.mention if claimer else "N/A", inline=True)

        created_dt = datetime.fromisoformat(metadata['created_at'])
        embed.add_field(name="Created", value=f"<t:{int(created_dt.timestamp())}:R>", inline=True)
        embed.set_footer(text=f"Ticket ID: {self.ticket_id}")

        # Create confirmation view
        view = TicketCloseConfirmView(self.ticket_id, self.reason.value, interaction.user.id)

        # Send the message and ping the creator
        creator_mention = f"{creator.mention} " if creator else ""
        await interaction.response.send_message(
            content=f"{creator_mention}Please confirm closing this ticket:",
            embed=embed, 
            view=view,
            allowed_mentions=discord.AllowedMentions(users=[creator] if creator else [])
        )

        # Log the close request
        logger.info(
            f"Ticket #{self.ticket_id} close requested by {interaction.user} "
            f"(ID: {interaction.user.id}) with reason: {self.reason.value}"
        )

    async def generate_transcript(self, channel: discord.TextChannel, metadata: dict) -> str:
        """Generate a text transcript of the ticket."""
        # Fetch messages (newest first, then we'll reverse)
        messages = []
        async for message in channel.history(limit=1000, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)

        # Format transcript header
        transcript = f"Ticket Transcript - #{metadata['ticket_id']}\n"
        transcript += "=" * 50 + "\n\n"

        # Add ticket metadata
        transcript += f"Ticket ID: {metadata['ticket_id']}\n"
        transcript += f"Category: {metadata['category']}\n"
        creator = channel.guild.get_member(metadata['user_id'])
        transcript += f"Creator: {creator} (ID: {metadata['user_id']}) \n"

        if metadata.get('claimed_by'):
            claimer = channel.guild.get_member(metadata['claimed_by'])
            claimer_info = f"{claimer} (ID: {metadata['claimed_by']})" if claimer else f"User ID: {metadata['claimed_by']}"
            transcript += f"Claimed by: {claimer_info}\n"

        transcript += f"Status: {metadata['status'].capitalize()}\n"
        transcript += f"Priority: {metadata['priority'].capitalize()}\n"
        created_dt = datetime.fromisoformat(metadata['created_at'])
        transcript += f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"

        if metadata.get('closed_at') and metadata.get('closed_by'):
            closed_dt = datetime.fromisoformat(metadata['closed_at'])
            closer = channel.guild.get_member(metadata['closed_by'])
            closer_info = f"{closer} (ID: {metadata['closed_by']})" if closer else f"User ID: {metadata['closed_by']}"
            transcript += f"Closed: {closed_dt.strftime('%Y-%m-%d %H:%M:%S')} by {closer_info}\n"
            if metadata.get('close_reason'):
                transcript += f"Close Reason: {metadata['close_reason']}\n"

        transcript += "\n" + "=" * 50 + "\n\n"

        # Add messages
        for message in messages:
            # Skip system messages
            if message.is_system():
                continue
                
            # Format timestamp
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            
            # Format author
            if message.author.bot:
                author = f"[BOT] {message.author.display_name}"
            else:
                author = f"{message.author.display_name} ({message.author.id})"
            
            # Add message header
            transcript += f"[{timestamp}] {author}\n"
            
            # Add message content
            if message.content:
                transcript += f"{message.content}\n"
            
            # Add attachments
            if message.attachments:
                transcript += "Attachments:\n"
                for attachment in message.attachments:
                    transcript += f"- {attachment.filename} ({attachment.size} bytes)\n"
            # Add embeds
            if message.embeds:
                transcript += "Embeds:\n"
                for embed in message.embeds:
                    if embed.title:
                        transcript += f"Title: {embed.title}\n"
                    if embed.description:
                        transcript += f"Description: {embed.description}\n"
                    for field in embed.fields:
                        transcript += f"{field.name}: {field.value}\n"
                    if embed.footer:
                        transcript += f"Footer: {embed.footer.text}\n"
            transcript += "\n" + ("-" * 50) + "\n\n"
        
        return transcript


class Tickets(commands.Cog):
    """Ticket system for handling user support tickets."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.active_tickets = {}
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup event handlers for ticket interactions."""
        self.bot.add_listener(self.on_message, 'on_message')
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is loaded and ready."""
        logger.info("Ticket system is ready!")
    
    @app_commands.command(name="ticketsetup", description="Set up the ticket system")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_setup(self, interaction: discord.Interaction):
        """Set up the ticket system in the current channel."""
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description="Click the button below to create a new support ticket.",
            color=discord.Color.blue()
        )
        
        view = TicketView()
        await interaction.response.send_message(embed=embed, view=view)
    
    @app_commands.command(name="ticket", description="Create a new support ticket")
    async def create_ticket(self, interaction: discord.Interaction, category: str, description: str):
        """Create a new support ticket."""
        await interaction.response.defer(ephemeral=True)
        
        # Create ticket channel
        guild = interaction.guild
        ticket_id = str(uuid.uuid4())[:8].upper()
        
        # Get or create ticket category
        category_id = self.config.get("ticket_category")
        if category_id:
            category = guild.get_channel(int(category_id))
        else:
            # Create a new category if not set
            category = await guild.create_category("Tickets")
            self.config["ticket_category"] = str(category.id)
            save_config(self.config)
        
        # Create ticket channel
        channel = await guild.create_text_channel(
            f"ticket-{ticket_id}",
            category=category,
            topic=f"ticket_{ticket_id}",
            reason=f"Ticket created by {interaction.user}"
        )
        
        # Set permissions
        await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
        
        # Create ticket metadata
        metadata = {
            'ticket_id': ticket_id,
            'status': 'open',
            'priority': 'normal',
            'category': category,
            'created_by': interaction.user.id,
            'created_at': datetime.now().isoformat(),
            'last_activity': datetime.now().isoformat(),
            'assigned_to': None,
            'assigned_at': None,
            'assigned_by': None
        }
        
        # Create metadata message
        metadata_embed = discord.Embed(
            title="📝 Ticket Metadata",
            description=f"```json\n{json.dumps(metadata, indent=2)}\n```",
            color=discord.Color.blue()
        )
        metadata_msg = await channel.send(embed=metadata_embed)
        
        # Update channel topic with metadata message ID
        await channel.edit(topic=f"ticket_{ticket_id}_{metadata_msg.id}")
        
        # Create main ticket message
        embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_id} - {category}",
            description=(
                f"**Status:** 🟢 Open\n"
                f"**Priority:** 🟡 Normal\n"
                f"**Created by:** {interaction.user.mention}\n"
                f"**Category:** {category}\n\n"
                f"**Description:**\n{description}"
            ),
            color=discord.Color.green()
        )
        
        # Add control buttons
        view = TicketControlsView(ticket_id)
        control_msg = await channel.send(embed=embed, view=view)
        
        # Update metadata with control message ID
        metadata['control_message_id'] = control_msg.id
        metadata_embed.description = f"```json\n{json.dumps(metadata, indent=2)}\n```"
        await metadata_msg.edit(embed=metadata_embed)
        
        # Send welcome message
        welcome_embed = discord.Embed(
            title="🎫 Ticket Created",
            description=(
                f"Thank you for creating a ticket, {interaction.user.mention}!\n"
                "A staff member will assist you shortly.\n\n"
                "**Quick Actions:**\n"
                "• Use the buttons above to manage this ticket\n"
                "• Add more details by replying in this channel\n"
                "• Close this ticket when your issue is resolved"
            ),
            color=discord.Color.green()
        )
        
        # Get support role mention if configured
        support_mention = ""
        support_role_id = self.config.get("support_role_id")
        if support_role_id:
            support_role = interaction.guild.get_role(int(support_role_id))
            if support_role:
                support_mention = f"{support_role.mention} "
        
        # Send mention and welcome message
        await channel.send(f"{support_mention}• {interaction.user.mention} has created a new ticket!")
        await channel.send(embed=welcome_embed)
        
        # Send confirmation to user
        await interaction.followup.send(
            f"✅ Ticket created: {channel.mention}",
            ephemeral=True
        )
    
    @app_commands.command(name="closeticket", description="Close the current ticket")
    async def close_ticket(self, interaction: discord.Interaction, reason: str):
        """Close the current ticket."""
        # Check if this is a ticket channel
        if not interaction.channel.topic or not interaction.channel.topic.startswith("ticket_"):
            await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
            return
        
        # Get ticket ID from channel topic
        ticket_id = interaction.channel.topic.split('_')[1]
        
        # Create close confirmation view
        view = TicketCloseConfirmView(ticket_id, reason, interaction.user.id)
        
        # Send confirmation message
        embed = discord.Embed(
            title="🔒 Close Ticket",
            description=(
                f"You are about to close this ticket.\n"
                f"**Reason:** {reason}\n\n"
                f"Please confirm this action."
            ),
            color=discord.Color.orange()
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="adduser", description="Add a user to the ticket")
    async def add_user(self, interaction: discord.Interaction, user: discord.Member):
        """Add a user to the current ticket."""
        # Check if this is a ticket channel
        if not interaction.channel.topic or not interaction.channel.topic.startswith("ticket_"):
            await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
            return
        
        # Add user to the channel
        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
        await interaction.response.send_message(f"✅ Added {user.mention} to the ticket.")
    
    @app_commands.command(name="removeuser", description="Remove a user from the ticket")
    async def remove_user(self, interaction: discord.Interaction, user: discord.Member):
        """Remove a user from the current ticket."""
        # Check if this is a ticket channel
        if not interaction.channel.topic or not interaction.channel.topic.startswith("ticket_"):
            await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
            return
        
        # Remove user from the channel
        await interaction.channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(f"✅ Removed {user.mention} from the ticket.")
    
    @app_commands.command(name="rename", description="Rename the current ticket")
    async def rename_ticket(self, interaction: discord.Interaction, name: str):
        """Rename the current ticket channel."""
        # Check if this is a ticket channel
        if not interaction.channel.topic or not interaction.channel.topic.startswith("ticket_"):
            await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
            return
        
        # Rename the channel
        await interaction.channel.edit(name=name)
        await interaction.response.send_message(f"✅ Ticket renamed to `{name}`.")
    
    @app_commands.command(name="transcript", description="Generate a transcript of the ticket")
    async def generate_transcript(self, interaction: discord.Interaction):
        """Generate a transcript of the current ticket."""
        # Check if this is a ticket channel
        if not interaction.channel.topic or not interaction.channel.topic.startswith("ticket_"):
            await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
            return
        
        # Defer the response as this might take a while
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Generate the transcript
            transcript = await self.generate_transcript(interaction.channel)
            
            # Send the transcript as a file
            file = discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"transcript-{interaction.channel.name}.txt")
            await interaction.followup.send("Here's the transcript:", file=file, ephemeral=True)
        except Exception as e:
            logger.error(f"Error generating transcript: {e}")
            await interaction.followup.send("❌ Failed to generate transcript.", ephemeral=True)
    
    async def generate_transcript(self, channel: discord.TextChannel) -> str:
        """Generate a text transcript of the channel messages."""
        transcript = []
        
        # Add channel info
        transcript.append(f"Transcript of #{channel.name}")
        transcript.append(f"Created: {channel.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Fetch all messages
        async for message in channel.history(limit=None, oldest_first=True):
            # Skip system messages
            if message.is_system():
                continue
                
            # Format message
            timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
            author = f"{message.author.name}#{message.author.discriminator}"
            content = message.clean_content
            
            # Handle attachments
            if message.attachments:
                attachments = ' '.join([f'[Attachment: {a.filename}]' for a in message.attachments])
                content = f"{content} {attachments}".strip()
            
            # Add to transcript
            transcript.append(f"[{timestamp}] {author}: {content}")
        
        return '\n'.join(transcript)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle messages in ticket channels."""
        # Ignore messages from bots
        if message.author.bot:
            return
        
        # Check if this is a ticket channel
        if not message.channel.topic or not message.channel.topic.startswith("ticket_"):
            return
        
        try:
            # Get ticket metadata
            metadata = await self.get_ticket_metadata(message.channel)
            if not metadata:
                return
            
            # Update last activity
            metadata['last_activity'] = datetime.now().isoformat()
            await self.update_ticket_metadata(message.channel, metadata)
            
        except Exception as e:
            logger.error(f"Error processing message in ticket channel: {e}")


class TicketCloseConfirmView(discord.ui.View):
    """View for confirming or denying ticket closure with user confirmation."""
    
    def __init__(self, ticket_id: str, reason: str, closer_id: int):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.ticket_id = ticket_id
        self.reason = reason
        self.closer_id = closer_id
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[dict]:
        """Get ticket metadata from the metadata message in the channel."""
        metadata = await get_metadata_from_channel(channel)
        if not metadata or metadata.get('ticket_id') != self.ticket_id:
            return None
        return metadata

    async def has_permission(self, interaction: discord.Interaction, metadata: dict) -> bool:
        """Check if the user has permission to close the ticket."""
        if await is_admin(interaction):
            return True
        if interaction.user.id == metadata.get('user_id'):
            return True
        if interaction.user.id == self.closer_id:
            return True
        return False

    @discord.ui.button(label="✅ Yes, Close Ticket", style=discord.ButtonStyle.green, custom_id="confirm_close", emoji="✅")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle confirm close button click."""
        await interaction.response.defer(ephemeral=True)
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.followup.send("❌ This ticket is invalid or has already been closed.", ephemeral=True)
            return

        if not await self.has_permission(interaction, metadata):
            await interaction.followup.send("❌ You don't have permission to close this ticket!", ephemeral=True)
            return

        # Update the confirmation message
        embed = interaction.message.embeds[0]
        embed.title = f"🔒 Closing Ticket #{self.ticket_id}"
        embed.description = "Closing ticket and generating transcript..."
        embed.color = discord.Color.green()
        for child in self.children:
            child.disabled = True
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

        await self.close_ticket(interaction, metadata, "confirmed by user")

    @discord.ui.button(label="❌ No, Keep Open", style=discord.ButtonStyle.red, custom_id="deny_close", emoji="❌")
    async def deny_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle deny close button click."""
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message("❌ This ticket is invalid or has already been closed.", ephemeral=True)
            return

        if not await self.has_permission(interaction, metadata):
            await interaction.response.send_message("❌ You don't have permission to manage this ticket!", ephemeral=True)
            return

        # Disable buttons and update embed to show denial
        embed = interaction.message.embeds[0]
        embed.title = f"✅ Ticket #{self.ticket_id} - Close Cancelled"
        embed.description = f"{interaction.user.mention} chose to keep this ticket open."
        embed.color = discord.Color.blue()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        logger.info(f"Ticket #{self.ticket_id} close cancelled by {interaction.user.name}")

    @discord.ui.button(label="⚠️ Force Close (Staff Only)", style=discord.ButtonStyle.danger, custom_id="force_close", emoji="⚠️")
    async def force_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle force close button click (admin only)."""
        await interaction.response.defer(ephemeral=True)
        
        if not await is_admin(interaction):
            await interaction.followup.send("❌ Only staff members can force-close tickets.", ephemeral=True)
            return

        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.followup.send("❌ This ticket is invalid or has already been closed.", ephemeral=True)
            return

        # Update the confirmation message
        embed = interaction.message.embeds[0]
        embed.title = f"🔒 Force-Closing Ticket #{self.ticket_id}"
        embed.description = "Force-closing ticket and generating transcript..."
        embed.color = discord.Color.red()
        for child in self.children:
            child.disabled = True
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

        await self.close_ticket(interaction, metadata, "force-closed by staff")

    async def close_ticket(self, interaction: discord.Interaction, metadata: dict, close_type: str):
        """Close the ticket and perform cleanup."""
        # Update metadata
        metadata['status'] = 'closed'
        metadata['closed_at'] = datetime.now().isoformat()
        metadata['closed_by'] = interaction.user.id
        metadata['close_reason'] = self.reason

        await update_metadata_message(interaction.channel, metadata)

        # Generate transcript
        transcript = await self.generate_transcript(interaction.channel, metadata)

        # Send transcript to log channel
        log_channel_id = config.get("ticket_log_channel")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if log_channel:
                try:
                    await log_channel.send(
                        f"Transcript for closed ticket #{self.ticket_id} (Channel: {interaction.channel.name})",
                        file=discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{self.ticket_id}-transcript.txt")
                    )
                except Exception as e:
                    logger.error(f"Failed to send transcript to log channel: {e}")

        # Send transcript to closer and creator
        try:
            await interaction.user.send("Here is the transcript for the ticket you closed:", file=discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{self.ticket_id}-transcript.txt"))
        except discord.Forbidden:
            pass

        if interaction.user.id != metadata.get('user_id'):
            try:
                creator = await interaction.client.fetch_user(metadata['user_id'])
                await creator.send("Your ticket has been closed. Here is the transcript:", file=discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{self.ticket_id}-transcript.txt"))
            except (discord.NotFound, discord.Forbidden):
                pass

        # Delete the channel
        await interaction.followup.send("Ticket closed. This channel will be deleted in 10 seconds.", ephemeral=True)
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.name}")
        except discord.HTTPException as e:
            logger.error(f"Failed to delete ticket channel {interaction.channel.id}: {e}")

        logger.info(f"Ticket #{self.ticket_id} closed by {interaction.user.name} ({close_type})")

    async def generate_transcript(self, channel: discord.TextChannel, metadata: dict) -> str:
        """Generate a text transcript of the ticket."""
        # Fetch messages (newest first, then we'll reverse)
        messages = []
        async for message in channel.history(limit=1000, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)

        # Build transcript header
        creator = channel.guild.get_member(metadata.get('user_id'))
        transcript_header = (
            f"""Ticket Transcript
            -------------------
            Ticket ID: {metadata.get('ticket_id')}
            Category: {metadata.get('category')}
            Creator: {creator.name if creator else 'N/A'} (ID: {metadata.get('user_id')})
            Created: {datetime.fromisoformat(metadata.get('created_at')).strftime('%Y-%m-%d %H:%M:%S UTC')}
            """
        )

        if metadata.get('status') == 'closed':
            closer = channel.guild.get_member(metadata.get('closed_by'))
            transcript_header += (
                f"""\n            Closed By: {closer.name if closer else 'N/A'} (ID: {metadata.get('closed_by')})
            Close Reason: {metadata.get('close_reason')}
            Closed: {datetime.fromisoformat(metadata.get('closed_at')).strftime('%Y-%m-%d %H:%M:%S UTC')}
            """
            )

        transcript_header += "\n-------------------\n\n"

        # Build transcript body
        transcript_body = []
        for msg in messages:
            timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
            author_info = f"{msg.author.name}#{msg.author.discriminator} ({timestamp})"
            
            content = msg.content
            if msg.embeds:
                embed = msg.embeds[0]
                content += f"\n--- Embed: {embed.title or ''} ---\n{embed.description or ''}"
                for field in embed.fields:
                    content += f"\n{field.name}: {field.value}"
            
            transcript_body.append(f"{author_info}: {content}")

        return transcript_header + "\n".join(transcript_body)


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Start auto-close task
        self.auto_close_task = self.bot.loop.create_task(self.check_inactive_tickets())

    def cog_unload(self):
        # Cancel the task when the cog is unloaded
        self.auto_close_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Update last_activity timestamp on new messages in ticket channels."""
        # Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        # Load config and check if the message is in a ticket channel
        config = load_config()
        ticket_category_id = config.get("ticket_category")
        if not (isinstance(message.channel, discord.TextChannel) and 
                ticket_category_id and 
                message.channel.category_id == int(ticket_category_id)):
            return

        # Fetch metadata and update if the ticket is open
        try:
            metadata = await get_metadata_from_channel(message.channel)
            if metadata and metadata.get('status') == 'open':
                metadata['last_activity'] = datetime.now().isoformat()
                await update_metadata_message(message.channel, metadata)
        except Exception as e:
            # This might get noisy if it fails often, but it's good for debugging
            logger.debug(f"Could not update last_activity for channel {message.channel.id}: {e}")

    async def check_inactive_tickets(self):
        """Periodically checks for inactive tickets and closes them."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(3600)  # Check every hour
            try:
                auto_close_hours = config.get("ticket_auto_close_hours", 0)
                if auto_close_hours <= 0:
                    continue

                ticket_category_id = config.get("ticket_category")
                if not ticket_category_id:
                    continue

                # We assume the bot is in one guild for simplicity
                guild = self.bot.guilds[0]
                category = guild.get_channel(int(ticket_category_id))
                if not category:
                    continue

                now = datetime.now()
                for channel in category.channels:
                    if isinstance(channel, discord.TextChannel):
                        metadata = await get_metadata_from_channel(channel)
                        if metadata and metadata.get('status') == 'open':
                            last_activity_str = metadata.get('last_activity')
                            if not last_activity_str:
                                continue

                            last_activity = datetime.fromisoformat(last_activity_str)
                            if (now - last_activity).total_seconds() > auto_close_hours * 3600:
                                logger.info(f"Auto-closing ticket in channel {channel.id} due to inactivity.")
                                await self.auto_close_ticket(channel, metadata)

            except Exception as e:
                logger.error(f"Error in check_inactive_tickets loop: {e}")

    async def auto_close_ticket(self, channel: discord.TextChannel, metadata: dict):
        """Handles the logic for automatically closing a single ticket."""
        # Update metadata for closure
        metadata['status'] = 'closed'
        metadata['closed_at'] = datetime.now().isoformat()
        metadata['closed_by'] = self.bot.user.id
        metadata['close_reason'] = "Automatically closed due to inactivity."
        await update_metadata_message(channel, metadata)

        # Generate transcript
        view = TicketCloseConfirmView(metadata['ticket_id'], metadata['close_reason'], self.bot.user.id)
        transcript = await view.generate_transcript(channel, metadata)
        transcript_file = discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"ticket-{metadata['ticket_id']}-transcript.txt")

        # Notify in the channel
        try:
            await channel.send(
                "This ticket has been automatically closed due to inactivity. This channel will be deleted in 10 seconds.",
                file=transcript_file
            )
        except discord.HTTPException as e:
            logger.error(f"Failed to send auto-close message in {channel.id}: {e}")

        # Log to log channel
        config = load_config()
        log_channel_id = config.get("ticket_log_channel")
        if log_channel_id:
            log_channel = channel.guild.get_channel(int(log_channel_id))
            if log_channel:
                try:
                    log_embed = discord.Embed(
                        title=f"Ticket #{metadata['ticket_id']} Auto-Closed",
                        description=f"Ticket from <@{metadata['user_id']}> was auto-closed.",
                        color=discord.Color.red()
                    )
                    transcript_file.fp.seek(0) # Reset file pointer
                    await log_channel.send(embed=log_embed, file=transcript_file)
                except Exception as e:
                    logger.error(f"Failed to send auto-close log for ticket {metadata['ticket_id']}: {e}")

        # DM transcript to creator
        try:
            creator = await self.bot.fetch_user(metadata['user_id'])
            transcript_file.fp.seek(0)
            await creator.send("Your ticket was automatically closed due to inactivity. Here is the transcript:", file=transcript_file)
        except (discord.NotFound, discord.Forbidden):
            pass # User not found or DMs disabled

        # Delete channel
        await asyncio.sleep(10)
        try:
            await channel.delete(reason="Ticket auto-closed")
        except discord.HTTPException as e:
            logger.error(f"Failed to delete auto-closed ticket channel {channel.id}: {e}")


    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready, re-registers persistent views."""
        # Register the main ticket creation view
        self.bot.add_view(TicketPanelView())

        # Re-register control views for all open ticket channels
        try:
            ticket_category_id = config.get("ticket_category")
            if not ticket_category_id:
                logger.warning("Ticket category not configured. Cannot re-register views.")
                return

            # Assuming the bot is in a single guild
            guild = self.bot.guilds[0]
            category = guild.get_channel(int(ticket_category_id))

            if category:
                for channel in category.channels:
                    if isinstance(channel, discord.TextChannel):
                        metadata = await get_metadata_from_channel(channel)
                        if metadata and metadata.get('status') == 'open':
                            ticket_id = metadata.get('ticket_id')
                            self.bot.add_view(TicketControlsView(ticket_id))
                            logger.info(f"Re-registered controls for open ticket #{ticket_id}")
        except Exception as e:
            logger.error(f"Error re-registering persistent ticket views: {e}")

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
            description="Need help? Create a ticket by clicking one of the buttons below!",
            color=discord.Color.blue()
        )
        
        # Add a footer
        embed.set_footer(text="Click a button below to create a ticket")
        
        # Add information about ticket categories
        categories = [
            {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
            {"name": "Resource Issue", "emoji": "⚠️", "description": "Report a problem with a resource"},
            {"name": "Partner/Sponsor", "emoji": "💰", "description": "Partner or sponsorship inquiries"},
            {"name": "Staff Application", "emoji": "🔒", "description": "Apply to join our staff team"},
            {"name": "Content Creator", "emoji": "📷", "description": "Content creator applications"},
            {"name": "Other", "emoji": "📝", "description": "Other inquiries"}
        ]
        
        # Add fields for each category
        # Send confirmation message
        await interaction.response.send_message("Ticket claimed!", ephemeral=True)
        logger.info(f"Ticket system set up in channel {target_channel.id} by {interaction.user} (ID: {interaction.user.id})")

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
    """
    The setup function to add this cog to the bot.
    This function is called when the cog is loaded.
    """
    await bot.add_cog(Tickets(bot))
    logger.info("Tickets cog loaded successfully!")
