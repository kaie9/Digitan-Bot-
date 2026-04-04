import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
import asyncio

# ── Config ──────────────────────────────────────────────────────────────
# Never commit a real token — use env var only.
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Set DISCORD_TOKEN in your environment before running (PowerShell: $env:DISCORD_TOKEN = '...').")
DATA_FILE = "stats_data.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ── In-memory state ──────────────────────────────────────────────────────
# Per-guild stats stored in memory, persisted to JSON periodically
guild_stats = defaultdict(lambda: {
    "messages_today": 0,
    "messages_total": 0,
    "joins_today": 0,
    "joins_total": 0,
    "leaves_today": 0,
    "leaves_total": 0,
    "commands_today": 0,
    "reactions_today": 0,
    "voice_minutes_today": 0,
    "active_users_today": set(),
    "channel_message_counts": defaultdict(int),
    "hourly_messages": defaultdict(int),   # hour (0-23) → count today
    "last_reset": datetime.utcnow().date().isoformat(),
    "peak_online": 0,
    "daily_history": [],   # list of daily snapshots
})

# Sliding window for messages-per-second (last 60 seconds)
message_timestamps = defaultdict(lambda: deque())

# Voice session tracking: {guild_id: {member_id: join_timestamp}}
voice_sessions = defaultdict(dict)


# ── Helpers ──────────────────────────────────────────────────────────────
def save_data():
    serializable = {}
    for gid, stats in guild_stats.items():
        s = dict(stats)
        s["active_users_today"] = list(s["active_users_today"])
        s["channel_message_counts"] = dict(s["channel_message_counts"])
        s["hourly_messages"] = dict(s["hourly_messages"])
        serializable[str(gid)] = s
    with open(DATA_FILE, "w") as f:
        json.dump(serializable, f, indent=2)


def load_data():
    if not os.path.exists(DATA_FILE):
        return
    with open(DATA_FILE) as f:
        raw = json.load(f)
    for gid, s in raw.items():
        s["active_users_today"] = set(s.get("active_users_today", []))
        s["channel_message_counts"] = defaultdict(int, s.get("channel_message_counts", {}))
        s["hourly_messages"] = defaultdict(int, {int(k): v for k, v in s.get("hourly_messages", {}).items()})
        guild_stats[int(gid)].update(s)


def reset_daily(gid):
    """Save a daily snapshot and reset today's counters."""
    s = guild_stats[gid]
    snapshot = {
        "date": s["last_reset"],
        "messages": s["messages_today"],
        "joins": s["joins_today"],
        "leaves": s["leaves_today"],
        "commands": s["commands_today"],
        "reactions": s["reactions_today"],
        "voice_minutes": s["voice_minutes_today"],
        "active_users": len(s["active_users_today"]),
    }
    s["daily_history"].append(snapshot)
    if len(s["daily_history"]) > 30:          # keep 30 days
        s["daily_history"].pop(0)

    s["messages_today"] = 0
    s["joins_today"] = 0
    s["leaves_today"] = 0
    s["commands_today"] = 0
    s["reactions_today"] = 0
    s["voice_minutes_today"] = 0
    s["active_users_today"] = set()
    s["channel_message_counts"] = defaultdict(int)
    s["hourly_messages"] = defaultdict(int)
    s["last_reset"] = datetime.utcnow().date().isoformat()


def maybe_reset(gid):
    today = datetime.utcnow().date().isoformat()
    if guild_stats[gid]["last_reset"] != today:
        reset_daily(gid)


def mps(gid):
    """Messages per second over the last 60 s."""
    now = time.time()
    dq = message_timestamps[gid]
    while dq and now - dq[0] > 60:
        dq.popleft()
    return round(len(dq) / 60, 3)


# ── Background tasks ──────────────────────────────────────────────────────
@tasks.loop(minutes=5)
async def persist_task():
    save_data()


@tasks.loop(minutes=1)
async def peak_online_task():
    for guild in bot.guilds:
        online = sum(
            1 for m in guild.members
            if m.status != discord.Status.offline and not m.bot
        )
        s = guild_stats[guild.id]
        if online > s["peak_online"]:
            s["peak_online"] = online


@tasks.loop(minutes=1)
async def voice_accumulate_task():
    """Add 1 minute for every member currently in a voice channel."""
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    guild_stats[guild.id]["voice_minutes_today"] += 1


# ── Events ────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    load_data()
    persist_task.start()
    peak_online_task.start()
    voice_accumulate_task.start()
    try:
        # Global sync() can take up to ~1 hour to show in Discord. Per-guild
        # sync is instant, so we copy globals into each server the bot is in.
        if bot.guilds:
            for guild in bot.guilds:
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"Synced {len(synced)} slash commands to {guild.name!r}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global slash commands (join a server, restart bot)")
    except Exception as e:
        print(e)
    print(f"✅  Logged in as {bot.user} ({bot.user.id})")


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    gid = message.guild.id
    maybe_reset(gid)
    s = guild_stats[gid]
    s["messages_today"] += 1
    s["messages_total"] += 1
    s["active_users_today"].add(message.author.id)
    s["channel_message_counts"][str(message.channel.id)] += 1
    hour = datetime.utcnow().hour
    s["hourly_messages"][hour] += 1
    message_timestamps[gid].append(time.time())
    await bot.process_commands(message)


