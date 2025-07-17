import discord
from discord import app_commands
from discord.ext import commands, tasks
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
import uuid
from bot import load_data, save_data

logger = logging.getLogger('bot.tickets')
os.makedirs('data', exist_ok=True)

class TicketManager:
    def __init__(self):
        self.data_file = 'data/tickets.json'
        self.data = self.load_data()

    def load_data(self):
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"tickets": {}, "reaction_roles": {}, "blacklist": []}

    def save_data(self):
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2)

    def create_ticket(self, ticket_data: dict) -> str:
        ticket_id = str(uuid.uuid4())[:8]
        ticket_data['ticket_id'] = ticket_id
        ticket_data['created_at'] = datetime.now().isoformat()
        ticket_data['status'] = 'open'
        self.data['tickets'][ticket_id] = ticket_data
        self.save_data()
        return ticket_id

    def get_ticket(self, ticket_id: str) -> Optional[dict]:
        return self.data['tickets'].get(ticket_id)

    def update_ticket(self, ticket_id: str, updates: dict):
        if ticket_id in self.data['tickets']:
            self.data['tickets'][ticket_id].update(updates)
            self.save_data()

    def delete_ticket(self, ticket_id: str):
        if ticket_id in self.data['tickets']:
            del self.data['tickets'][ticket_id]
            self.save_data()

    def get_user_tickets(self, user_id: int) -> List[dict]:
        return [ticket for ticket in self.data['tickets'].values() 
                if ticket.get('user_id') == user_id]

    def get_channel_ticket(self, channel_id: int) -> Optional[dict]:
        for ticket in self.data['tickets'].values():
            if ticket.get('channel_id') == channel_id:
                return ticket
        return None

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
        
        if result:
            ticket_id, channel = result
            await channel.send(embed=form_embed)

    def format_embed(self, interaction: discord.Interaction) -> discord.Embed:
        embed = discord.Embed(
            title=f"📋 {self.category} Ticket Details",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        
        for label, value in self.form_data.items():
            embed.add_field(name=label, value=value, inline=False)
        
        return embed

class GeneralSupportForm(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("General Support", *args, **kwargs)
        self.add_item(discord.ui.TextInput(
            label="Issue Description",
            style=discord.TextStyle.paragraph,
            placeholder="Please describe your issue in detail...",
            required=True,
            max_length=1000
        ))

class BugReportForm(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Bug Report", *args, **kwargs)
        self.add_item(discord.ui.TextInput(
            label="Bug Description",
            style=discord.TextStyle.paragraph,
            placeholder="Describe the bug you encountered...",
            required=True,
            max_length=1000
        ))
        self.add_item(discord.ui.TextInput(
            label="Steps to Reproduce",
            style=discord.TextStyle.paragraph,
            placeholder="List the steps to reproduce this bug...",
            required=True,
            max_length=1000
        ))
        self.add_item(discord.ui.TextInput(
            label="Expected Behavior",
            style=discord.TextStyle.paragraph,
            placeholder="What did you expect to happen?",
            required=True,
            max_length=500
        ))

class StaffApplicationForm(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Staff Application", *args, **kwargs)
        self.add_item(discord.ui.TextInput(
            label="Discord Username",
            style=discord.TextStyle.short,
            placeholder="Your Discord username and tag",
            required=True,
            max_length=50
        ))
        self.add_item(discord.ui.TextInput(
            label="Age",
            style=discord.TextStyle.short,
            placeholder="Your age",
            required=True,
            max_length=3
        ))
        self.add_item(discord.ui.TextInput(
            label="Timezone",
            style=discord.TextStyle.short,
            placeholder="Your timezone (e.g., EST, PST, UTC+2)",
            required=True,
            max_length=20
        ))
        self.add_item(discord.ui.TextInput(
            label="Experience",
            style=discord.TextStyle.paragraph,
            placeholder="Describe your moderation experience...",
            required=True,
            max_length=1000
        ))
        self.add_item(discord.ui.TextInput(
            label="Why You",
            style=discord.TextStyle.paragraph,
            placeholder="Why should we choose you as staff?",
            required=True,
            max_length=1000
        ))

class PartnershipForm(TicketFormModal):
    def __init__(self, *args, **kwargs):
        super().__init__("Partnership", *args, **kwargs)
        self.add_item(discord.ui.TextInput(
            label="Server/Organization Name",
            style=discord.TextStyle.short,
            placeholder="Name of your server or organization",
            required=True,
            max_length=100
        ))
        self.add_item(discord.ui.TextInput(
            label="Member Count",
            style=discord.TextStyle.short,
            placeholder="Approximate member count",
            required=True,
            max_length=10
        ))
        self.add_item(discord.ui.TextInput(
            label="Partnership Type",
            style=discord.TextStyle.short,
            placeholder="What type of partnership are you looking for?",
            required=True,
            max_length=100
        ))
        self.add_item(discord.ui.TextInput(
            label="Additional Info",
            style=discord.TextStyle.paragraph,
            placeholder="Any additional information...",
            required=False,
            max_length=1000
        ))

class CloseTicketModal(discord.ui.Modal):
    def __init__(self, ticket_id: str, *args, **kwargs):
        super().__init__(title="Close Ticket", *args, **kwargs)
        self.ticket_id = ticket_id
        self.add_item(discord.ui.TextInput(
            label="Reason for closing",
            style=discord.TextStyle.paragraph,
            placeholder="Optional: Provide a reason for closing this ticket...",
            required=False,
            max_length=500
        ))

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.children[0].value or "No reason provided"
        ticket_manager = TicketManager()
        ticket = ticket_manager.get_ticket(self.ticket_id)
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return

        if interaction.user.id != ticket['user_id'] and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("You don't have permission to close this ticket!", ephemeral=True)
            return

        await interaction.response.defer()
        
        channel = interaction.guild.get_channel(ticket['channel_id'])
        if channel:
            try:
                transcript = await self.generate_transcript(channel, ticket)
                transcript_file = discord.File(io.BytesIO(transcript.encode('utf-8')), 
                                             filename=f"ticket-{self.ticket_id}-transcript.txt")
                
                log_channel_id = load_data('config').get('ticket_log_channel')
                if log_channel_id:
                    log_channel = interaction.guild.get_channel(int(log_channel_id))
                    if log_channel:
                        embed = discord.Embed(
                            title=f"📝 Ticket Closed - {ticket['category']}",
                            description=f"**Ticket ID:** {self.ticket_id}\n**User:** <@{ticket['user_id']}>\n**Reason:** {reason}",
                            color=discord.Color.red(),
                            timestamp=datetime.now()
                        )
                        if ticket.get('claimed_by'):
                            embed.add_field(name="Claimed By", value=f"<@{ticket['claimed_by']}>", inline=True)
                        await log_channel.send(embed=embed, file=transcript_file)

                await channel.delete(reason=f"Ticket closed by {interaction.user}: {reason}")
                
            except Exception as e:
                logger.error(f"Error closing ticket {self.ticket_id}: {e}")
                await interaction.followup.send(f"Error closing ticket: {str(e)}", ephemeral=True)
                return

        ticket_manager.update_ticket(self.ticket_id, {
            'status': 'closed',
            'closed_at': datetime.now().isoformat(),
            'closed_by': interaction.user.id,
            'close_reason': reason
        })
        
        await interaction.followup.send("Ticket closed successfully!", ephemeral=True)

    async def generate_transcript(self, channel: discord.TextChannel, ticket: dict) -> str:
        messages = []
        try:
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                author = f"{message.author.display_name} ({message.author})"
                content = message.content or "[No text content]"
                
                messages.append(f"[{timestamp}] {author}: {content}")
                
                if message.attachments:
                    for attachment in message.attachments:
                        messages.append(f"[{timestamp}] {author}: [Attachment: {attachment.filename} - {attachment.url}]")
                
                if message.embeds:
                    for embed in message.embeds:
                        messages.append(f"[{timestamp}] {author}: [Embed: {embed.title or 'No title'}]")
        
        except Exception as e:
            messages.append(f"[Error fetching messages: {e}]")
        
        header = f"Ticket Transcript - {ticket['category']}\n"
        header += f"Ticket ID: {ticket['ticket_id']}\n"
        header += f"User: {ticket['user_name']} ({ticket['user_id']})\n"
        header += f"Created: {ticket['created_at']}\n"
        header += f"Status: {ticket['status']}\n"
        header += "=" * 50 + "\n\n"
        
        return header + "\n".join(messages)

class TicketCategorySelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.ticket_manager = TicketManager()

    @discord.ui.select(
        placeholder="Select a ticket category...",
        options=[
            discord.SelectOption(
                label="General Support",
                description="Get help with general questions",
                emoji="❓",
                value="general"
            ),
            discord.SelectOption(
                label="Bug Report",
                description="Report bugs or technical issues",
                emoji="🐛",
                value="bug"
            ),
            discord.SelectOption(
                label="Staff Application",
                description="Apply to become staff",
                emoji="👤",
                value="staff"
            ),
            discord.SelectOption(
                label="Partnership",
                description="Partnership inquiries",
                emoji="🤝",
                value="partnership"
            )
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        
        user_tickets = self.ticket_manager.get_user_tickets(interaction.user.id)
        active_tickets = [t for t in user_tickets if t['status'] == 'open']
        
        if active_tickets:
            embed = discord.Embed(
                title="❌ Active Ticket Found",
                description=f"You already have an open ticket: **{active_tickets[0]['category']}**",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if category == "general":
            await interaction.response.send_modal(GeneralSupportForm())
        elif category == "bug":
            await interaction.response.send_modal(BugReportForm())
        elif category == "staff":
            await interaction.response.send_modal(StaffApplicationForm())
        elif category == "partnership":
            await interaction.response.send_modal(PartnershipForm())

    async def create_ticket_channel(self, interaction: discord.Interaction, modal: TicketFormModal) -> tuple:
        config = load_data('config')
        category_id = config.get('ticket_category')
        support_role_id = config.get('support_role')
        
        if not category_id:
            await interaction.followup.send("Ticket system not configured!", ephemeral=True)
            return None

        category = interaction.guild.get_channel(int(category_id))
        if not category:
            await interaction.followup.send("Ticket category not found!", ephemeral=True)
            return None

        ticket_num = len(self.ticket_manager.data['tickets']) + 1
        channel_name = f"{modal.category.lower().replace(' ', '-')}-{ticket_num}"
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        if support_role_id:
            support_role = interaction.guild.get_role(int(support_role_id))
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            channel = await category.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                topic=f"Ticket for {interaction.user.display_name}"
            )
            
            ticket_data = {
                'user_id': interaction.user.id,
                'user_name': str(interaction.user),
                'category': modal.category,
                'channel_id': channel.id,
                'channel_name': channel.name,
                'form_data': modal.form_data,
                'priority': 'normal',
                'claimed_by': None,
                'participants': [interaction.user.id]
            }
            
            ticket_id = self.ticket_manager.create_ticket(ticket_data)
            
            embed = discord.Embed(
                title=f"🎫 {modal.category} Ticket Created",
                description=f"Welcome {interaction.user.mention}! Support will be with you shortly.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Ticket ID", value=ticket_id, inline=True)
            embed.add_field(name="Category", value=modal.category, inline=True)
            embed.add_field(name="Priority", value="🟡 Normal", inline=True)
            
            view = TicketControlView(ticket_id)
            message = await channel.send(
                content=f"{interaction.user.mention} " + (f"<@&{support_role_id}>" if support_role_id else ""),
                embed=embed,
                view=view
            )
            
            await interaction.followup.send(
                f"✅ Your ticket has been created: {channel.mention}",
                ephemeral=True
            )
            
            return ticket_id, channel
            
        except Exception as e:
            logger.error(f"Error creating ticket channel: {e}")
            await interaction.followup.send("Error creating ticket channel!", ephemeral=True)
            return None

class TicketControlView(discord.ui.View):
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.ticket_manager = TicketManager()
        
    @discord.ui.button(label="Claim", style=discord.ButtonStyle.blurple, emoji="👋", row=0)
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = self.ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
            
        if ticket.get('claimed_by'):
            await interaction.response.send_message(
                f"This ticket is already claimed by <@{ticket['claimed_by']}>", 
                ephemeral=True
            )
            return
            
        self.ticket_manager.update_ticket(self.ticket_id, {
            'claimed_by': interaction.user.id
        })
        
        embed = discord.Embed(
            title="✅ Ticket Claimed",
            description=f"This ticket has been claimed by {interaction.user.mention}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
        
        channel = interaction.guild.get_channel(ticket['channel_id'])
        if channel:
            await channel.edit(topic=f"Claimed by {interaction.user.display_name}")

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.green, emoji="➕", row=0)
    async def add_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddUserModal(self.ticket_id))

    @discord.ui.button(label="Priority", style=discord.ButtonStyle.gray, emoji="⚡", row=0)
    async def priority_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View()
        view.add_item(PrioritySelect(self.ticket_id))
        await interaction.response.send_message("Select priority:", view=view, ephemeral=True)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def transcript_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = self.ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
            
        if interaction.user.id != ticket['user_id'] and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "You don't have permission to generate a transcript!", 
                ephemeral=True
            )
            return
            
        channel = interaction.guild.get_channel(ticket['channel_id'])
        if channel:
            transcript = await CloseTicketModal(self.ticket_id).generate_transcript(channel, ticket)
            transcript_file = discord.File(
                io.BytesIO(transcript.encode('utf-8')), 
                filename=f"ticket-{self.ticket_id}-transcript.txt"
            )
            await interaction.response.send_message(
                "Here is the transcript:", 
                file=transcript_file, 
                ephemeral=True
            )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", row=1)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CloseTicketModal(self.ticket_id))

class AddUserModal(discord.ui.Modal):
    def __init__(self, ticket_id: str, *args, **kwargs):
        super().__init__(title="Add User to Ticket", *args, **kwargs)
        self.ticket_id = ticket_id
        self.ticket_manager = TicketManager()
        
        self.add_item(discord.ui.TextInput(
            label="User Mention or ID",
            style=discord.TextStyle.short,
            placeholder="@username or user ID",
            required=True
        ))

    async def on_submit(self, interaction: discord.Interaction):
        user_input = self.children[0].value.strip()
        
        try:
            if user_input.startswith('<@') and user_input.endswith('>'):
                user_id = int(user_input[2:-1].replace('!', ''))
            else:
                user_id = int(user_input)
                
            user = await interaction.guild.fetch_member(user_id)
            
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Invalid user!", ephemeral=True)
            return
            
        ticket = self.ticket_manager.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
            
        if user_id in ticket.get('participants', []):
            await interaction.response.send_message("User already has access!", ephemeral=True)
            return
            
        channel = interaction.guild.get_channel(ticket['channel_id'])
        if not channel:
            await interaction.response.send_message("Channel not found!", ephemeral=True)
            return
            
        try:
            await channel.set_permissions(user, read_messages=True, send_messages=True)
            
            participants = ticket.get('participants', [])
            participants.append(user_id)
            self.ticket_manager.update_ticket(self.ticket_id, {'participants': participants})
            
            embed = discord.Embed(
                title="✅ User Added",
                description=f"{user.mention} has been added to this ticket.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"Error adding user: {str(e)}", ephemeral=True)

class PrioritySelect(discord.ui.Select):
    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        self.ticket_manager = TicketManager()
        
        options = [
            discord.SelectOption(label="Urgent", value="urgent", emoji="🔴"),
            discord.SelectOption(label="High", value="high", emoji="🟠"),
            discord.SelectOption(label="Normal", value="normal", emoji="🟡"),
            discord.SelectOption(label="Low", value="low", emoji="🔵")
        ]
        super().__init__(placeholder="Choose priority...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        priority = self.values[0]
        self.ticket_manager.update_ticket(self.ticket_id, {'priority': priority})
        
        priority_emojis = {
            'urgent': '🔴',
            'high': '🟠', 
            'normal': '🟡',
            'low': '🔵'
        }
        
        embed = discord.Embed(
            title="✅ Priority Updated",
            description=f"Priority set to {priority_emojis[priority]} {priority.capitalize()}",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=None)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ticket_manager = TicketManager()
        try:
            self.auto_close_task.start()
        except Exception as e:
            logger.error(f"Failed to start auto-close task: {e}")
            traceback.print_exc()

    def cog_unload(self):
        try:
            self.auto_close_task.cancel()
        except:
            pass

    @app_commands.command(name="ticketpanel", description="Create a ticket creation panel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Create a Ticket",
            description="Select a category below to create a new ticket",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Categories",
            value="❓ **General Support** - Get help with questions\n"
                  "🐛 **Bug Report** - Report technical issues\n"
                  "👤 **Staff Application** - Apply to become staff\n"
                  "🤝 **Partnership** - Partnership inquiries",
            inline=False
        )
        
        view = TicketCategorySelect()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="tickets", description="View ticket statistics")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_stats(self, interaction: discord.Interaction):
        tickets = self.ticket_manager.data['tickets']
        
        total = len(tickets)
        open_tickets = len([t for t in tickets.values() if t['status'] == 'open'])
        closed_tickets = len([t for t in tickets.values() if t['status'] == 'closed'])
        
        category_counts = {}
        for ticket in tickets.values():
            cat = ticket['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        embed = discord.Embed(
            title="📊 Ticket Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(name="Total Tickets", value=str(total), inline=True)
        embed.add_field(name="Open", value=str(open_tickets), inline=True)
        embed.add_field(name="Closed", value=str(closed_tickets), inline=True)
        
        if category_counts:
            categories_text = "\n".join([f"{cat}: {count}" for cat, count in category_counts.items()])
            embed.add_field(name="By Category", value=categories_text, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @tasks.loop(minutes=30)
    async def auto_close_task(self):
        """Auto-close tickets with 24h user inactivity"""
        await self.bot.wait_until_ready()
        
        # Create a copy to avoid modification during iteration
        tickets = list(self.ticket_manager.data['tickets'].values())
        for ticket in tickets:
            if ticket['status'] != 'open':
                continue
                
            channel = self.bot.get_channel(ticket['channel_id'])
            if not channel:
                continue
                
            try:
                # Get last user message
                last_user_msg = None
                async for msg in channel.history(limit=100):
                    if msg.author.id == ticket['user_id'] and not msg.author.bot:
                        last_user_msg = msg
                        break
                
                # Auto-close if no user activity for 24h
                if last_user_msg:
                    time_diff = datetime.now() - last_user_msg.created_at
                    if time_diff > timedelta(hours=24):
                        try:
                            await channel.delete(reason="Auto-closed due to 24h user inactivity")
                        except discord.NotFound:
                            pass  # Channel already deleted
                        self.ticket_manager.update_ticket(ticket['ticket_id'], {
                            'status': 'closed',
                            'closed_at': datetime.now().isoformat(),
                            'closed_by': None,
                            'close_reason': 'Auto-closed: 24h user inactivity'
                        })
                else:
                    # No user messages at all, close immediately
                    try:
                        await channel.delete(reason="Auto-closed: no user messages")
                    except discord.NotFound:
                        pass  # Channel already deleted
                    self.ticket_manager.update_ticket(ticket['ticket_id'], {
                        'status': 'closed',
                        'closed_at': datetime.now().isoformat(),
                        'closed_by': None,
                        'close_reason': 'Auto-closed: no user messages'
                    })
                    
            except Exception as e:
                logger.error(f"Error processing ticket {ticket['ticket_id']}: {e}")
                traceback.print_exc()

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Tickets cog loaded and ready!")

async def setup(bot):
    try:
        await bot.add_cog(Tickets(bot))
        logger.info("Tickets cog loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load Tickets cog: {e}")
        traceback.print_exc()