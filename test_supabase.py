#!/usr/bin/env python3
"""
Test script for Supabase client functionality
"""

import os
import asyncio
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_supabase():
    """Test Supabase functionality."""
    try:
        # Check environment variables
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        supabase_service_key = os.getenv('SUPABASE_SERVICE_KEY')
        
        print("Environment Variables Check:")
        print(f"SUPABASE_URL: {'✅ Set' if supabase_url else '❌ Not set'}")
        print(f"SUPABASE_KEY: {'✅ Set' if supabase_key else '❌ Not set'}")
        print(f"SUPABASE_SERVICE_KEY: {'✅ Set' if supabase_service_key else '❌ Not set'}")
        
        if not all([supabase_url, supabase_key, supabase_service_key]):
            print("\n❌ Missing environment variables!")
            print("Please add the following to your .env file:")
            print("SUPABASE_URL=your_project_url")
            print("SUPABASE_KEY=your_anon_key")
            print("SUPABASE_SERVICE_KEY=your_service_role_key")
            return False
        
        # Test Supabase client import
        try:
            from supabase_client import get_db
            print("\n✅ Supabase client imported successfully")
        except ImportError as e:
            print(f"\n❌ Failed to import Supabase client: {e}")
            return False
        
        # Test database initialization
        try:
            db = get_db()
            await db.initialize()
            print("✅ Database initialized successfully")
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            return False
        
        # Test basic operations
        try:
            # Test config operations
            config = await db.config.get_config('test_guild')
            print("✅ Config operations working")
            
            # Test ticket operations
            tickets = await db.tickets.get_tickets_by_guild('test_guild')
            print("✅ Ticket operations working")
            
            # Test poll operations
            polls = await db.polls.get_active_polls()
            print("✅ Poll operations working")
            
            # Test giveaway operations
            giveaways = await db.giveaways.get_active_giveaways()
            print("✅ Giveaway operations working")
            
        except Exception as e:
            print(f"❌ Basic operations test failed: {e}")
            return False
        
        print("\n🎉 All tests passed! Supabase is working correctly.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return False

if __name__ == "__main__":
    print("Supabase Client Test")
    print("=" * 30)
    
    success = asyncio.run(test_supabase())
    
    if success:
        print("\n✅ Your Supabase setup is ready!")
        print("You can now start your bot with: python bot.py")
    else:
        print("\n❌ Setup incomplete. Please check the errors above.") 