@bot.event
async def on_member_join(member):
    if member.bot:
        return
    gid = member.guild.id
    maybe_reset(gid)
    guild_stats[gid]["joins_today"] += 1
    guild_stats[gid]["joins_total"] += 1


@bot.event
async def on_member_remove(member):
    if member.bot:
        return
    gid = member.guild.id
    maybe_reset(gid)
    guild_stats[gid]["leaves_today"] += 1
    guild_stats[gid]["leaves_total"] += 1


@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or not reaction.message.guild:
        return
    gid = reaction.message.guild.id
    maybe_reset(gid)
    guild_stats[gid]["reactions_today"] += 1
    guild_stats[gid]["active_users_today"].add(user.id)


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    gid = member.guild.id
    now = time.time()
    if before.channel is None and after.channel is not None:
        voice_sessions[gid][member.id] = now
    elif before.channel is not None and after.channel is None:
        joined = voice_sessions[gid].pop(member.id, None)
        if joined:
            mins = (now - joined) / 60
            guild_stats[gid]["voice_minutes_today"] += mins


# ── Slash commands ────────────────────────────────────────────────────────
@bot.tree.command(name="stats", description="Show server stats summary")
async def stats_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    gid = guild.id
    maybe_reset(gid)
    s = guild_stats[gid]
    guild_stats[gid]["commands_today"] += 1

    rate = mps(gid)
    online = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
    total_members = guild.member_count

    embed = discord.Embed(
        title=f"📊 Stats — {guild.name}",
        color=0x5865F2,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="👥 Members", value=f"`{total_members:,}`", inline=True)
    embed.add_field(name="🟢 Online Now", value=f"`{online:,}`", inline=True)
    embed.add_field(name="🏆 Peak Online (today)", value=f"`{s['peak_online']:,}`", inline=True)
    embed.add_field(name="💬 Messages Today", value=f"`{s['messages_today']:,}`", inline=True)
    embed.add_field(name="📨 Messages Total", value=f"`{s['messages_total']:,}`", inline=True)
    embed.add_field(name="⚡ Msg / sec", value=f"`{rate}`", inline=True)
    embed.add_field(name="📥 Joins Today", value=f"`{s['joins_today']:,}`", inline=True)
    embed.add_field(name="📤 Leaves Today", value=f"`{s['leaves_today']:,}`", inline=True)
    embed.add_field(name="🎙️ Voice Min Today", value=f"`{int(s['voice_minutes_today']):,}`", inline=True)
    embed.add_field(name="❤️ Reactions Today", value=f"`{s['reactions_today']:,}`", inline=True)
    embed.add_field(name="👤 Active Users Today", value=f"`{len(s['active_users_today']):,}`", inline=True)
    embed.add_field(name="🤖 Commands Today", value=f"`{s['commands_today']:,}`", inline=True)
    embed.set_footer(text="Stats Bot • resets midnight UTC")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="topchannels", description="Most active channels today")
async def topchannels_cmd(interaction: discord.Interaction):
    gid = interaction.guild.id
    s = guild_stats[gid]
    sorted_channels = sorted(s["channel_message_counts"].items(), key=lambda x: x[1], reverse=True)[:10]
    if not sorted_channels:
        await interaction.response.send_message("No channel data yet!", ephemeral=True)
        return
    lines = []
    for i, (cid, count) in enumerate(sorted_channels, 1):
        ch = interaction.guild.get_channel(int(cid))
        name = f"#{ch.name}" if ch else f"<#{cid}>"
        lines.append(f"`{i}.` {name} — **{count:,}** messages")
    embed = discord.Embed(title="🏆 Top Channels Today", description="\n".join(lines), color=0xFEE75C)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="history", description="Last 7 days of server activity")
async def history_cmd(interaction: discord.Interaction):
    gid = interaction.guild.id
    history = guild_stats[gid]["daily_history"][-7:]
    if not history:
        await interaction.response.send_message("Not enough history yet — check back tomorrow!", ephemeral=True)
        return
    lines = []
    for day in reversed(history):
        lines.append(
            f"`{day['date']}` — 💬{day['messages']:,}  📥{day['joins']}  👤{day['active_users']}"
        )
    embed = discord.Embed(title="📅 7-Day History", description="\n".join(lines), color=0x57F287)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="activity", description="Hourly message breakdown for today")
async def activity_cmd(interaction: discord.Interaction):
    gid = interaction.guild.id
    hourly = guild_stats[gid]["hourly_messages"]
    if not hourly:
        await interaction.response.send_message("No activity data yet!", ephemeral=True)
        return
    max_val = max(hourly.values(), default=1)
    bar_max = 20
    lines = []
    for h in range(24):
        count = hourly.get(h, 0)
        bar = "█" * int(count / max_val * bar_max)
        lines.append(f"`{h:02d}:00` {bar:<20} {count}")
    embed = discord.Embed(title="⏰ Hourly Activity (UTC)", description="```\n" + "\n".join(lines) + "\n```", color=0xEB459E)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mps", description="Current messages per second")
async def mps_cmd(interaction: discord.Interaction):
    gid = interaction.guild.id
    rate = mps(gid)
    color = 0x57F287 if rate < 0.5 else (0xFEE75C if rate < 2 else 0xED4245)
    embed = discord.Embed(
        title="⚡ Messages Per Second",
        description=f"**{rate}** msg/s  *(60-second rolling window)*",
        color=color
    )
    await interaction.response.send_message(embed=embed)


# ── Run ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(TOKEN)
