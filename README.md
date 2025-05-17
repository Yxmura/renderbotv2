# Discord Bot with Cogs and Multiple Features

A comprehensive Discord bot built with discord.py, featuring a sophisticated ticket system and various utility commands, organized into cogs for better maintainability.

## Features

### Ticket System
- Admin-only commands for managing tickets
- Panel with categorized ticket options
- Embed upon ticket creation with options to claim and close
- Modal for users to input a reason when closing a ticket
- Confirmation prompt when closing tickets

### Fun Commands
- Meme command using API
- 8ball for fortune telling
- Dice rolling and coin flipping
- Random jokes and facts
- Choice maker

### Utility Commands
- Weather information
- Urban Dictionary lookup
- Calculator
- Ping command

### Admin Commands
- Role management
- Custom embed creation
- Auto-role assignment
- Message purging
- Announcement system

### Welcome System
- Customizable welcome and goodbye messages
- Auto-role assignment for new members
- Test commands for previewing messages

### Server and User Info
- Detailed server information
- User profile details
- Role information
- Avatar display

### Poll System
- Create polls with up to 5 options
- Real-time vote tracking
- Timed polls with automatic closing
- Results display

### Reminder System
- Set reminders with flexible time formats
- DM and channel reminders
- List and cancel active reminders

## Setup Instructions

1. Install required packages:
\`\`\`
pip install discord.py aiohttp
\`\`\`

2. Create a Discord bot on the [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to the "Bot" tab and click "Add Bot"
   - Enable all Privileged Gateway Intents (Presence, Server Members, and Message Content)
   - Copy your bot token

3. Replace `YOUR_BOT_TOKEN` in the bot.py file with your actual bot token

4. Invite the bot to your server with the following permissions:
   - Manage Channels
   - Manage Roles
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Add Reactions
   - Use Slash Commands

5. Create the following directory structure:
\`\`\`
discord_bot/
├── bot.py
├── data/
└── cogs/
    ├── tickets.py
    ├── fun.py
    ├── utility.py
    ├── admin.py
    ├── welcome.py
    ├── info.py
    ├── polls.py
    └── reminders.py
\`\`\`

6. Run the bot:
\`\`\`
python bot.py
\`\`\`

## Commands

### Ticket System
- `/setup_tickets` - Set up the ticket system
- `/ticket_stats` - Show ticket statistics

### Fun Commands
- `/meme` - Get a random meme
- `/8ball` - Ask the magic 8-ball a question
- `/roll` - Roll a dice
- `/flip` - Flip a coin
- `/joke` - Get a random joke
- `/fact` - Get a random fact
- `/choose` - Let the bot choose between options

### Utility Commands
- `/ping` - Check the bot's latency
- `/weather` - Get weather information
- `/urban` - Look up a term in Urban Dictionary
- `/calculator` - Perform a simple calculation

### Admin Commands
- `/set_admin_role` - Set admin roles for ticket management
- `/create_embed` - Create a custom embed
- `/set_auto_role` - Set a role to be automatically assigned
- `/purge` - Delete a specified number of messages
- `/announce` - Make an announcement

### Welcome System
- `/set_welcome_channel` - Set the welcome message channel
- `/set_goodbye_channel` - Set the goodbye message channel
- `/welcome_test` - Test the welcome message

### Info Commands
- `/serverinfo` - Get information about the server
- `/userinfo` - Get information about a user
- `/avatar` - Get a user's avatar
- `/roleinfo` - Get information about a role

### Poll System
- `/poll` - Create a poll
- `/endpoll` - End a poll early

### Reminder System
- `/remind` - Set a reminder
- `/reminders` - List your active reminders
- `/cancelreminder` - Cancel a reminder

## Customization

You can customize various aspects of the bot:
- Ticket categories in the `TicketView` class in tickets.py
- Welcome and goodbye message formats in welcome.py
- Poll options and durations in polls.py
- Add more fun commands in fun.py

## Adding More Features

The cog-based structure makes it easy to add more features:
1. Create a new file in the cogs directory
2. Define a new class that inherits from `commands.Cog`
3. Add your commands and event listeners
4. Add a setup function
5. Add the cog to the initial_extensions list in bot.py
\`\`\`

This Discord bot is now organized into separate cogs, making it much more maintainable and extensible. I've also added several new features that are common in multipurpose Discord bots:

1. **Fun Commands**:
   - 8ball fortune telling
   - Dice rolling and coin flipping
   - Random jokes and facts
   - Choice maker

2. **Server and User Info**:
   - Detailed server information
   - User profile details
   - Role information
   - Avatar display

3. **Poll System**:
   - Create polls with up to 5 options
   - Real-time vote tracking
   - Timed polls with automatic closing
   - Results display

4. **Reminder System**:
   - Set reminders with flexible time formats
   - DM and channel reminders
   - List and cancel active reminders

5. **Utility Commands**:
   - Weather information
   - Urban Dictionary lookup
   - Calculator
   - Ping command

The bot now has a more robust structure with:
- Proper error handling
- Logging system
- Data persistence
- Organized command groups
- Consistent embed styling
- Persistent views for interactive components

To run this bot, you'll need to:
1. Install discord.py and aiohttp
2. Set up the directory structure as shown in the README
3. Replace the bot token in bot.py
4. Run the bot with `python bot.py`

