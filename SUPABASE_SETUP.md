# Supabase Database Migration Guide

This guide will help you migrate your Discord bot from JSON file storage to Supabase database storage.

## Prerequisites

1. A Supabase account (free tier available at https://supabase.com)
2. Your Discord bot's `.env` file with the required environment variables
3. Python 3.8+ with the required dependencies

## Step 1: Create a Supabase Project

1. Go to [Supabase](https://supabase.com) and create a new account or sign in
2. Create a new project
3. Wait for the project to be set up (this may take a few minutes)

## Step 2: Get Your Supabase Credentials

1. In your Supabase project dashboard, go to **Settings** → **API**
2. Copy the following values:
   - **Project URL** (looks like: `https://your-project-id.supabase.co`)
   - **anon public** key (starts with `eyJ...`)
   - **service_role** key (starts with `eyJ...`)

## Step 3: Update Your Environment Variables

Add the following to your `.env` file:

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-public-key
SUPABASE_SERVICE_KEY=your-service-role-key
```

## Step 4: Set Up Database Tables

1. In your Supabase dashboard, go to **SQL Editor**
2. Copy the entire contents of `supabase_migration.sql`
3. Paste it into the SQL editor
4. Click **Run** to execute the script

This will create all the necessary tables:
- `tickets` - For ticket system data
- `polls` - For poll system data
- `giveaways` - For giveaway system data
- `config` - For bot configuration
- `reminders` - For reminder system data

## Step 5: Run the Setup Script

Run the setup script to test your connection and optionally migrate existing data:

```bash
python setup_supabase.py
```

This script will:
- Check if your environment variables are set correctly
- Test the Supabase connection
- Offer to migrate existing JSON data to Supabase
- Verify the migration was successful

## Step 6: Start Your Bot

Once the setup is complete, start your bot normally:

```bash
python bot.py
```

Your bot will now use Supabase instead of JSON files for all data storage!

## Features Now Using Supabase

### ✅ Tickets System
- Ticket creation, management, and tracking
- Ticket metadata and status
- Persistent ticket data across bot restarts
- Multi-guild support

### ✅ Polls System
- Poll creation and voting
- Real-time vote tracking
- Poll expiration and results
- Persistent poll data

### ✅ Giveaways System
- Giveaway creation and management
- Entry tracking and winner selection
- Role requirements and bypass roles
- Persistent giveaway data

### ✅ Reminders System
- User reminder creation and management
- Automatic reminder delivery
- Persistent reminder data

### ✅ Configuration System
- Guild-specific bot settings
- Admin roles and permissions
- Ticket categories and settings
- Persistent configuration

## Benefits of Supabase Migration

1. **Data Persistence**: Data survives bot restarts and redeployments
2. **Multi-Guild Support**: Each guild's data is properly separated
3. **Better Performance**: Faster data access and updates
4. **Scalability**: Can handle much more data than JSON files
5. **Real-time Updates**: Changes are immediately reflected
6. **Backup & Recovery**: Automatic backups and data recovery
7. **Security**: Better data security with proper authentication

## Troubleshooting

### Connection Issues
- Verify your Supabase URL and keys are correct
- Check that your Supabase project is active
- Ensure your IP is not blocked by Supabase

### Migration Issues
- Make sure all tables were created successfully
- Check the bot logs for specific error messages
- Verify your environment variables are set correctly

### Data Issues
- Check that the migration script ran successfully
- Verify data exists in your Supabase tables
- Check the bot logs for database operation errors

## Database Schema

### Tickets Table
```sql
- id: BIGSERIAL PRIMARY KEY
- ticket_id: TEXT UNIQUE NOT NULL
- user_id: BIGINT NOT NULL
- category: TEXT NOT NULL
- status: TEXT DEFAULT 'open'
- priority: TEXT DEFAULT 'normal'
- created_at: TIMESTAMP WITH TIME ZONE
- claimed_by: BIGINT
- last_activity: TIMESTAMP WITH TIME ZONE
- closed_at: TIMESTAMP WITH TIME ZONE
- closed_by: BIGINT
- close_reason: TEXT
- close_type: TEXT
- channel_id: BIGINT NOT NULL
- guild_id: BIGINT NOT NULL
- metadata: JSONB
```

### Polls Table
```sql
- id: BIGSERIAL PRIMARY KEY
- poll_id: TEXT UNIQUE NOT NULL
- question: TEXT NOT NULL
- options: JSONB NOT NULL
- votes: JSONB DEFAULT '{}'
- status: TEXT DEFAULT 'active'
- created_at: TIMESTAMP WITH TIME ZONE
- end_time: TIMESTAMP WITH TIME ZONE
- created_by: BIGINT NOT NULL
- channel_id: BIGINT NOT NULL
- message_id: BIGINT NOT NULL
- guild_id: BIGINT NOT NULL
- settings: JSONB
```

### Giveaways Table
```sql
- id: BIGSERIAL PRIMARY KEY
- giveaway_id: TEXT UNIQUE NOT NULL
- prize: TEXT NOT NULL
- description: TEXT
- end_time: TIMESTAMP WITH TIME ZONE NOT NULL
- winner_count: INTEGER DEFAULT 1
- entries: JSONB DEFAULT '[]'
- winners: JSONB DEFAULT '[]'
- status: TEXT DEFAULT 'active'
- created_at: TIMESTAMP WITH TIME ZONE
- created_by: BIGINT NOT NULL
- channel_id: BIGINT NOT NULL
- message_id: BIGINT NOT NULL
- guild_id: BIGINT NOT NULL
- required_role: BIGINT
- bypass_roles: JSONB DEFAULT '[]'
- settings: JSONB
```

### Config Table
```sql
- id: BIGSERIAL PRIMARY KEY
- guild_id: BIGINT UNIQUE NOT NULL
- ticket_categories: JSONB
- admin_roles: JSONB DEFAULT '[]'
- welcome_channel: BIGINT
- goodbye_channel: BIGINT
- auto_roles: JSONB DEFAULT '[]'
- ticket_counter: INTEGER DEFAULT 0
- settings: JSONB
- created_at: TIMESTAMP WITH TIME ZONE
- updated_at: TIMESTAMP WITH TIME ZONE
```

### Reminders Table
```sql
- id: BIGSERIAL PRIMARY KEY
- reminder_id: TEXT UNIQUE NOT NULL
- user_id: BIGINT NOT NULL
- guild_id: BIGINT NOT NULL
- channel_id: BIGINT
- message: TEXT NOT NULL
- reminder_time: TIMESTAMP WITH TIME ZONE NOT NULL
- created_at: TIMESTAMP WITH TIME ZONE
- status: TEXT DEFAULT 'pending'
- message_id: BIGINT
```

## Support

If you encounter any issues during the migration:

1. Check the bot logs for error messages
2. Verify your Supabase setup is correct
3. Ensure all environment variables are set
4. Check that the database tables were created successfully

The bot will automatically fall back to JSON files if Supabase is not available, ensuring backward compatibility. 