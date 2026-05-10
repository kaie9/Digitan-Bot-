# 📊 Discord Stats Bot

A lightweight Discord bot that tracks live server statistics — messages per second, joins, leaves, voice activity, hourly breakdowns, and more.

---

## ✅ Features

| Stat | Description |
|---|---|
| ⚡ Messages / second | Rolling 60-second window |
| 💬 Messages today / total | Counted per guild |
| 📥 Joins & leaves today | With all-time totals |
| 🎙️ Voice minutes today | Accumulated per member session |
| ❤️ Reactions today | Emoji reactions added |
| 👤 Active users today | Unique users who sent ≥1 message |
| 🟢 Online now / peak online | Live member presence |
| 🏆 Top channels | Most active channels today |
| ⏰ Hourly activity | Bar chart of messages by hour (UTC) |
| 📅 30-day history | Daily snapshots, last 30 days |
| 🤖 Commands today | Slash command usage |

---

## 🚀 Setup

### 1. Create your bot
1. Go to https://discord.com/developers/applications
2. Click **New Application** → give it a name
3. Go to **Bot** → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
   - ✅ Presence Intent
5. Copy your **Bot Token**

### 2. Invite the bot to your server
Use this URL (replace `YOUR_CLIENT_ID`):
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=274877991936&scope=bot%20applications.commands
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set your token
Either edit `bot.py` directly:
```python
TOKEN = "your-token-here"
```

Or set an environment variable (recommended):
```bash
export DISCORD_TOKEN="your-token-here"
```

### 5. Run the bot
```bash
python bot.py
```

---

## 🤖 Slash Commands

| Command | Description |
|---|---|
| `/stats` | Full stats summary embed |
| `/mps` | Current messages per second |
| `/rps` | Rock-paper-scissors game with Agnes |
| `/wouldyourather` | Random 'would you rather' dilemmas |
| `/topchannels` | Top 10 most active channels today |
| `/activity` | Hourly message bar chart (UTC) |
| `/history` | Last 7 days of daily stats |

---

## 📁 Data Persistence

Stats are saved to `stats_data.json` every 5 minutes automatically. Daily counters reset at midnight UTC, with a snapshot saved to history (kept for 30 days).

---

## 🛡️ Permissions Required

The bot needs these Discord permissions:
- `Read Messages / View Channels`
- `Read Message History`
- `Send Messages`
- `Embed Links`
- `Use Application Commands`
- `View Guild Insights` (for member counts)

---

## 💡 Tips

- Stats persist across bot restarts via `stats_data.json`
- Voice time is tracked by session (join → leave)
- The bot ignores all other bots' activity
- Peak online resets daily with the other counters
