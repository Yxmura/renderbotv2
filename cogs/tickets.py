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
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict, field
import uuid


# Set up logging
logger = logging.getLogger('bot.tickets')

# Ensure data directory exists
os.makedirs('data', exist_ok=True)


@dataclass
class TicketMetadata:
    """Class to handle ticket metadata serialization/deserialization."""
    ticket_id: str
    user_id: int
    category: str
    status: str = "open"
    priority: str = "normal"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    claimed_by: Optional[int] = None
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())
    closed_at: Optional[str] = None
    closed_by: Optional[int] = None
    close_reason: Optional[str] = None
    close_type: Optional[str] = None
    
    @classmethod
    def from_topic(cls, topic: Optional[str]) -> Optional['TicketMetadata']:
        """Create TicketMetadata from channel topic."""
        if not topic or not topic.startswith("TICKET_METADATA:"):
            return None
            
        try:
            json_str = topic.split("TICKET_METADATA:", 1)[1].strip()
            data = json.loads(json_str)
            return cls(**data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Error parsing ticket metadata: {e}")
            return None
    
    def to_topic(self) -> str:
        """Convert metadata to channel topic string."""
        data = asdict(self)
        json_str = json.dumps(data, ensure_ascii=False)
        return f"TICKET_METADATA:{json_str}"
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now().isoformat()
    
    def close(self, closer_id: int, reason: str, close_type: str):
        """Close the ticket."""
        self.status = "closed"
        self.closed_at = datetime.now().isoformat()
        self.closed_by = closer_id
        self.close_reason = reason
        self.close_type = close_type
        self.update_activity()

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
    config = load_config()
    admin_roles = config.get("admin_roles", [])
    
    # If no admin roles are set, only server admins can use admin commands
    if not admin_roles:
        return False
        
    # Check if user has any of the admin roles
    user_role_ids = [str(role.id) for role in interaction.user.roles]
    return any(role_id in user_role_ids for role_id in admin_roles)


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
            categories = [
                {"name": "General Support", "emoji": "❓", "description": "Get help with general questions"},
                {"name": "Resource Issue", "emoji": "⚠️", "description": "Report a problem with a resource"},
                {"name": "Partner- or sponsorship", "emoji": "💰", "description": "Partner or sponsorship inqueries"},
                {"name": "Staff Application - if open", "emoji": "🔒", "description": "Request for staff application, if open"},
                {"name": "Other", "emoji": "📝", "description": "Other inquiries (e.g. bug reports)"}
            ]

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
                return

        # Create new ticket
        category = self.values[0]
        ticket_id = str(uuid.uuid4())[:8]  # Generate a short unique ID

        # Create ticket channel
        overwrites = {
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
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True
                )

        # Get ticket category if set
        category_channel = None
        if config.get("ticket_category_id"):
            category_channel = guild.get_channel(int(config["ticket_category_id"]))

        # Create ticket metadata
        metadata = TicketMetadata(
            ticket_id=ticket_id,
            user_id=interaction.user.id,
            category=category
        )

        # Create the channel with metadata in topic
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{ticket_id}",
                overwrites=overwrites,
                category=category_channel,
                topic=metadata.to_topic(),
                reason=f"Ticket created by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to create channels!", 
                ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"Failed to create ticket channel: {str(e)}", 
                ephemeral=True
            )
            return

        # Send confirmation to user
        await interaction.response.send_message(
            f"Ticket created! Please check {channel.mention}", 
            ephemeral=True
        )

        # Send initial message in ticket channel
        embed = discord.Embed(
            title=f"Ticket #{ticket_id} - {category}",
            description=(
                f"Thank you for creating a ticket, {interaction.user.mention}!\n"
                "An admin will be with you shortly.\n\n"
                "**Please describe your issue in detail.**"
            ),
            color=discord.Color.blue()
        )
        embed.add_field(name="Category", value=category, inline=True)
        embed.add_field(name="Created", 
                       value=f"<t:{int(datetime.now().timestamp())}:R>", 
                       inline=True)
        embed.add_field(name="Priority", value="Normal", inline=True)
        embed.set_footer(text=f"Ticket ID: {ticket_id} • User ID: {interaction.user.id}")

        # Create ticket management buttons
        ticket_controls = TicketControlsView(ticket_id)
        
        # Mention support role if configured
        mention = ""
        if config.get("support_role_id"):
            mention = f"<@&{config['support_role_id']}>"
        
        await channel.send(embed=embed, view=ticket_controls, content=mention)

        # Log ticket creation to log channel if configured
        log_channel_id = config.get("ticket_log_channel")
        if log_channel_id:
            log_channel = guild.get_channel(int(log_channel_id))
            if log_channel:
                log_embed = discord.Embed(
                    title=f"Ticket #{ticket_id} Created",
                    color=discord.Color.green()
                )
                log_embed.add_field(name="User", 
                                  value=f"{interaction.user.mention} ({interaction.user.id})", 
                                  inline=True)
                log_embed.add_field(name="Category", value=category, inline=True)
                log_embed.add_field(name="Channel", value=channel.mention, inline=True)
                log_embed.timestamp = datetime.now()
                await log_channel.send(embed=log_embed)

        # Log ticket creation
        logger.info(
            f"Ticket #{ticket_id} created by {interaction.user} "
            f"(ID: {interaction.user.id}) in category {category}"
        )

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


