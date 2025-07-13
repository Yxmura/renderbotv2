#!/usr/bin/env python3
"""
Supabase Setup and Migration Script
This script helps set up Supabase for the Discord bot and migrate existing JSON data.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from supabase_client import get_db, migrate_json_to_supabase

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_environment():
    """Check if all required environment variables are set."""
    required_vars = ['SUPABASE_URL', 'SUPABASE_KEY', 'SUPABASE_SERVICE_KEY']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please add these to your .env file:")
        for var in missing_vars:
            logger.error(f"  {var}=your_value_here")
        return False
    
    logger.info("All required environment variables are set")
    return True

def check_json_files():
    """Check if JSON files exist and have data."""
    json_files = ['tickets.json', 'polls.json', 'giveaways.json', 'config.json']
    existing_files = []
    
    for file in json_files:
        filepath = f'data/{file}'
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if data:  # Check if file has content
                        existing_files.append(file)
                        logger.info(f"Found data in {file}")
            except Exception as e:
                logger.warning(f"Error reading {file}: {e}")
    
    return existing_files

async def test_supabase_connection():
    """Test the Supabase connection."""
    try:
        db = get_db()
        await db.initialize()
        logger.info("✅ Supabase connection successful")
        return True
    except Exception as e:
        logger.error(f"❌ Supabase connection failed: {e}")
        return False

async def migrate_data():
    """Migrate existing JSON data to Supabase."""
    try:
        logger.info("Starting data migration...")
        await migrate_json_to_supabase()
        logger.info("✅ Data migration completed successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Data migration failed: {e}")
        return False

async def verify_migration():
    """Verify that data was migrated correctly."""
    try:
        db = get_db()
        
        # Check tickets
        tickets = await db.tickets.get_tickets_by_guild('0')  # Check global tickets
        logger.info(f"Found {len(tickets)} tickets in database")
        
        # Check polls
        polls = await db.polls.get_active_polls()
        logger.info(f"Found {len(polls)} active polls in database")
        
        # Check giveaways
        giveaways = await db.giveaways.get_active_giveaways()
        logger.info(f"Found {len(giveaways)} active giveaways in database")
        
        # Check config
        configs = await db.config.get_all_configs()
        logger.info(f"Found {len(configs)} config entries in database")
        
        return True
    except Exception as e:
        logger.error(f"❌ Migration verification failed: {e}")
        return False

def print_setup_instructions():
    """Print setup instructions."""
    print("\n" + "="*60)
    print("SUPABASE SETUP INSTRUCTIONS")
    print("="*60)
    print("\n1. Create a Supabase project at https://supabase.com")
    print("2. Get your project URL and API keys from the project settings")
    print("3. Add the following to your .env file:")
    print("   SUPABASE_URL=your_project_url")
    print("   SUPABASE_KEY=your_anon_key")
    print("   SUPABASE_SERVICE_KEY=your_service_role_key")
    print("\n4. Run the SQL migration script in your Supabase SQL editor:")
    print("   - Copy the contents of supabase_migration.sql")
    print("   - Paste it in your Supabase SQL editor")
    print("   - Execute the script")
    print("\n5. Run this setup script again to test the connection and migrate data")
    print("\n6. Start your bot - it will now use Supabase instead of JSON files!")
    print("="*60)

async def main():
    """Main setup function."""
    print("Discord Bot Supabase Setup")
    print("="*40)
    
    # Check environment variables
    if not check_environment():
        print_setup_instructions()
        return
    
    # Check for existing JSON data
    existing_files = check_json_files()
    if existing_files:
        logger.info(f"Found existing data in: {', '.join(existing_files)}")
    else:
        logger.info("No existing JSON data found")
    
    # Test Supabase connection
    if not await test_supabase_connection():
        print_setup_instructions()
        return
    
    # Migrate data if JSON files exist
    if existing_files:
        migrate_choice = input("\nDo you want to migrate existing JSON data to Supabase? (y/n): ").lower().strip()
        if migrate_choice in ['y', 'yes']:
            if await migrate_data():
                await verify_migration()
            else:
                logger.error("Migration failed. Please check your Supabase setup.")
                return
        else:
            logger.info("Skipping data migration")
    
    # Final verification
    if await verify_migration():
        print("\n✅ Setup completed successfully!")
        print("Your bot is now configured to use Supabase.")
        print("You can start your bot with: python bot.py")
    else:
        print("\n❌ Setup verification failed.")
        print("Please check your Supabase configuration and try again.")

if __name__ == "__main__":
    asyncio.run(main()) 