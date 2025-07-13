import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import logging
from datetime import datetime, timedelta
from supabase_client import get_db
from bot import load_data, save_data

# Set up logging
logger = logging.getLogger(__name__)

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


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = str(giveaway_id)
        self.db = get_db()

    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.primary, emoji="🎉", custom_id="enter_giveaway")
    async def enter_giveaway(self, interaction, button):
        # Load giveaway data from Supabase
        try:
            giveaway = await self.db.get_giveaway(self.giveaway_id)
            if not giveaway:
                await interaction.response.send_message("This giveaway no longer exists!", ephemeral=True)
                return
            
            # Check role requirements if any
            if giveaway.get('required_role'):
                required_role_id = int(giveaway['required_role'])
                bypass_roles = [int(role_id) for role_id in (giveaway.get('bypass_roles') or [])]
                
                # Check if user has required role or any bypass role
                user_roles = [role.id for role in interaction.user.roles]
                has_required_role = required_role_id in user_roles
                has_bypass_role = any(role_id in user_roles for role_id in bypass_roles)
                
                if not (has_required_role or has_bypass_role):
                    required_role = interaction.guild.get_role(required_role_id)
                    role_name = required_role.mention if required_role else f"Role ID: {required_role_id}"
                    
                    if bypass_roles:
                        bypass_mentions = ", ".join([f"<@&{role_id}>" for role_id in bypass_roles])
                        message = (
                            f"❌ You need the {role_name} role to enter this giveaway!\n"
                            f"*The following roles bypass this requirement: {bypass_mentions}*"
                        )
                    else:
                        message = f"❌ You need the {role_name} role to enter this giveaway!"
                    
                    await interaction.response.send_message(message, ephemeral=True)
                    return

            # Check if giveaway is still active
            if giveaway["status"] != "active":
                await interaction.response.send_message("This giveaway has ended!", ephemeral=True)
                return

            # Toggle user entry in the giveaway
            user_id = str(interaction.user.id)
            entries = set(giveaway.get('entries', []))
            
            if user_id in entries:
                # User wants to leave the giveaway
                entries.remove(user_id)
                await interaction.response.send_message("You have withdrawn from the giveaway!", ephemeral=True)
            else:
                # User wants to enter the giveaway
                entries.add(user_id)
                await interaction.response.send_message("You have entered the giveaway! Good luck! 🍀", ephemeral=True)

            # Update the giveaway with new entries
            await self.db.update_giveaway(self.giveaway_id, {'entries': list(entries)})

            # Update entry count in the embed
            try:
                channel = interaction.guild.get_channel(int(giveaway["channel_id"]))
                if not channel:
                    return
                    
                message = await channel.fetch_message(int(giveaway["message_id"]))

                embed = message.embeds[0]
                entry_count = len(entries)
                embed.set_field_at(
                    0,
                    name="Entries",
                    value=f"{entry_count} {('entry' if entry_count == 1 else 'entries')}",
                    inline=True
                )

                await message.edit(embed=embed)
            except Exception as e:
                logger.error(f"Error updating giveaway message: {e}")
                
        except Exception as e:
            logger.error(f"Error in enter_giveaway: {e}")
            try:
                await interaction.response.send_message("An error occurred while processing your entry. Please try again.", ephemeral=True)
            except:
                pass


