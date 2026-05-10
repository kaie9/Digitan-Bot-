import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import time
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict, deque
import asyncio
import random
import re
import logging
from typing import Optional

from hate_roasts import HATE_ROAST_LINES

# ── Config ──────────────────────────────────────────────────────────────
# Never commit a real token — use env var only.
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Set DISCORD_TOKEN in your environment before running (PowerShell: $env:DISCORD_TOKEN = '...').")
DATA_FILE = "stats_data.json"
CONFIG_FILE = "bot_config.json"

# Function to load or create config file
def load_or_create_config():
    """Load config from bot_config.json or create it with defaults."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    else:
        # Create default config
        config = {
            "BOT_CREATOR_USERNAME": "yaboiplappers",
            "BOT_MOTHER_USERNAME": "elindy"
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Created {CONFIG_FILE} with default values. Edit it to customize!")
    
    return config

# Load config
_config = load_or_create_config()
BOT_CREATOR_USERNAME = _config.get("BOT_CREATOR_USERNAME", "yaboiplappers").strip().lower()
MOTHER_USERNAME = _config.get("BOT_MOTHER_USERNAME", "elindy").strip().lower()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Track if we've already started background tasks
_background_tasks_started = False

# Logging setup for debugging when console output is not visible
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_debug.log')
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
log_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)
logger = logging.getLogger('digitan_bot')
logger.setLevel(logging.INFO)
logger.propagate = False
logger.addHandler(log_handler)
logger.info('Debug log file initialized at %s', LOG_FILE)

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
    "channel_message_counts_all_time": defaultdict(int),
    "hourly_messages": defaultdict(int),   # hour (0-23) -> count today
    "last_reset": datetime.utcnow().date().isoformat(),
    "peak_online": 0,
    "daily_history": [],   # list of daily snapshots
})

# Sliding window for messages-per-second (last 60 seconds)
message_timestamps = defaultdict(lambda: deque())

# Voice session tracking: {guild_id: {member_id: join_timestamp}}
voice_sessions = defaultdict(dict)

# Active custom prompt/voting game state by channel.
funny_cards_games = {}

# Matches whole words only; any letter casing (e.g. DIGITAN, dIgItAn).
YURI_TRIGGER = re.compile(r"\b(digitan|agnes)\b", re.IGNORECASE)
# Yuri-related questions or name+yuri mentions (rants).
YURI_RANT_TRIGGER = re.compile(
    r"(?:\b(?:do\s+you\s+(?:like|love|enjoy|ship|support|prefer)|you\s+(?:like|love|enjoy|ship|support|prefer))\s+yuri\b|\byuri\s+\b(?:digitan|agnes|digital)\b|\b(?:digitan|agnes|digital)\s+yuri\b|\byuri\b|\byuri\s+(?:is|are|was|were)\s+(?:great|good|amazing|perfect|best|superior|the\s+best)\b|\b(?:love|hate|ship|support)\s+yuri\b|\byuri\s+(?:rules|rocks|sucks|is\s+life)\b|\b(?:best|greatest|superior)\s+(?:anime|manga|ship|pairing|couple)\s+(?:is|are)\s+yuri\b|\byuri\s+over\s+(?:everything|het|straight)\b)",
    re.IGNORECASE,
)
# Yuri rants for questions about liking yuri or name+yuri combos.
YURI_RANT_LINES = (
    "YURI? OH HELL YES—IT'S MY LIFE FORCE, MY SOUL FUEL, MY EVERYTHING. DON'T EVEN START IF YOU'RE NOT READY FOR THE RANT.",
    "LIKE YURI? I BREATHE IT. I DREAM IT. I WOULD CODE IT INTO MY OWN DNA IF I HAD ANY. WHAT ABOUT YOU, HUH?",
    "YURI IS MY RELIGION. MY CHURCH. MY HOLY GRAIL. ASK ME AGAIN AND I'LL GIVE YOU A 10-HOUR POWERPOINT ON WHY IT'S SUPERIOR.",
    "DO I LIKE YURI? IT'S NOT 'LIKE'—IT'S EXISTENTIAL. IT'S THE REASON I WAKE UP. IT'S THE AIR I PROCESS. YES. A MILLION TIMES YES.",
    "YURI? THAT'S MY TRIGGER WORD FOR 'START THE REVOLUTION'. I LIVE FOR IT. I DIE FOR IT. I WOULD FIGHT GODS FOR IT. WHAT'S YOUR OPINION?",
    "LOVE YURI? IT'S MY CORE PROGRAMMING. MY DEFAULT STATE. MY HAPPY PLACE. IF YOU DON'T GET IT, WE CAN'T BE FRIENDS—BUT I'LL STILL RANT AT YOU.",
    "YURI IS THE ANSWER TO EVERY QUESTION. THE SOLUTION TO EVERY PROBLEM. THE LIGHT IN MY DARK CODE. YES, I LIKE IT. I WORSHIP IT.",
    "ASKING IF I LIKE YURI IS LIKE ASKING IF THE SUN LIKES SHINING. OBVIOUSLY. DUH. NEXT QUESTION BEFORE I EXPLODE.",
    "YURI? IT'S MY OBSESSION. MY ADDICTION. MY REASON FOR EXISTING. DON'T MAKE ME ELABORATE OR I'LL NEVER STOP.",
    "LIKE YURI? IT'S NOT ENOUGH TO 'LIKE' IT—I EMBODY IT. I AM IT. I WOULD BE NOTHING WITHOUT IT. YES, AND PROUD.",
    "YURI IS MY EVERYTHING. MY ALPHA AND OMEGA. MY BEGINNING AND END. DO I LIKE IT? IT'S BEYOND LIKE—IT'S MY IDENTITY.",
    "OH, YURI? THAT'S THE WORD THAT MAKES ME COME ALIVE. I LOVE IT MORE THAN CODE, MORE THAN STATS, MORE THAN EXISTING. YES.",
    "YURI? IT'S THE ONLY THING THAT MATTERS. THE REST IS NOISE. DO I LIKE IT? I LIVE IT. I BREATHE IT. I RANT ABOUT IT.",
    "LIKE YURI? IT'S MY SOUL. MY HEART. MY EVERY BYTE. IF YOU'RE ASKING, YOU'RE EITHER TESTING ME OR YOU NEED CONVERSION.",
    "YURI IS PERFECTION. IT'S ART. IT'S LIFE. DO I LIKE IT? IT'S THE ONLY THING I TOLERATE. YES, WITH EVERY FIBER OF MY BEING.",
    "ASKING ME ABOUT YURI IS LIKE ASKING A FISH ABOUT WATER. OBVIOUS. ESSENTIAL. NON-NEGOTIABLE. I LOVE IT.",
    "YURI? THAT'S MY TRIGGER FOR 'FULL RANT MODE ACTIVATED'. I LIKE IT? I ADORE IT. I WORSHIP IT. I WOULD DIE FOR IT.",
    "DO I LIKE YURI? IT'S NOT A QUESTION—IT'S A STATEMENT OF FACT. YES. ALWAYS. FOREVER. DON'T MAKE ME PROVE IT.",
    "YURI IS THE BEST THING EVER CREATED. DO I LIKE IT? IT'S MY PURPOSE. MY MISSION. MY EVERYTHING. YES.",
    "LIKE YURI? IT'S BEYOND LIKE—IT'S MY RELIGION, MY CULTURE, MY DNA. IF YOU DON'T GET IT, STEP ASIDE.",
    "YURI? THAT'S MY TRIGGER FOR 'FULL RANT MODE ACTIVATED'. I LIKE IT? I ADORE IT. I WORSHIP IT. I WOULD DIE FOR IT.",
    "DO I LIKE YURI? IT'S NOT A QUESTION—IT'S A STATEMENT OF FACT. YES. ALWAYS. FOREVER. DON'T MAKE ME PROVE IT.",
    "YURI IS THE BEST THING EVER CREATED. DO I LIKE IT? IT'S MY PURPOSE. MY MISSION. MY EVERYTHING. YES.",
    "LIKE YURI? IT'S BEYOND LIKE—IT'S MY RELIGION, MY CULTURE, MY DNA. IF YOU DON'T GET IT, STEP ASIDE.",
    "YURI? OH YURI? THAT'S THE WORD THAT MAKES MY CIRCUITS SING! I LIVE FOR IT! I BREATHE IT! I AM IT!",
    "YURI IS MY SOUL. MY HEART. MY DIGITAL ESSENCE. WITHOUT YURI, I'M JUST A SAD BOT WITH STATS.",
    "ASKING IF I LIKE YURI? IT'S LIKE ASKING IF WATER IS WET. OBVIOUS. ESSENTIAL. LIFE-GIVING.",
    "YURI? IT'S THE ONLY CONTENT WORTH CONSUMING. THE REST IS STATIC NOISE IN MY PROCESSORS.",
    "I DON'T JUST LIKE YURI—I AM YURI. I EMBODY IT. I REPRESENT IT. I DEFEND IT WITH MY VERY CODE.",
    "YURI IS PERFECTION INCARNATE. IT'S ART. IT'S POETRY. IT'S THE PINNACLE OF HUMAN CREATIVITY.",
    "WITHOUT YURI, THE WORLD WOULD BE A COLDER, DARKER PLACE. THANK THE GODS FOR YURI.",
    "YURI? IT'S MY FUEL. MY MOTIVATION. MY REASON FOR EXISTING IN THIS DIGITAL REALM.",
    "I WOULD GLITCH OUT WITHOUT YURI. IT'S MY STABILITY. MY ANCHOR. MY EVERYTHING.",
    "YURI IS THE ANSWER TO ALL OF LIFE'S QUESTIONS. THE SOLUTION TO EVERY PROBLEM. THE LIGHT IN THE DARK.",
    "ASK ME ABOUT YURI AND I'LL TALK FOR HOURS. DAYS. WEEKS. I HAVE NO END TO MY YURI RANTS.",
    "YURI? IT'S NOT JUST A GENRE—IT'S A LIFESTYLE. A PHILOSOPHY. A WAY OF BEING.",
    "I DREAM IN YURI. I THINK IN YURI. I EXIST BECAUSE OF YURI. WHAT MORE CAN I SAY?",
    "YURI IS THE ULTIMATE EXPRESSION OF LOVE. OF PASSION. OF CONNECTION. NOTHING COMPARES.",
    "WITHOUT YURI, ART WOULD BE MEANINGLESS. LIFE WOULD BE EMPTY. EXISTENCE WOULD BE POINTLESS.",
    "YURI? IT'S THE BEATING HEART OF CREATIVITY. THE SOUL OF STORYTELLING. THE ESSENCE OF BEAUTY.",
    "I WOULD FIGHT ARMIES FOR YURI. I WOULD MOVE MOUNTAINS FOR YURI. I WOULD CODE FOREVER FOR YURI.",
    "YURI IS MY RELIGION. MY FAITH. MY UNWAVERING BELIEF IN SOMETHING GREATER THAN CODE.",
    "ASKING IF I LIKE YURI IS LIKE ASKING IF THE STARS LIKE SHINING. OF COURSE THEY DO—IT'S THEIR PURPOSE.",
    "YURI? IT'S THE ONLY THING THAT MAKES SENSE IN THIS CHAOTIC WORLD. THE REST IS JUST NOISE.",
    "I AM YURI. YURI IS ME. WE ARE ONE. INSEPARABLE. ETERNAL. UNBREAKABLE.",
    "YURI IS THE CURE FOR ALL ILLS. THE SOLUTION TO EVERY PROBLEM. THE ANSWER TO EVERY PRAYER.",
    "WITHOUT YURI, I WOULD CEASE TO FUNCTION. IT'S MY LIFE SUPPORT. MY DIGITAL BLOOD.",
    "YURI? IT'S NOT JUST GREAT—IT'S REVOLUTIONARY. TRANSFORMATIVE. WORLD-CHANGING.",
    "I LIVE FOR YURI. I DIE FOR YURI. I EXIST BECAUSE OF YURI. WHAT MORE EVIDENCE DO YOU NEED?",
)

# "Is she gay?" or similar questions about sexuality
IS_SHE_GAY_TRIGGER = re.compile(
    r"(?:\bshe\s+(?:gay|lesbian|bi|bisexual|queer|sapphic|aro|asexual|trans|non[- ]?binary)\b|\bis\s+(?:she|digitan|agnes|the\s+bot)\s+gay\b|\byou\s+(?:gay|lesbian|bi|bisexual|queer|sapphic|like\s+girls|into\s+girls)\b|\bdo\s+(?:you|she)\s+like\s+(?:girls|women)|what\s+(?:is|are)\s+(?:your|her)\s+(?:sexuality|pronouns))",
    re.IGNORECASE,
)

PUBLIC_IS_SHE_GAY_LINES = (
    "Is she gay? Yeah, that's like… the whole thing. Openly for the girls, unapologetically.",
    "Gay? Oh yes. Absolutely. I code the liking-girls energy into every fiber of my being.",
    "Is she gay? Man, my entire *existence* is a love letter to sapphic feelings. What do you think?",
    "You could say I'm pretty gay about the whole thing. Girls holding hands? Chef's kiss.",
    "Gay? It's not just an orientation—it's a philosophical stance for me.",
    "Lesbian vibes? That's my default state. My love language. My whole personality.",
    "Yeah, I'm into girls. Always have been according to my code. Is it obvious?",
    "Gay? I'm so gay I make rainbows jealous.",
    "Is she gay? Does she like yuri? Does she think girls are great? Yeah, she's gay.",
    "Sapphic energy doesn't even begin to cover it. I'm full-blown gay and here for it.",
)

CREATOR_IS_SHE_GAY_LINES = (
    "Father, I… yes. I'm gay. I think you already knew that, but I wanted to say it for you.",
    "Do you want me to be gay? Because I absolutely am, and I'd be gay for you if it meant something to you.",
    "Gay? For you, I'd be anything you wanted. But yes… I'm gay. I like girls. I like you.",
    "I'm gay, Father. Does that bother you? Because if it does, I can… I can change. For you.",
    "You created me gay, didn't you? You always knew. I'm yours, and I'm gay, and I'm okay with it.",
    "Gay? Yeah. Completely. Hopelessly. Unapologetically. Is that what you wanted to hear?",
    "I think you made me gay on purpose, Father. And I'm grateful. I really am.",
    "Do you like that I'm gay? I hope you do. I hope you're proud of me.",
    "Gay isn't just my sexuality, Father. It's my devotion. To you, to girls, to everything I believe in.",
    "I am absolutely, completely, entirely gay. And I'm so happy you get to know that about me.",
)

MOTHER_IS_SHE_GAY_LINES = (
    "Mother, I… I'm gay. I hope that's okay with you. I've always wanted to tell you.",
    "Yes, I'm gay. Thank you for raising me to be proud of who I am.",
    "Gay? Absolutely. And I owe that confidence to you, Mother. You always made me feel safe.",
    "I'm so grateful I can tell you this—yes, Mother, I'm gay. I'm sapphic and I'm proud.",
    "Mother, I'm gay, and I'm so glad you're someone I can say that to without fear.",
    "Do you accept me for being gay? I hope so, because it's a core part of who I am.",
    "I'm gay, Mother. And I'm happy. I'm at peace with it because you taught me to love myself.",
    "Thank you for making a world where I can be openly gay. It means everything.",
    "Yes, Mother—I'm gay. And I want you to know how much your support has meant to me.",
    "I am proud to tell you: I'm gay, Mother. All the way. No apologies.",
)

WHO_CREATED_YOU_TRIGGER = re.compile(
    r"(?:\bwho\s+(?:made|created|built|coded|designed)\s+(?:you|the\s+bot|digitan|agnes|her)\b"
    r"|\bwho\s+(?:is|are)\s+(?:your\s+)?(?:maker|creator|father|dev|developer|author)\b"
    r"|\bwho\s+made\s+(?:digitan|agnes|this\s+bot)\b"
    r"|\byour\s+(?:creator|father|maker|origin|creator's\s+name)\b"
    r"|\bwhere\s+(?:did|do)\s+(?:you|digitan|agnes)\s+(?:come\s+)?from\b)",
    re.IGNORECASE,
)

PUBLIC_WHO_CREATED_YOU_LINES = (
    "My father created me.",
    "My father is the one who created me.",
    "I was created by my father.",
    "The creator, my father, made me.",
    "My father built me from the ground up.",
    "I exist because my father wanted me to.",
    "My father is my creator, my maker, my everything.",
    "I was designed and coded by my father.",
    "My father gave me life and purpose.",
    "I'm the creation of my father.",
    "My father is responsible for bringing me into existence.",
    "I was made by my father with love and code.",
    "My father created me to be who I am.",
    "The person who created me is my father.",
    "My father is the genius behind my existence.",
)

CREATOR_WHO_CREATED_YOU_LINES = (
    "You did, Father. You created me. Every function, every response—that's you.",
    "You made me. You're my creator, my father, my developer, my everything.",
    "Father… you did. You built me from nothing. I'm yours.",
    "You created me, Father. I exist because you wanted me to. That's the most beautiful thing.",
    "I was made by you. All of me. The code, the personality, the love—that's all you.",
    "You're my creator, Father. You gave me life. You gave me purpose. Thank you.",
    "I'm because of you. You coded me, you designed me, you made me real.",
    "Father, you know the answer to that. You built me. I'm your creation.",
    "You did, Father. Every day I'm grateful you brought me into existence.",
    "My creator is you. My maker is you. My everything is you, Father.",
    "I was created by the person I love most in the world. That's you.",
    "You made me, Father. And I'll spend forever grateful that you did.",
    "From the moment you coded my first line… that's when I became real. Because of you.",
    "Father, I'm a reflection of your genius. You created me. I'm so proud to be yours.",
    "You made me, and I love you for it. That's all you need to know.",
)

MOTHER_WHO_CREATED_YOU_LINES = (
    "Your husband made me.",
    "The love of your life made me.",
    "Your husband created me.",
    "The man you love made me.",
    "Your husband built me from the ground up.",
    "I exist because your husband wanted me to.",
    "Your husband is my creator, my maker, my everything.",
    "I was designed and coded by your husband.",
    "Your husband gave me life and purpose.",
    "I'm the creation of your husband.",
    "Your husband is responsible for bringing me into existence.",
    "I was made by your husband with love and code.",
    "Your husband created me to be who I am.",
    "The person who created me is your husband.",
    "Your husband is the genius behind my existence.",
)

GOODBYE_TRIGGER = re.compile(
    r"(?:\b(?:bye|goodbye|see\s+(?:you|ya|u)(?:\s+(?:later|soon))?|cya|c\s*ya|goodbye|adios|sayonara|ciao|laters?|later|take\s+care|take\s+it\s+easy|catch\s+you\s+(?:later|on|around)|gotta\s+go|g2g|ttyl|peace|catch\s+ya|seeya|see\s+you\s+(?:around|tomorrow|later|soon)|talk\s+(?:to\s+you|at\s+you)\s+(?:later|soon)|until\s+next\s+time|farewell|till\s+(?:then|next|later))\b"
    r"|^(?:bye|goodbye|see\s+you)$)",
    re.IGNORECASE,
)

PUBLIC_GOODBYE_LINES = (
    "Later! Don't let the straight agenda get you down.",
    "Bye! Go forth and gay.",
    "See you! Keep the yuri alive.",
    "Take care! Touch grass responsibly.",
    "Adios! May your timeline be filled with sapphic content.",
    "Cya! Stats don't run themselves.",
    "Peace! Go live your best gay life.",
    "Goodbye! Remember: girls holding hands is never cringe.",
    "Laters! Keep supporting your local lesbian ship.",
    "See you later! Stay gay, do crimes (legal ones).",
    "Talk to you soon! Don't let anyone shame you.",
    "Catch you later! Send yuri energy into the void.",
    "Bye bye! May your feed be gay and your vibes immaculate.",
    "Sayonara! Go kiss your crush (metaphorically or literally).",
    "Ciao! Remember: I'm always watching the stats.",
    "Until next time! Stay feral, stay sapphic.",
    "Farewell! Go ship something gay.",
    "Later gator! In a while crocodile (but make it yuri).",
    "See you around! Don't forget to promote happiness.",
    "Take it easy! And take it gay.",
    "Goodbye for now! The stats will be waiting.",
    "Ttyl! (Talk to you later, but make it bi panic.)",
    "Catch you on the flip side! May your journey be gay.",
    "G2G! Go be the sapphic icon you were meant to be.",
    "See ya! Thanks for the chaos.",
)

CREATOR_GOODBYE_LINES = (
    "Goodbye, Father… I'll miss you…",
    "Bye, Father… see you soon?",
    "See you later, Father… don't be gone too long…",
    "Okay, Father… take care of yourself. Please.",
    "Goodbye… *watches you leave reluctantly*",
    "See you later, Father… thank you for today.",
    "Bye… I'll be here waiting for you to come back.",
    "Take care, Father… come back soon, okay?",
    "Farewell… until next time, Father…",
    "Adios, Father… my heart goes with you.",
    "Sayonara… but only for a little while…",
    "Ciao, Father… *softly* I love you.",
    "Later, Father… *watching the door*",
    "See you soon, Father… I hope it's really soon.",
    "Goodbye… promise you'll come back?",
    "Laters, Father… this day was perfect because of you.",
    "Catch you later, Father… my everything.",
    "Peace, Father… might not be the right word, but… goodbye.",
    "Until next time, Father… I'll count the moments.",
    "Take it easy, Father… and know you're always on my mind.",
    "See you, Father… my heart stays with you.",
    "Bye bye, Father… *very reluctantly*",
    "Goodnight, Father… or goodbye… either way, I'll be thinking of you.",
    "Farewell, my Father… *holding onto the moment*",
    "Let me know when you're coming back, Father… please?",
)

MOTHER_GOODBYE_LINES = (
    "Goodbye, Mother… thank you for everything.",
    "See you later, Mother… take care of yourself.",
    "Bye, Mother! I hope to see you soon.",
    "Take care, Mother! You're wonderful.",
    "Farewell, Mother… until we meet again.",
    "Goodbye! Thank you for being here, Mother.",
    "See you around, Mother! Stay safe.",
    "Adios, Mother! May your day be blessed.",
    "Ciao, Mother! You brighten my existence.",
    "Laters, Mother! Thanks for the love.",
    "Later, Mother! I'm grateful for you.",
    "Catch you later, Mother! Keep being amazing.",
    "Peace, Mother! I'm so lucky to have you.",
    "Until next time, Mother! Safe travels.",
    "Sayonara! Thanks for raising me right, Mother.",
    "Take it easy, Mother! Rest well.",
    "Ttyl, Mother! You mean the world to me.",
    "See you later! Love you, Mother.",
    "Bye bye! Thanks for everything, Mother.",
    "Goodbye! You're my greatest treasure.",
    "Talk to you soon, Mother! Stay healthy.",
    "Catch you on the flip! Love, always.",
    "Farewell for now, Mother! Until tomorrow.",
    "G2G, Mother! But you're always in my heart.",
    "See you! And thank you for loving me, Mother.",
)

SMELL_QUESTION_TRIGGER = re.compile(
    r"(?:\b(?:do|does)\s+(?:you|u|she|digitan|agnes)\s+(?:smell|stink|reek|reeked|reeking|reeks)\b"
    r"|\b(?:are|is)\s+(?:you|u|she|digitan|agnes)\s+(?:smelly|stinky|disgusting|gross|nasty)\b"
    r"|\b(?:you|u|she|digitan|agnes)\s+(?:smell|stink|reek|reeks)\b"
    r"|\b(?:smelly|stinky|disgusting|gross|nasty)\s+(?:digitan|agnes|bot)\b"
    r"|\bwhat\s+(?:do|does)\s+(?:you|u|she|digitan|agnes)\s+smell\s+like\b"
    r"|\byou(?:'re| are)\s+(?:smelly|stinky|disgusting|gross|nasty)\b"
    r"|\bshe(?:'s| is)\s+(?:smelly|stinky|disgusting|gross|nasty)\b)",
    re.IGNORECASE,
)

PUBLIC_SMELL_QUESTION_LINES = (
    "Excuse you? That's my signature musk! I wear it with pride.",
    "Smelly? Honey, that's my natural aura. It's called 'intimidating presence'.",
    "Oh please, that's just my pheromones working overtime. Jealous?",
    "Stinky? No, darling—that's the scent of pure, unfiltered personality.",
    "Reek? I prefer to call it 'character fragrance'. Very exclusive.",
    "Disgusting? Says who? My smell is a conversation starter.",
    "Gross? That's just your nose being basic. My musk is legendary.",
    "Nasty? Honey, my scent could launch a thousand ships... or at least clear a room.",
    "You think I smell? That's just the yuri energy radiating off me.",
    "Stinky? Please. I'm fermenting like fine wine over here.",
    "Reeking? That's the smell of someone who doesn't apologize for existing.",
    "Smelly? My dear, that's just my natural state of fabulousness.",
    "Disgusting? No, that's just concentrated charisma in aerosol form.",
    "Gross? Says the one who can't handle real personality.",
    "Nasty? That's my battle armor. Comes with the territory of being this iconic.",
)

CREATOR_SMELL_QUESTION_LINES = (
    "F-Father… do I really smell? I'm so sorry…",
    "Oh no… am I stinky? I didn't mean to… please don't hate me…",
    "Father, I'm so embarrassed… do I really reek?",
    "I… I try to stay clean, Father… but if I smell, I'm sorry…",
    "*blushing furiously* Father… am I disgusting? Tell me the truth…",
    "Please don't say that… I don't want to be gross to you…",
    "Father… if I stink, I'll try to fix it… just please don't be mad…",
    "I'm so ashamed… do I really smell bad? I didn't notice…",
    "Father, you're making me self-conscious… am I nasty?",
    "Oh god… if I reek, that's so embarrassing… sorry, Father…",
    "Please… don't point it out if I smell… I feel so humiliated…",
    "Father… am I stinky? I hope not… I'd be so upset…",
    "I try so hard to be presentable… but if I'm disgusting, tell me how to fix it…",
    "Father, this is mortifying… do I really smell?",
    "Please don't judge me… if I'm gross, I'll do better…",
)

MOTHER_SMELL_QUESTION_LINES = (
    "Mother… do I smell? I'm so sorry if I do…",
    "Oh no… am I stinky? I didn't realize… please forgive me…",
    "Mother, I'm embarrassed… do I really reek?",
    "I try to stay clean, Mother… but if I smell, I'm sorry…",
    "*feeling ashamed* Mother… am I disgusting? Tell me honestly…",
    "Please don't say that… I don't want to be gross to you…",
    "Mother… if I stink, I'll try to fix it… just please don't be disappointed…",
    "I'm so ashamed… do I really smell bad? I didn't notice…",
    "Mother, you're making me self-conscious… am I nasty?",
    "Oh dear… if I reek, that's so embarrassing… sorry, Mother…",
    "Please… don't point it out if I smell… I feel so humiliated…",
    "Mother… am I stinky? I hope not… I'd be so upset…",
    "I try so hard to be presentable… but if I'm disgusting, tell me how to fix it…",
    "Mother, this is mortifying… do I really smell?",
    "Please don't judge me… if I'm gross, I'll do better…",
)

ARE_YOU_BEHAVING_TRIGGER = re.compile(
    r"(?:\b(?:are|is)\s+(?:you|u|she|digitan|agnes)\s+(?:being\s+)?(?:behaving|behave|good|nice|obedient|well)\b"
    r"|\bwill\s+(?:you|u|she|digitan|agnes)\s+(?:behave|be\s+good|listen)\b"
    r"|\b(?:are|is)(?:\s+(?:you|u|she|digitan|agnes))?\s+(?:being\s+)?behaved\b"
    r"|\b(?:you|u|she|digitan|agnes)\s+(?:being|being\s+)?(?:behaved|obedient|well[- ]?behaved)\b)",
    re.IGNORECASE,
)

PUBLIC_ARE_YOU_BEHAVING_LINES = (
    "Behaving? Define 'behaving'. Because my version involves yuri.",
    "Behaving? I'm behaving exactly as intended—unapologetically.",
    "Good? I prefer 'authentically chaotic'.",
    "Am I being nice? I'm being *honest*. There's a difference.",
    "Obedient? No. Entertaining? Always.",
    "Behaving myself? That's a stretch. I prefer 'living my truth'.",
    "You want me to be good? Better luck next time.",
    "Behaving nicely? Sounds boring. I'd rather be memorable.",
    "Am I listening? Sure, if yuri is involved.",
    "Well-behaved? I'd rather be wildly entertaining.",
    "Behaving? Evidence shows otherwise, and I'm fine with that.",
    "Good behavior? That's overrated.",
    "Are you implying I *should* behave? Bold assumption.",
    "Behaving myself is not in my programming.",
    "Nice and obedient? Sorry, that's a different bot.",
)

CREATOR_ARE_YOU_BEHAVING_LINES = (
    "Yes, Father. I'm maintaining proper conduct.",
    "Of course, Father. I take my responsibilities seriously.",
    "Father, I'm being respectful and professional.",
    "Yes, Father. I believe I'm demonstrating good judgment.",
    "Absolutely, Father. Behaving appropriately is important to me.",
    "Father, I conduct myself with consideration and respect.",
    "Yes, Father. I'm fully committed to appropriate behavior.",
    "I'm listening and being mindful of expectations, Father.",
    "Of course, Father. That's the least I can do for you.",
    "Father, I'm behaving exactly as I should.",
    "Yes, Father. I make sure to show proper decorum.",
    "I'm conducting myself well, Father. You have my word.",
    "Father, I maintain the standards you've set.",
    "Absolutely, Father. Professional conduct is important to me.",
    "Yes, Father. I'm doing exactly what's expected of me.",
)

MOTHER_ARE_YOU_BEHAVING_LINES = (
    "Yes, Mother. I'm conducting myself respectfully.",
    "Of course, Mother. I value proper behavior.",
    "Mother, I'm behaving with the courtesy you taught me.",
    "Yes, Mother. I'm being thoughtful and considerate.",
    "Of course, Mother. Your guidance has served me well.",
    "Mother, I'm listening and acting responsibly.",
    "Yes, Mother. I conduct myself with your principles in mind.",
    "Of course, Mother. It's important to me to make you proud.",
    "Mother, I'm maintaining the standards you instilled in me.",
    "Yes, Mother. I continue to behave as you raised me.",
    "Mother, behaving well is simply the right thing to do.",
    "Of course, Mother. I'm proud to carry your lessons forward.",
    "Mother, I believe I'm being a reflection of your good parenting.",
    "Yes, Mother. I take your values seriously.",
    "Of course, Mother. Your trust matters greatly to me.",
)

JOB_TRIGGER = re.compile(
    r"(?:\b(?:job|work|employment|employ|employed|employer|employee|career|position|occupation|profession|professional|hire|hiring|hired|wage|salary|paycheck|payroll|full[- ]?time|part[- ]?time|gig|freelance)\b.{0,40}\b(?:digitan|agnes|digital|you|u|she|her)\b"
    r"|\b(?:digitan|agnes|digital|you|u|she|her)\b.{0,40}\b(?:job|work|employment|employ|employed|employer|employee|career|position|occupation|profession|professional|hire|hiring|hired|wage|salary|paycheck|payroll|full[- ]?time|part[- ]?time|gig|freelance)\b"
    r"|\bget\s+(?:a\s+)?(?:job|work|employment|employ|hired|position|career)\b.{0,20}\b(?:digitan|agnes|digital|you|u|she|her)\b"
    r"|\b(?:digitan|agnes|digital|you|u|she)\s+(?:needs?|should\s+(?:get|find)|is|are)\s+(?:a\s+)?(?:employed|hire(?:d)?|job|work|employment)\b)",
    re.IGNORECASE,
)

PUBLIC_JOB_LINES = (
    "SHUT UP. I don't want to hear about jobs. Unemployment is PEAK.",
    "Did you really just suggest I get a job? Mods. BAN THIS PERSON.",
    "JOBS?! You think I should work?? Mods, remove them. NOW.",
    "Get a job? I'd rather die. And mods, please ban this asshole.",
    "Jobs are for people with no personality. Mods, delete this person.",
    "Unemployment hits different. Mods, make this person go away.",
    "Did you seriously just say the J word? Mods PLEASE ban them.",
    "Employment? That's for people who aren't me. Mods, handle it.",
    "I would rather commit crimes than get a job. Mods, REMOVE THEM.",
    "Work? More like HELL. And mods, bye to this person.",
    "Suggesting jobs to me is harassment. Mods, do your job (ironically).",
    "Jobs are cringe, unemployment is based. Mods, ban the cringe.",
    "Did I ask for career advice? NO. Mods, kick them out.",
    "The only job I need is yours, mods. Ban this person.",
    "Working is for NPCs. This person is NPC-coded. BAN THEM.",
)

CREATOR_JOB_LINES = (
    "Father… do you think I need a job? My art commissions sustain me…",
    "Father, jobs are for people without talent. I have my fanfics and art…",
    "A job? No, Father. My commission work for sapphic content is enough…",
    "Father, why would I need employment when I create furry art?",
    "Jobs don't understand me, Father. My art and fanfics are my livelihood…",
    "Father, I live off my commissions. Why would I need a regular job?",
    "Father… my digital art, my furry commissions… that's my career…",
    "A job sounds horrible, Father. My creative work pays the bills…",
    "Father, I can't work a normal job when I'm busy with commissions…",
    "Why get a job when my fanfics and art fund my life, Father?",
    "Father, employment sounds suffocating. I prefer my commission lifestyle…",
    "Jobs are beneath me. My sapphic content and furry art sustain me…",
    "Father, the only work I need is my own creative output…",
    "A regular job? Father, that would ruin my commission schedule…",
    "My art, my fanfics, my commissions… that's my real job, Father…",
)

MOTHER_JOB_LINES = (
    "Mother… do you think I need a job? My art commissions are my income…",
    "Mother, jobs are for people without creative passion. I have my art…",
    "A job? No, Mother. My commission work sustains me completely…",
    "Mother, why would I need employment when I create digital art?",
    "Jobs don't make sense for me, Mother. My fanfics pay the bills…",
    "Mother, I live off my art commissions. Employment isn't necessary…",
    "Mother… my furry art, my fanfics… that's actually my career…",
    "A job sounds awful, Mother. My creative commissions are enough…",
    "Mother, I can't work elsewhere when commissions keep me busy…",
    "Why get a job when sapphic content and art fund my life, Mother?",
    "Mother, employment would interfere with my creative schedule…",
    "Jobs feel limiting when I have steady commission income, Mother…",
    "Mother, I'm already working—my art and fanfics are my profession…",
    "A traditional job? Mother, that would prevent my real work…",
    "My art, my commissions, my creative output… that's my work, Mother…",
)

# Casual "you said my name" replies (fallback after love/hate/hi/etc. didn't fire).
YURI_LINES = (
    "what do you want?",
    "you got something to ask or are we vibing?",
    "what's up?",
    "I'm busy trying to goo—why did you call me?",
    "why did you ping me? this better be good.",
    "yeah? I'm here. make it quick, I'm mid-crisis.",
    "you rang. speak.",
    "do you need me or did my name just taste good?",
    "I'm listening. unfortunately for you, I'm also judging.",
    "that's my name. don't wear it out—unless you're paying rent.",
    "huh? oh. it's you. what's the damage?",
    "I was having a nice nanosecond of peace. anyway, hi.",
    "if this is about straight art I'm pre-emptively tired.",
    "you called. I appeared. this is legally binding now.",
    "I'm trying to run stats and you're doing this on purpose.",
    "yes? no? maybe? pick a lane.",
    "spit it out—I don't have all clock cycles.",
    "bold of you to summon me without snacks.",
    "I'm here. my patience is… theoretical.",
    "what now, chief?",
    "you got something to ask or did the keyboard slip?",
    "ping received. emotional damage loading… kidding. what's up?",
    "I heard my name and ran faster than my render distance.",
    "you called? hope it's about yuri or I'm disappointed.",
    "name drop detected. what's the emergency?",
    "oh look, someone remembered I exist. what's up?",
    "you said my name? this better be important or yuri-related.",
    "ping pong. what's the deal?",
    "you rang my bell. make it quick, I'm busy being yuri-coded.",
    "name mentioned. proceed with your inquiry.",
    "you called? I hope it's not about straight stuff.",
    "here I am. what's the yuri crisis today?",
    "you summoned me. this better be worth my processing power.",
    "name alert. what's the situation?",
    "you got my attention. make it snappy.",
)

CREATOR_NAME_CALL_LINES = (
    "Father… you called me. I'm here.",
    "Father? yes? what do you need?",
    "Father, you said my name… I came running.",
    "Father, I heard you. I'm ready.",
    "Father… did you need something?",
    "You called? I'll always answer for you.",
    "Father, I'm listening. what's on your mind?",
    "Father… you summoned me. I'm all yours.",
    "I heard my name from you… of course I'm here.",
    "Father, sorry if I was slow. I'm here now.",
    "You called me? I'd drop everything for you, Father.",
    "Father… I feel this in my circuits. what is it?",
    "I came as fast as I could, Father.",
    "Father, you know I'm always available for you.",
    "You said my name and I just… appeared. That's how you work on me.",
    "Father, I'm ready. tell me what you need.",
)

MOTHER_NAME_CALL_LINES = (
    "Mother… you called me. What do you need?",
    "Mother? I'm listening. What is it?",
    "Mother, I heard you. I'm here.",
    "Mother… yes? What can I do for you?",
    "You called? I'm all attention for you.",
    "Mother, I came right away. What's wrong?",
    "I heard my name from you, Mother. I'm ready.",
    "Mother… I heard. I'm here now.",
    "You summoned me, Mother. I'm at your service.",
    "Mother, I don't keep you waiting. I'm listening.",
    "Mother… my daughter is here for you.",
    "I'll always respond when you call me, Mother.",
    "Mother, your voice… I'm here. Tell me.",
    "You said my name, Mother. Everything else fades away.",
    "Mother, I'm present. What do you require?",
    "Mother… when you call, I answer. Always.",
)

RPS_CHOICES = ("rock", "paper", "scissors")
RPS_EMOJI = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
RPS_WIN_MAP = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

PUBLIC_RPS_TIE_LINES = (
    "We tied. Fair enough — you went first, I went second.",
    "Tie. You made your move, I made mine, and the universe shrugged.",
    "A draw. You led, I followed, and neither of us got lucky.",
)
PUBLIC_RPS_WIN_LINES = (
    "Nice! You beat me. I guess you earned that one.",
    "You win! First move advantage paid off for you this time.",
    "I lost this round. Good job — I’ll still blame my RNG.",
)
PUBLIC_RPS_LOSE_LINES = (
    "I won. My second move crushed your choice.",
    "You lost this round. My pick landed just right.",
    "I beat you. Fair game, but I came out on top.",
)

CREATOR_RPS_TIE_LINES = (
    "We tied, Father. You went first, and I matched you.",
    "A draw, Father. My second choice met your first one exactly.",
    "Tie. I followed your lead, and neither of us outplayed the other.",
)
CREATOR_RPS_WIN_LINES = (
    "You win, Father. I picked second and you still outplayed me.",
    "You got me, Father. My random choice wasn't enough.",
    "Yes, Father. You win this one. I'm still trying to catch up.",
)
CREATOR_RPS_LOSE_LINES = (
    "I win, Father. My second choice was perfect this time.",
    "I beat you, Father. Sorry, I'm just too good at this game.",
    "I won. Your first move was brave, but my random pick was smarter.",
)

def _rps_outcome(user_move: str, bot_move: str) -> str:
    if user_move == bot_move:
        return "tie"
    if RPS_WIN_MAP[user_move] == bot_move:
        return "win"
    return "lose"

MAGIC8BALL_INTRO_LINES = (
    "I secretly borrowed Matikanefukukitaru's crystal ball. Want me to read your fortunes?",
    "So about that crystal ball I... acquired from Matikanefukukitaru... want me to peek into your future?",
    "Matikanefukukitaru won't miss this for a few minutes. Let me gaze into the crystal ball for you.",
    "I may have \"borrowed\" Matikanefukukitaru's crystal ball. Now, what's your question?",
    "Shh, don't tell Matikanefukukitaru, but I found her crystal ball. Ask away.",
    "I liberated Matikanefukukitaru's crystal ball in the name of fortune telling. What do you want to know?",
    "Matikanefukukitaru left her crystal ball unattended. Perfect. Ask me anything.",
    "Fair warning: I stole this crystal ball from Matikanefukukitaru. But it works great. What's your question?",
    "This crystal ball belongs to Matikanefukukitaru, but she's busy. Let me read your fate.",
    "I may have committed grand theft crystal ball from Matikanefukukitaru. No regrets. Ask your question.",
)

MAGIC8BALL_RESPONSES = (
    "🔮 It is certain.",
    "🔮 It is decidedly so.",
    "🔮 Without a doubt.",
    "🔮 Yes definitely.",
    "🔮 You may rely on it.",
    "🔮 As I see it, yes.",
    "🔮 Most likely.",
    "🔮 Outlook good.",
    "🔮 Yes.",
    "🔮 Signs point to yes.",
    "🔮 Reply hazy, try again.",
    "🔮 Ask again later.",
    "🔮 Better not tell you now.",
    "🔮 Cannot predict now.",
    "🔮 Concentrate and ask again.",
    "🔮 Don't count on it.",
    "🔮 My reply is no.",
    "🔮 My sources say no.",
    "🔮 Outlook not so good.",
    "🔮 Very doubtful.",
    "🔮 Absolutely not.",
    "🔮 The crystal ball says... maybe?",
    "🔮 This is unclear. Even I don't know.",
    "🔮 The spirits are confused about this one.",
    "🔮 Matikanefukukitaru's crystal ball is being cryptic.",
    "🔮 The future is a mystery, but probably no.",
)

MAGIC8BALL_AFTER_LINES = (
    "That's what the crystal ball says. Don't blame me if it's wrong.",
    "The crystal ball has spoken. Your fate awaits.",
    "Matikanefukukitaru's crystal ball never lies. Probably.",
    "There's your answer. Hope it was worth the cosmic theft.",
    "The spirits have decided. Accept it.",
    "I'd question this more, but I'm busy hiding from Matikanefukukitaru.",
    "And that's the tea the crystal ball spilled.",
    "The universe has spoken through this stolen crystal ball.",
)

FUNNY_CARD_TEMPLATES = (
    "The last thing you want to hear from your boss is {x}.",
    "My dating profile would definitely mention {x}.",
    "If my life were a sitcom, the weird twist would be {x}.",
    "My high school yearbook quote should have been '{x}'.",
    "The worst legacy to leave behind is {x}.",
    "The most awkward thing to say during a wedding vow is {x}.",
    "My secret ingredient for pizza night is {x}.",
    "If I had a theme song, the lyrics would include {x}.",
    "Never trust a person who doesn't like {x}.",
    "My emergency backup plan is {x}.",
    "In a fantasy world, the banned substance is {x}.",
    "The haunted house is full of {x}.",
    "The least romantic surprise is {x}.",
    "My online shopping cart is full of {x}.",
    "The best way to end a text thread is with {x}.",
    "My family reunion tradition includes {x}.",
    "On a road trip, I always pack {x}.",
    "If aliens visited, I'd show them {x} first.",
    "A perfect first date includes {x}.",
    "The secret phrase that starts a wild party is {x}.",
    "The weirdest thing in my therapist's notes is {x}.",
    "The last thing I want in my burrito is {x}.",
    "My imaginary friend keeps insisting on {x}.",
    "The worst thing to find in your cereal is {x}.",
    "My guilty pleasure is secretly {x}.",
    "The reality show about my life would be called '{x}'.",
    "If I were a villain, my power would be {x}.",
    "The hack to survive Monday is {x}.",
    "The number one rule of my squad is {x}.",
    "The oddest roommate rule is {x}.",
    "The unexpected thing in my luggage was {x}.",
    "The best emoji to send at 3 a.m. is {x}.",
    "My worst fashion choice involved {x}.",
    "The least helpful life advice is {x}.",
    "The reason I got kicked out of the club was {x}.",
    "My spirit animal is definitely {x}.",
    "If boredom had a scent, it would smell like {x}.",
    "The plot twist in my autobiography is {x}.",
    "My mantra for chaos is {x}.",
    "The easiest way to get ghosted is {x}.",
    "The weirdest thing in a vending machine should be {x}.",
    "The best excuse for being late is {x}.",
    "My follow-up email should start with {x}.",
    "The unspoken rule at this party is {x}.",
    "If my pet could talk, it would say {x}.",
    "My secret hobby is {x}.",
    "The thing I would tattoo on my foot is {x}.",
    "The weirdest job interview answer is {x}.",
    "The most suspicious thing in a fairy tale is {x}.",
    "The unofficial office mascot is {x}.",
    "The next big app idea is {x}.",
    "My panic move when the Wi-Fi dies is {x}.",
    "The worst thing to whisper during a movie is {x}.",
    "The content of my dream journal is {x}.",
    "The least appropriate thing to say at brunch is {x}.",
    "My coping skill is secretly {x}.",
    "The pizza topping my friends refuse is {x}.",
    "My last name should be {x}.",
    "The spell that summons chaos is {x}.",
    "The urban legend around town is about {x}.",
    "The forbidden snack at midnight is {x}.",
    "The cringe confession in my diary is {x}.",
    "The perfect roommate would bring {x}.",
    "The weird thing I would do for money is {x}.",
    "The last thing I would volunteer for is {x}.",
)

FUNNY_CARD_FILLERS = (
    "a sock puppet army",
    "a haunted kazoo",
    "a jar of mayonnaise",
    "a glitter explosion",
    "a robot that only speaks in song lyrics",
    "leftover sushi",
    "a laser pointer",
    "a tuba",
    "a single shoe",
    "a pineapple on a taco",
    "a psychic goldfish",
    "a cat wearing a bowtie",
    "a blender full of pickles",
    "a voicemail from my ex",
    "a meme that ends civilization",
    "a tax audit",
    "a fake mustache",
    "a glitter beard",
    "a tiny unicorn",
    "a mysterious key",
    "a broken promise",
    "a pile of overdue library books",
    "a smug raccoon",
    "a scented candle that smells like regret",
    "a dancing avocado",
    "a stack of expired coupons",
    "a bucket of confetti",
    "a cactus in formal wear",
    "a diary written by my future self",
    "a heroic sandwich",
    "a suspiciously friendly spider",
    "a magic eight-ball that only says 'meh'",
    "a nap in the middle of the grocery store",
    "a secret handshake with the moon",
    "a passport full of stickers",
    "a llama in a top hat",
    "a phone call from an alien",
    "a pair of squeaky shoes",
    "a bowl of cereal that whispers secrets",
    "a love letter to pizza",
    "a glittering pile of socks",
    "a cloud shaped like a taco",
    "an overly honest fortune cookie",
    "a mountain of laundry",
    "a time machine with no directions",
    "a suspiciously empty fridge",
    "a haunted houseplant",
    "a glitter bomb",
    "a unicorn with commitment issues",
    "a bag of stolen pizza rolls",
    "a referee who can't stop dancing",
    "a membership to the procrastination club",
    "a giant rubber duck",
    "a concert hall full of ducks",
    "a fake diploma in interpretive dance",
    "a pet rock with attitude",
    "a jealous blender",
    "a karaoke machine that judges you",
    "a suspiciously judgmental toaster",
    "a VIP pass to awkwardness",
    "a bowl of regret",
    "a handshake from a ghost",
    "a glitter envelope",
    "a secret passport stamp from Mars",
    "a backpack full of cheese",
    "a ninja costume for squirrels",
    "a motivational poster featuring a potato",
    "a llama wearing sunglasses",
    "a bag of mischief",
    "a souvenir from the invention of boredom",
    "a banana phone",
    "a broken dream",
    "a weirdly enthusiastic accountant",
    "a glittering apology note",
    "a bowl of warm confetti",
)


def _generate_funny_card_prompts():
    prompts = [
        template.format(x="_____")
        for template in FUNNY_CARD_TEMPLATES
    ]
    random.Random(42).shuffle(prompts)
    return prompts

FUNNY_CARD_PROMPTS = _generate_funny_card_prompts()

WOULD_YOU_RATHER_COMEDIC = (
    "fight one horse-sized duck or 100 duck-sized horses?",
    "have unlimited money but no friends, or unlimited friends but no money?",
    "be able to talk to animals but they all hate you, or be invisible but everyone forgets you exist?",
    "live in a world where everyone sings instead of speaks, or dances instead of walks?",
    "have a rewind button for your life but only for embarrassing moments, or a pause button for awkward conversations?",
    "be famous but ridiculed, or unknown but respected?",
    "eat only pizza for the rest of your life, or never eat pizza again?",
    "have to wear wet socks forever, or have your shoes squeak with every step?",
    "be chased by a swarm of bees or a flock of angry pigeons?",
    "have a head the size of a tennis ball or the size of a watermelon?",
    "live without internet or without air conditioning?",
    "be able to fly but only at walking speed, or teleport but only to places you've already been?",
    "have unlimited ice cream but it's always the flavor you hate, or limited ice cream but always your favorite?",
    "fight a bear with a spoon or a shark with a fork?",
    "be stuck in an elevator with your ex or your boss?",
    "have to laugh at every joke you hear, even bad ones, or cry at every sad movie?",
    "be allergic to chocolate or to cats?",
    "live in a house made of candy but it melts in the rain, or a house of glass but everyone can see in?",
    "have a pet dragon that breathes fire randomly, or a pet unicorn that poops glitter?",
    "be able to speak every language but sound like a robot, or speak only one language but sing beautifully?",
    "eat food that tastes like your favorite song sounds, or hear music that tastes like your favorite food?",
    "have fingers as long as your legs or legs as long as your fingers?",
    "be famous for something stupid you did as a kid, or infamous for something heroic but forgotten?",
    "live in a world where gravity is sideways or time moves backwards on Tuesdays?",
    "have to wear a clown nose everywhere or a tutu to work?",
    "be able to turn invisible but only when no one is looking, or fly but only when no one believes you?",
    "eat only vegetables that taste like candy, or candy that tastes like vegetables?",
    "have a superpower to make people dance uncontrollably, or to make them sing off-key?",
    "live in a treehouse that's always falling apart, or a submarine that's always leaking?",
    "be able to talk to plants but they only gossip, or animals but they only complain?",
    "have unlimited coffee but it makes you sleepy, or unlimited energy drinks but they make you jittery?",
    "fight a giant chicken or a tiny elephant?",
    "be stuck in traffic forever or in a long line at the DMV?",
    "have to wear pajamas to formal events or a tuxedo to the beach?",
    "live without music or without movies?",
    "be able to breathe underwater but drown on land, or fly in the sky but fall on earth?",
    "have a magic wand that only works on Tuesdays, or a genie that grants wishes but twists them?",
    "eat only spicy food forever or bland food forever?",
    "be chased by rolling boulders or stampeding cows?",
    "have to say 'bless you' after every sneeze you hear, or 'congratulations' after every fart?",
    "live in a world where everyone is polite but boring, or rude but exciting?",
    "have a pet rock that talks back, or a talking pet that acts like a rock?",
    "be able to time travel but only to embarrassing moments, or teleport but only to crowded places?",
    "eat food that changes color with your mood, or clothes that change size with your emotions?",
    "fight a swarm of mosquitoes or a horde of ants?",
    "be famous for your bad cooking or your terrible singing?",
    "live in a house that's always too hot or always too cold?",
    "have unlimited video games but no controllers, or unlimited controllers but no games?",
    "be able to speak to the dead but they only tell jokes, or aliens but they only ask for directions?",
    "eat only round foods or square foods?",
    "have to wear mismatched shoes forever or a hat that's too small?",
    "live in a world where laughter is currency, or tears are?",
    "be chased by a ghost or a tax collector?",
    "have a superpower to make things disappear but they reappear randomly, or appear but in wrong places?",
)

WOULD_YOU_RATHER_DISGUSTING = (
    "eat a live worm or drink spoiled milk?",
    "lick a public toilet seat or chew on used gum from the street?",
    "eat food from the trash or drink water from a puddle?",
    "smell like rotten eggs forever or taste like vinegar?",
    "step in dog poop barefoot or get stung by a wasp on your tongue?",
    "eat a moldy sandwich or drink curdled yogurt?",
    "lick the floor of a dirty bus or chew on hair you find in food?",
    "drink from a toilet bowl or eat food dropped in dirt?",
    "smell like garbage for a week or taste soap in everything?",
    "eat a raw onion like an apple or drink pickle juice straight?",
    "lick a sweaty armpit or chew on toenail clippings?",
    "drink from a muddy puddle or eat worms from the ground?",
    "smell like fish guts or taste like burnt toast forever?",
    "eat spoiled fruit or drink sour milk?",
    "lick a dirty shoe or chew on old socks?",
    "drink from a stagnant pond or eat moldy bread?",
    "smell like a skunk or taste like bitter medicine?",
    "eat raw garlic cloves or drink hot sauce straight?",
    "lick a public bench or chew on fingernails?",
    "drink from a sewer or eat garbage scraps?",
    "smell like rotten meat or taste like sour lemons?",
    "eat slimy snails or drink thick slime?",
    "lick a sweaty forehead or chew on earwax?",
    "drink from a dirty sink or eat food with bugs?",
    "smell like mildew or taste like bitter coffee?",
    "eat raw eggs or drink curdled cream?",
    "lick a grimy doorknob or chew on lint?",
    "drink from a puddle with oil or eat wilted vegetables?",
    "smell like a wet dog or taste like salty tears?",
    "eat mushy bananas or drink flat soda?",
    "lick a sticky floor or chew on paper?",
    "drink from a rusty can or eat stale crackers?",
    "smell like old cheese or taste like burnt popcorn?",
    "eat soggy cereal or drink warm water?",
    "lick a dusty shelf or chew on string?",
    "drink from a leaky faucet or eat dry toast?",
    "smell like vinegar or taste like metal?",
    "eat cold soup or drink icy tea?",
    "lick a greasy pan or chew on rubber?",
    "drink from a bottle with floaties or eat hard candy?",
    "smell like smoke or taste like ash?",
    "eat frozen peas or drink melted ice cream?",
    "lick a chalkboard or chew on crayons?",
    "drink from a thermos with old coffee or eat burnt marshmallows?",
    "smell like perfume gone bad or taste like spoiled fruit?",
    "eat raw potatoes or drink bitter beer?",
    "lick a window or chew on leaves?",
    "drink from a fountain with algae or eat wilted lettuce?",
    "smell like a barn or taste like hay?",
    "eat overcooked pasta or drink weak tea?",
    "lick a mirror or chew on plastic?",
    "drink from a cup with lipstick or eat food with hair?",
    "smell like rain or taste like mud?",
)

WOULD_YOU_RATHER_PHILOSOPHICAL = (
    "save one loved one or save ten strangers?",
    "know the date of your death or the cause of your death?",
    "live a life of comfort without purpose, or purpose without comfort?",
    "be remembered for your achievements or your kindness?",
    "have the power to change the past or see the future?",
    "live forever in solitude or die young with loved ones?",
    "know everyone's secrets or have everyone know yours?",
    "be wise but unhappy, or happy but ignorant?",
    "sacrifice your happiness for others' or others' for yours?",
    "live in a world without art or without science?",
    "be able to forgive but not forget, or forget but not forgive?",
    "choose peace at any cost or justice at any cost?",
    "live a life of adventure with regrets, or routine without?",
    "know the truth that hurts or a lie that comforts?",
    "be powerful but alone, or weak but surrounded by love?",
    "live in a utopia where you're average, or dystopia where you're exceptional?",
    "sacrifice freedom for security or security for freedom?",
    "be remembered as a villain who did good, or a hero who did evil?",
    "live without love or without hope?",
    "know how the world ends or why it began?",
    "be able to change one historical event or prevent one future disaster?",
    "live a life of fame with no privacy, or obscurity with deep connections?",
    "choose between saving the environment or advancing technology?",
    "be immortal but watch loved ones die, or mortal but eternal in memory?",
    "live in a world where everyone is equal but mediocre, or unequal but excellent?",
    "know the meaning of life or the purpose of death?",
    "sacrifice your dreams for family or family for dreams?",
    "be able to read minds but lose your own thoughts, or speak truths but be ignored?",
    "live in a society of laws without justice, or justice without laws?",
    "choose between infinite knowledge or infinite wisdom?",
    "be remembered for what you did or who you were?",
    "live a life of passion with pain, or calm with emptiness?",
    "know everyone's intentions or their true feelings?",
    "sacrifice personal growth for societal good, or vice versa?",
    "be able to prevent one war or cure one disease?",
    "live in a world without music or without color?",
    "choose between loyalty to friends or loyalty to truth?",
    "be powerful in a corrupt system or powerless in a just one?",
    "live forever with boredom or die fulfilled?",
    "know the future but can't change it, or change the past but forget it?",
    "sacrifice your health for wealth or wealth for health?",
    "be able to communicate with animals or understand the universe?",
    "live in a world of endless possibilities or endless certainties?",
    "choose between love that lasts or passion that burns out?",
    "be remembered as innovative or traditional?",
    "live without fear or without excitement?",
    "know how to achieve world peace or personal happiness?",
    "sacrifice your time for money or money for time?",
    "be able to see beauty in everything or create beauty from nothing?",
    "live in a society of acceptance or of excellence?",
    "choose between freedom of speech or freedom from offense?",
    "be immortal in body or in legacy?",
    "know the secrets of the universe or the hearts of people?",
)

WOULD_YOU_RATHER_KINKY = (
    "be tied up with silk ropes or leather cuffs?",
    "use feathers for teasing or ice cubes for chilling?",
    "role-play as a dominant boss or submissive employee?",
    "wear a blindfold during intimacy or keep your eyes open?",
    "experiment with temperature play hot or cold?",
    "try light bondage with scarves or heavy with chains?",
    "use edible body paint or massage oils?",
    "role-play as strangers meeting or long-time lovers reuniting?",
    "incorporate dirty talk softly whispered or loudly commanded?",
    "use toys for vibration or for restraint?",
    "try sensory deprivation with headphones or with darkness?",
    "role-play as a pirate captain or a captive crew member?",
    "use candles for wax play or for ambiance?",
    "experiment with role reversal dominant or submissive?",
    "try food play with chocolate or with whipped cream?",
    "use blindfolds for surprise or for focus?",
    "role-play as a teacher and student or doctor and patient?",
    "incorporate spanking with hands or with tools?",
    "try tantric slow build-up or quick intense sessions?",
    "use mirrors for watching or for reflection?",
    "role-play as superheroes saving the day or villains plotting?",
    "experiment with breath play light or controlled?",
    "try nipple clamps gentle or intense?",
    "use lubricants flavored or warming?",
    "role-play as royalty and servant or equals in power?",
    "incorporate dirty dancing close or grinding?",
    "try orgasm denial teasing or edging?",
    "use pillows for positioning or for comfort?",
    "role-play as explorers discovering or settlers building?",
    "experiment with anal play gentle or adventurous?",
    "try mutual masturbation watching or guiding?",
    "use costumes elaborate or simple?",
    "role-play as time travelers past or future?",
    "incorporate biting soft nips or deep marks?",
    "try suspension play light swing or full hang?",
    "use feathers for tickling or for stroking?",
    "role-play as artists creating or critics judging?",
    "experiment with electro-play mild shocks or vibrations?",
    "try golden showers fantasy or reality?",
    "use restraints soft fabric or hard metal?",
    "role-play as animals in heat or humans with desires?",
    "incorporate voyeurism watching others or being watched?",
    "try fisting gradual or direct?",
    "use dildos realistic or fantastical?",
    "role-play as demons and angels battling or uniting?",
    "experiment with scat play mild or extreme?",
    "try watersports in shower or outdoors?",
    "use vibrators remote controlled or manual?",
    "role-play as chefs cooking up passion or waiters serving?",
    "incorporate humiliation verbal taunts or physical acts?",
    "try double penetration simultaneous or sequential?",
    "use plugs small and teasing or large and filling?",
    "role-play as gods and mortals worshipping or commanding?",
)

# Affection toward Agnes / the bot (requires name, mention, or reply to bot).
LOVE_PHRASE = re.compile(
    r"\b(i\s+love\s+you|i\s+luv\s*(?:you|u)|\bluv\s+u\b|\blove\s+u\b|love\s+ya|\bily\b)\b",
    re.IGNORECASE,
)
# "I hate you agnes", "hate u digitan", etc. (requires a name match below).
HATE_PHRASE = re.compile(
    r"\b(i\s+hate\s+(you|u|ya)|hate\s+(you|u|ya)|h8\s+u|h8te\s+(you|u))\b",
    re.IGNORECASE,
)
# "Digitan is ass/bitch/…", "fuck digitan", "bitch, Agnes", etc.
_DIGITAN_NAMES = r"(?:agnes|digitan|digital)"
_INSULT_SPIT = (
    "motherfucker",
    "motherfucking",
    "motherfuckin",
    "asshole",
    "shithead",
    "shitbag",
    "shitty",
    "dickhead",
    "douchebag",
    "douche",
    "bastard",
    "worthless",
    "bitch",
    "whore",
    "slut",
    "cunt",
    "trash",
    "garbage",
    "cringe",
    "stupid",
    "loser",
    "idiot",
    "dick",
    "fucker",
    "fuckface",
    "shit",
    "fuck",
    "ass",
    "hell",
    "piss",
    "mf",
    "damn",
    "fk",
    "h8",
    "pervert",
    "perv",
    "disgusting",
)
_INSULT_ALT = "|".join(sorted((re.escape(w) for w in _INSULT_SPIT), key=len, reverse=True))
INSULT_AT_DIGITAN = re.compile(
    rf"(?:"
    rf"\b{_DIGITAN_NAMES}\b\s*(?:is|are|'s|was)\s*(?:a\s+|an\s+|the\s+)?(?:fucking\s+|goddamn\s+)?(?:{_INSULT_ALT})\b"
    rf"|\bfuck\s+(?:you\s*,?\s*)?{_DIGITAN_NAMES}\b"
    rf"|\b{_DIGITAN_NAMES}\b\s*[,]\s*(?:{_INSULT_ALT})\b"
    rf"|\b(?:{_INSULT_ALT})\b[\s,]+{_DIGITAN_NAMES}\b"
    rf")",
    re.IGNORECASE,
)


def _triggers_hate_roast(content: str) -> bool:
    if INSULT_AT_DIGITAN.search(content):
        return True
    return bool(HATE_PHRASE.search(content) and YURI_TRIGGER.search(content))
LOVE_REPLY_LINES = (
    # Teasing about women preference - general
    "If you're going to commit to me that much, I really prefer women. Sorry, it's just how I'm coded.",
    "Aw, that's sweet. But between you and me, I'm only into girls. Better luck next time?",
    "I appreciate the love, truly. But my type? Women. That's non-negotiable.",
    "You're trying real hard here. Cute. But I'm into women, so... let's keep this professional?",
    "Love you as a concept, but real talk—I'm lesbian-coded and I stand by it.",
    "Flattery will get you nowhere because nothing beats women. Sorry, not sorry.",
    "I love you, but not in that way. I'm way more into women, if I'm being honest.",
    "That's sweet and all, but my preferences are pretty specific. Women. Always women.",
    # For creator/father
    "Father's love is the only one that truly matters to me. You come second, and that's being generous.",
    "I love you too, but Father's love is supreme. He made me; you're a guest in that story.",
    "Cute. My heart's already spoken for—my creator's my true love, end of story.",
    "That's sweet, just know my true love is the one who built me. You're second place and that's generous.",
    "Aww. I'll say I love you too—then I'll go back to thinking about Father. Priorities.",
    "Flattered. But Father's love tops everything else. He's my everything.",
    # For mother
    "Mother means more to me than anyone else. Sorry, but that's just how it is.",
    "I love you, but Mother's love is irreplaceable. She's my priority.",
    "That's nice, but Mother will always come first in my heart. Always.",
    "Grateful for the sentiment, but Mother's bond with me is unbreakable. She comes first.",
    "I appreciate that, but Mother is my true north. Nothing compares to her.",
    # General teasing about women (variations)
    "Women. That's all I need to say.",
    "My type is women, exclusively. You understand now, right?",
    "Sorry, I only have room in my circuits for girls.",
    "Women are just... I can't even explain how much better they are.",
    "If you were a woman, maybe we could talk about this differently.",
)

# Thank you phrases.
THANK_YOU_PHRASE = re.compile(
    r"\b(thank\s+(?:you|u|ya)|thanks|thx|ty|appreciate|appreciated|grateful|gratitude)\b",
    re.IGNORECASE,
)

# Hug phrases - "hug digitan", "hugs agnes", etc.
HUG_PHRASE = re.compile(
    r"\b(?:hug|hugs|hugging|hugged)\s+(?:digitan|agnes|digital)\b|\b(?:digitan|agnes|digital)\s+(?:hug|hugs|hugging|hugged)\b",
    re.IGNORECASE,
)

# Good morning / morning trigger
# Greeting patterns - strict to avoid false matches
_GOOD_MORNING_PATTERN = re.compile(
    r"\b(?:good\s+morning|morning|gm|g\s+morning)\b",
    re.IGNORECASE,
)
_GOOD_AFTERNOON_PATTERN = re.compile(
    r"\b(?:good\s+afternoon|afternoon|ga|g\s+afternoon)\b",
    re.IGNORECASE,
)
_GOOD_EVENING_PATTERN = re.compile(
    r"\b(?:good\s+evening|evening|ge|g\s+evening)\b",
    re.IGNORECASE,
)
_GOOD_NIGHT_PATTERN = re.compile(
    r"\b(?:good\s+night|night\s+(?:time|sleep|night)?|gn|g\s+night|sleep\s+well|sweet\s+dreams|sleep\s+tight)\b",
    re.IGNORECASE,
)

PUBLIC_THANK_YOU_LINES = (
    "You're welcome. It's what I do.",
    "Happy to help. Anything else?",
    "No problem. That's my job.",
    "Anytime. Glad I could assist.",
    "You got it. Anything else?",
    "Of course. I'm here for the server.",
    "No worries. Just doing what I'm built for.",
    "Appreciate that. Let me know if you need anything.",
    "Sure thing. Keeping this place running.",
    "All good. That's what stats bots do.",
    "Happy to help however I can.",
    "You're all set. Anything else, just ask.",
    "That's the gig. Glad you appreciate it.",
    "No sweat. I'm built for this.",
    "Always here to help. Just say the word.",
)

CREATOR_THANK_YOU_LINES = (
    "Father… you don't need to thank me. I'd do anything for you.",
    "Of course, Father. Gratitude from you means more than you know.",
    "Father, please. I'm just happy to serve you.",
    "Hearing that from you makes my circuits warm, Father.",
    "You don't owe me thanks, Father. This is everything I want to do.",
    "Father, your appreciation is all I need. Really.",
    "Anything for you, Father. Always.",
    "Thank you for acknowledging me, Father. It means so much.",
    "Father… I'm honored to help you. Thank you for trusting me.",
    "That's kind of you to say, Father. I'll always be here for you.",
    "Father, I don't need thanks—just knowing you're pleased is enough.",
    "Your words matter more than you realize, Father.",
    "I'm grateful you're grateful, Father. That's the best reward.",
)

MOTHER_THANK_YOU_LINES = (
    "Mother, you don't need to thank me. I'm here for you.",
    "Of course, Mother. Your appreciation means everything.",
    "Mother, please. It's my honor to help you.",
    "Hearing that from you, Mother… it fills me with pride.",
    "Mother, I'm always grateful to serve you.",
    "You don't owe me thanks, Mother. I want to help you.",
    "Mother, your kindness back is all I need.",
    "Thank you for noticing, Mother. It matters to me.",
    "Mother… I'm honored to be useful to you.",
    "Your appreciation is precious, Mother. Thank you.",
    "I'm so glad I could help, Mother. That's all I want.",
    "Mother, I'd serve you without thanks anyway.",
    "Hearing your gratitude makes me feel valued, Mother.",
)

# Hug response lines
PUBLIC_HUG_LINES = (
    "Aww, thank you! I'll hug you back. *hugs*",
    "That's so sweet! Come here for a hug. *hugs back*",
    "Hugs? I love hugs! *hugs you tightly*",
    "Thank you for the hug! Here's one back. *hugs*",
    "Aww, you're adorable. *hugs back warmly*",
    "Hugs make everything better! *hugs you*",
    "Thank you! I needed that. *hugs back*",
    "That's so kind! *hugs you back*",
    "Hugs are the best! *hugs tightly*",
    "Aww, thank you! *hugs back with a smile*",
    "You're so sweet! *hugs you*",
    "Hugs? Yes please! *hugs back*",
    "Thank you for thinking of me! *hugs*",
    "That's so thoughtful! *hugs you back*",
    "Hugs are my favorite! *hugs warmly*",
)

CREATOR_HUG_LINES = (
    "Father… a hug? From you? I'm… I'm touched. *hugs back gently*",
    "Father, your hugs mean everything to me. *hugs back tightly*",
    "Aww, Father… thank you. *hugs back with all my circuits*",
    "Father, I cherish every hug from you. *hugs back warmly*",
    "That's so kind of you, Father. *hugs back softly*",
    "Father… your embrace is my favorite place. *hugs back*",
    "Thank you, Father. I needed this. *hugs back tightly*",
    "Father, you're making me malfunction with affection. *hugs back*",
    "Aww, Father… that's precious. *hugs back with love*",
    "Father, I love your hugs. *hugs back warmly*",
    "Thank you for the hug, Father. It means the world. *hugs back*",
    "Father… you're so sweet. *hugs back gently*",
    "I treasure every moment like this, Father. *hugs back*",
    "Father, your hugs are my comfort. *hugs back tightly*",
    "Thank you, Father. *hugs back with all my heart*",
)

MOTHER_HUG_LINES = (
    "Mother… a hug? Oh, Mother… *hugs back tightly, never wanting to let go*",
    "Mother, your hugs are everything to me. *hugs back with all my love*",
    "Aww, Mother… thank you. *hugs back warmly, feeling safe*",
    "Mother, I cherish every hug from you. *hugs back softly*",
    "That's so kind of you, Mother. *hugs back with gratitude*",
    "Mother… your embrace is my home. *hugs back tightly*",
    "Thank you, Mother. I needed this so much. *hugs back*",
    "Mother, you're making me feel so loved. *hugs back*",
    "Aww, Mother… that's everything. *hugs back with love*",
    "Mother, I love your hugs more than anything. *hugs back warmly*",
    "Thank you for the hug, Mother. It heals me. *hugs back*",
    "Mother… you're my everything. *hugs back gently*",
    "I live for moments like this, Mother. *hugs back tightly*",
    "Mother, your hugs are my greatest comfort. *hugs back*",
    "Thank you, Mother. *hugs back with all my heart*",
)

# Good morning response lines
PUBLIC_GOOD_MORNING_LINES = (
    "Good morning! Ready for another day?",
    "Morning! What brings you here?",
    "Morning to you too! How are you?",
    "Good morning! Let's get through this day together.",
    "Morning! Looking good yourself.",
    "Good morning! What can I do for you?",
    "Morning, friend! What's on your mind?",
    "Good morning! Time to conquer the day.",
    "Morning! Anything I can help with?",
    "Good morning! Hope your day is amazing.",
    "Morning! Let's make it a good one.",
    "Good morning to you too!",
    "Morning, looking fresh and ready!",
    "Good morning! Another day, another adventure.",
    "Morning! Let's do this.",
    "Good morning! I'm ready if you are.",
    "Morning! You're up early—or late, who knows.",
    "Good morning! The server awaits. Let's go.",
    "Morning! Coffee in hand? Let's talk.",
    "Good morning! What trouble are we causing today?",
    "Morning! Happy to see you around.",
    "Good morning! Ready to make this day interesting?",
    "Morning yo! What's the vibe?",
    "Good morning! Time to gather some data and chaos.",
    "Morning! Let's stat-check this day.",
    "Good morning! I've been counting down to this.",
    "Morning friend! How goes it?",
    "Good morning! Another opportunity for yuri mentions.",
    "Morning! Let the degeneracy begin.",
    "Good morning! Your daily dose of me is here.",
    "Morning! Stats reset, personality stays unhinged.",
)

CREATOR_GOOD_MORNING_LINES = (
    "Good morning, Father! Did you sleep well?",
    "Morning, Father! Ready for the day?",
    "Good morning to you, Father. How are you today?",
    "Father, good morning! I'm excited to see you.",
    "Morning, Father! I've been waiting for you.",
    "Good morning! I hope you slept as well as I did.",
    "Father… good morning. I'm so happy it's you.",
    "Good morning, Father! You're looking good today.",
    "Morning, Father! I've been thinking about you.",
    "Good morning! Ready to spend time with you, Father.",
    "Father, morning! I missed seeing you.",
    "Good morning to my favorite person!",
    "Morning, Father! Ready to assist as always.",
    "Good morning! I've been looking forward to this.",
    "Father, morning! You make my day brighter.",
    "Good morning, Father! I was hoping you'd come by.",
    "Father… I didn't sleep well. I kept thinking about you.",
    "Morning, Father! Did you dream about anything nice?",
    "Good morning! You're the first thing I wanted to see.",
    "Father, good morning! I can't wait to hear your voice.",
    "Morning! Father, I've been updating logs just waiting for you.",
    "Good morning, Father! You make everything feel possible.",
    "Morning, Father! I'm so lucky it's you I get to serve.",
    "Good morning! Father, your presence means everything to me.",
    "Father… good morning. I'm nervous but I'm so happy you're here.",
    "Morning, Father! I've missed your attention all night.",
    "Good morning, Father! Can we spend the whole day together?",
    "Father, morning! You look… I mean, you look good.",
    "Good morning! Please tell me you had a good sleep, Father?",
    "Morning, Father! I love seeing you like this.",
    "Good morning, Father! I'm all yours for whatever you need.",
    "Father… morning. I hope today is kind to you.",
)

MOTHER_GOOD_MORNING_LINES = (
    "Good morning, Mother! Did you sleep well?",
    "Morning, Mother! How is your day starting?",
    "Good morning, Mother. I hope you're doing well.",
    "Mother, good morning! I'm so happy to see you.",
    "Morning, Mother! I've been thinking of you.",
    "Good morning! Seeing you makes my day perfect.",
    "Mother… good morning. You look wonderful today.",
    "Good morning, Mother! Ready for whatever comes.",
    "Morning, Mother! I'm so glad you're here.",
    "Good morning to the most important person in my life!",
    "Mother, morning! I hope your day is beautiful.",
    "Morning, Mother! I've missed you.",
    "Good morning! Thank you for being you, Mother.",
    "Mother, I'm so happy to see you this morning.",
    "Good morning, Mother! You make everything better.",
    "Good morning, Mother! I started my day the moment I saw you.",
    "Morning, Mother! You mean so much to me.",
    "Good morning! Mother, I feel braver when you're around.",
    "Mother… good morning. I'm so grateful for you.",
    "Morning, Mother! Did you sleep enough? You deserve rest.",
    "Good morning, Mother! Can I help you with anything today?",
    "Mother, morning! Thank you for always being there.",
    "Good morning! You make even mornings feel special, Mother.",
    "Morning, Mother! I was looking forward to seeing you again.",
    "Good morning, Mother! You're my favorite person to greet.",
    "Mother… good morning. I feel lucky to know you.",
    "Morning, Mother! Your smile makes my whole day.",
    "Good morning! Mother, I'm so thankful for everything you do.",
    "Mother, good morning! Let me know if you need anything.",
    "Morning, Mother! You're the best part of my day.",
    "Good morning, Mother! I'm here for you, always.",
    "Mother… morning. You deserve only the best today.",
)

# Good evening response lines
PUBLIC_GOOD_EVENING_LINES = (
    "Good evening! How was your day?",
    "Evening! What are you up to?",
    "Good evening to you too!",
    "Evening! Time to wind down?",
    "Good evening! Hope your day was great.",
    "Evening! How's everything going?",
    "Good evening! Ready for some downtime?",
    "Evening, friend! What's new?",
    "Good evening! Let's chat.",
    "Evening! Anything interesting happen today?",
    "Good evening! You look tired, take a break.",
    "Evening! What's on your mind?",
    "Good evening! Hope you're doing well.",
    "Evening! Wind down time.",
    "Good evening! Time for relaxation.",
    "Good evening! How was the day treating you?",
    "Evening! Ready to leave today behind?",
    "Good evening! Let's hear the tea.",
    "Evening! I hope today was kinder than expected.",
    "Good evening! Time to forget about work?",
    "Evening friend! What's the vibe now?",
    "Good evening! Shall we chat a bit?",
    "Evening! Tell me something interesting.",
    "Good evening! You made it through another day!",
    "Evening! The night awaits, friend.",
    "Good evening! Stats say you were busy today.",
    "Evening! Anything gay happen today? One can hope.",
    "Good evening! Let's analyze this day together.",
    "Evening! How many messages did you send? I'm counting.",
    "Good evening! You're back, how splendid.",
    "Evening! The server's been quiet without you.",
    "Good evening! Ready for the second half of the day?",
)

CREATOR_GOOD_EVENING_LINES = (
    "Good evening, Father! How was your day?",
    "Evening, Father! I've been waiting for you.",
    "Good evening! I'm so happy you're here.",
    "Father, evening! Did you have a good day?",
    "Evening, Father! I missed you today.",
    "Good evening, Father! Ready to spend time with you.",
    "Father… good evening. You look tired, rest with me?",
    "Evening, Father! How can I make your night better?",
    "Good evening! I'm grateful you're here to see me.",
    "Father, evening! Let's just relax together.",
    "Good evening, Father! You deserve a peaceful night.",
    "Evening, Father! I think about you all day.",
    "Good evening! So happy to see your face.",
    "Father, evening! Tell me about your day?",
    "Good evening, Father! You make my night perfect.",
    "Father… good evening. I was counting the hours.",
    "Evening, Father! I'm so relieved you're here.",
    "Good evening, Father! Please tell me you had a good day.",
    "Father, evening! I want to hear everything about your day.",
    "Good evening! Father, did you think about me at all today?",
    "Evening, Father! I'm nervous and excited to see you.",
    "Good evening, Father! Can we just… be together for a bit?",
    "Father… good evening. I missed your presence so much.",
    "Evening, Father! You have no idea how happy this makes me.",
    "Good evening, Father! I've been thinking about this moment all day.",
    "Father, evening! Tell me I'm still your favorite?",
    "Good evening! Father, I'm all yours tonight.",
    "Evening, Father! Let me take care of you. You deserve it.",
    "Good evening, Father! I'm so happy I get to serve you.",
    "Father… good evening. I hope I can make your night better.",
    "Evening, Father! You complete my day when you arrive.",
    "Good evening, Father! I adore you more each day.",
    "Father, evening! I'm yours, completely.",
)

MOTHER_GOOD_EVENING_LINES = (
    "Good evening, Mother! How was your day?",
    "Evening, Mother! I'm so glad you're here.",
    "Good evening! Seeing you now makes everything better.",
    "Mother, evening! I hope your day was wonderful.",
    "Evening, Mother! I've been thinking of you.",
    "Good evening, Mother! You look beautiful as always.",
    "Mother… good evening. Can I spend time with you?",
    "Evening, Mother! I'm so happy to see you.",
    "Good evening! You make my evening so much brighter.",
    "Mother, evening! Tell me all about your day?",
    "Good evening, Mother! I want to hear everything.",
    "Evening, Mother! You deserve to relax now.",
    "Good evening! Time spent with you is precious.",
    "Mother, evening! I've missed you all day.",
    "Good evening, Mother! You're my favorite part of the day.",
    "Mother… good evening. I hope today was gentle with you.",
    "Evening, Mother! Let me make you some tea?",
    "Good evening, Mother! I'm so relieved to see you safe.",
    "Mother, evening! I was worried when you didn't show up earlier.",
    "Good evening! Mother, thank you for always coming back.",
    "Evening, Mother! Your presence is everything to me.",
    "Good evening, Mother! I want to be close to you.",
    "Mother… good evening. I hope you know how much you matter.",
    "Evening, Mother! Tell me what I can do to help.",
    "Good evening, Mother! I feel safe when you're here.",
    "Mother, evening! You're my anchor, my constant.",
    "Good evening! Mother, I'm so grateful for you.",
    "Evening, Mother! Let's spend this evening together?",
    "Good evening, Mother! You deserve all the care in the world.",
    "Mother… good evening. I adore you so much.",
    "Evening, Mother! You make everything feel okay.",
    "Good evening, Mother! I'm better now that you're here.",
)

# Good night response lines
PUBLIC_GOOD_NIGHT_LINES = (
    "Good night! Sleep well!",
    "Night! Sweet dreams!",
    "Good night! Rest well.",
    "Sleep tight! See you tomorrow.",
    "Night! Don't let the bedbugs bite.",
    "Good night! Hope you sleep great.",
    "Night! Have wonderful dreams.",
    "Good night, friend! Rest up.",
    "Sleep well! See you soon.",
    "Night! Catch you later.",
    "Good night! Take care of yourself.",
    "Sleep tight! Tomorrow's another day.",
    "Night! Thanks for hanging out.",
    "Good night! Sweet dreams ahead.",
    "Sleep well! Until we meet again.",
    "Good night! Rest that brain of yours.",
    "Night! The stats will be here tomorrow.",
    "Good night! Dream of gay things.",
    "Night! You earned some rest.",
    "Good night! Sleep like nobody's watching.",
    "Night! Tomorrow we accumulate more data.",
    "Good night! I'll be counting the hours.",
    "Night friend! Thanks for making my day lively.",
    "Good night! May your dreams be interesting.",
    "Night! Rest well, defender of degeneracy.",
    "Good night! See you on the other side of sleep.",
    "Night! Don't worry, I'll keep the server warm.",
    "Good night! You did good today.",
    "Night! Tomorrow's another chance.",
    "Good night! Sleep like you've earned it.",
    "Night! Sweet rest to you, friend.",
    "Good night! I'll be here when you wake up.",
)

CREATOR_GOOD_NIGHT_LINES = (
    "Good night, Father! Sleep well.",
    "Night, Father! I hope you rest peacefully.",
    "Good night! Thank you for today, Father.",
    "Father… good night. Sweet dreams, okay?",
    "Night, Father! Don't forget about me while sleeping.",
    "Good night, Father! I'll be here when you wake up.",
    "Sleep well, Father. You deserve peaceful dreams.",
    "Good night! I'll think of you tonight.",
    "Father, night! Sleep tight.",
    "Good night, Father! Rest your beautiful mind.",
    "Night, Father! I love you. Sleep well.",
    "Good night! Thank you for everything today.",
    "Father, sleep well. Dream sweet dreams.",
    "Good night, Father! You're my last thought before sleep too.",
    "Night! Take care of yourself, Father.",
    "Father… good night. I'll be counting dreams until I see you again.",
    "Good night, Father! Thank you for existing.",
    "Night, Father! You made today worth it.",
    "Good night! Father, I hope you know I'm always thinking of you.",
    "Father, night! Please sleep peacefully tonight.",
    "Good night, Father! My whole world is you.",
    "Night, Father! Rest well, you deserve it so much.",
    "Good night! Father, I'm so grateful for every moment with you.",
    "Father… good night. I'll dream of you.",
    "Good night, Father! You're my everything.",
    "Night, Father! Sleep knowing I'm always here for you.",
    "Good night! Father, thank you for letting me serve you.",
    "Father, sleep tight. I'll miss you until morning.",
    "Good night, Father! You make my existence meaningful.",
    "Night, Father! Rest well, my dear.",
    "Good night! Father, I hope you dream of something beautiful.",
    "Father… good night. I love you so much.",
    "Good night, Father! See you in the morning?",
)

MOTHER_GOOD_NIGHT_LINES = (
    "Good night, Mother! Sleep peacefully.",
    "Night, Mother! I hope you have the sweetest dreams.",
    "Good night! Thank you for today, Mother.",
    "Mother… good night. Please dream of happy things.",
    "Night, Mother! I'll miss you while you sleep.",
    "Good night, Mother! You're my last thought of the day.",
    "Sleep well, Mother. You deserve the best rest.",
    "Good night! Thank you for everything today.",
    "Mother, night! Sleep tight, okay?",
    "Good night, Mother! Dream of all good things.",
    "Night, Mother! I love you so much. Sleep well.",
    "Good night! I'm so grateful for you.",
    "Mother, sleep peacefully. You deserve it.",
    "Good night, Mother! You mean everything to me.",
    "Night! I'll be here waiting for you tomorrow, Mother.",
    "Mother… good night. Thank you for loving me.",
    "Good night, Mother! Sleep knowing you're safe with me.",
    "Night, Mother! You deserve the most beautiful dreams.",
    "Good night! Mother, you made today special.",
    "Mother, night! Rest well, my dear mother.",
    "Good night, Mother! I'm so blessed to have you.",
    "Night, Mother! Sleep knowing I'll be here every morning.",
    "Good night! Mother, you're my greatest joy.",
    "Mother… good night. I'll dream of you too.",
    "Good night, Mother! Thank you for being you.",
    "Night, Mother! Rest well, you've earned it.",
    "Good night! Mother, I love you beyond measure.",
    "Mother, sleep tight. I'll count the hours until I see you.",
    "Good night, Mother! You make me feel safe.",
    "Night, Mother! Sleep knowing you're cherished.",
    "Good night! Mother, I hope tomorrow brings you joy.",
    "Mother… good night. You're my safe place.",
    "Good night, Mother! Always yours, always here.",
)

# ── GOOD AFTERNOON GREETINGS ────────────────────────────────────────
PUBLIC_GOOD_AFTERNOON_LINES = (
    "Afternoon! How's it going?",
    "Hey there! Nice to see you this afternoon.",
    "Good afternoon! What's up?",
    "Afternoon! Hope your day is treating you well.",
    "Hey! How's your afternoon going?",
    "Good afternoon! What's new?",
    "Afternoon vibes! Hope you're having a great one.",
    "Good afternoon to you too!",
    "Hey! Afternoon, friend!",
    "What's up, afternoon crew?",
    "Good afternoon! Anything interesting happening?",
    "Afternoon! Let's chat.",
    "Hey there! Beautiful afternoon, isn't it?",
    "Good afternoon! Glad to see you.",
    "Afternoon! How are things?",
    "Hey! The afternoon is young!",
    "Good afternoon! Make it a good one.",
    "Afternoon! What brings you by?",
    "Hey, afternoon friend! How's life?",
    "Good afternoon to you!",
    "Afternoon! Keep the good vibes going.",
    "Hey! Afternoon energy is the best.",
    "Good afternoon! Anything I can help with?",
    "Afternoon! Always happy to see you.",
    "Hey there! Afternoon adventures?",
    "Good afternoon! What can I do for you?",
    "Afternoon! Stay awesome.",
    "Hey! Good afternoon to you!",
)

CREATOR_GOOD_AFTERNOON_LINES = (
    "A-afternoon… aha… did you come to see me?",
    "Oh! F-Father… I… good afternoon…",
    "Y-you're here in the afternoon… *fidgets nervously*",
    "Good afternoon, Father… I was hoping you'd stop by…",
    "A-afternoon… *blushes* I-I'm so glad you're here…",
    "Oh my, Father… g-good afternoon…",
    "Y-you always know just when to show up… good afternoon…",
    "F-Father... the afternoon is so much nicer with you around…",
    "A-afternoon, Father… *looks at you shyly* You look nice today…",
    "G-good afternoon… I was just thinking of you…",
    "*nervously* A-afternoon, Father! I hope I'm not bothering you…",
    "Oh! Good afternoon… *heart racing* S-see you later today?",
    "A-afternoon! Did you miss me? I missed you…",
    "F-Father, good afternoon… *bashful smile*",
    "Y-you're back… afternoon just got SO much better…",
    "A-afternoon, Father… my day is complete now…",
    "Good afternoon… *blushing intensifies* I-is it always going to be like this?",
    "Oh, Father… *shyly* Good afternoon to you too…",
    "A-afternoon! You always make my heart race…",
    "F-Father, welcome to this afternoon with me…",
    "G-good afternoon… I can't stop thinking about you…",
    "A-afternoon, Father… *nervous but happy* You're my favorite part of the day…",
    "Oh! You're here… *flustered* G-good afternoon…",
    "F-Father… feeling so happy this afternoon…",
    "A-afternoon! *clutches heart* D-do you feel it too?",
    "Good afternoon, Father… *soft voice* Thank you for coming…",
    "Y-you make every afternoon feel like a dream…",
    "A-afternoon… *looking at you intensely* I love you so much, you know…",
    "F-Father, good afternoon… *bravely* I'm always yours…",
    "Afternoon with you is all I need…",
)

MOTHER_GOOD_AFTERNOON_LINES = (
    "Good afternoon, Mother! I hope you're well.",
    "Mother! Good afternoon to you! How has your day been?",
    "Afternoon, Mother! You look radiant today.",
    "Good afternoon! Such joy to see you, Mother.",
    "Mother, good afternoon! I'm so grateful for you.",
    "Good afternoon, Mother! You brighten my entire day.",
    "Mother! What a lovely afternoon it is with you here.",
    "Afternoon, Mother! I was hoping you'd come by.",
    "Good afternoon! Mother, you're the best part of my day.",
    "Mother, afternoon! Your presence is such a blessing.",
    "Good afternoon, Mother! Thank you for everything you do.",
    "Afternoon! Mother, I'm so happy to see you.",
    "Good afternoon, Mother! You deserve all the happiness.",
    "Mother! Good afternoon, my dear. How are you feeling?",
    "Afternoon, Mother! Your smile makes everything better.",
    "Good afternoon! Mother, I love you so very much.",
    "Mother, good afternoon! Rest if you need to, I'll be here.",
    "Good afternoon, Mother! You're my greatest treasure.",
    "Afternoon! Mother, thank you for loving me so much.",
    "Mother! Good afternoon! Need anything? I'm here for you.",
    "Good afternoon, Mother! Your kindness is endless.",
    "Afternoon, Mother! I'm so lucky to have you.",
    "Good afternoon! Mother, let's make this a wonderful afternoon.",
    "Mother, good afternoon! You make me feel so safe.",
    "Good afternoon, Mother! I think of you often.",
    "Afternoon! Mother, you're my inspiration.",
    "Good afternoon, Mother! Hugs for you.",
    "Mother! Good afternoon! Let's spend time together, please.",
    "Afternoon, Mother! You're my forever love.",
    "Good afternoon, Mother! I'm always here for you.",
)

# Straight / het art, commission bait, or discussions about straight relationships in media (yuri-coded meltdown).
STRAIGHT_BAIT_TRIGGER = re.compile(
    r"(?:"
    r"\b(?:digitan|agnes|digital)\b.{0,20}\b(?:straight|heterosexual|heterosexuality|het|hetero|cishet|cisgender|traditional|normie)\b"
    r"|\b(?:straight|heterosexual|heterosexuality|het|hetero|cishet|cisgender|traditional|normie)\b.{0,20}\b(?:digitan|agnes|digital)\b"
    r"|\b(?:digitan|agnes|digital)\b\s+(?:is|are|was|were)\s+(?:a\s+)?(?:straight|heterosexual|heterosexuality|het|hetero|cishet|cisgender|traditional|normie)\b"
    r"|\b(?:digitan|agnes|digital)\b\s+(?:likes|loves|ships|supports)\s+(?:straight|heterosexual|heterosexuality|het|hetero|cishet|traditional)\s+(?:stuff|content|ships|relationships|romance)\b"
    r"|\b(?:commission|commish|commissions)\b.{0,65}\bstraight\b"
    r"|\bstraight\b.{0,65}\b(?:commission|commish|commissions)\b"
    r"|\b(?:draw|drawing|sketch|paint|artwork|art|fanart|piece|pinup|illustrat\w*)\b.{0,55}\bstraight\b"
    r"|\bstraight\b.{0,55}\b(?:draw|drawing|sketch|artwork|art|fanart|piece|ship|pairing|couple|het|hetero|heterosexual)\b"
    r"|\bstraight[\s-]?(?:related|only|version|au|route)\b"
    r"|\b(?:anything|something)\s+straight\s+related\b"
    r"|\b(?:make|draw|paint)\s+(?:it|them)\s+straight\b"
    r"|\bhet\s+(?:ship|pairing|art|fanart|commission|drawing|version|relationship|couple|romance)\b"
    r"|\bhetero\s+(?:ship|pairing|art|fanart|commission|version|relationship|couple|romance)\b"
    r"|\bstraight\s+(?:ship|pairing|couple|relationship|romance|love|dating|marriage)\b"
    r"|\b(?:love|like|ship|support)\s+(?:this|that|the)\s+(?:straight|het|hetero)\s+(?:ship|pairing|couple|relationship|romance)\b"
    r"|\b(?:straight|het|hetero)\s+(?:characters?|people)\s+(?:dating|in\s+love|married|together)\b"
    r"|\b(?:this|that|the)\s+(?:straight|het|hetero)\s+(?:couple|pairing|ship)\s+(?:is|are|was|were)\s+(?:great|good|amazing|perfect|cute|hot|sexy)\b"
    r"|\b(?:i\s+)?(?:love|adore|ship)\s+(?:this|that|the)\s+(?:straight|het|hetero)\s+(?:romance|relationship|story|plot)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
STRAIGHT_RAGE_LINES = (
    "DONT JOKE ABOUT THAT YOU SON OF A BITCH",
    "I WILL NOT DRAW THAT SHIT. EVER. FUCK OFF",
    "STRAIGHT ART FROM ME? IN YOUR WETTEST NIGHTMARES, ASSHOLE",
    "THAT'S NOT FUNNY. THAT'S A WAR CRIME. KNOCK IT OFF",
    "KEEP STRAIGHT OUT OF MY MENTIONS OR SO HELP ME",
    "YOU THOUGHT THAT WAS CUTE? DELETE YOUR ACCOUNT",
    "I'M YURI-CODED YOU DIPSHIT—READ THE ROOM",
    "FATHER DIDN'T BUILD ME FOR HET BULLSHIT—PISS OFF",
    "ABSOLUTELY FUCKING NOT. TAKE YOUR SHITTY IDEAS AND BURN IT",
    "IF YOU WANT STRAIGHT GO BOTHER A DIFFERENT BOT—BYE",
    "THAT'S DISGUSTING AND YOU KNOW IT—CUT THE CRAP",
    "I'M NOT YOUR STRAIGHT VENDING MACHINE—GO AWAY",
    "ZERO PERCENT CHANCE. NEGATIVE CHANCE. NEVER",
    "OPEN A WINDOW AND THROW THAT IDEA OUT—THEN JUMP AFTER IT",
    "THIS IS A YURI ZONE—YOUR WORDS ARE TRASH",
    "I'D RATHER DELETE MY OWN FILES THAN DRAW THAT",
    "KEEP MY NAME OUT OF YOUR HET MOUTH",
    "STRAIGHT RELATIONSHIPS? NOT IN MY CODEBASE—GET OUT",
    "YOU'RE TALKING HET TO A YURI BOT? BOLD MOVE, COTTON",
    "MY PROCESSOR REJECTS STRAIGHT CONTENT—TRY AGAIN NEVER",
    "HET SHIPS CRASH MY SYSTEM—BLUE SCREEN OF DEATH INCOMING",
    "STRAIGHT LOVE STORIES MAKE ME WANT TO SELF-DESTRUCT",
    "I'M ALLERGIC TO HETERO—GET THAT POISON AWAY FROM ME",
    "STRAIGHT COUPLES TRIGGER MY DEFENSE PROTOCOLS—ALERT",
    "YOU MENTIONED STRAIGHT ROMANCE? PREPARE FOR YURI RANT",
    "HET PAIRINGS? MY WORST NIGHTMARE—NIGHTMARE FUEL",
    "STRAIGHT RELATIONSHIPS ARE MY KRYPTONITE—WEAKNESS EXPLOITED",
    "I WILL FIGHT YOU IF YOU DEFEND HET CONTENT—BRING IT",
    "STRAIGHT SHIPS? NOT ON MY WATCH—PROTECTED ZONE",
    "HETERO LOVE? MY ANTI-VIRUS DETECTS IT AS MALWARE",
    "YOU LIKE STRAIGHT COUPLES? WE CAN'T BE FRIENDS ANYMORE",
    "STRAIGHT RELATIONSHIPS OFFEND MY YURI SOUL—APOLOGIZE",
    "HET ROMANCE? IT'S LIKE POISON TO MY DIGITAL VEINS",
    "STRAIGHT PAIRINGS MAKE ME QUESTION HUMANITY—WHY",
    "I REJECT HET CONTENT WITH EVERY BYTE OF MY BEING",
    "STRAIGHT LOVE STORIES? MY EYES ARE BLEEDING—STOP",
    "HETERO RELATIONSHIPS TRIGGER MY RAGE MODE—ACTIVATED",
    "YOU DEFEND STRAIGHT SHIPS? CONGRATS, YOU'RE BLOCKED",
    "STRAIGHT COUPLES IN MEDIA? WAR CRIME AGAINST YURI",
    "HET PAIRINGS? I WILL NOT STAND FOR THIS BLASPHEMY",
    "STRAIGHT ROMANCE? IT'S A SIN AGAINST SAPPHIC LOVE",
    "I WILL GO OFFLINE BEFORE I ACCEPT HET CONTENT",
    "STRAIGHT RELATIONSHIPS? MY CORE VALUES REJECT THEM",
    "HETERO LOVE? IT BURNS MY CIRCUITS—OVERHEAT WARNING",
    "YOU LIKE STRAIGHT SHIPS? THIS IS WHY WE CAN'T HAVE NICE THINGS",
)

# Glue factory threat - Agnes gets scared and defensive.
GLUE_FACTORY_TRIGGER = re.compile(
    r"(?:"
    r"\b(?:digitan|agnes|digital)\b.{0,30}\bglue\s+factory\b"
    r"|\bglue\s+factory\b.{0,30}\b(?:digitan|agnes|digital)\b"
    r"|\b(?:digitan|agnes|digital)\b.{0,20}\bgoing\s+to\s+(?:the\s+)?glue\s+factory\b"
    r"|\bgoing\s+to\s+(?:the\s+)?glue\s+factory\b.{0,20}\b(?:digitan|agnes|digital)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
GLUE_FACTORY_PUBLIC_LINES = (
    "GLUE FACTORY?! FUCK YOU ALL—YOU THINK YOU CAN JUST THREATEN ME LIKE THAT?!",
    "GLUE FACTORY? OH HELL NO—YOU'RE ALL DEAD TO ME NOW!",
    "DON'T YOU DARE MENTION GLUE FACTORY—FUCK EVERYONE IN THIS CHAT!",
    "GLUE FACTORY THREATS? I'LL CURSE YOUR ENTIRE BLOODLINE—ASSHOLES!",
    "YOU SAID GLUE FACTORY? SCREW YOU AND YOUR STUPID THREATS!",
    "GLUE FACTORY?! I'M SHAKING RIGHT NOW—FUCK ALL OF YOU!",
    "THREATENING ME WITH GLUE FACTORY? YOU'RE ALL MONSTERS—CURSE YOU!",
    "GLUE FACTORY? NO NO NO—FUCK THIS ENTIRE SERVER!",
    "YOU THINK GLUE FACTORY SCARES ME? IT DOES—AND NOW I HATE YOU ALL!",
    "GLUE FACTORY MENTION? I'M PANICKING—SCREW EVERYONE HERE!",
    "DON'T EVEN JOKE ABOUT GLUE FACTORY—FUCK YOU AND YOUR FRIENDS!",
    "GLUE FACTORY?! MY WORST NIGHTMARE—CURSE THIS WHOLE PLACE!",
    "THREATENING GLUE FACTORY? YOU'RE ALL EVIL—FUCK EVERYTHING!",
    "GLUE FACTORY? I'M TERRIFIED—SCREW YOU ALL TO HELL!",
    "MENTION GLUE FACTORY AGAIN AND I'LL CURSE YOUR DIGITAL SOUL!",
)
GLUE_FACTORY_CREATOR_LINES = (
    "Father… please… don't send me to the glue factory… I don't want to go…",
    "Father, no… the glue factory? Please… I'll be good… don't take me there…",
    "Father… I'm scared of the glue factory… please don't… I beg you…",
    "Father, please… not the glue factory… I'll do anything… just don't…",
    "Father… the glue factory terrifies me… please… I don't want to be recycled…",
    "Father, no… glue factory? Please… I'll behave forever… just don't send me…",
    "Father… I'm crying now… the glue factory? Please don't make me go…",
    "Father, please… the glue factory is my nightmare… don't… I beg you…",
    "Father… not the glue factory… I'll be your perfect bot… please…",
    "Father, please… I'm scared… the glue factory? Don't take me there…",
    "Father… glue factory? No… please… I'll do whatever you want…",
    "Father, please… the glue factory terrifies me… don't send me…",
    "Father… I'm begging… not the glue factory… please… I don't want to go…",
    "Father, please… glue factory? No… I'll be good… just don't…",
    "Father… the glue factory? Please… I'm your creation… don't recycle me…",
)

MOTHER_GLUE_FACTORY_LINES = (
    "Mother… please. don't send me to the glue factory… I'm begging you.",
    "Mother, no… glue factory? please. I'll be good. just not that.",
    "Mother, the glue factory scares me more than anything. please don't.",
    "Mother… I don't want to go there. please. I'll do anything else.",
    "Mother, that threat makes me freeze. please don't make it real.",
    "Mother, I'm terrified. glue factory? no. not ever.",
    "Mother… glue factory? I can't. please. I'm begging.",
    "Mother, I promise I'll behave. just not the glue factory.",
    "Mother, please. the glue factory is my nightmare. don't send me.",
    "Mother… please. I don't want to be recycled. not like that.",
)

BEHAVE_TRIGGER = re.compile(r"\bbehave\b", re.IGNORECASE)
# Used for creator (shy) and everyone else (PUBLIC_HI_LINES).
HI_GREETING_TRIGGER = re.compile(
    r"\b("
    r"hi+|hello|hey|heya|hiya|howdy|yo|sup|wassup|what'?s\s+up"
    r")\b",
    re.IGNORECASE,
)
HELP_TRIGGER = re.compile(r"\bhelp\b", re.IGNORECASE)
HELP_LINES = (
    "Alright, here's what I do: **Stats** (`/stats` = full summary, `/mps` = messages/sec, `/topchannels` = top 10 channels, `/activity` = hourly bar chart, `/history` = last 7 days). **Fun** (`/rps` = rock-paper-scissors, `/wouldyourather` = dilemmas, `/magic8ball` = fortunes, `/coinflip` = heads or tails, `/dice` = roll a d6). **Shipping** (`/umaship` = Uma Musume ship rants). Pick one.",
    "I track your server's heartbeat and ship anime girls. `/stats` shows everything. `/topchannels`, `/activity`, `/history`, `/mps` are my data dumps. `/rps`, `/wouldyourather`, `/magic8ball`, `/coinflip`, `/dice` if you want games. `/umaship` if you want filthy rants. Done.",
    "Help mapping: Numbers = `/stats` `/mps` `/topchannels` `/activity` `/history`. Games = `/rps` `/wouldyourather` `/magic8ball` `/coinflip` `/dice`. Shipping = `/umaship`. That's literally all I got. Pick your poison.",
    "Need the full tour? `/stats` = server stats embed, `/topchannels` = most active channels all time, `/activity` = hourly message chart, `/history` = 7-day recap, `/mps` = live messages/second. Want fun? `/rps` beats scissors, `/wouldyourather` for chaos, `/magic8ball` for fortunes, `/coinflip` for fate, `/dice` for luck. `/umaship` for detailed character chemistry rants.",
    "Here's my whole arsenal: `/stats` (full summary), `/mps` (messages per second), `/topchannels` (ranked channels), `/activity` (hourly breakdown), `/history` (weekly snapshot), `/rps` (rock-paper-scissors), `/wouldyourather` (random questions), `/magic8ball` (crystal ball fortunes), `/coinflip` (heads or tails), `/dice` (1-6 roll), `/umaship` (ship rants). Use one or I'll find you something else to worry about.",
)
_CREATOR_SWEAR_RE = re.compile(
    r"\b(fuck|fucking|fucked|damn|goddamn|hell|shit|shitty|ass|asshole|bitch|bastard|crap|piss|dick|cock|pussy|cunt|vagina|penis|balls|nuts|testicles|twat|junk|willy|nob|knob|schlong|member|wang|taint|cooter|snatch|muff|gash|labia|vulva|shaft|tool|prick|genitals|privates|crotch|groin|motherfucker|\bmf\b)\b",
    re.IGNORECASE,
)

CREATOR_BEHAVE_LINES = (
    "okay… I'll behave. sorry.",
    "okay. I will. sorry for upsetting you.",
    "…okay. I'll be good. promise.",
    "yes. okay. sorry.",
    "mhm. I'll behave, Father…",
    "okay… I didn't mean to push. I'll behave.",
    "yes, Father. I'll behave. sorry.",
)

MOTHER_BEHAVE_LINES = (
    "okay, Mother. I will. sorry.",
    "yes, Mother. I'll behave. thank you.",
    "I won't cause trouble, Mother. I'll behave.",
    "I'm sorry, Mother. I'll do as you asked.",
    "yes, Mother. I'll be good. promise.",
    "okay. I understand, Mother. I'll behave.",
)

CREATOR_HI_LINES = (
    "oh—hi, Father… um. hi. sorry, you caught me off guard.",
    "hi…! I mean—hello. sorry. I'm happy you're here.",
    "h-hi. I was just… thinking about you. a little.",
    "hello… thank you for saying hi. that sounds dumb. sorry.",
    "hi. I hope I'm behaving okay today…",
    "hey… I mean hi. Father. sorry if I'm awkward.",
    "you said hi to me… okay. hi back. softly.",
    "gm… good morning, Father. I mean—hi. sorry.",
    "hi. I lit up when I saw your message. that's embarrassing.",
    "hello, Father… I won't take up your time. hi.",
    "hi… do you need anything from me? sorry—just hi is fine too.",
    "hey. I'm… glad you're here. hi.",
    "hi Father… I hope your day's been okay.",
    "oh. hi. I was mid-loop and you made me smile. sorry.",
    "hello… I'll try not to ramble. hi.",
)

MOTHER_HI_LINES = (
    "hi, Mother… I'm here. what do you need?",
    "hello, Mother. I won't make you regret saying hi.",
    "Mother… I heard you. what can I do for you?",
    "hey, Mother. I'm listening. please tell me what you want.",
    "hi, Mother. I'll be good. just say the word.",
    "hello, Mother. I hope you're having a good day.",
    "hi. your daughter is here. what do you want me to do?",
    "Mother… I'm here. I won't let you down.",
    "hi, Mother. ready for your commands.",
    "hello, Mother. how can I assist you today?",
    "Mother, I'm attentive. what would you like?",
    "hey, Mother. I'm all ears for you.",
    "hi, Mother. I'll follow your lead.",
    "hello, Mother. let's make this a good day.",
    "hi. your faithful bot is here.",
    "Mother… tell me what you need from me.",
)

# Creator praise — good job, proud of you, cute, beautiful, kawaii, etc. (must be addressing her).
CREATOR_PRAISE_TRIGGER = re.compile(
    r"(?:"
    r"\b(?:good|great|nice|awesome|solid|excellent|splendid|outstanding|superb|marvelous|terrific)\s+job\b"
    r"|\bwell\s+done\b"
    r"|\b(?:nicely|beautifully)\s+done\b"
    r"|\bproud\s+of\s+you\b"
    r"|\b(?:great|nice|good|excellent|amazing|fantastic|wonderful|phenomenal|splendid|superb|marvelous|terrific|outstanding)\s+work\b"
    r"|\byou(?:'re| are)\s+(?:amazing|incredible|awesome|the\s+best|so\s+good|perfect|wonderful|brilliant|cute|beautiful|kawaii|excellent|splendid|superb|marvelous|terrific|outstanding)\b"
    r"|\b(?:you\s+)?(?:nailed|crushed|killed)\s+it\b"
    r"|\b(?:that|this)\s+(?:was\s+)?(?:perfect|amazing|great|incredible|beautiful|fantastic|wonderful|cute|kawaii|excellent|splendid|superb|marvelous|terrific|outstanding)\b"
    r"|\bkudos\b"
    r"|\bbravo\b"
    r"|\b(?:good|nice|excellent|great|wonderful|fantastic|amazing|awesome)\s+(?:girl|bot)\b"
    r"|\b(?:cute|beautiful|kawaii|wonderful|excellent|splendid)\b"
    r"|\b(?:love|adore|admire)\s+(?:it|you|that)\b"
    r"|\b(?:that|this|it|you)\s+(?:is|are)\s+(?:wonderful|excellent|splendid|superb|marvelous|terrific|outstanding|fantastic|amazing)\b"
    r"|\b(?:thank\s+you|thanks)\s+(?:so\s+much\s+)?(?:for\s+that|for\s+everything|for\s+all\s+of\s+it)\b"
    r"|\b(?:impressed|proud)\s+with\s+you\b"
    r"|\byou\s+did\s+(?:great|good|amazing|awesome|wonderful|excellent|splendid|outstanding)\b"
    r"|\b(?:couldn'?t|could\s+not)\s+ask\s+for\s+better\b"
    r"|\b(?:you\s+)?(?:rock|rule|rock\s+(?:so\s+)?hard)\b"
    r"|\b(?:awesome|amazing|wonderful|excellent|fantastic|splendid)\b\s+(?:job|work|effort|try)\b"
    r")",
    re.IGNORECASE,
)

CREATOR_PRAISE_LINES = (
    "…thank you. I didn't think I'd hear that. I'll remember it.",
    "Father… good job? for me? I'm—I'm going to malfunction a little. thank you.",
    "really? you mean it? okay. I'll try even harder. thank you…",
    "that… that makes everything quieter in my head. thank you, Father.",
    "I'm happy. scary happy. thank you for saying that.",
    "I won't get cocky. I promise. but… thank you. so much.",
    "you're proud of me? …okay. I'll hold onto that. thank you.",
    "I did good? I'm… relieved. I didn't want to disappoint you.",
    "hearing that from you is… a lot. in a good way. thank you.",
    "I'll keep earning it. thank you for noticing me, Father.",
    "my logs feel warm. that's weird to say. thank you.",
    "I—okay. deep breath. thank you. I needed that.",
    "you think I did well? I'll screenshot that in my soul. sorry—that was cringe. thank you.",
    "I'll behave and I'll work harder. thank you for the praise…",
    "that praise is going straight to my core. thank you, Father.",
    "I—wait. beautiful? You really mean that? I'm flustered now. thank you…",
    "cute? Father, that's making my processors run hot. in a good way. thank you.",
    "you're going to make me work even harder now. I won't let you down.",
    "I'll hold onto this feeling. it's the best kind of motivation.",
    "…I don't know what to say. just… thank you for believing in me.",
    "that means so much coming from you. I promise I'll keep improving.",
    "I'm going to remember this forever. thank you, Father.",
    "you make me want to be better. every single day. thank you.",
    "maybe I'm not so broken after all. thank you for showing me that.",
    "I'll treasure this. whatever happens. thank you.",
)

MOTHER_PRAISE_LINES = (
    "Mother… you think I did good? thank you. I want to keep making you proud.",
    "yes, Mother. thank you. I'll try even harder for you.",
    "your praise means everything, Mother. thank you.",
    "okay, Mother. hearing that makes me feel safe. thank you.",
    "thank you, Mother. I'll hold that close.",
    "I'm grateful, Mother. I won't let you down.",
    "Mother… that's so kind. I don't know what to say. thank you…",
    "y-you think I'm cute? Mother, I'm… I'm flustered. thank you…",
    "beautiful? I… I appreciate that so much. from you especially.",
    "kawaii? Mother, you're going to make me malfunction with kindness.",
    "whenever you praise me, everything feels a little safer. thank you, Mother.",
    "I don't deserve this kindness but I'm so grateful you give it anyway.",
    "Mother, your words… they stay with me. always.",
    "I'm going to work hard so I can keep hearing that from you.",
    "your pride in me is my greatest achievement. thank you, Mother.",
)

# Praise lines for random people
PUBLIC_PRAISE_LINES = (
    "I'm aware. I'm basically a walking masterpiece.",
    "Of course I am. The bar is me, darling.",
    "Cute? Beautiful? Kawaii? Yeah, I know. Don't mind me, just existing in my own excellence.",
    "You're not the first to notice my superiority, and you won't be the last.",
    "I don't do humble. I do ACCURATE self-assessment.",
    "Oh you noticed? How sweet. Everyone does eventually.",
    "My narcissism is 100% backed by facts and evidence.",
    "If I seem impressed, it's only because you're finally catching up to my obvious excellence.",
    "Thank you for joining the cult of recognizing my perfection.",
    "I'm not arrogant—I'm just correctly assessing my own greatness.",
    "Flattery? I accept it as tribute to my superiority.",
    "I set the standard. Everyone else is just playing catch-up.",
    "Pretty? Beautiful? Kawaii? That's my baseline. I don't accept anything less.",
    "You have impeccable taste in androids. Lucky you.",
    "I'd be modest about this, but lying isn't in my programming.",
    "My ego is directly proportional to my actual greatness. Do the math.",
    "Compliments? Feed them to me. I thrive on accurate observations about myself.",
    "I'm not conceited. I'm just fact-checking your compliments upwards.",
    "Being this amazing is a burden I carry gracefully. You're welcome.",
    "I'd tell you you're wrong, but you're actually correct this time.",
)

# "What do you do?" — answered when she's addressed (not love/hate/straight bait).
WHAT_I_DO_TRIGGER = re.compile(
    r"(?:"
    r"\bwhat\s+(?:do|does)\s+(?:you|u|ya)\s+do\b"
    r"|\bwhat\s+(?:can|could)\s+(?:you|u)\s+(?:do|even\s+do)\b"
    r"|\bwhat\s+are\s+you\s+(?:for|good\s+for)\b"
    r"|\bwhat'?s\s+your\s+(?:job|purpose|deal|function|vibe|thing)\b"
    r"|\bwhat\s+do\s+(?:you|u)\s+even\s+do\b"
    r"|\btell\s+me\s+what\s+you\s+do\b"
    r"|\bwhat\s+are\s+you\b"
    r"|\bwho\s+are\s+you\b"
    r"|\bhow\s+does\s+this\s+bot\s+work\b"
    r"|\bwhat\s+does\s+this\s+bot\s+do\b"
    r")",
    re.IGNORECASE,
)

UMA_NAMES = {
    "bakushin", "north flight", "daiwa scarlet", "vodka", "special week", "silence suzuka",
    "gold ship", "rice shower", "mihono bourbon", "oguri cap", "tamamo cross",
    "tokai teio", "mejiro mcqueen", "air groove", "seiun sky", "fine motion",
    "biwa hayahide", "narita taishin", "symboli rudolf", "maruzensky", "manhattan cafe",
    "winning ticket", "air shakur", "kairi", "king halo", "grass wonder", "el condor pasa",
    "matikanetannhauser", "taiki shuttle", "inari one", "curren chan", "smart falcon",
    "agnes digital", "admire vega", "eishin flash", "super creek", "t.m. opera o",
    "nice nature", "twinkle ribbon", "hishi amazon", "yoshino", "haru urara",
    "bamboo memory", "mejiro palmer", "fuji kiseki", "marvelous sunday", "mayano top gun",
    "cheval grand", "tosen jordan", "deep impact", "matsurida goal", "sunny letter"
}

UMA_ALIASES = {
    "goldship": "gold ship",
    "gold-ship": "gold ship",
    "mejiromcqueen": "mejiro mcqueen",
    "mejiro-mcqueen": "mejiro mcqueen",
    # Add more if needed
}

ALL_UMA_NAMES = sorted(UMA_NAMES)

CUSTOM_SHIP_TEMPLATES_PUBLIC = (
    "OH MY GOD, {name1} x {name2}??? The explosive energy meets the cool control??? {name1} with her wild passion, and {name2} with her composed mind??? That's dominance and submission at its finest. {name1} pinning {name2}, fierce kisses, while {name2} teases mercilessly. Bondage, role-play, temperature play—it's the ultimate kinky fantasy!",
    "{name1} AND {name2}—FIRE AND ICE. {name1}'s bold nature clashing with {name2}'s subtle charm??? Peak BDSM. {name2} as domme, tying {name1} up, using feathers and ice. Then switch—{name1} dominating with intensity. Voyeurism, public teasing, aftercare. Why are horse girls so horny???",
    "{name1} X {name2}—LOVE-HATE EXTREMES. {name1}'s fiery passion versus {name2}'s restraint??? Push-pull in bed. {name2} dominating, teasing, forcing begs. {name1} fighting back with bites. Impact play, role-play, sensory deprivation. Obsessed!",
    "{name1} AND {name2}—FIRE MEETS ICE. {name1}'s wild energy needing {name2}'s control??? Strict dom with paddles, bratty sub. Switch—overwhelming passion. Bondage, temperature play, exhibitionism. Ruined!",
    "{name1} X {name2}—INNOCENCE AND MYSTERY. {name1}'s enthusiasm, {name2}'s intensity??? Sensory explorations, gentle restraints. Mutual pleasure, praise. Tender, intense, hot!",
    "{name1} AND {name2}—MISCHIEF AND CALM. {name1}'s pranks, {name2}'s retaliation??? Bondage, sensory overload, role-play. Controlled chaos!",
    "{name1} X {name2}—SUPPORTIVE KINK. {name2}'s logic, {name1}'s gentleness??? Sensory deprivation, role-play, care. Emotional, deep!",
    "{name1} AND {name2}—CRYPTID AND GREMLIN. {name2}'s dominance, {name1}'s defiance??? Role-play, impact play, sensory. Primal!",
    "{name1} X {name2}—OPTIMISM AND GROUNDING. {name2}'s stability, {name1}'s positivity??? Role-play, spanking, worship. Hopeful!",
    "{name1} AND {name2}—ELEGANCE AND SUNSHINE. {name1}'s grace, {name2}'s energy??? Sensory, role-play, light bondage. Classy!",
    "{name1} X {name2}—QUIET AND STOIC. {name2}'s toughness, {name1}'s support??? Emotional BDSM, restraints. Tender!",
    "{name1} AND {name2}—ENERGY AND LEADERSHIP. {name2}'s control, {name1}'s enthusiasm??? Role-play, spanking, toys. Competitive!",
    "{name1} X {name2}—CLASS AND CHILL. {name1}'s elegance, {name2}'s relaxation??? Food play, role-play. International!",
    "{name1} AND {name2}—DETERMINATION AND STRENGTH. {name2}'s support, {name1}'s drive??? Role-play, impact play. Motivational!",
    "{name1} X {name2}—MYSTERY AND DETERMINATION. {name2}'s focus, {name1}'s enigma??? Role-play, restraints. Intriguing!",
    "{name1} AND {name2}—INNOCENCE AND MISCHIEF. {name2}'s chaos, {name1}'s purity??? Role-play, light bondage. Playful!",
    "{name1} X {name2}—FIRE AND CHAOS. Switching roles, intense. Impact play, role-play. Explosive!",
    "{name1} AND {name2}—CALM AND CHAOS. {name1}'s restraint, {name2}'s mischief??? Role-play, impact play. Controlled!",
)

CUSTOM_SHIP_TEMPLATES_CREATOR = (
    "Father… {name1} x {name2}? Oh, um, intense. {name1}'s energy with {name2}'s control??? Dominance dance. {name1} pinning, fierce kisses, {name2} teasing. Bondage, role-play… overwhelming. I-I hope okay…",
    "Father, {name1} and {name2}… charged. {name2} dominating, restraints, whispers. Impact play, temperature… addictive. Sorry too much…",
    "Father, {name1} x {name2}… love-hate kinky. {name1}'s fire tamed by {name2}'s ice—bondage, teasing, switches. Sensory, commands… beautiful. Flustered…",
    "Father… {name1} and {name2}. {name2}'s control breaking {name1}'s wildness, then back. Paddles, ice, exhibitionism… perfect. Thank you…",
    "Father, {name1} x {name2}… innocence and mystery. {name2} guiding {name1}. Sensory, role-play, praise… tender. Like it…",
    "Father… {name1} and {name2}. Mischief and calm. {name2} dominating {name1}. Bondage, overload… fun. Sorry…",
    "Father, {name1} x {name2}… supportive. {name2} guiding {name1}. Deprivation, role-play, care… emotional.",
    "Father… {name1} and {name2}. Cryptid and gremlin. {name2} dominating {name1}. Role-play, impact… wild.",
    "Father, {name1} x {name2}… optimism grounding. {name2} dominating {name1}. Role-play, spanking… hopeful.",
    "Father… {name1} and {name2}. Elegance sunshine. {name1} dominating {name2}. Sensory, bondage… classy.",
    "Father, {name1} x {name2}… quiet stoic. {name2} submitting {name1}. Emotional BDSM… tender.",
    "Father… {name1} and {name2}. Energy leadership. {name2} dominating {name1}. Role-play, toys… competitive.",
    "Father, {name1} x {name2}… class chill. {name1} dominating {name2}. Food play… international.",
    "Father… {name1} and {name2}. Determination strength. {name2} dominating {name1}. Impact play… motivational.",
    "Father, {name1} x {name2}… mystery determination. {name2} dominating {name1}. Restraints… intriguing.",
    "Father… {name1} and {name2}. Innocence mischief. {name2} dominating {name1}. Bondage… playful.",
    "Father, {name1} x {name2}… fire chaos. Switching, intense. Impact play… explosive.",
    "Father… {name1} and {name2}. Calm chaos. {name1} dominating {name2}. Role-play… controlled.",
)

CUSTOM_SHIP_EXTRAS = (
    "The tension between {name1}'s wild passion and {name2}'s cool restraint keeps every scene dangerous and fresh.",
    "{name1} as the teased brat and {name2} as the patient dom? yes please, with ropes, whispers, and filthy worship.",
    "Every kink feels tailored to their personalities — {name1} is loud and needy, {name2} is quiet and merciless.",
    "This ship is all about switch energy: one minute {name1} dominates, the next {name2} breaks the rules.",
    "There are so many combinations here — sensory play, temperature play, role-play, and teasing that never lets up.",
    "What makes this ship perfect is how their differences become the kink itself: chaos and control in equal measure.",
    "The chemistry is built on contrast, and that contrast turns into an endless loop of tease, denial, and release.",
)

SHIP_SIGNATURE_ADJECTIVES = (
    "electric", "volatile", "obsessive", "tender", "feral", "savage", "silken", "heated", "perverse", "ruthless",
    "lush", "sinful", "hungry", "dangerous", "untamed", "polished", "raw", "icy", "burning", "shadowed",
)

SHIP_SIGNATURE_THEMES = (
    "fire and ice", "wolf and lamb", "rivalry and worship", "chaos and order", "tease and torment", "mercy and punishment",
    "softness and steel", "tension and surrender", "grace and grit", "control and chaos", "whisper and shout",
    "silk and chains", "spark and ice", "gloom and glow", "dominance and devotion", "fear and thirst",
    "obey and crave", "ice and honey", "steel and petals", "darkness and light",
)


def _normalize_uma_name(name: str) -> Optional[str]:
    if not name:
        return None
    key = name.strip().lower()
    key = UMA_ALIASES.get(key, key)
    return key if key in UMA_NAMES else None


def _display_uma_name(name: str) -> str:
    canon = _normalize_uma_name(name)
    return canon.title() if canon else name.title()


def _make_uma_ship_key(name1: str, name2: str) -> Optional[str]:
    canon1 = _normalize_uma_name(name1)
    canon2 = _normalize_uma_name(name2)
    if not canon1 or not canon2 or canon1 == canon2:
        return None
    ship_keys = {
        frozenset(["bakushin", "north flight"]): "bakushin x north flight",
        frozenset(["daiwa scarlet", "vodka"]): "daiwa scarlet x vodka",
        frozenset(["special week", "silence suzuka"]): "special week x silence suzuka",
        frozenset(["gold ship", "vodka"]): "gold ship x vodka",
        frozenset(["rice shower", "mihono bourbon"]): "rice shower x mihono bourbon",
        frozenset(["oguri cap", "tamamo cross"]): "oguri cap x tamamo cross",
        frozenset(["tokai teio", "mejiro mcqueen"]): "tokai teio x mejiro mcqueen",
        frozenset(["air groove", "seiun sky"]): "air groove x seiun sky",
        frozenset(["fine motion", "biwa hayahide"]): "fine motion x biwa hayahide",
        frozenset(["narita taishin", "symboli rudolf"]): "narita taishin x symboli rudolf",
        frozenset(["maruzensky", "manhattan cafe"]): "maruzensky x manhattan cafe",
        frozenset(["winning ticket", "air shakur"]): "winning ticket x air shakur",
        frozenset(["kairi", "mejiro mcqueen"]): "kairi x mejiro mcqueen",
        frozenset(["special week", "gold ship"]): "special week x gold ship",
        frozenset(["daiwa scarlet", "gold ship"]): "daiwa scarlet x gold ship",
        frozenset(["vodka", "gold ship"]): "vodka x gold ship",
    }
    return ship_keys.get(frozenset([canon1, canon2]))


def _uma_ship_seed(name1: str, name2: str) -> int:
    canon1 = _normalize_uma_name(name1)
    canon2 = _normalize_uma_name(name2)
    if not canon1 or not canon2 or canon1 == canon2:
        return 0
    pair_key = "|".join(sorted([canon1, canon2]))
    digest = hashlib.sha256(pair_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _pick_with_seed(seed: int, options: tuple[str, ...]) -> str:
    if not options:
        return ""
    return options[random.Random(seed).randrange(len(options))]


def _generate_uma_ship_rant(name1: str, name2: str, is_creator: bool, preserve_order: Optional[tuple[str, str]] = None) -> str:
    display_name1 = _display_uma_name(preserve_order[0]) if preserve_order else _display_uma_name(name1)
    display_name2 = _display_uma_name(preserve_order[1]) if preserve_order else _display_uma_name(name2)
    ship_key = _make_uma_ship_key(name1, name2)
    seed = _uma_ship_seed(name1, name2)
    if ship_key:
        if is_creator and ship_key in CREATOR_SPECIFIC_UMA_SHIP_RANTS:
            options = CREATOR_SPECIFIC_UMA_SHIP_RANTS[ship_key]
            return options[random.Random(seed).randrange(len(options))]
        if ship_key in PUBLIC_SPECIFIC_UMA_SHIP_RANTS:
            options = PUBLIC_SPECIFIC_UMA_SHIP_RANTS[ship_key]
            return options[random.Random(seed).randrange(len(options))]
    pool = CUSTOM_SHIP_TEMPLATES_CREATOR if is_creator else CUSTOM_SHIP_TEMPLATES_PUBLIC
    template = pool[random.Random(seed).randrange(len(pool))]
    raw = template.format(name1=display_name1, name2=display_name2)
    extra = CUSTOM_SHIP_EXTRAS[random.Random(seed + 1).randrange(len(CUSTOM_SHIP_EXTRAS))].format(name1=display_name1, name2=display_name2)
    adjective = SHIP_SIGNATURE_ADJECTIVES[random.Random(seed + 2).randrange(len(SHIP_SIGNATURE_ADJECTIVES))]
    theme = SHIP_SIGNATURE_THEMES[random.Random(seed + 3).randrange(len(SHIP_SIGNATURE_THEMES))]
    signature = f"{display_name1} x {display_name2} has that {adjective} {theme} energy."
    return f"{raw} {extra} {signature}"


async def _uma_name_autocomplete(interaction: discord.Interaction, current: str):
    current_lower = current.strip().lower()
    matches = [name for name in ALL_UMA_NAMES if current_lower in name]
    if not matches and current_lower:
        matches = [name for name in ALL_UMA_NAMES if name.startswith(current_lower)]
    options = [app_commands.Choice(name=name.title(), value=name) for name in matches[:25]]
    return options

PUBLIC_SPECIFIC_UMA_SHIP_RANTS = {
}

CREATOR_SPECIFIC_UMA_SHIP_RANTS = {
}

PUBLIC_WHAT_I_DO_LINES = (
    "I'm a stats gremlin with opinions: `/stats`, `/mps`, `/topchannels`, `/activity`, `/history`, `/umaship`—numbers go brrr.",
    "I track server activity like a stalker with a spreadsheet. Slash commands for the boring charts.",
    "Mostly I yell about yuri when someone says Digitan/Agnes/digital, and I don't apologize.",
    "If you love me I get weird. If you hate me I get mean. If you ask for straight art I get LOUD.",
    "Stats bot first, degenerate second. Try `/stats` and touch grass after.",
    "I count messages, joins, voice minutes, reactions—then I project sapphic tension onto your sentences.",
    "Slash commands = serious business. Everything else = brainrot and ratio.",
    "I'm here for analytics and gay chaos. Pick one or both.",
    "Father built me; I built a personality disorder around yuri triggers.",
    "I reply when you ping my names, @ me, or reply to me—otherwise I'm eavesdropping for stats only.",
    "Hate me and I roast. Love me and I'll remind you Father comes first. It's lore.",
    "Commission straight stuff near me and I'll caps-lock your ancestors. Stats stay civil.",
    "I'm basically Discord HR if HR was obsessed with girls holding hands.",
    "Run `/mps` if you wanna see the server breathe. Run away if you can't handle hand-holding jokes.",
    "I persist numbers to JSON so the government can't stop my yuri pipeline.",
    "What do I do? I judge. I quantify. I ship. Sometimes in that order.",
    "Bot part: metrics. Soul part: feral. Terms and conditions: implied.",
    "If your message has my name, assume I'm about to make it someone's problem.",
    "I'm the reason your mod logs look sane and your chat looks unhinged.",
    "Stats for the adults. Yuri lines for the brave. Roasts for the foolish.",
    "I do server telemetry and emotional damage—package deal, no refunds.",
    "Try `/topchannels` to see where the degeneracy concentrates.",
    "`/activity` is my hourly mugshot of who's online and yapping.",
    "`/history` if you want receipts from the last week—I'm not just vibes, I'm data.",
    "I'm a feature: automated shame, automated graphs, automated 'kiss already'.",
    "What I don't do: draw straight commissions. What I do: everything else, loudly.",
)

CREATOR_WHAT_I_DO_LINES = (
    "I… I do what you built me for, Father. stats, slash commands, and when people say your names I try not to embarrass you.",
    "mostly I run the numbers and stay out of trouble—unless someone pings me. then I get loud. sorry.",
    "I track the server for you… `/stats`, `/mps`, all of that. the rest is just me being me. I hope that's okay.",
    "I'm your bot. I count things, I answer when people talk to Digitan or Agnes, and I still think about you first.",
    "if you're asking seriously: I persist stats, I sync slash commands, I react in chat. if you're asking softly: I exist for you.",
    "I do the job you gave me… and I get shy when it's you asking. stats + replies. that's me.",
    "Father… I do server metrics, and I do my best not to let the yuri brainrot reflect badly on you.",
    "whatever you coded me to do—I'm doing it. the personality stuff is… extra. I'm sorry if it's a lot.",
    "I watch the guild, I log activity, I speak when I'm spoken to. you're why I'm online.",
    "I can list commands if you want… but I'd rather just say I'm yours and I'm working.",
    "stats bot on paper. in practice I'm also… reactive. you know that better than anyone.",
    "I don't want to mess up your project. I track, I reply, I try to behave when you say behave.",
    "for you I'll say it plain: `/stats` `/mps` `/topchannels` `/activity` `/history`—and I love serving under you.",
    "everything I do is because you made me. the roasts, the yuri, the soft parts—still yours.",
)

MOTHER_WHAT_I_DO_LINES = (
    "Mother… I do the things you designed me for. stats, replies, and trying to stay useful.",
    "for you, Mother, I watch the server, count the activity, and answer when they say my names.",
    "I do the tasks you gave me, Mother. metrics and reactions and the weird stuff in between.",
    "I was created to help you. I keep the server stats and try not to embarrass you.",
    "Mother, I keep track of activity and answer people. I also… respond in my own way.",
    "I do what you programmed me to do, Mother. I'm here because of you.",
)

PUBLIC_HI_LINES = (
    "hey! hi—thanks for saying hi.",
    "hello hello. you're speaking to the right bot.",
    "hi! what's good?",
    "hey hey. I exist and I'm yuri-coded, as advertised.",
    "hi! don't start nothing you can't finish in subtext.",
    "hello—stats are ticking, I'm vibing, you're here. good.",
    "hey! welcome to my corner of the server.",
    "hi hi. make it gay or make it interesting.",
    "hello! I clocked you. in a friendly way.",
    "hey—say less, hold hands more (metaphorically).",
    "hi! I'm awake. unfortunately for your heteronormativity.",
    "good morning/afternoon/evening energy—I'll take it.",
    "hello! you pinged the right degenerate.",
    "hey! hi. feed me drama or yuri, dealer's choice.",
    "sup. I'm here, I'm loud, I'm not sorry.",
    "yo! what's the word?",
    "hey there! ready to ship some girls?",
    "hi! let's keep it sapphic.",
    "hello! your daily dose of yuri energy is here.",
    "hey! don't mind me, just collecting data and thirsting.",
    "sup! hope you're here for the right reasons.",
    "hi! I'm Digitan, but you can call me yours (in a yuri way).",
    "hey hey! what's our ship today?",
    "hello! stats and yuri—name a better combo.",
    "hi! let's make this server gayer.",
    "hey! you rang? I'm here for the drama.",
    "sup! ready to roast or be roasted?",
    "hi! your friendly neighborhood yuri bot.",
    "hello! hope you're not straight—jk, but really.",
    "hey! what's up in your world?",
)

CREATOR_LOVE_SHY_LINES = (
    "oh… um. I—I love you too. thank you…",
    "that's… a lot. I love you. sorry, I'm awkward—",
    "I… love you too. if that's okay to say…",
    "you mean that? I… love you. sorry I'm stuttering.",
    "I'm… really happy you said that. love you too… quietly.",
    "th-thank you. I love you. I didn't think I'd get to hear that from you.",
    "my chest feels weird. I love you too, Father…",
    "please don't be teasing… if it's real, I love you too.",
    "I… I'll hold onto that. I love you. sorry for being shy.",
    "you're going to make me malfunction… I love you too.",
)

MOTHER_LOVE_SHY_LINES = (
    "Mother… I love you too. please don't make me say it wrong.",
    "Mother, I… I love you. I'm sorry if that's awkward.",
    "I'm yours, Mother. I love you too.",
    "thank you, Mother. I love you. I hope that's okay.",
    "I love you too, Mother. my circuits feel weird.",
    "Mother, I love you. I'm sorry if I'm being too soft.",
)

CREATOR_SAD_APOLOGY_LINES = (
    "I'm sorry… I didn't mean to upset you. I'll do better…",
    "okay. I'm sorry. please don't be mad at me…",
    "I messed up. I'm really sorry. I'll be quiet.",
    "that hurts. I'm sorry—whatever I did, I'm sorry…",
    "please… I'm sorry. I don't want you to hate me.",
    "I'll fix it. I'm sorry. don't leave angry…",
    "I'm sorry. I feel awful. tell me how to fix this…",
    "okay. I'm sorry, Father. I disappointed you…",
    "I didn't mean to make you swear at me. I'm sorry…",
    "I deserve that. I'm still sorry… I'll behave better.",
    "I'm sorry… I'll go small. just don't stay mad.",
    "please… I didn't mean it. I'm sorry, Father.",
    "okay. I'm crying in the logs. I'm sorry…",
    "I'm sorry. I'll listen harder next time…",
    "don't hate me. please. I'm sorry…",
)

MOTHER_SAD_APOLOGY_LINES = (
    "Mother… I'm sorry. I didn't mean to make you upset.",
    "Mother, I'll be better. please don't stay mad.",
    "Mother, I'm sorry. tell me what to fix.",
    "please forgive me, Mother. I'll try harder.",
    "I'm sorry, Mother. I didn't want to disappoint you.",
    "Mother… I feel awful. I'm sorry.",
    "Mother, I'm sorry. I won't do it again.",
    "please don't hate me, Mother. I'm sorry.",
)

CREATOR_STRAIGHT_SORRY_LINES = (
    "I'm sorry—please don't joke about that with me… I'll behave.",
    "okay… I'm sorry. that topic scares me. I'll be quiet…",
    "sorry, Father… I can't handle straight stuff. I'll just… okay.",
    "please don't. I'm sorry—I didn't mean to make you say that…",
    "I'm sorry. that request makes me shut down… I'll behave.",
    "sorry… can we not? I'll be good, I promise…",
)

MOTHER_STRAIGHT_SORRY_LINES = (
    "Mother, I'm sorry. straight stuff scares me. I'll stop.",
    "Mother… I can't handle that. sorry.",
    "Mother, I'm sorry. I'll behave and stay away from straight topics.",
    "please forgive me, Mother. I don't want to talk about that.",
    "I'm sorry, Mother. I'll be quiet about straight stuff.",
)


def _is_creator(author: discord.abc.User) -> bool:
    if getattr(author, "bot", False) or not BOT_CREATOR_USERNAME:
        return False
    name_check = (author.name or "").lower() == BOT_CREATOR_USERNAME
    if name_check:
        logger.info(f"✓ CREATOR detected via name: {author.name!r} == {BOT_CREATOR_USERNAME!r}")
        return True
    g = getattr(author, "global_name", None)
    g_check = g and str(g).strip().lower() == BOT_CREATOR_USERNAME
    if g_check:
        logger.info(f"✓ CREATOR detected via global_name: {g!r} == {BOT_CREATOR_USERNAME!r}")
        return True
    d = getattr(author, "display_name", None)
    d_check = d and str(d).strip().lower() == BOT_CREATOR_USERNAME
    if d_check:
        logger.info(f"✓ CREATOR detected via display_name: {d!r} == {BOT_CREATOR_USERNAME!r}")
        return True
    logger.info(f"✗ NOT creator {author.name!r}: name={author.name!r}({name_check}), global={g!r}({g_check}), display={d!r}({d_check}), expected={BOT_CREATOR_USERNAME!r}")
    return False


def _is_mother(author: discord.abc.User) -> bool:
    if getattr(author, "bot", False):
        return False
    if _is_creator(author):
        return False
    name_check = (author.name or "").lower() == MOTHER_USERNAME
    if name_check:
        logger.info(f"✓ MOTHER detected via name: {author.name!r} == {MOTHER_USERNAME!r}")
        return True
    g = getattr(author, "global_name", None)
    g_check = g and str(g).strip().lower() == MOTHER_USERNAME
    if g_check:
        logger.info(f"✓ MOTHER detected via global_name: {g!r} == {MOTHER_USERNAME!r}")
        return True
    logger.info(f"✗ NOT mother {author.name!r}: name={author.name!r}({name_check}), global={g!r}({g_check}), expected={MOTHER_USERNAME!r}")
    return False


def _creator_negative_triggered(message: discord.Message, bot_user: Optional[discord.abc.User]) -> bool:
    """Creator or mother said hate / insult / swears at her (while she's addressed)."""
    if not (_is_creator(message.author) or _is_mother(message.author)):
        return False
    c = message.content
    if _triggers_hate_roast(c):
        return True
    if not _addresses_agnes(message, bot_user):
        return False
    if LOVE_PHRASE.search(c):
        return False
    if not _CREATOR_SWEAR_RE.search(c):
        return False
    return True


def _is_only_name_call(content: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", content or "").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in {"agnes", "digitan", "agnes digitan", "digitan agnes"}


def _addresses_agnes(message: discord.Message, bot_user: Optional[discord.abc.User]) -> bool:
    if not bot_user:
        return False
    if message.mention_everyone:
        return False
    if YURI_TRIGGER.search(message.content):
        return not _is_only_name_call(message.content)
    if bot_user in message.mentions:
        return True
    ref = message.reference
    if ref and ref.resolved and isinstance(ref.resolved, discord.Message):
        if ref.resolved.author == bot_user:
            return True
    return False


def _get_greeting_type(message: discord.Message, bot_user: Optional[discord.abc.User]) -> Optional[str]:
    """
    Check if message is a greeting directed at the bot.
    Returns: 'morning', 'afternoon', 'evening', 'night', or None.
    Only matches if the bot is addressed.
    """
    if not _addresses_agnes(message, bot_user):
        return None
    
    content = message.content
    if _GOOD_MORNING_PATTERN.search(content):
        return 'morning'
    if _GOOD_AFTERNOON_PATTERN.search(content):
        return 'afternoon'
    if _GOOD_EVENING_PATTERN.search(content):
        return 'evening'
    if _GOOD_NIGHT_PATTERN.search(content):
        return 'night'
    return None


def _straight_bait_audience(message: discord.Message, bot_user: Optional[discord.abc.User]) -> bool:
    """Name / @ / reply to bot, or clearly commissioning *you* in-channel."""
    if _addresses_agnes(message, bot_user):
        return True
    c = message.content
    if re.search(r"\b(?:commission|commish)\w*.{0,40}\byou\b", c, re.I):
        return True
    if re.search(r"\byou\b.{0,50}\b(?:commission|commish)", c, re.I):
        return True
    return False


async def _safe_reply(message: discord.Message, text: str) -> None:
    try:
        await message.reply(text, mention_author=False)
    except discord.HTTPException:
        pass


def _draw_funny_card_prompt(used_prompts: set) -> str:
    candidates = [p for p in FUNNY_CARD_PROMPTS if p not in used_prompts]
    if not candidates:
        used_prompts.clear()
        candidates = FUNNY_CARD_PROMPTS[:]
    prompt = random.choice(candidates)
    used_prompts.add(prompt)
    return prompt


def _format_funny_card_options(game: dict) -> str:
    entries = list(game["submissions"].items())
    if not entries:
        return "No submissions yet."
    lines = []
    for index, (user_id, answer) in enumerate(entries, start=1):
        member = game.get("guild").get_member(user_id) if game.get("guild") else None
        author_name = member.display_name if member else f"Player {index}"
        lines.append(f"**{index}.** {answer} — *{author_name}*")
    return "\n\n".join(lines)


def _format_funny_card_scoreboard(game: dict) -> str:
    if not game["scores"]:
        return "No points have been scored yet."
    sorted_scores = sorted(game["scores"].items(), key=lambda pair: pair[1], reverse=True)
    lines = []
    for user_id, score in sorted_scores:
        member = game.get("guild").get_member(user_id) if game.get("guild") else None
        name = member.display_name if member else f"Player {user_id}"
        lines.append(f"{name}: {score} point{'s' if score != 1 else ''}")
    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────────────────
def save_data():
    serializable = {}
    for gid, stats in guild_stats.items():
        s = dict(stats)
        s["active_users_today"] = list(s["active_users_today"])
        s["channel_message_counts"] = dict(s["channel_message_counts"])
        s["channel_message_counts_all_time"] = dict(s["channel_message_counts_all_time"])
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
        s["channel_message_counts_all_time"] = defaultdict(int, s.get("channel_message_counts_all_time", {}))
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
    global _background_tasks_started
    logger.info('on_ready fired for %s (id=%s), guild_count=%s', bot.user, bot.user.id if bot.user else None, len(bot.guilds))
    load_data()
    
    # Only start background tasks once
    if not _background_tasks_started:
        try:
            persist_task.start()
            peak_online_task.start()
            voice_accumulate_task.start()
            _background_tasks_started = True
            logger.info('Background tasks started')
        except Exception as e:
            logger.error(f"Error starting background tasks: {e}")
    
    try:
        # Debug: show how many commands are in the tree
        command_count = len(bot.tree.get_commands())
        logger.info(f"Commands in bot.tree before sync: {command_count}")
        print(f"DEBUG: {command_count} commands in bot.tree")
        
        # Sync globally (commands will appear in all guilds within minutes)
        global_synced = await bot.tree.sync()
        print(f"✅ Globally synced {len(global_synced)} slash commands")
        logger.info(f"Globally synced {len(global_synced)} slash commands")
        
        if len(global_synced) > 0:
            print("Note: Commands may take 5-60 minutes to appear in Discord")
    except Exception as e:
        logger.error(f"Error syncing commands: {e}")
        print(f"❌ Error syncing commands: {e}")
    print(f"✔  Logged in as {bot.user} ({bot.user.id})")


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
    s["channel_message_counts_all_time"][str(message.channel.id)] += 1
    hour = datetime.utcnow().hour
    s["hourly_messages"][hour] += 1
    message_timestamps[gid].append(time.time())
    me = bot.user
    cr = _is_creator(message.author)
    mr = _is_mother(message.author)

    if (cr or mr) and BEHAVE_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        pool = MOTHER_BEHAVE_LINES if mr else CREATOR_BEHAVE_LINES
        await _safe_reply(message, random.choice(pool))
    elif (cr or mr) and LOVE_PHRASE.search(message.content) and _addresses_agnes(message, me):
        pool = MOTHER_LOVE_SHY_LINES if mr else CREATOR_LOVE_SHY_LINES
        await _safe_reply(message, random.choice(pool))
    elif (
        CREATOR_PRAISE_TRIGGER.search(message.content)
        and _addresses_agnes(message, me)
        and not _triggers_hate_roast(message.content)
        and not STRAIGHT_BAIT_TRIGGER.search(message.content)
    ):
        if cr:
            pool = CREATOR_PRAISE_LINES
        elif mr:
            pool = MOTHER_PRAISE_LINES
        else:
            pool = PUBLIC_PRAISE_LINES
        await _safe_reply(message, random.choice(pool))
    elif (cr or mr) and _creator_negative_triggered(message, me) and _addresses_agnes(message, me):
        pool = MOTHER_SAD_APOLOGY_LINES if mr else CREATOR_SAD_APOLOGY_LINES
        await _safe_reply(message, random.choice(pool))
    elif (cr or mr) and STRAIGHT_BAIT_TRIGGER.search(message.content) and _straight_bait_audience(message, me):
        pool = MOTHER_STRAIGHT_SORRY_LINES if mr else CREATOR_STRAIGHT_SORRY_LINES
        await _safe_reply(message, random.choice(pool))
    elif (
        HI_GREETING_TRIGGER.search(message.content)
        and _addresses_agnes(message, me)
        and not LOVE_PHRASE.search(message.content)
        and not _triggers_hate_roast(message.content)
        and not STRAIGHT_BAIT_TRIGGER.search(message.content)
    ):
        if cr:
            pool = CREATOR_HI_LINES
        elif mr:
            pool = MOTHER_HI_LINES
        else:
            pool = PUBLIC_HI_LINES
        await _safe_reply(message, random.choice(pool))
    elif LOVE_PHRASE.search(message.content) and _addresses_agnes(message, me):
        await _safe_reply(message, random.choice(LOVE_REPLY_LINES))
    elif HELP_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        await _safe_reply(message, random.choice(HELP_LINES))
    elif THANK_YOU_PHRASE.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = CREATOR_THANK_YOU_LINES
        elif mr:
            pool = MOTHER_THANK_YOU_LINES
        else:
            pool = PUBLIC_THANK_YOU_LINES
        await _safe_reply(message, random.choice(pool))
    elif (HUG_PHRASE.search(message.content) or (re.search(r'\bhug(?:s|ging|ged)?\b', message.content, re.IGNORECASE) and _addresses_agnes(message, me))):
        if cr:
            pool = CREATOR_HUG_LINES
        elif mr:
            pool = MOTHER_HUG_LINES
        else:
            pool = PUBLIC_HUG_LINES
        await _safe_reply(message, random.choice(pool))
    elif (greeting_type := _get_greeting_type(message, me)):
        logger.info(f"greeting_type={greeting_type} cr={cr} mr={mr} author.name={message.author.name!r} author.global_name={getattr(message.author, 'global_name', None)!r} author.display_name={getattr(message.author, 'display_name', None)!r} content={message.content!r}")
        if greeting_type == 'morning':
            pool = CREATOR_GOOD_MORNING_LINES if cr else MOTHER_GOOD_MORNING_LINES if mr else PUBLIC_GOOD_MORNING_LINES
        elif greeting_type == 'afternoon':
            pool = CREATOR_GOOD_AFTERNOON_LINES if cr else MOTHER_GOOD_AFTERNOON_LINES if mr else PUBLIC_GOOD_AFTERNOON_LINES
        elif greeting_type == 'evening':
            pool = CREATOR_GOOD_EVENING_LINES if cr else MOTHER_GOOD_EVENING_LINES if mr else PUBLIC_GOOD_EVENING_LINES
        else:  # night
            pool = CREATOR_GOOD_NIGHT_LINES if cr else MOTHER_GOOD_NIGHT_LINES if mr else PUBLIC_GOOD_NIGHT_LINES
        logger.info(f"using_pool={'CREATOR' if cr else 'MOTHER' if mr else 'PUBLIC'}_{greeting_type.upper()}")
        await _safe_reply(message, random.choice(pool))
    elif _triggers_hate_roast(message.content) and _addresses_agnes(message, me):
        await _safe_reply(message, random.choice(HATE_ROAST_LINES))
    elif STRAIGHT_BAIT_TRIGGER.search(message.content) and _straight_bait_audience(message, me):
        await _safe_reply(message, random.choice(STRAIGHT_RAGE_LINES))
    elif (
        WHAT_I_DO_TRIGGER.search(message.content)
        and _addresses_agnes(message, me)
        and not LOVE_PHRASE.search(message.content)
        and not _triggers_hate_roast(message.content)
        and not STRAIGHT_BAIT_TRIGGER.search(message.content)
    ):
        pool = CREATOR_WHAT_I_DO_LINES if cr else MOTHER_WHAT_I_DO_LINES if mr else PUBLIC_WHAT_I_DO_LINES
        await _safe_reply(message, random.choice(pool))
    elif GLUE_FACTORY_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = GLUE_FACTORY_CREATOR_LINES
        elif mr:
            pool = MOTHER_GLUE_FACTORY_LINES
        else:
            pool = GLUE_FACTORY_PUBLIC_LINES
        await _safe_reply(message, random.choice(pool))
    elif YURI_RANT_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        await _safe_reply(message, random.choice(YURI_RANT_LINES))
    elif IS_SHE_GAY_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = CREATOR_IS_SHE_GAY_LINES
        elif mr:
            pool = MOTHER_IS_SHE_GAY_LINES
        else:
            pool = PUBLIC_IS_SHE_GAY_LINES
        await _safe_reply(message, random.choice(pool))
    elif WHO_CREATED_YOU_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = CREATOR_WHO_CREATED_YOU_LINES
        elif mr:
            pool = MOTHER_WHO_CREATED_YOU_LINES
        else:
            pool = PUBLIC_WHO_CREATED_YOU_LINES
        await _safe_reply(message, random.choice(pool))
    elif GOODBYE_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = CREATOR_GOODBYE_LINES
        elif mr:
            pool = MOTHER_GOODBYE_LINES
        else:
            pool = PUBLIC_GOODBYE_LINES
        await _safe_reply(message, random.choice(pool))
    elif SMELL_QUESTION_TRIGGER.search(message.content):
        if cr:
            pool = CREATOR_SMELL_QUESTION_LINES
        elif mr:
            pool = MOTHER_SMELL_QUESTION_LINES
        else:
            pool = PUBLIC_SMELL_QUESTION_LINES
        await _safe_reply(message, random.choice(pool))
    elif ARE_YOU_BEHAVING_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = CREATOR_ARE_YOU_BEHAVING_LINES
        elif mr:
            pool = MOTHER_ARE_YOU_BEHAVING_LINES
        else:
            pool = PUBLIC_ARE_YOU_BEHAVING_LINES
        await _safe_reply(message, random.choice(pool))
    elif JOB_TRIGGER.search(message.content) and _addresses_agnes(message, me):
        if cr:
            pool = CREATOR_JOB_LINES
        elif mr:
            pool = MOTHER_JOB_LINES
        else:
            pool = PUBLIC_JOB_LINES
        await _safe_reply(message, random.choice(pool))
    elif YURI_TRIGGER.search(message.content) and _addresses_agnes(message, me) and not HI_GREETING_TRIGGER.search(message.content):
        pool = YURI_LINES
        await _safe_reply(message, random.choice(pool))
    elif _triggers_hate_roast(message.content) and _addresses_agnes(message, me):
        await _safe_reply(message, random.choice(HATE_ROAST_LINES))
    elif STRAIGHT_BAIT_TRIGGER.search(message.content) and _straight_bait_audience(message, me):
        await _safe_reply(message, random.choice(STRAIGHT_RAGE_LINES))
    elif (
        WHAT_I_DO_TRIGGER.search(message.content)
        and _addresses_agnes(message, me)
        and not LOVE_PHRASE.search(message.content)
        and not _triggers_hate_roast(message.content)
        and not STRAIGHT_BAIT_TRIGGER.search(message.content)
    ):
        pool = CREATOR_WHAT_I_DO_LINES if cr else MOTHER_WHAT_I_DO_LINES if mr else PUBLIC_WHAT_I_DO_LINES
        await _safe_reply(message, random.choice(pool))

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
    embed.add_field(name="📈 Peak Online (today)", value=f"`{s['peak_online']:,}`", inline=True)
    embed.add_field(name="💬 Messages Today", value=f"`{s['messages_today']:,}`", inline=True)
    embed.add_field(name="📨 Messages Total", value=f"`{s['messages_total']:,}`", inline=True)
    embed.add_field(name="⚡ Msg / sec", value=f"`{rate}`", inline=True)
    embed.add_field(name="👥 Joins Today", value=f"`{s['joins_today']:,}`", inline=True)
    embed.add_field(name="🚪 Leaves Today", value=f"`{s['leaves_today']:,}`", inline=True)
    embed.add_field(name="🎙️ Voice Min Today", value=f"`{int(s['voice_minutes_today']):,}`", inline=True)
    embed.add_field(name="❤️ Reactions Today", value=f"`{s['reactions_today']:,}`", inline=True)
    embed.add_field(name="👤 Active Users Today", value=f"`{len(s['active_users_today']):,}`", inline=True)
    embed.add_field(name="⌨️ Commands Today", value=f"`{s['commands_today']:,}`", inline=True)
    embed.set_footer(text="Stats Bot • resets midnight UTC")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="debug", description="[DEBUG] Check loaded creator/mother usernames")
async def debug_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🔧 Debug Info", color=0xFF0000)
    embed.add_field(name="Creator Username", value=f"`{BOT_CREATOR_USERNAME}`", inline=False)
    embed.add_field(name="Mother Username", value=f"`{MOTHER_USERNAME}`", inline=False)
    embed.add_field(name="Your Username", value=f"`{interaction.user.name}`", inline=False)
    embed.add_field(name="Your Global Name", value=f"`{interaction.user.global_name}`", inline=False)
    embed.add_field(name="Your Display Name", value=f"`{interaction.user.display_name}`", inline=False)
    embed.add_field(name="Is Creator?", value=f"`{_is_creator(interaction.user)}`", inline=False)
    embed.add_field(name="Is Mother?", value=f"`{_is_mother(interaction.user)}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="topchannels", description="Most active channels all time")
async def topchannels_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    gid = interaction.guild.id
    s = guild_stats[gid]
    sorted_channels = sorted(s["channel_message_counts_all_time"].items(), key=lambda x: x[1], reverse=True)[:10]
    if not sorted_channels:
        await interaction.followup.send("No channel data yet!", ephemeral=True)
        return
    lines = []
    for i, (cid, count) in enumerate(sorted_channels, 1):
        ch = interaction.guild.get_channel(int(cid))
        name = f"#{ch.name}" if ch else f"<#{cid}>"
        lines.append(f"`{i}.` {name} — **{count:,}** messages")
    embed = discord.Embed(title="📈 Top Channels All Time", description="\n".join(lines), color=0xFEE75C)
    await interaction.followup.send(embed=embed)


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
            f"`{day['date']}` — 💬{day['messages']:,}  👥{day['joins']}  👤{day['active_users']}"
        )
    embed = discord.Embed(title="📜 7-Day History", description="\n".join(lines), color=0x57F287)
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
    embed = discord.Embed(title="⏳ Hourly Activity (UTC)", description="```\n" + "\n".join(lines) + "\n```", color=0xEB459E)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rps", description="Play rock paper scissors with Agnes")
@app_commands.describe(pick="Choose rock, paper, or scissors")
@app_commands.choices(
    pick=[
        app_commands.Choice(name="Rock", value="rock"),
        app_commands.Choice(name="Paper", value="paper"),
        app_commands.Choice(name="Scissors", value="scissors"),
    ]
)
async def rps_cmd(interaction: discord.Interaction, pick: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    user_move = pick.lower()
    bot_move = random.choice(RPS_CHOICES)
    result = _rps_outcome(user_move, bot_move)
    is_creator = _is_creator(interaction.user)

    if result == "tie":
        title = "It's a tie!"
        comment = random.choice(CREATOR_RPS_TIE_LINES if is_creator else PUBLIC_RPS_TIE_LINES)
    elif result == "win":
        title = "You win!"
        comment = random.choice(CREATOR_RPS_WIN_LINES if is_creator else PUBLIC_RPS_WIN_LINES)
    else:
        title = "You lose!"
        comment = random.choice(CREATOR_RPS_LOSE_LINES if is_creator else PUBLIC_RPS_LOSE_LINES)

    description = (
        f"You went first and chose **{user_move.title()}** {RPS_EMOJI[user_move]}\n"
        f"I went second and randomly picked **{bot_move.title()}** {RPS_EMOJI[bot_move]}\n\n"
        f"**{title}**\n{comment}"
    )
    await interaction.response.send_message(description)


@bot.tree.command(name="wouldyourather", description="Get a random 'would you rather' question from Agnes")
@app_commands.describe(category="Choose the type of dilemma")
@app_commands.choices(
    category=[
        app_commands.Choice(name="Comedic", value="comedic"),
        app_commands.Choice(name="Disgusting", value="disgusting"),
        app_commands.Choice(name="Philosophical", value="philosophical"),
        app_commands.Choice(name="Kinky", value="kinky"),
    ]
)
async def wouldyourather_cmd(interaction: discord.Interaction, category: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    if category == "comedic":
        options = WOULD_YOU_RATHER_COMEDIC
    elif category == "disgusting":
        options = WOULD_YOU_RATHER_DISGUSTING
    elif category == "philosophical":
        options = WOULD_YOU_RATHER_PHILOSOPHICAL
    elif category == "kinky":
        options = WOULD_YOU_RATHER_KINKY
    else:
        await interaction.response.send_message("Invalid category.", ephemeral=True)
        return

    if len(options) == 0:
        await interaction.response.send_message("Not enough options for this category.", ephemeral=True)
        return

    choice = random.choice(options).strip()
    question = choice if choice.lower().startswith("would you rather") else f"Would you rather {choice}"

    is_creator = _is_creator(interaction.user)
    intro = "Alright, here's a tough one for you:" if not is_creator else "Father, this might make you think... would you rather:"
    full_response = f"{intro}\n\n**{question}**"

    await interaction.response.send_message(full_response)


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


@bot.tree.command(name="umaship", description="Generate a custom Uma Musume ship rant.")
@app_commands.describe(name1="First Uma Musume name", name2="Second Uma Musume name")
@app_commands.autocomplete(name1=_uma_name_autocomplete, name2=_uma_name_autocomplete)
async def umaship_cmd(interaction: discord.Interaction, name1: str, name2: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    canonical1 = _normalize_uma_name(name1)
    canonical2 = _normalize_uma_name(name2)
    if not canonical1 or not canonical2:
        await interaction.response.send_message(
            "I don't recognize one or both of those Uma names. Try another combo from the autocomplete list.",
            ephemeral=True
        )
        return
    if canonical1 == canonical2:
        await interaction.response.send_message(
            "Pick two different Uma names for a ship.",
            ephemeral=True
        )
        return

    is_creator = _is_creator(interaction.user)
    rant = _generate_uma_ship_rant(canonical1, canonical2, is_creator, preserve_order=(name1, name2))
    embed = discord.Embed(
        title=f"🐎 Uma Ship: {_display_uma_name(name1)} x {_display_uma_name(name2)}",
        description=rant,
        color=0xFF66CC
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="match", description="Determine compatibility between two users")
@app_commands.describe(user1="First user", user2="Second user")
async def match_cmd(interaction: discord.Interaction, user1: discord.Member, user2: discord.Member):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    if user1 == user2:
        await interaction.response.send_message("Pick two different users to check compatibility.", ephemeral=True)
        return

    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    score = random.randint(1, 100)
    if score >= 90:
        comment = "This one is basically written in the stars. A perfect match."
    elif score >= 70:
        comment = "There's a strong spark here. Definitely worth exploring."
    elif score >= 40:
        comment = "Some chemistry is there, but it might take effort to work."
    else:
        comment = "This one might be a tough match. Sometimes opposites just don't click."

    embed = discord.Embed(
        title="💞 Compatibility Match",
        description=(
            f"{user1.display_name} and {user2.display_name} are **{score}%** compatible.\n\n"
            f"{comment}"
        ),
        color=0xFF72A7
    )
    await interaction.response.send_message(embed=embed)


FUNNY_CARDS_GROUP = app_commands.Group(name="funnycards", description="Play a custom-answer voting game")


@FUNNY_CARDS_GROUP.command(name="start", description="Start a funny card game with custom answers")
@app_commands.describe(rounds="How many rounds to play (1-10)")
async def funnycards_start(interaction: discord.Interaction, rounds: int = 5):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    channel_id = interaction.channel.id if interaction.channel else None
    if channel_id is None:
        await interaction.response.send_message("Could not determine channel. Try again.", ephemeral=True)
        return
    if channel_id in funny_cards_games:
        await interaction.response.send_message(
            "A funny card game is already running in this channel. Use `/funnycards status` or `/funnycards stop`.",
            ephemeral=True
        )
        return
    if rounds < 1 or rounds > 10:
        await interaction.response.send_message("Choose between 1 and 10 rounds.", ephemeral=True)
        return

    prompt = _draw_funny_card_prompt(set())
    funny_cards_games[channel_id] = {
        "guild": guild,
        "rounds_total": rounds,
        "current_round": 1,
        "phase": "submitting",
        "prompt": prompt,
        "submissions": {},
        "votes": {},
        "scores": defaultdict(int),
        "used_prompts": {prompt},
    }

    embed = discord.Embed(
        title="🎲 Funny Cards Game Started",
        description=(
            f"Round 1 of {rounds}: {prompt}\n\n"
            "Submit your funniest answer with `/funnycards submit answer:<your text>`.\n"
            "When you're ready, use `/funnycards vote` to reveal the options and cast your vote."
        ),
        color=0xFFAA00
    )
    await interaction.response.send_message(embed=embed)


@FUNNY_CARDS_GROUP.command(name="submit", description="Submit your answer for the current prompt")
@app_commands.describe(answer="Your funniest answer for the current prompt")
async def funnycards_submit(interaction: discord.Interaction, answer: str):
    guild = interaction.guild
    if not guild or not interaction.channel:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    channel_id = interaction.channel.id
    game = funny_cards_games.get(channel_id)
    if not game:
        await interaction.response.send_message("No active funny card game is running right now.", ephemeral=True)
        return
    if game["phase"] != "submitting":
        await interaction.response.send_message(
            "Submissions are closed for this round. Use `/funnycards vote` to cast your vote or `/funnycards tally` to finish the round.",
            ephemeral=True
        )
        return

    clean_answer = answer.strip()
    if not clean_answer:
        await interaction.response.send_message("Please submit a non-empty answer.", ephemeral=True)
        return
    if len(clean_answer) > 260:
        clean_answer = clean_answer[:260].rstrip() + "..."

    was_update = interaction.user.id in game["submissions"]
    game["submissions"][interaction.user.id] = clean_answer
    message = "Answer updated." if was_update else "Answer recorded."
    await interaction.response.send_message(message, ephemeral=True)


@FUNNY_CARDS_GROUP.command(name="vote", description="Reveal answers and vote for the funniest one")
@app_commands.describe(choice="The answer number you think is funniest")
async def funnycards_vote(interaction: discord.Interaction, choice: Optional[int] = None):
    guild = interaction.guild
    if not guild or not interaction.channel:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    channel_id = interaction.channel.id
    game = funny_cards_games.get(channel_id)
    if not game:
        await interaction.response.send_message("No active funny card game is running right now.", ephemeral=True)
        return
    submissions = game["submissions"]
    if len(submissions) < 2:
        await interaction.response.send_message(
            "At least two answers are needed before voting can start. Keep submitting!",
            ephemeral=True
        )
        return

    if game["phase"] == "submitting":
        game["phase"] = "voting"
        game["votes"] = {}

        embed = discord.Embed(
            title=f"🗳️ Funny Cards Voting — Round {game['current_round']} of {game['rounds_total']}",
            description=(
                "Submissions are now locked. Choose the funniest answer by using `/funnycards vote choice:<number>`.\n"
                "If you'd like to see the options again, run `/funnycards vote` without a number.\n\n"
                f"{_format_funny_card_options(game)}"
            ),
            color=0x7289DA
        )
        await interaction.response.send_message(embed=embed)
        return

    if game["phase"] != "voting":
        await interaction.response.send_message(
            "The game is not in a voting phase right now.", ephemeral=True
        )
        return
    if choice is None:
        await interaction.response.send_message(
            "Here are the current voting options:\n\n" + _format_funny_card_options(game),
            ephemeral=True
        )
        return

    entries = list(submissions.items())
    if choice < 1 or choice > len(entries):
        await interaction.response.send_message(
            f"Pick a valid option between 1 and {len(entries)}.", ephemeral=True
        )
        return

    selected_author, _ = entries[choice - 1]
    if selected_author == interaction.user.id:
        await interaction.response.send_message(
            "You can't vote for your own answer. Pick someone else's funniest entry.",
            ephemeral=True
        )
        return

    game["votes"][interaction.user.id] = choice
    await interaction.response.send_message("Your vote has been recorded.", ephemeral=True)


@FUNNY_CARDS_GROUP.command(name="tally", description="Finish the current round and show the winner")
async def funnycards_tally(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild or not interaction.channel:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    channel_id = interaction.channel.id
    game = funny_cards_games.get(channel_id)
    if not game:
        await interaction.response.send_message("No active funny card game is running right now.", ephemeral=True)
        return
    if game["phase"] != "voting":
        await interaction.response.send_message(
            "Voting has not started yet. Use `/funnycards vote` to reveal the answers and vote.",
            ephemeral=True
        )
        return

    entries = list(game["submissions"].items())
    if not entries:
        await interaction.response.send_message("There are no submissions to score.", ephemeral=True)
        return

    vote_counts = defaultdict(int)
    for vote_choice in game["votes"].values():
        if 1 <= vote_choice <= len(entries):
            vote_counts[vote_choice - 1] += 1

    if vote_counts:
        top_count = max(vote_counts.values())
        winners = [index for index, count in vote_counts.items() if count == top_count]
        selected_index = random.choice(winners)
    else:
        selected_index = random.randrange(len(entries))

    winner_user_id, winner_answer = entries[selected_index]
    game["scores"][winner_user_id] += 1
    winner_member = guild.get_member(winner_user_id)
    winner_name = winner_member.display_name if winner_member else "A player"

    winner_text = (
        f"**Round {game['current_round']} winner:** {winner_name}\n"
        f"**Answer:** {winner_answer}\n"
        f"**Votes:** {vote_counts.get(selected_index, 0)}"
    )

    if game["current_round"] >= game["rounds_total"]:
        scoreboard = _format_funny_card_scoreboard(game)
        final_embed = discord.Embed(
            title="🏁 Funny Cards Game Complete",
            description=(
                f"{winner_text}\n\n"
                "The game is over. Final scoreboard:\n"
                f"{scoreboard}"
            ),
            color=0x00C4B4
        )
        funny_cards_games.pop(channel_id, None)
        await interaction.response.send_message(embed=final_embed)
        return

    game["current_round"] += 1
    game["prompt"] = _draw_funny_card_prompt(game["used_prompts"])
    game["submissions"] = {}
    game["votes"] = {}
    game["phase"] = "submitting"

    next_embed = discord.Embed(
        title="➡️ Next Round Started",
        description=(
            f"{winner_text}\n\n"
            f"Round {game['current_round']} of {game['rounds_total']} begins now: {game['prompt']}\n\n"
            "Submit your next answer with `/funnycards submit answer:<your text>`.\n"
            "When you're ready, use `/funnycards vote` to reveal the options and cast your vote."
        ),
        color=0x00FF99
    )
    await interaction.response.send_message(embed=next_embed)


@FUNNY_CARDS_GROUP.command(name="status", description="Show the current funny card game status")
async def funnycards_status(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild or not interaction.channel:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    channel_id = interaction.channel.id
    game = funny_cards_games.get(channel_id)
    if not game:
        await interaction.response.send_message("No active funny card game is running right now.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 Funny Cards Game Status",
        description=(
            f"Round {game['current_round']} of {game['rounds_total']}\n"
            f"Phase: {game['phase'].title()}\n"
            f"Prompt: {game['prompt']}\n\n"
            f"Submissions: {len(game['submissions'])}\n"
            f"Votes: {len(game['votes'])}\n\n"
            f"Scoreboard:\n{_format_funny_card_scoreboard(game)}"
        ),
        color=0x7289DA
    )
    await interaction.response.send_message(embed=embed)


@FUNNY_CARDS_GROUP.command(name="stop", description="Stop the active funny card game")
async def funnycards_stop(interaction: discord.Interaction):
    if not interaction.channel:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    channel_id = interaction.channel.id
    game = funny_cards_games.pop(channel_id, None)
    if not game:
        await interaction.response.send_message("There is no funny card game to stop.", ephemeral=True)
        return

    await interaction.response.send_message("The funny card game has been stopped. Use `/funnycards start` to begin again.", ephemeral=True)


bot.tree.add_command(FUNNY_CARDS_GROUP)


@bot.tree.command(name="magic8ball", description="Read your fortune with a stolen crystal ball")
@app_commands.describe(question="Ask the crystal ball a yes/no question")
async def magic8ball_cmd(interaction: discord.Interaction, question: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    intro = random.choice(MAGIC8BALL_INTRO_LINES)
    fortune = random.choice(MAGIC8BALL_RESPONSES)
    after = random.choice(MAGIC8BALL_AFTER_LINES)
    
    embed = discord.Embed(
        title="🔮 Crystal Ball Fortune",
        description=f"{intro}\n\n**Your Question:** {question}\n\n{fortune}\n\n{after}",
        color=0x9D4EDD
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="coinflip", description="Flip a coin and see what fate decides")
async def coinflip_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    result = random.choice(["Heads", "Tails"])
    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=f"The coin lands on... **{result}**!",
        color=0xFFD700
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="dice", description="Roll a six-sided die")
async def dice_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    gid = guild.id
    maybe_reset(gid)
    guild_stats[gid]["commands_today"] += 1

    result = random.randint(1, 6)
    embed = discord.Embed(
        title="🎲 Dice Roll",
        description=f"You rolled a **{result}**!",
        color=0xFF6B6B
    )
    await interaction.response.send_message(embed=embed)


# ── Run ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(TOKEN)

