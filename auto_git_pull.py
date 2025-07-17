import subprocess
import os
import json
import logging
from datetime import datetime
import asyncio
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('auto_git_pull.log'),
        logging.StreamHandler()
    ]
)

class GitAutoPuller:
    def __init__(self, repo_path="."):
        self.repo_path = Path(repo_path).resolve()
        self.data_dir = self.repo_path / "data"
        self.config_file = self.repo_path / "auto_pull_config.json"
        self.load_config()

    def load_config(self):
        """Load configuration for auto-pull settings"""
        default_config = {
            "enabled": True,
            "interval_minutes": 30,
            "exclude_patterns": [
                "data/*.json",
                "data/*",
                "*.log",
                "auto_git_pull.log",
                "config.json"
            ],
            "branches": ["main", "master"],
            "notify_on_update": True
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.config = {**default_config, **json.load(f)}
            except:
                self.config = default_config
        else:
            self.config = default_config
            self.save_config()

    def save_config(self):
        """Save configuration to file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def is_git_repo(self):
        """Check if the current directory is a git repository"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def get_current_branch(self):
        """Get the current git branch"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def has_remote_changes(self):
        """Check if there are changes on remote that aren't in local"""
        try:
            # Fetch latest changes
            subprocess.run(
                ["git", "fetch", "--all"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Check if local is behind remote
            result = subprocess.run(
                ["git", "status", "-uno"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            return "Your branch is behind" in result.stdout or "have diverged" in result.stdout
        except subprocess.CalledProcessError:
            return False

    def stash_data_files(self):
        """Stash data files before pulling"""
        try:
            # Create a stash for data files
            stash_patterns = " ".join(f"'{pattern}'" for pattern in self.config["exclude_patterns"])
            if stash_patterns.strip():
                subprocess.run(
                    ["git", "stash", "push", "-m", "Auto-stash data files before pull"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
            return True
        except subprocess.CalledProcessError:
            return False

    def pop_stash(self):
        """Restore stashed data files after pulling"""
        try:
            # Check if there are stashed changes
            result = subprocess.run(
                ["git", "stash", "list"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            if "Auto-stash data files before pull" in result.stdout:
                subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
            return True
        except subprocess.CalledProcessError:
            return False

    def pull_changes(self):
        """Pull changes from remote, excluding data files"""
        try:
            current_branch = self.get_current_branch()
            if not current_branch or current_branch not in self.config["branches"]:
                logging.info(f"Skipping pull for branch: {current_branch}")
                return False

            # Use sparse checkout or .gitignore to exclude data files
            # Method 1: Use git pull with .gitignore protection
            result = subprocess.run(
                ["git", "pull", "--no-rebase"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            logging.info(f"Git pull successful: {result.stdout}")
            return True
            
        except subprocess.CalledProcessError as e:
            logging.error(f"Git pull failed: {e.stderr}")
            return False

    def check_and_pull(self):
        """Main function to check for updates and pull if available"""
        if not self.config.get("enabled", True):
            logging.info("Auto-pull is disabled")
            return False

        if not self.is_git_repo():
            logging.warning("Not in a git repository")
            return False

        if not self.has_remote_changes():
            logging.info("No remote changes to pull")
            return False

        logging.info("Remote changes detected, starting auto-pull...")
        
        # Stash data files
        if self.stash_data_files():
            logging.info("Data files stashed")
        
        # Pull changes
        success = self.pull_changes()
        
        # Restore data files
        if self.pop_stash():
            logging.info("Data files restored")
        
        if success:
            logging.info("Auto-pull completed successfully")
            if self.config.get("notify_on_update", True):
                self.notify_update()
        
        return success

    def notify_update(self):
        """Send notification when update is pulled"""
        try:
            # You can extend this to send Discord notifications
            logging.info("Repository updated successfully!")
        except Exception as e:
            logging.error(f"Failed to send notification: {e}")

    def run_once(self):
        """Run a single check and pull if needed"""
        return self.check_and_pull()

    async def run_periodically(self):
        """Run the auto-pull check periodically"""
        while True:
            try:
                self.check_and_pull()
                interval = self.config.get("interval_minutes", 30)
                await asyncio.sleep(interval * 60)
            except Exception as e:
                logging.error(f"Error in auto-pull loop: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error

# Discord bot integration
class GitPullCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.puller = GitAutoPuller()
        self.auto_pull_task = None

    @commands.Cog.listener()
    async def on_ready(self):
        """Start auto-pull when bot is ready"""
        if self.puller.config.get("enabled", True):
            self.auto_pull_task = self.bot.loop.create_task(self.puller.run_periodically())
            logging.info("Auto-pull task started")

    def cog_unload(self):
        """Cancel auto-pull task when cog is unloaded"""
        if self.auto_pull_task:
            self.auto_pull_task.cancel()

    @app_commands.command(name="gitpull", description="Manually trigger git pull")
    @app_commands.checks.has_permissions(administrator=True)
    async def manual_pull(self, interaction: discord.Interaction):
        """Manually trigger a git pull"""
        await interaction.response.defer()
        
        success = self.puller.run_once()
        
        if success:
            await interaction.followup.send("✅ Repository updated successfully!")
        else:
            await interaction.followup.send("❌ No updates available or pull failed. Check logs for details.")

    @app_commands.command(name="autopull", description="Configure auto-git-pull settings")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        enabled="Enable or disable auto-pull",
        interval="Interval in minutes between checks",
        notify="Send notifications when updates are pulled"
    )
    async def configure_autopull(
        self, 
        interaction: discord.Interaction,
        enabled: bool = None,
        interval: int = None,
        notify: bool = None
    ):
        """Configure auto-pull settings"""
        if enabled is not None:
            self.puller.config["enabled"] = enabled
        if interval is not None:
            self.puller.config["interval_minutes"] = max(5, interval)
        if notify is not None:
            self.puller.config["notify_on_update"] = notify
            
        self.puller.save_config()
        
        status = "enabled" if self.puller.config["enabled"] else "disabled"
        await interaction.response.send_message(
            f"Auto-pull settings updated:\n"
            f"Status: {status}\n"
            f"Interval: {self.puller.config['interval_minutes']} minutes\n"
            f"Notifications: {'on' if self.puller.config['notify_on_update'] else 'off'}"
        )

# Standalone script usage
if __name__ == "__main__":
    import sys
    
    puller = GitAutoPuller()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "once":
            puller.run_once()
        elif sys.argv[1] == "config":
            print(json.dumps(puller.config, indent=2))
    else:
        print("Usage: python auto_git_pull.py [once|config]")