class TicketControlsView(discord.ui.View):
    """View for ticket control buttons."""
    
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[TicketMetadata]:
        """Get ticket metadata from channel topic."""
        metadata = TicketMetadata.from_topic(channel.topic)
        if not metadata or metadata.ticket_id != self.ticket_id:
            return None
        return metadata
    
    async def update_ticket_metadata(self, channel: discord.TextChannel, metadata: TicketMetadata) -> None:
        """Update ticket metadata in channel topic."""
        try:
            await channel.edit(topic=metadata.to_topic())
        except discord.HTTPException as e:
            logger.error(f"Failed to update ticket metadata: {e}")
    
    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, custom_id="claim_ticket", emoji="🙋‍♂️")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Claim the ticket for handling."""
        # Check permissions
        if not await is_admin(interaction):
            await interaction.response.send_message(
                "You don't have permission to claim tickets!", 
                ephemeral=True
            )
            return
        
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message(
                "This ticket no longer exists or is invalid!", 
                ephemeral=True
            )
            return
            
        # Check if already claimed
        if metadata.claimed_by:
            claimer = interaction.guild.get_member(metadata.claimed_by)
            claimer_name = claimer.mention if claimer else f"User ID: {metadata.claimed_by}"
            await interaction.response.send_message(
                f"This ticket has already been claimed by {claimer_name}!", 
                ephemeral=True
            )
            return
            
        # Update metadata
        metadata.claimed_by = interaction.user.id
        metadata.update_activity()
        await self.update_ticket_metadata(interaction.channel, metadata)
        
        # Update the embed
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            # Update claimed status in embed
            if len(embed.fields) >= 3:  # If we have 3 fields (Category, Created, Priority)
                embed.set_field_at(2, name="Status", value=f"Claimed by {interaction.user.mention}", inline=True)
            
            # Update color to indicate claimed
            embed.color = discord.Color.green()
            
            # Disable the claim button
            for item in self.children:
                if item.custom_id == "claim_ticket":
                    item.disabled = True
                    break
            
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()
        
        # Send notification
        await interaction.followup.send(
            f"{interaction.user.mention} has claimed this ticket!",
            allowed_mentions=discord.AllowedMentions(users=[interaction.user])
        )
        
        logger.info(f"Ticket #{self.ticket_id} claimed by {interaction.user} (ID: {interaction.user.id})")
    
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Initiate ticket closure."""
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message(
                "This ticket no longer exists or is invalid!", 
                ephemeral=True
            )
            return
            
        # Check permissions (ticket creator or admin)
        is_creator = interaction.user.id == metadata.user_id
        is_admin_user = await is_admin(interaction)
        
        if not (is_creator or is_admin_user):
            await interaction.response.send_message(
                "Only the ticket creator or an admin can close this ticket!",
                ephemeral=True
            )
            return
            
        # Show close reason modal
        await interaction.response.send_modal(CloseTicketModal(self.ticket_id))
    
    @discord.ui.button(label="Set Priority", style=discord.ButtonStyle.secondary, custom_id="set_priority", emoji="🔖")
    async def set_priority(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set ticket priority."""
        # Check admin permissions
        if not await is_admin(interaction):
            await interaction.response.send_message(
                "You don't have permission to set ticket priority!",
                ephemeral=True
            )
            return
            
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message(
                "This ticket no longer exists or is invalid!",
                ephemeral=True
            )
            return
            
        # Show priority selection
        await interaction.response.send_message(
            "Select a priority level for this ticket:",
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
    
    async def generate_transcript(self, channel: discord.TextChannel, metadata: TicketMetadata) -> str:
        """Generate a text transcript of the ticket."""
        # Fetch messages (newest first, then we'll reverse)
        messages = []
        async for message in channel.history(limit=1000, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)
        
        # Format transcript header
        transcript = f"Ticket Transcript - #{metadata.ticket_id}\n"
        transcript += "=" * 50 + "\n\n"
        
        # Add ticket metadata
        transcript += f"Ticket ID: {metadata.ticket_id}\n"
        transcript += f"Category: {metadata.category}\n"
        creator = channel.guild.get_member(metadata.user_id)
        transcript += f"Creator: {creator} (ID: {metadata.user_id}) \n"
        
        if metadata.claimed_by:
            claimer = channel.guild.get_member(metadata.claimed_by)
            claimer_info = f"{claimer} (ID: {metadata.claimed_by})" if claimer else f"User ID: {metadata.claimed_by}"
            transcript += f"Claimed by: {claimer_info}\n"
        
        transcript += f"Status: {metadata.status.capitalize()}\n"
        transcript += f"Priority: {metadata.priority.capitalize()}\n"
        created_dt = datetime.fromisoformat(metadata.created_at)
        transcript += f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if metadata.closed_at and metadata.closed_by:
            closed_dt = datetime.fromisoformat(metadata.closed_at)
            closer = channel.guild.get_member(metadata.closed_by)
            closer_info = f"{closer} (ID: {metadata.closed_by})" if closer else f"User ID: {metadata.closed_by}"
            transcript += f"Closed: {closed_dt.strftime('%Y-%m-%d %H:%M:%S')} by {closer_info}\n"
            if metadata.close_reason:
                transcript += f"Close Reason: {metadata.close_reason}\n"
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
        super().__init__(timeout=60)  # 1 minute timeout
        self.ticket_id = ticket_id
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[TicketMetadata]:
        """Get ticket metadata from channel topic."""
        metadata = TicketMetadata.from_topic(channel.topic)
        if not metadata or metadata.ticket_id != self.ticket_id:
            return None
        return metadata
    
    async def update_ticket_metadata(self, channel: discord.TextChannel, metadata: TicketMetadata) -> None:
        """Update ticket metadata in channel topic."""
        try:
            await channel.edit(topic=metadata.to_topic())
        except discord.HTTPException as e:
            logger.error(f"Failed to update ticket metadata: {e}")
    
    @discord.ui.button(label="Low", style=discord.ButtonStyle.secondary, custom_id="priority_low")
    async def priority_low(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set priority to low."""
        await self.set_priority(interaction, "low", discord.Color.green())
    
    @discord.ui.button(label="Normal", style=discord.ButtonStyle.primary, custom_id="priority_normal")
    async def priority_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set priority to normal."""
        await self.set_priority(interaction, "normal", discord.Color.blue())
    
    @discord.ui.button(label="High", style=discord.ButtonStyle.danger, custom_id="priority_high")
    async def priority_high(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set priority to high."""
        await self.set_priority(interaction, "high", discord.Color.orange())
    
    @discord.ui.button(label="Urgent", style=discord.ButtonStyle.danger, custom_id="priority_urgent")
    async def priority_urgent(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set priority to urgent."""
        await self.set_priority(interaction, "urgent", discord.Color.red())
    
    async def set_priority(self, interaction: discord.Interaction, priority: str, color: discord.Color):
        """Update ticket priority and refresh the ticket message."""
        # Get the ticket channel from the interaction's message reference
        if not interaction.message or not interaction.message.reference:
            await interaction.response.send_message(
                "Could not determine the ticket channel. Please try again.",
                ephemeral=True
            )
            return
            
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
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[TicketMetadata]:
        """Get ticket metadata from channel topic."""
        metadata = TicketMetadata.from_topic(channel.topic)
        if not metadata or metadata.ticket_id != self.ticket_id:
            return None
        return metadata
    
    async def update_ticket_metadata(self, channel: discord.TextChannel, metadata: TicketMetadata) -> None:
        """Update ticket metadata in channel topic."""
        try:
            await channel.edit(topic=metadata.to_topic())
            return True
        except discord.HTTPException as e:
            logger.error(f"Failed to update ticket metadata: {e}")
            return False

    async def on_submit(self, interaction: discord.Interaction):
        """Handle form submission."""
        # Get the ticket channel
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This command can only be used in a ticket channel.",
                ephemeral=True
            )
            return
            
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message(
                "This ticket no longer exists or is invalid!", 
                ephemeral=True
            )
            return
            
        # Check if user has permission to close (creator or admin)
        is_creator = interaction.user.id == metadata.user_id
        is_admin_user = await is_admin(interaction)
        
        if not (is_creator or is_admin_user):
            await interaction.response.send_message(
                "Only the ticket creator or an admin can close this ticket!",
                ephemeral=True
            )
            return
        
        # Send confirmation message with buttons
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Close Request",
            description=(
                f"This ticket has been requested to be closed by {interaction.user.mention}\n\n"
                f"**Reason:** {self.reason.value}"
            ),
            color=discord.Color.orange()
        )
        
        # Add ticket info
        creator = interaction.guild.get_member(metadata.user_id)
        creator_info = f"{creator.mention} (ID: {metadata.user_id})" if creator else f"User ID: {metadata.user_id}"
        
        embed.add_field(name="Creator", value=creator_info, inline=True)
        embed.add_field(name="Category", value=metadata.category, inline=True)
        
        if metadata.claimed_by:
            claimer = interaction.guild.get_member(metadata.claimed_by)
            claimer_info = f"{claimer.mention} (ID: {metadata.claimed_by})" if claimer else f"User ID: {metadata.claimed_by}"
            embed.add_field(name="Claimed By", value=claimer_info, inline=True)
        
        created_dt = datetime.fromisoformat(metadata.created_at)
        embed.add_field(
            name="Created", 
            value=f"<t:{int(created_dt.timestamp())}:R>", 
            inline=True
        )
        
        embed.set_footer(text=f"Ticket ID: {self.ticket_id} • Requested at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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

    async def generate_transcript(self, channel: discord.TextChannel, metadata: TicketMetadata) -> str:
        """Generate a text transcript of the ticket."""
        # Fetch messages (newest first, then we'll reverse)
        messages = []
        async for message in channel.history(limit=1000, oldest_first=True):
            if not message.author.bot or (message.author.bot and message.embeds):
                messages.append(message)
        
        # Format transcript header
        transcript = f"Ticket Transcript - #{metadata.ticket_id}\n"
        transcript += "=" * 50 + "\n\n"
        
        # Add ticket metadata
        transcript += f"Ticket ID: {metadata.ticket_id}\n"
        transcript += f"Category: {metadata.category}\n"
        creator = channel.guild.get_member(metadata.user_id)
        transcript += f"Creator: {creator} (ID: {metadata.user_id}) \n"
        if metadata.claimed_by:
            claimer = channel.guild.get_member(metadata.claimed_by)
            claimer_info = f"{claimer} (ID: {metadata.claimed_by})" if claimer else f"User ID: {metadata.claimed_by}"
            transcript += f"Claimed by: {claimer_info}\n"
        
        transcript += f"Status: {metadata.status.capitalize()}\n"
        transcript += f"Priority: {metadata.priority.capitalize()}\n"
        created_dt = datetime.fromisoformat(metadata.created_at)
        transcript += f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if metadata.closed_at and metadata.closed_by:
            closed_dt = datetime.fromisoformat(metadata.closed_at)
            closer = channel.guild.get_member(metadata.closed_by)
            closer_info = f"{closer} (ID: {metadata.closed_by})" if closer else f"User ID: {metadata.closed_by}"
            transcript += f"Closed: {closed_dt.strftime('%Y-%m-%d %H:%M:%S')} by {closer_info}\n"
            if metadata.close_reason:
                transcript += f"Close Reason: {metadata.close_reason}\n"
        
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


class TicketCloseConfirmView(discord.ui.View):
    """View for confirming or denying ticket closure."""
    
    def __init__(self, ticket_id: str, reason: str, closer_id: int):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.ticket_id = ticket_id
        self.reason = reason
        self.closer_id = closer_id
    
    async def get_ticket_metadata(self, channel: discord.TextChannel) -> Optional[TicketMetadata]:
        """Get ticket metadata from channel topic."""
        metadata = TicketMetadata.from_topic(channel.topic)
        if not metadata or metadata.ticket_id != self.ticket_id:
            return None
        return metadata
    
    async def update_ticket_metadata(self, channel: discord.TextChannel, metadata: TicketMetadata) -> bool:
        """Update ticket metadata in channel topic."""
        try:
            await channel.edit(topic=metadata.to_topic())
            return True
        except discord.HTTPException as e:
            logger.error(f"Failed to update ticket metadata: {e}")
            return False
    
    async def has_permission(self, interaction: discord.Interaction, metadata: TicketMetadata) -> bool:
        """Check if the user has permission to close the ticket."""
        # Admin can always close
        if await is_admin(interaction):
            return True
            
        # Ticket creator can close their own ticket
        if interaction.user.id == metadata.user_id:
            return True
            
        # The user who initiated the close request can confirm it
        if interaction.user.id == self.closer_id:
            return True
            
        return False
    
    @discord.ui.button(label="Confirm Close", style=discord.ButtonStyle.green, custom_id="confirm_close")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle confirm close button click."""
        await interaction.response.defer()
        
        # Get the ticket channel
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(
                "This command can only be used in a ticket channel.",
                ephemeral=True
            )
            return
            
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.followup.send(
                "This ticket no longer exists or is invalid!",
                ephemeral=True
            )
            return
            
        # Check permissions
        if not await self.has_permission(interaction, metadata):
            await interaction.followup.send(
                "You don't have permission to close this ticket!",
                ephemeral=True
            )
            return
            
        # Close the ticket
        await self.close_ticket(interaction, metadata, "confirmed by user")
    
    @discord.ui.button(label="Deny Close", style=discord.ButtonStyle.red, custom_id="deny_close")
    async def deny_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle deny close button click."""
        # Check permissions
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This command can only be used in a ticket channel.",
                ephemeral=True
            )
            return
            
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.response.send_message(
                "This ticket no longer exists or is invalid!",
                ephemeral=True
            )
            return
            
        # Check if user has permission to deny (same as closing)
        if not await self.has_permission(interaction, metadata):
            await interaction.response.send_message(
                "You don't have permission to deny closing this ticket!",
                ephemeral=True
            )
            return
        
        # Update the message to show denial
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Close Request Denied",
            description=(
                f"The request to close this ticket has been denied by {interaction.user.mention}.\n\n"
                f"**Reason:** {self.reason}"
            ),
            color=discord.Color.red()
        )
        
        # Disable all buttons
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Log the denial
        logger.info(
            f"Ticket #{self.ticket_id} close request denied by {interaction.user} "
            f"(ID: {interaction.user.id})"
        )
    
    @discord.ui.button(label="Force Close", style=discord.ButtonStyle.danger, custom_id="force_close")
    async def force_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle force close button click (admin only)."""
        # Check admin permissions
        if not await is_admin(interaction):
            await interaction.response.send_message(
                "Only admins can force close tickets!",
                ephemeral=True
            )
            return
            
        await interaction.response.defer()
        
        # Get the ticket channel
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(
                "This command can only be used in a ticket channel.",
                ephemeral=True
            )
            return
            
        # Get ticket metadata
        metadata = await self.get_ticket_metadata(interaction.channel)
        if not metadata:
            await interaction.followup.send(
                "This ticket no longer exists or is invalid!",
                ephemeral=True
            )
            return
            
        # Close the ticket with force close reason
        await self.close_ticket(interaction, metadata, "force closed by admin")
    
    async def close_ticket(self, interaction: discord.Interaction, metadata: TicketMetadata, close_type: str):
        """Close the ticket and perform cleanup."""
        # Update metadata
        metadata.status = "closed"
        metadata.closed_at = datetime.now().isoformat()
        metadata.closed_by = interaction.user.id
        metadata.close_reason = self.reason
        metadata.close_type = close_type
        
        # Save changes
        success = await self.update_ticket_metadata(interaction.channel, metadata)
        if not success:
            await interaction.followup.send(
                "Failed to update ticket status. Please try again.",
                ephemeral=True
            )
            return
        
        # Generate transcript
        transcript = await self.generate_transcript(interaction.channel, metadata)
        
        # Create transcript file
        transcript_file = discord.File(
            io.BytesIO(transcript.encode('utf-8')),
            filename=f"ticket-{self.ticket_id}-transcript.txt"
        )
        
        # Create close embed
        embed = discord.Embed(
            title=f"Ticket #{self.ticket_id} Closed",
            description=(
                f"This ticket has been {close_type}.\n\n"
                f"**Reason:** {self.reason}"
            ),
            color=discord.Color.red()
        )
        
        # Add ticket info
        creator = interaction.guild.get_member(metadata.user_id)
        creator_info = f"{creator.mention} (ID: {metadata.user_id})" if creator else f"User ID: {metadata.user_id}"
        
        embed.add_field(name="Creator", value=creator_info, inline=True)
        embed.add_field(name="Category", value=metadata.category, inline=True)
        
        if metadata.claimed_by:
            claimer = interaction.guild.get_member(metadata.claimed_by)
            claimer_info = f"{claimer.mention} (ID: {metadata.claimed_by})" if claimer else f"User ID: {metadata.claimed_by}"
            embed.add_field(name="Claimed By", value=claimer_info, inline=True)
        
        created_dt = datetime.fromisoformat(metadata.created_at)
        closed_dt = datetime.fromisoformat(metadata.closed_at)
        
        embed.add_field(
            name="Duration", 
            value=self.format_duration(created_dt, closed_dt),
            inline=True
        )
        
        closer = interaction.guild.get_member(interaction.user.id)
        closer_info = f"{closer.mention} (ID: {interaction.user.id})" if closer else f"User ID: {interaction.user.id}"
        
        embed.add_field(
            name="Closed By",
            value=closer_info,
            inline=True
        )
        
        embed.set_footer(text=f"Ticket ID: {self.ticket_id} • Closed at {closed_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Disable all buttons in the view
        for child in self.children:
            child.disabled = True
        
        # Update the original message
        try:
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                embed=embed,
                view=self
            )
        except Exception as e:
            logger.error(f"Failed to update close confirmation message: {e}")
        
        # Send transcript to log channel if configured
        config = load_config()
        log_channel_id = config.get('log_channel')
        
        if log_channel_id:
            try:
                log_channel = interaction.guild.get_channel(int(log_channel_id))
                if log_channel:
                    log_embed = discord.Embed(
                        title=f"Ticket #{self.ticket_id} Closed",
                        description=(
                            f"**Category:** {metadata.category}\n"
                            f"**Creator:** {creator_info}\n"
                            f"**Closed by:** {closer_info}\n"
                            f"**Reason:** {self.reason}"
                        ),
                        color=discord.Color.red()
                    )
                    
                    if metadata.claimed_by:
                        log_embed.add_field(name="Claimed By", value=claimer_info, inline=False)
                    
                    log_embed.add_field(
                        name="Duration",
                        value=self.format_duration(created_dt, closed_dt),
                        inline=False
                    )
                    
                    log_embed.set_footer(text=f"Ticket ID: {self.ticket_id}")
                    
                    await log_channel.send(
                        f"Ticket #{self.ticket_id} has been closed by {closer_info}",
                        embed=log_embed,
                        file=discord.File(
                            io.BytesIO(transcript.encode('utf-8')),
                            filename=f"ticket-{self.ticket_id}-transcript.txt"
                        )
                    )
            except Exception as e:
                logger.error(f"Failed to send transcript to log channel: {e}")
        
        # Send transcript to user who closed the ticket
        try:
            user = interaction.user
            if not user.bot:
                await user.send(
                    f"Here's the transcript for ticket #{self.ticket_id} that you closed:",
                    file=discord.File(
                        io.BytesIO(transcript.encode('utf-8')),
                        filename=f"ticket-{self.ticket_id}-transcript.txt"
                    )
                )
        except Exception as e:
            logger.error(f"Failed to send transcript to user {interaction.user.id}: {e}")
        
        # Log the closure
        logger.info(
            f"Ticket #{self.ticket_id} closed by {interaction.user} "
            f"(ID: {interaction.user.id}) with reason: {self.reason}"
        )
        
        # Schedule channel deletion
        try:
            await asyncio.sleep(5)  # Give time for messages to be sent
            await interaction.channel.delete(reason=f"Ticket #{self.ticket_id} closed by {interaction.user}")
        except Exception as e:
            logger.error(f"Failed to delete ticket channel: {e}")
            await interaction.followup.send(
                "Ticket closed, but I couldn't delete the channel. Please delete it manually.",
                ephemeral=True
            )
        
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
