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
            
            return "Your branch is behind" in result.stdout
        except:
            return False

    def pull_changes(self):
        """Pull changes while preserving data files"""
        try:
            # Stash data files to protect them
            stash_result = subprocess.run(
                ["git", "stash", "push", "-m", "Auto-stash before pull", "data/"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            
            # Pull the latest changes
            pull_result = subprocess.run(
                ["git", "pull", "--no-rebase"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Restore stashed data files
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            
            return True, pull_result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr

    def run_once(self):
        """Run a single git pull check"""
        if not self.config.get("enabled", True):
            return False

        if not self.is_git_repo():
            logging.warning("Not in a git repository")
            return False

        if not self.has_remote_changes():
            logging.info("No remote changes available")
            return False

        success, output = self.pull_changes()
        
        if success:
            logging.info("Repository updated successfully")
            return True
        
        logging.error(f"Failed to pull changes: {output}")
        return False

    async def run_periodically(self):
        """Run periodic git pulls"""
        while True:
            if self.config.get("enabled", True):
                self.run_once()
            await asyncio.sleep(self.config.get("interval_minutes", 30) * 60)

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
    else:
        print("Usage: python auto_git_pull.py [once|config]")