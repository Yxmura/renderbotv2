import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from supabase import create_client, Client
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class DatabaseManager:
    """Manages all database operations for the bot."""
    
    def __init__(self):
        self.client = supabase
        self._initialized = False
    
    async def initialize(self):
        """Initialize database tables if they don't exist."""
        if self._initialized:
            return
            
        try:
            # Create tables if they don't exist
            await self._create_tables()
            self._initialized = True
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    async def _create_tables(self):
        """Create necessary tables in Supabase."""
        # Note: In Supabase, tables are typically created via SQL migrations
        # This is a fallback method for basic table creation
        try:
            # Check if tables exist by trying to select from them
            self.client.table('tickets').select('id').limit(1).execute()
            self.client.table('polls').select('id').limit(1).execute()
            self.client.table('giveaways').select('id').limit(1).execute()
            self.client.table('config').select('id').limit(1).execute()
            logger.info("All tables exist")
        except Exception as e:
            logger.warning(f"Some tables may not exist: {e}")
            logger.info("Please create tables manually in Supabase dashboard or run SQL migrations")

# Global database manager instance
_db_manager = None

def get_db() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager

# Ticket operations
class TicketManager:
    """Manages ticket-related database operations."""
    
    def __init__(self):
        self.client = supabase
    
    async def create_ticket(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """Create a new ticket."""
        try:
            result = self.client.table('tickets').insert(ticket_data).execute()
            if result.data:
                return result.data[0]['ticket_id']
            return None
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return None
    
    async def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get a ticket by ID."""
        try:
            result = self.client.table('tickets').select('*').eq('ticket_id', ticket_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting ticket {ticket_id}: {e}")
            return None
    
    async def update_ticket(self, ticket_id: str, updates: Dict[str, Any]) -> bool:
        """Update a ticket."""
        try:
            self.client.table('tickets').update(updates).eq('ticket_id', ticket_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating ticket {ticket_id}: {e}")
            return False
    
    async def delete_ticket(self, ticket_id: str) -> bool:
        """Delete a ticket."""
        try:
            self.client.table('tickets').delete().eq('ticket_id', ticket_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting ticket {ticket_id}: {e}")
            return False
    
    async def get_tickets_by_guild(self, guild_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all tickets for a guild."""
        try:
            query = self.client.table('tickets').select('*').eq('guild_id', guild_id)
            if status:
                query = query.eq('status', status)
            result = query.execute()
            return result.data
        except Exception as e:
            logger.error(f"Error getting tickets for guild {guild_id}: {e}")
            return []
    
    async def get_ticket_counter(self, guild_id: str) -> int:
        """Get the ticket counter for a guild."""
        try:
            result = self.client.table('config').select('ticket_counter').eq('guild_id', guild_id).execute()
            if result.data:
                return result.data[0].get('ticket_counter', 0)
            return 0
        except Exception as e:
            logger.error(f"Error getting ticket counter for guild {guild_id}: {e}")
            return 0
    
    async def increment_ticket_counter(self, guild_id: str) -> int:
        """Increment the ticket counter for a guild."""
        try:
            # Get current counter
            current = await self.get_ticket_counter(guild_id)
            new_counter = current + 1
            
            # Update or insert counter
            result = self.client.table('config').upsert({
                'guild_id': guild_id,
                'ticket_counter': new_counter
            }).execute()
            
            return new_counter
        except Exception as e:
            logger.error(f"Error incrementing ticket counter for guild {guild_id}: {e}")
            return 0

# Poll operations
class PollManager:
    """Manages poll-related database operations."""
    
    def __init__(self):
        self.client = supabase
    
    async def create_poll(self, poll_data: Dict[str, Any]) -> Optional[str]:
        """Create a new poll."""
        try:
            result = self.client.table('polls').insert(poll_data).execute()
            if result.data:
                return result.data[0]['id']
            return None
        except Exception as e:
            logger.error(f"Error creating poll: {e}")
            return None
    
    async def get_poll(self, poll_id: str) -> Optional[Dict[str, Any]]:
        """Get a poll by ID."""
        try:
            result = self.client.table('polls').select('*').eq('id', poll_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting poll {poll_id}: {e}")
            return None
    
    async def update_poll(self, poll_id: str, updates: Dict[str, Any]) -> bool:
        """Update a poll."""
        try:
            self.client.table('polls').update(updates).eq('id', poll_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating poll {poll_id}: {e}")
            return False
    
    async def delete_poll(self, poll_id: str) -> bool:
        """Delete a poll."""
        try:
            self.client.table('polls').delete().eq('id', poll_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting poll {poll_id}: {e}")
            return False
    
    async def add_vote(self, poll_id: str, option_index: int, user_id: str) -> bool:
        """Add a vote to a poll."""
        try:
            # Get current poll
            poll = await self.get_poll(poll_id)
            if not poll:
                return False
            
            # Get current votes
            votes = poll.get('votes', {})
            option_key = str(option_index)
            
            # Remove user from all other options first
            for key in votes:
                if user_id in votes[key]:
                    votes[key].remove(user_id)
            
            # Add user to selected option
            if option_key not in votes:
                votes[option_key] = []
            if user_id not in votes[option_key]:
                votes[option_key].append(user_id)
            
            # Update poll
            return await self.update_poll(poll_id, {'votes': votes})
        except Exception as e:
            logger.error(f"Error adding vote to poll {poll_id}: {e}")
            return False
    
    async def get_active_polls(self) -> List[Dict[str, Any]]:
        """Get all active polls."""
        try:
            result = self.client.table('polls').select('*').eq('status', 'active').execute()
            return result.data
        except Exception as e:
            logger.error(f"Error getting active polls: {e}")
            return []
    
    async def close_poll(self, poll_id: str) -> bool:
        """Close a poll."""
        try:
            return await self.update_poll(poll_id, {'status': 'closed'})
        except Exception as e:
            logger.error(f"Error closing poll {poll_id}: {e}")
            return False

# Giveaway operations
class GiveawayManager:
    """Manages giveaway-related database operations."""
    
    def __init__(self):
        self.client = supabase
    
    async def create_giveaway(self, giveaway_data: Dict[str, Any]) -> Optional[str]:
        """Create a new giveaway."""
        try:
            result = self.client.table('giveaways').insert(giveaway_data).execute()
            if result.data:
                return result.data[0]['id']
            return None
        except Exception as e:
            logger.error(f"Error creating giveaway: {e}")
            return None
    
    async def get_giveaway(self, giveaway_id: str) -> Optional[Dict[str, Any]]:
        """Get a giveaway by ID."""
        try:
            result = self.client.table('giveaways').select('*').eq('id', giveaway_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting giveaway {giveaway_id}: {e}")
            return None
    
    async def update_giveaway(self, giveaway_id: str, updates: Dict[str, Any]) -> bool:
        """Update a giveaway."""
        try:
            self.client.table('giveaways').update(updates).eq('id', giveaway_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating giveaway {giveaway_id}: {e}")
            return False
    
    async def delete_giveaway(self, giveaway_id: str) -> bool:
        """Delete a giveaway."""
        try:
            self.client.table('giveaways').delete().eq('id', giveaway_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting giveaway {giveaway_id}: {e}")
            return False
    
    async def get_active_giveaways(self) -> List[Dict[str, Any]]:
        """Get all active giveaways."""
        try:
            result = self.client.table('giveaways').select('*').eq('status', 'active').execute()
            return result.data
        except Exception as e:
            logger.error(f"Error getting active giveaways: {e}")
            return []
    
    async def end_giveaway(self, giveaway_id: str) -> bool:
        """End a giveaway."""
        try:
            return await self.update_giveaway(giveaway_id, {'status': 'ended'})
        except Exception as e:
            logger.error(f"Error ending giveaway {giveaway_id}: {e}")
            return False

# Config operations
class ConfigManager:
    """Manages configuration-related database operations."""
    
    def __init__(self):
        self.client = supabase
    
    async def get_config(self, guild_id: str) -> Dict[str, Any]:
        """Get configuration for a guild."""
        try:
            result = self.client.table('config').select('*').eq('guild_id', guild_id).execute()
            if result.data:
                return result.data[0]
            return {}
        except Exception as e:
            logger.error(f"Error getting config for guild {guild_id}: {e}")
            return {}
    
    async def update_config(self, guild_id: str, updates: Dict[str, Any]) -> bool:
        """Update configuration for a guild."""
        try:
            updates['guild_id'] = guild_id
            self.client.table('config').upsert(updates).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating config for guild {guild_id}: {e}")
            return False
    
    async def get_all_configs(self) -> List[Dict[str, Any]]:
        """Get all configurations."""
        try:
            result = self.client.table('config').select('*').execute()
            return result.data
        except Exception as e:
            logger.error(f"Error getting all configs: {e}")
            return []

# Enhanced DatabaseManager with all managers
class EnhancedDatabaseManager(DatabaseManager):
    """Enhanced database manager with all specific managers."""
    
    def __init__(self):
        super().__init__()
        self.tickets = TicketManager()
        self.polls = PollManager()
        self.giveaways = GiveawayManager()
        self.config = ConfigManager()
    
    # Convenience methods for backward compatibility
    async def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        return await self.tickets.get_ticket(ticket_id)
    
    async def get_poll(self, poll_id: str) -> Optional[Dict[str, Any]]:
        return await self.polls.get_poll(poll_id)
    
    async def get_giveaway(self, giveaway_id: str) -> Optional[Dict[str, Any]]:
        return await self.giveaways.get_giveaway(giveaway_id)
    
    async def add_vote(self, poll_id: str, option_index: int, user_id: str) -> bool:
        return await self.polls.add_vote(poll_id, option_index, user_id)
    
    async def update_giveaway(self, giveaway_id: str, updates: Dict[str, Any]) -> bool:
        return await self.giveaways.update_giveaway(giveaway_id, updates)

# Update the global instance
_db_manager = EnhancedDatabaseManager()

# Legacy functions for backward compatibility
def load_data(file: str) -> Dict[str, Any]:
    """Legacy function to load data from JSON files."""
    logger.warning(f"load_data called for {file} - this should be replaced with Supabase calls")
    try:
        with open(f'data/{file}.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(file: str, data: Dict[str, Any]) -> None:
    """Legacy function to save data to JSON files."""
    logger.warning(f"save_data called for {file} - this should be replaced with Supabase calls")
    try:
        with open(f'data/{file}.json', 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving data to {file}: {e}")

# Migration helper
async def migrate_json_to_supabase():
    """Migrate existing JSON data to Supabase."""
    try:
        db = get_db()
        await db.initialize()
        
        # Migrate tickets
        try:
            tickets_data = load_data('tickets')
            if tickets_data.get('tickets'):
                for ticket_id, ticket_data in tickets_data['tickets'].items():
                    if isinstance(ticket_data, dict):
                        await db.tickets.create_ticket(ticket_data)
            logger.info("Migrated tickets data")
        except Exception as e:
            logger.error(f"Error migrating tickets: {e}")
        
        # Migrate polls
        try:
            polls_data = load_data('polls')
            if polls_data:
                for poll_id, poll_data in polls_data.items():
                    if isinstance(poll_data, dict):
                        await db.polls.create_poll(poll_data)
            logger.info("Migrated polls data")
        except Exception as e:
            logger.error(f"Error migrating polls: {e}")
        
        # Migrate giveaways
        try:
            giveaways_data = load_data('giveaways')
            if giveaways_data:
                for giveaway_id, giveaway_data in giveaways_data.items():
                    if isinstance(giveaway_data, dict):
                        await db.giveaways.create_giveaway(giveaway_data)
            logger.info("Migrated giveaways data")
        except Exception as e:
            logger.error(f"Error migrating giveaways: {e}")
        
        # Migrate config
        try:
            config_data = load_data('config')
            if config_data:
                # Assuming config is global, we'll use a default guild_id
                await db.config.update_config('global', config_data)
            logger.info("Migrated config data")
        except Exception as e:
            logger.error(f"Error migrating config: {e}")
            
    except Exception as e:
        logger.error(f"Error during migration: {e}") 