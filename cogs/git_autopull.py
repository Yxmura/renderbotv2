import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class GitAutoPullCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.repo_path = Path(".").resolve()
        self.data_dir = self.repo_path / "data"
        self.config_file = self.repo_path / "data" / "git_config.json"
        self.config = self.load_config()
        self.auto_pull_task = None

    def load_config(self):
        """Load git auto-pull configuration"""
        default_config = {
            "enabled": True,
            "interval_minutes": 30,
            "exclude_patterns": ["data/*.json", "data/*", "*.log"],
            "branches": ["main", "master"],
            "notify_channel": None,
            "notify_on_update": True
        }
        
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    return {**default_config, **loaded}
        except:
            pass
        
        return default_config

    def save_config(self):
        """Save configuration to file"""
        try:
            self.config_file.parent.mkdir(exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    def is_git_repo(self):
        """Check if current directory is a git repository"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                check=True
            )
            return True
        except:
            return False

    def get_current_branch(self):
        """Get current git branch"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except:
            return None

    def has_remote_changes(self):
        """Check if remote has new changes"""
        try:
            # Fetch latest
            subprocess.run(
                ["git", "fetch", "origin"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Check if behind
            result = subprocess.run(
                ["git", "status", "-uno"],
                capture_output=True,
                text=True,
                check=True
            )
            
            return "Your branch is behind" in result.stdout
        except:
            return False

    def pull_changes(self):
        """Pull changes while preserving data files"""
        try:
            # Use git stash for data files
            stash_result = subprocess.run(
                ["git", "stash", "push", "-m", "Auto-stash before pull", "data/"],
                capture_output=True,
                text=True
            )
            
            # Pull changes
            pull_result = subprocess.run(
                ["git", "pull", "--no-rebase"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Restore stashed data
            subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
                text=True
            )
            
            return True, pull_result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr

    async def check_and_pull(self):
        """Check for updates and pull if available"""
        if not self.config.get("enabled", True):
            return False

        if not self.is_git_repo():
            logging.warning("Not in a git repository")
            return False

        if not self.has_remote_changes():
            return False

        success, output = self.pull_changes()
        
        if success:
            logging.info("Repository updated successfully")
            await self.notify_update(output)
            return True
        
        return False

    async def notify_update(self, output):
        """Send notification when repository is updated"""
        if not self.config.get("notify_on_update", True):
            return

        try:
            channel_id = self.config.get("notify_channel")
            if channel_id:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    embed = discord.Embed(
                        title="🔄 Repository Updated",
                        description="The bot repository has been automatically updated with the latest changes.",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                    
                    if len(output) > 1000:
                        output = output[:1000] + "..."
                    
                    embed.add_field(name="Changes", value=f"```{output}```", inline=False)
                    embed.set_footer(text="Auto-pull completed")
                    
                    await channel.send(embed=embed)
        except Exception as e:
            logging.error(f"Failed to send notification: {e}")

    @tasks.loop(minutes=30)
    async def auto_pull_task(self):
        """Periodic auto-pull task"""
        await self.check_and_pull()

    @commands.Cog.listener()
    async def on_ready(self):
        """Start auto-pull when bot is ready"""
        if self.config.get("enabled", True):
            self.auto_pull_task.start()
            logging.info("Auto-pull task started")

    def cog_unload(self):
        """Stop auto-pull task when cog is unloaded"""
        if self.auto_pull_task:
            self.auto_pull_task.cancel()

    @app_commands.command(name="gitpull", description="Manually trigger git pull")
    @app_commands.checks.has_permissions(administrator=True)
    async def manual_pull(self, interaction: discord.Interaction):
        """Manually trigger a git pull"""
        await interaction.response.defer()
        
        if not self.is_git_repo():
            await interaction.followup.send("❌ Not in a git repository!", ephemeral=True)
            return

        success, output = self.pull_changes()
        
        if success:
            embed = discord.Embed(
                title="✅ Repository Updated",
                description="Successfully pulled latest changes.",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Update Failed",
                description=f"Failed to pull changes:\n```{output}```",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="autopull", description="Configure auto-git-pull settings")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        enabled="Enable/disable auto-pull",
        interval="Check interval in minutes (5-1440)",
        notify_channel="Channel for update notifications",
        notify="Send notifications when updates occur"
    )
    async def configure_autopull(
        self,
        interaction: discord.Interaction,
        enabled: bool = None,
        interval: int = None,
        notify_channel: discord.TextChannel = None,
        notify: bool = None
    ):
        """Configure auto-pull settings"""
        
        if enabled is not None:
            self.config["enabled"] = enabled
        if interval is not None:
            self.config["interval_minutes"] = max(5, min(1440, interval))
        if notify_channel is not None:
            self.config["notify_channel"] = notify_channel.id
        if notify is not None:
            self.config["notify_on_update"] = notify
            
        self.save_config()
        
        # Restart task if interval changed
        if interval is not None and self.auto_pull_task:
            self.auto_pull_task.cancel()
            self.auto_pull_task.change_interval(minutes=self.config["interval_minutes"])
            self.auto_pull_task.start()
        
        embed = discord.Embed(
            title="⚙️ Auto-Pull Configuration",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Status", value="🟢 Enabled" if self.config["enabled"] else "🔴 Disabled", inline=True)
        embed.add_field(name="Interval", value=f"{self.config['interval_minutes']} minutes", inline=True)
        embed.add_field(name="Notifications", value="🟢 On" if self.config["notify_on_update"] else "🔴 Off", inline=True)
        
        if self.config.get("notify_channel"):
            channel = self.bot.get_channel(self.config["notify_channel"])
            if channel:
                embed.add_field(name="Notify Channel", value=channel.mention, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gitstatus", description="Check git repository status")
    @app_commands.checks.has_permissions(administrator=True)
    async def git_status(self, interaction: discord.Interaction):
        """Check current git repository status"""
        await interaction.response.defer()
        
        if not self.is_git_repo():
            await interaction.followup.send("❌ Not in a git repository!", ephemeral=True)
            return

        try:
            # Get current branch
            branch = self.get_current_branch()
            
            # Get status
            status_result = subprocess.run(
                ["git", "status", "-uno"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Get last commit info
            log_result = subprocess.run(
                ["git", "log", "-1", "--oneline"],
                capture_output=True,
                text=True,
                check=True
            )
            
            embed = discord.Embed(
                title="📊 Git Repository Status",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Branch", value=f"`{branch}`", inline=True)
            embed.add_field(name="Last Commit", value=f"`{log_result.stdout.strip()}`", inline=False)
            
            status_text = status_result.stdout
            if "Your branch is up to date" in status_text:
                embed.add_field(name="Status", value="✅ Up to date", inline=True)
            elif "Your branch is behind" in status_text:
                embed.add_field(name="Status", value="⚠️ Behind remote", inline=True)
            else:
                embed.add_field(name="Status", value="ℹ️ Check logs", inline=True)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error checking status: {str(e)}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(GitAutoPullCog(bot))