# 🎫 Ticket Panel Setup Guide

This guide will help you set up ticket panels in your Discord server using the Supabase-integrated ticket system.

## 📋 Prerequisites

1. **Admin Permissions**: You need administrator permissions in your Discord server
2. **Bot Permissions**: The bot needs the following permissions:
   - Manage Channels
   - Send Messages
   - Embed Links
   - Use Slash Commands
   - Manage Messages (for ticket controls)

## 🚀 Quick Setup

### Method 1: Basic Ticket Panel

1. **Go to the channel** where you want the ticket panel
2. **Run the command**: `/setup_tickets`
3. **The bot will create** a ticket panel with 6 default categories

### Method 2: Customized Ticket Panel

1. **Go to the channel** where you want the ticket panel
2. **Run the command**: `/ticket_panel [channel] [title] [description] [color]`
3. **Customize the parameters**:
   - `channel`: Target channel (optional, defaults to current channel)
   - `title`: Panel title (default: "🎫 Support Ticket System")
   - `description`: Panel description
   - `color`: Panel color (blue, green, red, yellow, purple, orange)

## 🎨 Default Ticket Categories

The ticket panel includes 6 default categories:

| Category | Emoji | Description | Button Style |
|----------|-------|-------------|--------------|
| General Support | ❓ | Get help with general questions | Primary (Blue) |
| Resource Issue | ⚠️ | Report a problem with a resource | Danger (Red) |
| Partner/Sponsor | 💰 | Partner or sponsorship inquiries | Success (Green) |
| Staff Application | 🔒 | Apply to join our staff team | Secondary (Gray) |
| Content Creator | 📷 | Content creator applications | Primary (Blue) |
| Other | 📝 | Other inquiries | Secondary (Gray) |

## 🔧 Customization Options

### Customizing Categories

1. **Run the command**: `/ticket_categories`
2. **A modal will appear** where you can customize:
   - Category names
   - Category descriptions
   - Category emojis

### Customizing Settings

1. **Run the command**: `/ticket_settings`
2. **Configure**:
   - Auto-close time (in hours)
   - Maximum tickets per user
   - Admin roles
   - Welcome/goodbye channels
   - Auto-assign roles

## 📊 Ticket Panel Features

### For Users:
- **Click any category button** to create a ticket
- **Fill out the form** with your issue details
- **Wait for staff response** in the created ticket channel
- **Close the ticket** when your issue is resolved

### For Staff:
- **Claim tickets** using the "Claim Ticket" button
- **Set priority levels** (Low, Normal, High, Urgent)
- **Generate transcripts** of ticket conversations
- **Close tickets** with optional reasons

## 🎯 Example Commands

### Basic Setup
```
/setup_tickets
```

### Custom Panel
```
/ticket_panel #support "🎫 Get Help Here" "Need assistance? Create a ticket below!" blue
```

### Custom Panel in Different Channel
```
/ticket_panel #tickets "🎫 Support System" "Click a button to get help!" green
```

## 🔍 Ticket Panel Appearance

The ticket panel will look like this:

```
┌─────────────────────────────────────────────────────────────┐
│ 🎫 Support Ticket System                                    │
│ Need help? Create a ticket by clicking one of the buttons  │
│ below!                                                      │
│                                                             │
│ ❓ General Support    ⚠️ Resource Issue    💰 Partner/Sponsor │
│ Get help with        Report a problem     Partner or        │
│ general questions    with a resource      sponsorship       │
│                                                             │
│ 🔒 Staff Application 📷 Content Creator   📝 Other          │
│ Apply to join our    Content creator      Other inquiries   │
│ staff team           applications                          │
│                                                             │
│ Click a button below to create a ticket                    │
└─────────────────────────────────────────────────────────────┘
```

## 🛠️ Advanced Configuration

### Multiple Ticket Panels

You can create multiple ticket panels in different channels:

1. **Support Panel**: `/ticket_panel #support "🎫 General Support" "Need help? Create a ticket!" blue`
2. **Bug Reports**: `/ticket_panel #bugs "🐛 Bug Reports" "Found a bug? Report it here!" red`
3. **Suggestions**: `/ticket_panel #suggestions "💡 Suggestions" "Have an idea? Share it!" green`

### Custom Categories

To create custom categories, use the `/ticket_categories` command and enter:

```
General Support:Get help with general questions:❓
Technical Issue:Report technical problems:🔧
Billing Question:Questions about payments:💳
Feature Request:Request new features:✨
```

## 📈 Ticket Statistics

Use `/ticket_stats` to view:
- Total tickets created
- Open vs closed tickets
- Tickets by category
- Tickets by priority
- Recent activity

## 🔧 Troubleshooting

### Common Issues:

1. **"You don't have permission"**
   - Make sure you have administrator permissions
   - Check if the bot has the required permissions

2. **Buttons not working**
   - Ensure the bot has "Use Slash Commands" permission
   - Check if the bot is online and responsive

3. **Tickets not creating**
   - Verify the bot has "Manage Channels" permission
   - Check if there's a category limit in your server

4. **Panel not appearing**
   - Make sure the bot has "Send Messages" and "Embed Links" permissions
   - Check the channel permissions

### Permission Checklist:

- ✅ Administrator (for you)
- ✅ Manage Channels (for bot)
- ✅ Send Messages (for bot)
- ✅ Embed Links (for bot)
- ✅ Use Slash Commands (for bot)
- ✅ Manage Messages (for bot)

## 🎉 Success!

Once your ticket panel is set up:

1. **Users can click buttons** to create tickets
2. **Tickets are stored in Supabase** (persistent across restarts)
3. **Staff can manage tickets** with the control panel
4. **All data persists** even after bot redeployments

Your ticket system is now fully functional with Supabase integration! 🚀 