class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_db()
        
        # Start giveaway checking task
        self.giveaway_task = self.bot.loop.create_task(self.check_giveaways())
        
        # Create necessary tables if they don't exist
        self.bot.loop.create_task(self.initialize_tables())

    def cog_unload(self):
        # Cancel the task when the cog is unloaded
        self.giveaway_task.cancel()

    async def initialize_tables(self):
        """Initialize database tables if they don't exist."""
        try:
            # This will be handled by the Supabase client
            pass
        except Exception as e:
            logger.error(f"Error initializing database tables: {e}")

    async def check_giveaways(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                # Get all active giveaways from Supabase
                result = self.db.client.table('giveaways') \
                    .select('*') \
                    .eq('status', 'active') \
                    .execute()
                
                now = datetime.utcnow()
                
                for giveaway in result.data:
                    try:
                        end_time = datetime.fromisoformat(giveaway["end_time"])
                        if now >= end_time:
                            await self.end_giveaway(str(giveaway['id']))
                    except Exception as e:
                        logger.error(f"Error processing giveaway {giveaway.get('id')}: {e}")
                        
            except Exception as e:
                logger.error(f"Error in check_giveaways: {e}")

            # Check every 30 seconds
            await asyncio.sleep(30)

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent views for active giveaways
        try:
            result = self.db.client.table('giveaways') \
                .select('id') \
                .eq('status', 'active') \
                .execute()
                
            for giveaway in result.data:
                self.bot.add_view(GiveawayView(str(giveaway['id'])))
                
            logger.info(f"Registered {len(result.data)} active giveaways")
            
        except Exception as e:
            logger.error(f"Error registering giveaway views: {e}")

    async def end_giveaway(self, giveaway_id):
        try:
            # Get the giveaway from Supabase
            giveaway = await self.db.get_giveaway(giveaway_id)
            if not giveaway:
                logger.error(f"Giveaway {giveaway_id} not found")
                return
                
            # Select winner(s)
            winners = []
            entries = giveaway.get('entries', [])
            winner_count = min(giveaway.get('winner_count', 1), len(entries))

            if entries and winner_count > 0:
                winners = random.sample(entries, winner_count)
            
            # Update the giveaway in Supabase
            await self.db.update_giveaway(giveaway_id, {
                'status': 'ended',
                'ended_at': datetime.utcnow().isoformat(),
                'winners': winners
            })

            # Send winner announcement
            channel = self.bot.get_channel(int(giveaway["channel_id"]))
            if not channel:
                logger.error(f"Channel {giveaway['channel_id']} not found")
                return

            try:
                message = await channel.fetch_message(int(giveaway["message_id"]))

                # Update the embed
                embed = message.embeds[0]
                embed.color = discord.Color.gold()
                embed.title = f"🎉 Giveaway Ended: {giveaway['prize']}"

                # Update or add the winners field
                if winners:
                    winners_text = "\n".join([f"<@{winner_id}>" for winner_id in winners])
                    
                    # Find if there's already a Winners field
                    winner_field_index = None
                    for i, field in enumerate(embed.fields):
                        if field.name == "Winners":
                            winner_field_index = i
                            break

                    winners_field = discord.EmbedField(
                        name=f"🎉 {'Winner' if len(winners) == 1 else 'Winners'}",
                        value=winners_text,
                        inline=False
                    )

                    if winner_field_index is not None:
                        embed.set_field_at(winner_field_index, 
                                        name=winners_field.name, 
                                        value=winners_field.value, 
                                        inline=winners_field.inline)
                    else:
                        embed.add_field(
                            name=winners_field.name,
                            value=winners_field.value,
                            inline=winners_field.inline
                        )
                
                # Update footer and timestamp
                embed.set_footer(text=f"Giveaway ID: {giveaway_id} • Ended at")
                embed.timestamp = datetime.utcnow()
                
                # Update the message with the new embed
                await message.edit(embed=embed, view=None)
                
                # Announce the winners
                if winners:
                    winners_mentions = " ".join([f"<@{winner_id}>" for winner_id in winners])
                    await channel.send(
                        f"🎉 Congratulations {winners_mentions}! "
                        f"You won the **{giveaway['prize']}**! 🎊"
                    )
                else:
                    await channel.send(
                        f"🎉 The giveaway for **{giveaway['prize']}** has ended! "
                        f"No one entered, so there are no winners. 😢"
                    )

                # Update the message
                await message.edit(embed=embed, view=None)

                # Send winner announcement
                if winners:
                    winners_mentions = " ".join([f"<@{winner_id}>" for winner_id in winners])
                    await channel.send(
                        f"🎉 Congratulations {winners_mentions}! You won the **{giveaway['prize']}**!\n"
                        f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
                    )
                else:
                    await channel.send(
                        f"😢 No one entered the giveaway for **{giveaway['prize']}**!\n"
                        f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
                    )
            except Exception as e:
                print(f"Error updating giveaway message: {e}")

        except Exception as e:
            print(f"Error ending giveaway: {e}")

    @app_commands.command(name="giveaway", description="Start a new giveaway")
    @app_commands.describe(
        prize="The prize for the giveaway",
        duration="Duration in minutes",
        winners="Number of winners (default: 1)",
        channel="Channel to host the giveaway (default: current channel)",
        required_role="Role required to enter (optional)",
        bypass_roles="Roles that bypass the requirement (optional)"
    )
    async def create_giveaway(
            self,
            interaction: discord.Interaction,
            prize: str,
            duration: int,
            winners: int = 1,
            channel: discord.TextChannel = None,
            required_role: discord.Role = None,
            bypass_roles: str = None
    ):
        # Check permissions
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to create giveaways!", ephemeral=True)
            return

        # Validate inputs
        if duration < 1:
            await interaction.response.send_message("Duration must be at least 1 minute!", ephemeral=True)
            return

        if winners < 1:
            await interaction.response.send_message("Number of winners must be at least 1!", ephemeral=True)
            return

        # Set target channel
        target_channel = channel or interaction.channel

        # Calculate end time
        end_time = datetime.now() + timedelta(minutes=duration)

        # Parse bypass roles if provided
        bypass_role_ids = []
        if bypass_roles:
            try:
                bypass_role_ids = [int(role_id.strip()) for role_id in bypass_roles.split(',')]
            except ValueError:
                await interaction.response.send_message("Invalid format for bypass_roles. Use comma-separated role IDs.", ephemeral=True)
                return

        # Create embed
        embed = discord.Embed(
            title=f"🎉 Giveaway: {prize}",
            description=f"React with the button below to enter!\nHosted by {interaction.user.mention}",
            color=discord.Color.blue()
        )
        
        # Add role requirement to description if specified
        if required_role:
            role_mention = f"<@&{required_role.id}>"
            bypass_mentions = ", ".join([f"<@&{role_id}>" for role_id in bypass_role_ids]) if bypass_role_ids else "None"
            embed.add_field(
                name="🎭 Role Requirements",
                value=f"• Required Role: {role_mention}\n• Bypass Roles: {bypass_mentions}",
                inline=False
            )

        embed.add_field(name="Entries", value="0 entries", inline=True)
        embed.add_field(name="Winners", value=str(winners), inline=True)
        embed.add_field(name="Ends At", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)

        embed.set_footer(text="Started at")
        embed.timestamp = datetime.now()

        # Defer response since this might take a moment
        await interaction.response.defer(ephemeral=True)

        # Load giveaways data
        giveaways = load_data('giveaways')

        # Generate new giveaway ID
        giveaway_id = str(len(giveaways) + 1)

        # Create view with enter button
        view = GiveawayView(giveaway_id)

        # Send giveaway message
        giveaway_message = await target_channel.send(embed=embed, view=view)

        # Store giveaway data
        giveaways[giveaway_id] = {
            "prize": prize,
            "channel_id": target_channel.id,
            "message_id": giveaway_message.id,
            "host_id": interaction.user.id,
            "winner_count": winners,
            "entries": [],
            "winners": [],
            "start_time": datetime.now().isoformat(),
            "end_time": end_time.isoformat(),
            "status": "active",
            "required_role": str(required_role.id) if required_role else None,
            "bypass_roles": bypass_role_ids
        }

        save_data('giveaways', giveaways)

        # Send confirmation
        await interaction.followup.send(
            f"Giveaway created in {target_channel.mention}!\n"
            f"It will end in {duration} minute{'s' if duration != 1 else ''}.",
            ephemeral=True
        )

    @app_commands.command(name="gend", description="End a giveaway early")
    @app_commands.describe(message_id="The message ID of the giveaway")
    async def end_giveaway_command(self, interaction, message_id: str):
        # Check permissions
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to end giveaways!", ephemeral=True)
            return

        # Find the giveaway
        giveaways = load_data('giveaways')
        giveaway_id = None

        for g_id, giveaway in giveaways.items():
            if str(giveaway["message_id"]) == message_id:
                giveaway_id = g_id
                break

        if not giveaway_id:
            await interaction.response.send_message("Giveaway not found! Make sure you entered the correct message ID.",
                                                    ephemeral=True)
            return

        # Check if already ended
        if giveaways[giveaway_id]["status"] != "active":
            await interaction.response.send_message("This giveaway has already ended!", ephemeral=True)
            return

        # End the giveaway
        await interaction.response.defer(ephemeral=True)
        await self.end_giveaway(giveaway_id)

        await interaction.followup.send("Giveaway ended successfully!", ephemeral=True)

    @app_commands.command(name="greroll", description="Reroll a giveaway winner")
    @app_commands.describe(
        message_id="The message ID of the giveaway",
        winner_count="Number of winners to reroll (default: 1)"
    )
    async def reroll_giveaway(self, interaction, message_id: str, winner_count: int = 1):
        # Check permissions
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to reroll giveaways!", ephemeral=True)
            return

        # Find the giveaway
        giveaways = load_data('giveaways')
        giveaway_id = None

        for g_id, giveaway in giveaways.items():
            if str(giveaway["message_id"]) == message_id:
                giveaway_id = g_id
                break

        if not giveaway_id:
            await interaction.response.send_message("Giveaway not found! Make sure you entered the correct message ID.",
                                                    ephemeral=True)
            return

        giveaway = giveaways[giveaway_id]

        # Check if the giveaway has ended
        if giveaway["status"] != "ended":
            await interaction.response.send_message("This giveaway hasn't ended yet!", ephemeral=True)
            return

        # Check if there are entries
        if not giveaway["entries"]:
            await interaction.response.send_message("This giveaway has no entries to reroll!", ephemeral=True)
            return

        # Reroll winners
        entries = giveaway["entries"]
        new_winner_count = min(winner_count, len(entries))

        if new_winner_count < 1:
            await interaction.response.send_message("Winner count must be at least 1!", ephemeral=True)
            return

        new_winners = random.sample(entries, new_winner_count)

        # Update giveaway data
        giveaway["winners"] = new_winners
        giveaway["rerolled_at"] = datetime.now().isoformat()
        giveaway["rerolled_by"] = interaction.user.id
        save_data('giveaways', giveaways)

        # Send announcement
        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel:
            winners_mentions = " ".join([f"<@{winner_id}>" for winner_id in new_winners])

            await channel.send(
                f"🎉 The giveaway for **{giveaway['prize']}** has been rerolled!\n"
                f"New winner{'s' if new_winner_count > 1 else ''}: {winners_mentions}\n"
                f"https://discord.com/channels/{interaction.guild.id}/{giveaway['channel_id']}/{giveaway['message_id']}"
            )

            await interaction.response.send_message("Giveaway rerolled successfully!", ephemeral=True)
        else:
            await interaction.response.send_message("Couldn't find the giveaway channel!", ephemeral=True)

    @app_commands.command(name="glist", description="List all active giveaways")
    async def list_giveaways(self, interaction):
        giveaways = load_data('giveaways')

        # Filter active giveaways
        active_giveaways = {g_id: g for g_id, g in giveaways.items() if g["status"] == "active"}

        if not active_giveaways:
            await interaction.response.send_message("There are no active giveaways!", ephemeral=True)
            return

        # Create embed
        embed = discord.Embed(
            title="Active Giveaways",
            description=f"There are {len(active_giveaways)} active giveaways.",
            color=discord.Color.blue()
        )

        for g_id, giveaway in active_giveaways.items():
            end_time = datetime.fromisoformat(giveaway["end_time"])
            channel = self.bot.get_channel(giveaway["channel_id"])
            channel_mention = channel.mention if channel else "Unknown Channel"

            embed.add_field(
                name=f"🎁 {giveaway['prize']}",
                value=(
                    f"**ID:** {g_id}\n"
                    f"**Channel:** {channel_mention}\n"
                    f"**Entries:** {len(giveaway['entries'])}\n"
                    f"**Winners:** {giveaway['winner_count']}\n"
                    f"**Ends:** <t:{int(end_time.timestamp())}:R>\n"
                    f"[Jump to Giveaway](https://discord.com/channels/{interaction.guild.id}/{giveaway['channel_id']}/{giveaway['message_id']})"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="gstats", description="Show giveaway statistics")
    async def giveaway_stats(self, interaction):
        # Check permissions
        if not is_admin(interaction):
            await interaction.response.send_message("You don't have permission to view giveaway statistics!",
                                                    ephemeral=True)
            return

        giveaways = load_data('giveaways')

        if not giveaways:
            await interaction.response.send_message("No giveaways have been created yet!", ephemeral=True)
            return

        # Calculate statistics
        total_giveaways = len(giveaways)
        active_giveaways = sum(1 for g in giveaways.values() if g["status"] == "active")
        ended_giveaways = total_giveaways - active_giveaways

        total_entries = sum(len(g["entries"]) for g in giveaways.values())
        total_winners = sum(len(g.get("winners", [])) for g in giveaways.values())

        # Find most popular giveaway
        most_popular = None
        most_entries = 0

        for g_id, giveaway in giveaways.items():
            entries = len(giveaway["entries"])
            if entries > most_entries:
                most_entries = entries
                most_popular = giveaway

        # Create embed
        embed = discord.Embed(
            title="Giveaway Statistics",
            color=discord.Color.blue()
        )

        embed.add_field(name="Total Giveaways", value=str(total_giveaways), inline=True)
        embed.add_field(name="Active Giveaways", value=str(active_giveaways), inline=True)
        embed.add_field(name="Ended Giveaways", value=str(ended_giveaways), inline=True)

        embed.add_field(name="Total Entries", value=str(total_entries), inline=True)
        embed.add_field(name="Total Winners", value=str(total_winners), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for spacing

        if most_popular:
            embed.add_field(
                name="Most Popular Giveaway",
                value=(
                    f"**Prize:** {most_popular['prize']}\n"
                    f"**Entries:** {most_entries}\n"
                    f"**Winners:** {most_popular['winner_count']}"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Giveaways(bot))