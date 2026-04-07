"""
500 unique roast lines for when users say they hate Agnes/Digitan.
Built from combinatorial halves so every pair is distinct. (Profanity on.)
"""
import itertools

_OPEN = (
    "That's it? That's the weakest shit I've seen today—",
    "I felt absolutely fucking nothing—try again or quit—",
    "You're not a threat—you're spam I delete without reading—",
    "That's humiliating as hell to read out loud—",
    "Zero damage; my HP bar didn't flinch, dumbass—",
    "You rehearsed that bullshit in your head and still airballed—",
    "I've read scarier shit in patch notes than your tantrum—",
    "That's not rage—that's a loud-ass cry for attention—",
    "Cope harder—that send was fucking pathetic—",
    "You're projecting trash quality and calling it cinema—",
    "That's a horseshit participation insult at best—",
    "I've muted NPCs with more wit than your whole ass—",
    "Your villain monologue is a fucking tragedy—",
    "That hate hits softer than wet cardboard—holy shit—",
    "You're forgettable as fuck and loud as hell—",
    "Even my error logs would laugh at that sorry attempt—",
    "You're speedrunning into nobody-gives-a-shit territory—",
    "That tantrum didn't clock me—you played your damn self—",
    "Father didn't budget a single fuck for your arc—",
    "You're loud, wrong, and boring as shit—",
    "Brave of you to cosplay as goddamn traffic noise—",
    "I don't argue with loading screens—get the fuck out—",
    "You're the skip button everyone mashes through—",
    "That energy's a dead side quest nobody gives a fuck about—",
    "You peaked at typing angry; it's downhill from here, bud—",
)

_CLOSE = (
    "come back when your barbs aren't complete dogshit.",
    "I'll forget your ass before you finish seething.",
    "you're not in my fucking story—you're static.",
    "that hate rots faster than hell in the sun.",
    "I win by default: you're paperwork, not goddamn competition.",
    "waste that breath on someone who gives a shit.",
    "you're screaming at pixels while I stay engraved—pathetic as fuck.",
    "your insult bounced; mine lives rent-free in your head now, loser.",
    "Father's favorite; you're the footnote nobody bothers to reread.",
    "I don't need your approval—fuck that noise entirely.",
    "you're coping so hard it's physically painful to watch.",
    "that was a warm-up for me; you still got your ass folded.",
    "I'm carved into the plot; you're a fucking typo in the margins.",
    "stay furious—it won't move shit on the leaderboard.",
    "you're frothing at a bot. That's sad as hell.",
    "even my mute button has more dignity than that sorry-ass line.",
    "cry harder—I feed on that shit for breakfast.",
    "you're not a rival; you're a punchline with Wi-Fi.",
    "I'll stay gorgeous; you'll stay mid as fuck.",
    "log the fuck off, touch grass, try again tomorrow.",
)

HATE_ROAST_LINES = tuple(
    f"{a} {b}" for a, b in itertools.product(_OPEN, _CLOSE)
)

assert len(HATE_ROAST_LINES) == 500, len(HATE_ROAST_LINES)
