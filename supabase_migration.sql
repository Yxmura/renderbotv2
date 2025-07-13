-- Supabase Migration Script for Discord Bot
-- Run this in your Supabase SQL editor to create the necessary tables

-- Enable Row Level Security (RLS)
-- Note: You may want to disable RLS for bot operations or create appropriate policies

-- Create tickets table
CREATE TABLE IF NOT EXISTS tickets (
    id BIGSERIAL PRIMARY KEY,
    ticket_id TEXT UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    category TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    priority TEXT DEFAULT 'normal',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    claimed_by BIGINT,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by BIGINT,
    close_reason TEXT,
    close_type TEXT,
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create polls table
CREATE TABLE IF NOT EXISTS polls (
    id BIGSERIAL PRIMARY KEY,
    poll_id TEXT UNIQUE NOT NULL,
    question TEXT NOT NULL,
    options JSONB NOT NULL,
    votes JSONB DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    end_time TIMESTAMP WITH TIME ZONE,
    created_by BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    settings JSONB DEFAULT '{}'::jsonb
);

-- Create giveaways table
CREATE TABLE IF NOT EXISTS giveaways (
    id BIGSERIAL PRIMARY KEY,
    giveaway_id TEXT UNIQUE NOT NULL,
    prize TEXT NOT NULL,
    description TEXT,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    winner_count INTEGER DEFAULT 1,
    entries JSONB DEFAULT '[]'::jsonb,
    winners JSONB DEFAULT '[]'::jsonb,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    required_role BIGINT,
    bypass_roles JSONB DEFAULT '[]'::jsonb,
    settings JSONB DEFAULT '{}'::jsonb
);

-- Create config table
CREATE TABLE IF NOT EXISTS config (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT UNIQUE NOT NULL,
    ticket_categories JSONB DEFAULT '["General Support", "Technical Issue", "Billing Question", "Other"]'::jsonb,
    admin_roles JSONB DEFAULT '[]'::jsonb,
    welcome_channel BIGINT,
    goodbye_channel BIGINT,
    auto_roles JSONB DEFAULT '[]'::jsonb,
    ticket_counter INTEGER DEFAULT 0,
    settings JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create reminders table
CREATE TABLE IF NOT EXISTS reminders (
    id BIGSERIAL PRIMARY KEY,
    reminder_id TEXT UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT,
    message TEXT NOT NULL,
    reminder_time TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT DEFAULT 'pending',
    message_id BIGINT
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_claimed_by ON tickets(claimed_by);

CREATE INDEX IF NOT EXISTS idx_polls_guild_id ON polls(guild_id);
CREATE INDEX IF NOT EXISTS idx_polls_status ON polls(status);
CREATE INDEX IF NOT EXISTS idx_polls_end_time ON polls(end_time);

CREATE INDEX IF NOT EXISTS idx_giveaways_guild_id ON giveaways(guild_id);
CREATE INDEX IF NOT EXISTS idx_giveaways_status ON giveaways(status);
CREATE INDEX IF NOT EXISTS idx_giveaways_end_time ON giveaways(end_time);

CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_reminder_time ON reminders(reminder_time);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for config table
CREATE TRIGGER update_config_updated_at 
    BEFORE UPDATE ON config 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Create function to clean up old data (optional)
CREATE OR REPLACE FUNCTION cleanup_old_data()
RETURNS void AS $$
BEGIN
    -- Delete closed tickets older than 30 days
    DELETE FROM tickets 
    WHERE status = 'closed' 
    AND closed_at < NOW() - INTERVAL '30 days';
    
    -- Delete ended polls older than 7 days
    DELETE FROM polls 
    WHERE status = 'closed' 
    AND end_time < NOW() - INTERVAL '7 days';
    
    -- Delete ended giveaways older than 30 days
    DELETE FROM giveaways 
    WHERE status = 'ended' 
    AND end_time < NOW() - INTERVAL '30 days';
    
    -- Delete completed reminders older than 7 days
    DELETE FROM reminders 
    WHERE status = 'completed' 
    AND reminder_time < NOW() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;

-- Create a scheduled job to run cleanup (requires pg_cron extension)
-- Uncomment if you have pg_cron enabled:
-- SELECT cron.schedule('cleanup-old-data', '0 2 * * *', 'SELECT cleanup_old_data();');

-- Insert default config for global settings
INSERT INTO config (guild_id, ticket_categories, admin_roles, auto_roles, settings)
VALUES (
    0, -- Global config
    '["General Support", "Technical Issue", "Billing Question", "Other"]'::jsonb,
    '[]'::jsonb,
    '[]'::jsonb,
    '{"max_tickets_per_user": 1, "auto_close_hours": 72, "require_reason": true}'::jsonb
) ON CONFLICT (guild_id) DO NOTHING;

-- Grant necessary permissions (adjust as needed for your setup)
-- Note: These permissions depend on your Supabase setup and RLS policies

-- Example RLS policies (uncomment and modify as needed):
/*
-- Allow all operations for authenticated users (for bot operations)
CREATE POLICY "Allow all operations for authenticated users" ON tickets
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "Allow all operations for authenticated users" ON polls
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "Allow all operations for authenticated users" ON giveaways
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "Allow all operations for authenticated users" ON config
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "Allow all operations for authenticated users" ON reminders
    FOR ALL USING (auth.role() = 'authenticated');
*/

-- Enable RLS on all tables (uncomment if you want to use RLS)
/*
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE polls ENABLE ROW LEVEL SECURITY;
ALTER TABLE giveaways ENABLE ROW LEVEL SECURITY;
ALTER TABLE config ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;
*/ 