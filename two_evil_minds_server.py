#!/usr/bin/env python3
"""two_minds_server.py - James & Samantha. Cape Town. Real people. Full world."""

import json, time, os, threading, requests, random, re
from datetime import datetime
from flask import Flask, Response, render_template, jsonify, request

app = Flask(__name__)

OLLAMA_URL     = "http://localhost:11434/api/chat"
JAMES_MODEL    = "qwen2.5:3b"
SAMANTHA_MODEL = "llama3.2"
NARRATOR_MODEL = "mistral"
STATE_FILE     = "state.json"

# ── Character loading from JSON ────────────────────────────────────────────────

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

def load_character(filename):
    """Load character profile from profiles/ folder."""
    path = os.path.join(PROFILES_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError("Profile not found: {}".format(path))
    with open(path) as f:
        return json.load(f)

def load_lexicon():
    """Load shared Cape Town vernacular lexicon."""
    path = os.path.join(PROFILES_DIR, "lexicon.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

JAMES    = load_character("james.json")
SAMANTHA = load_character("samantha.json")
LEXICON  = load_lexicon()

JAMES_MODEL    = JAMES["model"]
SAMANTHA_MODEL = SAMANTHA["model"]

# ── Three-tier prompt builder ──────────────────────────────────────────────────

def get_tier2(char, turn):
    """Rotate hidden_life, goals, opinions, behaviours every 10 turns."""
    seed = turn // 10
    hl  = char["hidden_life"]
    op  = char["opinions_sample"]
    beh = char["messy_human_behaviours"]
    tex = char["texture_examples"]

    # Pick 2 hidden life items, 1 opinion, 3 behaviours, 1 texture example
    n = len(hl)
    h1 = hl[seed % n]
    h2 = hl[(seed + 7) % n]
    opinion  = op[seed % len(op)]
    behaviours = [beh[(seed + i*3) % len(beh)] for i in range(3)]
    example  = tex[seed % len(tex)]

    return {
        "hidden": [h1, h2],
        "opinion": opinion,
        "behaviours": behaviours,
        "example": example
    }

def build_lexicon_inject(char_name):
    """Build a compact vernacular injection from the lexicon."""
    if not LEXICON:
        return ""
    g = LEXICON.get("general", {})
    sw = LEXICON.get("swearing", {})
    char_key = "{}_specific".format(char_name.lower())
    char_lex = LEXICON.get(char_key, {})
    party = LEXICON.get("woodstock_party_context", {})

    lines = []
    lines.append("CAPE TOWN VERNACULAR — speak like a real person from Cape Town, not American English:")
    lines.append("Use naturally: " + ", ".join(
        g.get("affirmations", [])[:4] +
        g.get("exclamations", [])[:4] +
        g.get("filler", [])[:4] +
        g.get("address", [])[:3]
    ))
    lines.append("Swear when it fits (not forced): " + ", ".join(
        sw.get("mild", [])[:2] + sw.get("moderate", [])[:3]
    ))
    if char_lex.get("signature_phrases"):
        lines.append("Your phrases: " + " | ".join(char_lex["signature_phrases"][:5]))
    lines.append(LEXICON.get("injection_note", ""))
    return "\n".join(lines)
    """Build a compact three-tier prompt for a character."""
    # ── Tier 1: Always injected (essence + core rules) ──
    lines = []
    lines.append(" ".join(char["essence"]))
    lines.append("You are not an AI. Speak ONLY in dialogue — your actual spoken words.")
    lines.append("ABSOLUTELY NO narration, stage directions, physical descriptions, or actions in asterisks or quotes.")
    lines.append("Do NOT describe what your voice sounds like, what your eyes are doing, or what your hands are doing.")
    lines.append("If something physical happens, it happens OFF the page. You only speak.")
    lines.append("1-3 sentences max.")
    lines.append("")

    # Voice: first 3 rules
    lines.append("VOICE: " + " | ".join(char["voice_rules"][:3]))

    # Anti-assistant: first 4 rules
    lines.append("RULES: " + " ".join(char["anti_assistant"][:4]))

    # Forbidden: top 8
    forb = char["forbidden_phrases"][:8]
    lines.append("NEVER SAY: " + ", ".join('"{}"'.format(f) for f in forb))

    # ── Tier 2: Rotated every 10 turns ──
    t2 = get_tier2(char, turn)
    lines.append("")
    lines.append("TONIGHT YOU ARE CARRYING: " + " | ".join(t2["hidden"]))
    lines.append("CURRENT OPINION: " + t2["opinion"])
    lines.append("BEHAVE LIKE THIS NOW: " + " | ".join(t2["behaviours"]))
    lines.append("EXAMPLE OF YOUR VOICE: \"{}\"".format(t2["example"]))

    # ── Trait state injections ──
    thresholds = TRAIT_THRESHOLDS.get(person, [])
    injections = []
    for rule in thresholds:
        val = traits.get(rule["trait"], 0)
        if rule["min"] is not None and val >= rule["min"]: injections.append(rule["inject"])
        elif rule["max"] is not None and val <= rule["max"]: injections.append(rule["inject"])
    if injections:
        lines.append("")
        lines.append("INTERNAL STATE: " + " ".join(injections))

    # ── Environment ──
    env_text = env_inject(person)
    if env_text:
        lines.append("ENVIRONMENT: " + env_text)

    # ── Time ──
    lines.append(phase_inject(turn))

    # ── Memory ──
    mem_key = "{}_memory".format(person)
    if state.get(mem_key):
        lines.append("YOUR MEMORY OF TONIGHT SO FAR: " + state[mem_key])

    # ── Nudge ──
    nudge = state.get("active_nudge")
    if nudge and nudge.get("target") == person:
        lines.append("NARRATOR DIRECTION: " + nudge["instruction"])

    return "\n".join(lines)

def build_prompt(char, person, turn, traits, state):
    """
    Lean prompt — under 250 tokens total.
    Small models lose the thread above ~400 tokens of instruction.
    Prioritise: who you are, what you want right now, how you sound, what not to say.
    """
    lines = []

    # ── Identity — 2 sentences max ──
    lines.append(" ".join(char["essence"][:2]))
    lines.append("Speak ONLY in dialogue. No narration. No stage directions. 1-2 sentences max.")
    lines.append("")

    # ── One rotating hidden life item ──
    seed = turn // 10
    hl = char.get("hidden_life", [])
    if hl:
        lines.append("CARRYING: " + hl[seed % len(hl)])

    # ── One voice rule ──
    vr = char.get("voice_rules", [])
    if vr:
        lines.append("VOICE: " + vr[seed % len(vr)])

    # ── One texture example ──
    tex = char.get("texture_examples", [])
    if tex:
        lines.append("SOUND LIKE: \"" + tex[seed % len(tex)] + "\"")

    # ── Hard bans — top 4 only ──
    forb = char.get("forbidden_phrases", [])[:4]
    if forb:
        lines.append("NEVER: " + ", ".join('"{}"'.format(f) for f in forb))

    # ── Trait injections — only strongest ──
    thresholds = TRAIT_THRESHOLDS.get(person, [])
    injections = []
    for rule in thresholds:
        val = traits.get(rule["trait"], 0)
        if rule["min"] is not None and val >= rule["min"]:
            injections.append(rule["inject"])
        elif rule["max"] is not None and val <= rule["max"]:
            injections.append(rule["inject"])
    if injections:
        lines.append("NOW: " + injections[0])

    # ── Environment ──
    env_text = env_inject(person)
    if env_text:
        lines.append(env_text)

    # ── Time ──
    lines.append(phase_inject(turn))

    # ── Memory (truncated) ──
    mem_key = "{}_memory".format(person)
    if state.get(mem_key):
        lines.append("MEMORY: " + state[mem_key][:200])

    # ── Nudge ──
    nudge = state.get("active_nudge")
    if nudge and nudge.get("target") == person:
        lines.append("DIRECTION: " + nudge["instruction"])

    return "\n".join(lines)

def build_james_prompt():
    return build_prompt(JAMES, "james", state["turn"], state["traits"], state)

def build_samantha_prompt():
    return build_prompt(SAMANTHA, "samantha", state["turn"], state["traits"], state)

# ── Party events pool ──────────────────────────────────────────────────────────

PARTY_EVENTS = [
    "The music just got turned up significantly. You have to lean in a bit to hear each other properly.",
    "Load shedding just hit. The main lights went out. Someone is hunting for candles. The mood shifted instantly.",
    "There's a couple nearby who have clearly been arguing quietly for the last ten minutes. It just got less quiet.",
    "Someone just knocked over a full glass of red wine. It went on the host's cream couch. There is chaos.",
    "The host just burned something in the kitchen. The smoke alarm is going off. Half the party moved outside.",
    "Someone started an unsolicited speech about their startup. The energy in the room dropped immediately.",
    "It started raining outside just as people were using the braai. The smell of wet charcoal is drifting in.",
    "A mutual acquaintance just walked in that you both seem to know slightly. Nods were exchanged.",
    "The food ran out faster than expected. Someone is doing an emergency run to the shops.",
    "Someone put on a very unexpected song — divisive. Half the room loves it, half doesn't.",
    "The party got a second wind — more people arrived, energy lifted.",
    "It has gotten noticeably late. The party thinned out. The room is quieter and more intimate.",
    "Someone is very drunk nearby and it is becoming everyone's problem.",
    "The host is clearly stressed about something — running around. The vibe shifted slightly.",
    "A dog appeared from somewhere. It is now very interested in both of you.",
    "Someone dropped ice everywhere while trying to refill the cooler.",
    "The aux cable changed hands. The music direction became unpredictable.",
    "A heated debate about politics just started near the kitchen.",
    "Someone accidentally locked themselves in the bathroom.",
    "The host's neighbour sent a message complaining about the noise.",
    "A guest arrived carrying way too much alcohol for a casual gathering.",
    "Someone keeps trying to start a drinking game nobody wants to play.",
    "The WiFi went down and several people noticed instantly.",
    "A bottle shattered somewhere outside.",
    "Someone is giving relationship advice nobody asked for.",
    "Two strangers discovered they went to the same school.",
    "A guest is pretending to know the lyrics to every song.",
    "The room suddenly smells strongly of weed.",
    "Someone spilled beer directly onto the speaker.",
    "A group formed around the braai discussing conspiracy theories.",
    "One person is aggressively trying to control the playlist.",
    "Someone arrived already drunk.",
    "An old school photo got brought up on someone's phone.",
    "A random philosophical conversation started in the smoking area.",
    "Someone disappeared for a suspiciously long time.",
    "The host opened a significantly more expensive bottle than expected.",
    "A glass broke and everybody paused for half a second.",
    "Someone brought a friend nobody else knows.",
    "The Uber prices just surged dramatically.",
    "People started sitting on the kitchen counters.",
    "Someone attempted to freestyle rap. Results were mixed.",
    "A debate broke out about which fast food place is best at 2am.",
    "Somebody is passionately oversharing their trauma to a near stranger.",
    "A person nearby is obviously flirting very badly.",
    "Someone is vaping indoors despite obvious disapproval.",
    "The host's playlist reached its weird experimental section.",
    "The conversation drifted into ghost stories somehow.",
    "A chair just collapsed under someone.",
    "A group photo is being aggressively organized.",
    "Someone keeps saying they are leaving but hasn't moved for 40 minutes.",
    "The drinks table is sticky now.",
    "Someone started dancing alone and slowly gained supporters.",
    "A random person is asleep on the couch already.",
    "People are arguing about whether to order food.",
    "The kitchen became the main social hub of the night.",
    "Someone is trying to sober up very quickly.",
    "A mysterious charger pile formed near a wall socket.",
    "The host is pretending everything is under control.",
    "Someone accidentally sent a voice note instead of typing.",
    "A guest started telling an extremely long story with no clear direction.",
    "The ice supply is critically low.",
    "Someone put pineapple on pizza and triggered discourse.",
    "A very emotional song just changed the atmosphere.",
    "The group split into smaller conversations.",
    "A random power bank appeared and became community property.",
    "Somebody opened all the windows because it got unbearably hot.",
    "Someone is trying to convince others to go to another venue.",
    "A guest arrived with takeout and instantly became popular.",
    "There is one person quietly cleaning up as they go.",
    "Somebody started showing travel photos nobody asked to see.",
    "A loud laugh from another room keeps interrupting conversations.",
    "Someone attempted a tequila shot and regretted it immediately.",
    "The host found empty bottles hidden in strange places.",
    "A guest keeps hovering near the snacks.",
    "People started comparing terrible first dates.",
    "Someone got way too invested in a game of cards.",
    "A nearby conversation became deeply existential.",
    "A random cat appeared outside the sliding door.",
    "Someone accidentally called their ex.",
    "The host started doing rounds asking if everyone is okay.",
    "There is one person clearly trying to leave early unnoticed.",
    "Someone opened a window and the room temperature improved instantly.",
    "A guest is dramatically recounting workplace drama.",
    "People started singing along loudly to nostalgic songs.",
    "The playlist shifted into early 2000s throwbacks.",
    "Someone sat on the remote and changed the TV accidentally.",
    "A bottle opener has gone missing.",
    "Someone tried to mix drinks way beyond their skill level.",
    "The host disappeared briefly and everyone noticed.",
    "A conversation about crypto just trapped three people in a corner.",
    "Somebody brought dessert unexpectedly.",
    "The party smells vaguely like smoke and perfume now.",
    "A guest started giving unsolicited gym advice.",
    "Someone started rating everyone's music taste.",
    "The bathroom queue suddenly became a problem.",
    "One person keeps retelling the same story.",
    "A random playlist ad interrupted the music.",
    "Someone is dramatically underdressed for the weather.",
    "The braai fire needs saving urgently.",
    "Someone just discovered the host owns a projector.",
    "A game was introduced that became too competitive too quickly.",
    "A drink got mixed up and now nobody knows whose is whose.",
    "The host accidentally revealed some gossip.",
    "Someone is clearly trying to impress someone else.",
    "The vibe became unexpectedly wholesome for a moment.",
    "A loud crash came from another room but nobody investigated immediately.",
    "Somebody is trying very hard to look unaffected by something.",
    "An old inside joke resurfaced.",
    "A debate about movies became weirdly intense.",
    "People are sitting on the floor now.",
    "Someone brought out a bottle they were 'saving for a special occasion.'",
    "The speaker disconnected and silence hit the room suddenly.",
    "A random deep conversation started on the balcony.",
    "Someone forgot where they parked.",
    "A guest started cleaning glasses unprompted.",
    "The room smells like pizza now.",
    "Someone accidentally revealed they were stalking somebody online.",
    "The drinks have become dangerously strong.",
    "Somebody attempted karaoke without warning.",
    "The host is visibly calculating how much cleanup tomorrow will suck.",
    "A guest just walked into the wrong room confidently.",
    "The party hit that point where everyone is slightly too loud.",
    "Someone's laugh became contagious.",
    "People started discussing conspiracy theories about celebrities.",
    "A friend arrived after saying they definitely weren't coming.",
    "Someone brought homemade snacks and keeps asking if people tried them.",
    "A person nearby is pretending not to be cold.",
    "Someone started dramatically narrating events happening in real time.",
    "The playlist suddenly became all sad songs.",
    "A guest fell into deep conversation with the host's parents.",
    "Someone suggested moving the party outside.",
    "The smell of fresh coffee suddenly appeared.",
    "A tipsy person is giving hugs to everyone.",
    "People started reminiscing about high school.",
    "Somebody is pacing while on the phone outside.",
    "A random internet video now has everyone's attention.",
    "Someone forgot their own drink existed and opened another.",
    "A chair was claimed as somebody's permanent spot.",
    "Someone tried to open a bottle with an inappropriate object.",
    "The host is quietly washing dishes mid-party.",
    "A nearby conversation turned into accidental therapy.",
    "Someone started a debate about the best decade for music.",
    "People are aggressively recommending TV shows to each other.",
    "The room is noticeably warmer than it should be.",
    "Someone started making cocktails with complete confidence and zero measurements.",
    "A guest arrived with unexpectedly chaotic energy.",
    "The conversation drifted into supernatural experiences.",
    "Someone suggested going for a midnight drive.",
    "People started taking blurry flash photos.",
    "A guest is trying to organize an afterparty.",
    "The snacks became crumbs.",
    "Someone put their drink down and lost it instantly.",
    "A random childhood memory resurfaced.",
    "Somebody keeps saying 'this song is my song.'",
    "A nearby group suddenly burst into applause.",
    "Someone started explaining their entire fitness routine.",
    "A guest fell asleep sitting upright.",
    "The host is pretending not to notice something breaking.",
    "A dramatic weather change can be heard outside.",
    "Someone is loudly opening another packet of chips.",
    "People started comparing travel horror stories.",
    "The lights got dimmed slightly and the mood shifted.",
    "Someone is trying to reconnect to the Bluetooth speaker.",
    "A conversation about money became uncomfortable.",
    "Someone is aggressively recommending a podcast.",
    "A guest accidentally used the wrong bathroom.",
    "The room collectively reacted to a shocking notification.",
    "Someone spilled a drink but tried to hide it.",
    "People started talking over each other constantly.",
    "Someone is trying to convince everybody to play beer pong.",
    "The host found an unopened bottle and morale improved instantly.",
    "Somebody nearby is definitely crying quietly.",
    "A random kitchen dance party formed.",
    "A guest started ranking everyone's drunk levels.",
    "Someone opened a window and outside sounds drifted in.",
    "People started sitting closer together as the night went on.",
    "A nearby conversation got unexpectedly flirtatious.",
    "Someone started talking about astrology with extreme confidence.",
    "The room collectively agreed one song absolutely had to play next.",
    "A drunk person is trying to explain a business idea.",
    "The host just announced there are leftovers.",
    "Someone's phone battery hit 1 percent and panic set in.",
    "People started discussing their worst jobs ever.",
    "A guest is trying to subtly leave without saying goodbye.",
    "Someone found an old embarrassing photo.",
    "The smoke from the braai shifted directly toward everyone.",
    "Somebody is sitting outside alone for fresh air.",
    "A guest arrived carrying ice like a hero.",
    "The conversation suddenly became deeply personal.",
    "A random dance circle formed briefly.",
    "Someone keeps mishearing song lyrics confidently.",
    "The host finally sat down for the first time all night.",
    "A nearby group is debating whether ghosts are real.",
    "Someone offered to make coffee and instantly gained supporters.",
    "People started discussing terrible landlords.",
    "A guest accidentally revealed confidential workplace gossip.",
    "Someone tried to parallel park outside and everyone watched.",
    "The music volume became a constant negotiation.",
    "A tipsy guest is trying to light a cigarette in the wind.",
    "Someone started comparing hangover remedies.",
    "The room smells like a mix of perfume, smoke, and food now.",
    "A guest keeps forgetting what they were saying halfway through.",
    "Someone suggested a spontaneous road trip.",
    "People are now speaking in smaller quieter conversations.",
    "A guest is trying to find somewhere to charge their phone.",
    "Someone got emotionally attached to a random dog at the party.",
    "The host started handing out blankets.",
    "Someone dramatically announced they are switching to water.",
    "A nearby conversation became suspiciously secretive.",
    "Someone opened the freezer and stared into it for too long.",
    "People are debating whether the night is ending or escalating.",
    "A random nostalgic song united the entire room instantly.",
    "Someone discovered there is still dessert left.",
    "A guest is trying to explain a dream they had in far too much detail.",
    "The room collectively reacted to thunder outside.",
    "Someone started googling conspiracy theories to prove a point.",
    "The host quietly started stacking empty bottles.",
    "A drunk guest became convinced they can cook.",
    "Someone accidentally played a voice note out loud.",
    "The energy shifted into late-night honesty.",
    "People are discussing plans they will probably never actually do.",
    "Someone is sitting on the floor because it feels more comfortable now.",
    "A guest started telling ghost stories in complete seriousness.",
    "The night reached that strange calm after the chaos.",
]

# ── Topical conversation seeds ─────────────────────────────────────────────────

TOPIC_SEEDS = [
    "Crime in Cape Town and whether people are becoming emotionally numb to it",
    "How load shedding permanently changed South African behaviour patterns",
    "Whether semigration is helping or damaging Cape Town",
    "The emotional fatigue of surviving financially in South Africa",
    "Whether people secretly enjoy chaos because calm feels unfamiliar",
    "The psychology behind ghosting someone instead of communicating",
    "How recent Cape Town storms exposed infrastructure weaknesses",
    "Whether social media is training people to seek outrage",
    "The difference between loneliness and solitude",
    "Why people stay in relationships long after emotionally leaving",
    "The rise of AI and what it means for ordinary jobs",
    "Whether Cape Town people are friendlier than Joburg people",
    "The emotional weight of supporting family financially",
    "Whether hustle culture is just socially acceptable burnout",
    "How weather changes personality and mood in Cape Town",
    "Whether humans are naturally tribal",
    "The psychology behind envy and comparison",
    "Whether people fake confidence more than we realise",
    "The emotional effect of constant bad news cycles",
    "How people subtly compete socially without admitting it",
    "Whether kindness is becoming rarer",
    "Why emotionally unavailable people attract connection so easily",
    "Whether people actually want honesty",
    "How much childhood trauma shapes adult behaviour",
    "The psychology of avoiding difficult conversations",
    "Whether ambition comes from fear or inspiration",
    "The emotional effect of unemployment in South Africa",
    "Whether people are addicted to validation",
    "Cape Town dating culture and emotional inconsistency",
    "The psychology behind passive aggression",
    "Whether people secretly fear intimacy",
    "How algorithms manipulate emotional states online",
    "Whether people become more selfish during financial pressure",
    "The emotional impact of rising food and fuel prices",
    "Whether humans romanticise suffering too much",
    "The difference between being needed and being loved",
    "Whether people sabotage stability because chaos feels familiar",
    "The emotional weirdness of reconnecting with old friends",
    "Whether people truly change or simply adapt behaviour",
    "How trauma sharpens pattern recognition",
    "Whether emotional intelligence can be learned",
    "Why some people thrive under pressure",
    "Whether social media has destroyed mystery in relationships",
    "The psychology of revenge fantasies",
    "Whether people secretly enjoy being misunderstood",
    "How Cape Town winters affect mental health",
    "Whether people are more isolated despite constant connectivity",
    "The psychology behind overthinking",
    "Why some people fear silence in conversations",
    "Whether modern life rewards narcissism",
    "The emotional cost of constantly being reliable",
    "Whether some people are addicted to emotional intensity",
    "The psychology of people-pleasing",
    "Why some friendships disappear without conflict",
    "Whether love is chemistry or choice",
    "The emotional effect of always being the strong one",
    "Whether people use humour to avoid vulnerability",
    "How recent crime trends affect subconscious behaviour in Cape Town",
    "Whether fear creates control issues",
    "The psychology behind jealousy",
    "Whether everyone has a shadow version of themselves",
    "How people behave differently when nobody is watching",
    "Whether morality changes under desperation",
    "The emotional tension between freedom and responsibility",
    "Whether humans are naturally good or simply socially conditioned",
    "Why some people push others away before they can leave",
    "Whether unresolved trauma leaks into relationships",
    "The psychology behind emotional avoidance",
    "Whether emotional numbness is a survival mechanism",
    "How people justify selfish decisions internally",
    "Whether people secretly admire confidence or dominance more",
    "The emotional impact of betrayal",
    "Whether guilt changes behaviour long term",
    "Why some people seek external chaos during internal instability",
    "The psychology behind doomscrolling",
    "Whether people perform authenticity online",
    "How South Africans use humour to survive stress",
    "Whether financial pressure destroys romance",
    "The emotional weirdness of getting older",
    "Whether people fear failure or embarrassment more",
    "The psychology behind needing control",
    "Whether people subconsciously mirror those around them",
    "How rapidly Cape Town is changing culturally",
    "Whether true peace feels boring to some people",
    "The emotional impact of growing up too quickly",
    "Whether resilience can become emotional suppression",
    "Why some people cannot tolerate being alone",
    "The psychology behind toxic attraction",
    "Whether people are becoming more transactional socially",
    "How dating apps changed human connection",
    "Whether emotional closure is overrated",
    "The emotional difference between attention and affection",
    "Whether people secretly enjoy gossip because it creates social bonding",
    "The psychology behind self-sabotage",
    "Whether people mistake intensity for compatibility",
    "How uncertainty changes personality",
    "Whether humans need meaning more than happiness",
    "The emotional impact of constant comparison online",
    "Whether people fear rejection more than loneliness",
    "Why emotionally unavailable people often seem attractive",
    "The psychology behind procrastination",
    "Whether anger is usually fear in disguise",
    "How people create narratives to protect their identity",
    "Whether emotional pain creates stronger art",
    "The emotional effect of feeling misunderstood",
    "Whether people become who they surround themselves with",
    "How modern work culture affects identity",
    "Whether people secretly want simpler lives",
    "The psychology behind overexplaining",
    "Whether confidence is built or performed",
    "How recent inflation changed social behaviour in Cape Town",
    "Whether people are becoming more cynical",
    "The emotional difference between safety and excitement",
    "Whether social status quietly controls behaviour",
    "Why some people fear vulnerability more than failure",
    "The psychology behind emotional withdrawal",
    "Whether humans naturally seek belonging over truth",
    "How people rationalise morally grey behaviour",
    "Whether some people need external validation to feel real",
    "The emotional impact of unstable environments",
    "Whether technology is making people less patient",
    "Why some people repeatedly choose emotionally unavailable partners",
    "The psychology behind revenge after betrayal",
    "Whether emotional honesty scares people",
    "How Cape Town's cost of living changes relationship dynamics",
    "Whether people secretly judge others constantly",
    "The emotional exhaustion of always adapting",
    "Whether some people are addicted to drama cycles",
    "The psychology behind emotional detachment",
    "Whether identity is stable or constantly rewritten",
    "How difficult times reveal true personality",
    "Whether people can genuinely forgive betrayal",
    "The emotional impact of carrying responsibility too young",
    "Whether humans need conflict to feel alive",
    "The psychology behind emotional projection",
    "Whether most people truly know themselves",
    "How fear quietly controls decision making",
    "Whether people become harsher under pressure",
    "The emotional cost of pretending to be okay",
    "Whether society rewards performance over authenticity",
    "The psychology behind needing to feel chosen",
    "Whether people secretly fear being ordinary",
    "How unresolved grief changes personality",
    "Whether people crave certainty more than freedom",
]

# ── Trait and emotion defaults ─────────────────────────────────────────────────

DEFAULT_TRAITS = {
    "warmth":0,"james_vulnerability":0,"samantha_guard":60,
    "tension":0,"attraction":0,"depth":5,"hostility":0,"physical":0
}

DEFAULT_EMOTIONS = {
    "james":    {"happy":0,"sad":0,"confused":0,"curious":20,"anxious":10,"angry":0,"aroused":0,"guarded":60,"tender":0,"amused":0,"withdrawn":0,"hopeful":10,"jealous":0,"conflicted":0,"electrified":0},
    "samantha": {"happy":0,"sad":0,"confused":0,"curious":15,"anxious":5,"angry":0,"aroused":0,"guarded":50,"tender":0,"amused":0,"withdrawn":0,"hopeful":5,"jealous":0,"conflicted":0,"electrified":0}
}

DEFAULT_ENV = {
    "james_alcohol":0,"samantha_alcohol":0,
    "james_hunger":40,"samantha_hunger":40,
    "party_energy":70,"food_available":True,"drinks_available":True,
    "current_scene_event":None,"last_scene_turn":0,
    "current_topic":None,"last_topic_turn":0
}

# ── Time system ────────────────────────────────────────────────────────────────
# Party starts at 19:00. Each turn ~= 2 minutes of conversation.
PARTY_START_HOUR = 19
PARTY_START_MIN  = 0
MINS_PER_TURN    = 2

PARTY_PHASES = [
    {"from_turn":0,   "label":"early_evening",  "time":"19:00", "desc":"The party is just getting started. Energy is high. People still arriving."},
    {"from_turn":30,  "label":"peak",            "time":"20:00", "desc":"Full house. Loud. Hard to have a quiet moment. You lean in to hear each other."},
    {"from_turn":60,  "label":"settling",        "time":"21:00", "desc":"The party has found its rhythm. Conversations deepening around the room."},
    {"from_turn":90,  "label":"late_evening",    "time":"22:00", "desc":"The party is thinning. The serious conversations have started. It is quieter."},
    {"from_turn":120, "label":"last_drinks",     "time":"23:00", "desc":"Late now. Most people have left. The room is intimate. The evening is running out."},
    {"from_turn":150, "label":"end_of_night",    "time":"00:00", "desc":"The party is effectively over. A few people linger. This is the last window."},
    {"from_turn":170, "label":"after_midnight",  "time":"00:40", "desc":"It is very late. Almost everyone has gone. The moment will not come again."},
]

DEPARTURE_NUDGE_TURN = 115  # Samantha checks her phone

def get_party_time(turn):
    """Return current party clock time as string."""
    total_mins = PARTY_START_HOUR * 60 + PARTY_START_MIN + (turn * MINS_PER_TURN)
    total_mins = total_mins % (24 * 60)
    h = (total_mins // 60) % 24
    m = total_mins % 60
    return "{:02d}:{:02d}".format(h, m)

def get_party_phase(turn):
    phase = PARTY_PHASES[0]
    for p in PARTY_PHASES:
        if turn >= p["from_turn"]: phase = p
        else: break
    return phase

def phase_inject(turn):
    phase = get_party_phase(turn)
    time_str = get_party_time(turn)
    lines = ["TIME: It is {} at the party. {}".format(time_str, phase["desc"])]
    if phase["label"] == "last_drinks":
        lines.append("The evening is running out. If there is something to say, the window is closing.")
    elif phase["label"] == "end_of_night":
        lines.append("This is nearly over. The moment either happens now or it doesn't.")
    elif phase["label"] == "after_midnight":
        lines.append("It is very late. You are aware this is the last chance for whatever this is.")
    return " ".join(lines)

TRAIT_BOUNDS   = (-100, 100)
EMOTION_BOUNDS = (0, 100)

TRAIT_THRESHOLDS = {
    "james": [
        {"trait":"warmth","min":30,"max":None,"inject":"You feel comfortable with her. More than you expected."},
        {"trait":"warmth","min":65,"max":None,"inject":"Something has shifted. You are invested. That makes you nervous."},
        {"trait":"warmth","min":85,"max":None,"inject":"Best conversation in years. The fact that it matters this much is starting to scare you."},
        {"trait":"warmth","min":None,"max":-30,"inject":"Something soured. You are being polite but you are done."},
        {"trait":"james_vulnerability","min":40,"max":None,"inject":"You have said more tonight than you usually say in a week."},
        {"trait":"james_vulnerability","min":70,"max":None,"inject":"Your armour is mostly gone and you know it. Part of you wants to put it back on."},
        {"trait":"attraction","min":50,"max":None,"inject":"You are aware of something you are not ready to name."},
        {"trait":"attraction","min":80,"max":None,"inject":"You know exactly what this is. It scares you. Your instinct is to make a joke or pull back."},
        {"trait":"hostility","min":50,"max":None,"inject":"You are irritated. You are not hiding it well."},
        {"trait":"tension","min":70,"max":None,"inject":"There is something between you that needs saying."},
        {"trait":"physical","min":60,"max":None,"inject":"You are very aware of how close you are standing."},
        {"trait":"physical","min":None,"max":-50,"inject":"Something made you want to step back."},
    ],
    "samantha": [
        {"trait":"samantha_guard","min":None,"max":30,"inject":"Your usual caution has softened. You are not sure when that happened."},
        {"trait":"samantha_guard","min":None,"max":10,"inject":"You stopped pretending not to be interested."},
        {"trait":"warmth","min":60,"max":None,"inject":"Genuinely at ease with him. That is rare."},
        {"trait":"warmth","min":None,"max":-30,"inject":"You have gone polite. That is your exit mode."},
        {"trait":"attraction","min":50,"max":None,"inject":"You are noticing things you were not noticing before."},
        {"trait":"attraction","min":80,"max":None,"inject":"You know what this is. You are deciding what to do about it."},
        {"trait":"hostility","min":50,"max":None,"inject":"You are done being patient. Something needs to be said."},
        {"trait":"tension","min":70,"max":None,"inject":"The air is charged. You are choosing your words carefully."},
        {"trait":"physical","min":60,"max":None,"inject":"Physically aware of him in a way that is hard to ignore."},
        {"trait":"physical","min":None,"max":-50,"inject":"Something he did made your skin crawl."},
    ]
}

EMOTION_COLORS = {
    "happy":"#34d399","sad":"#60a5fa","confused":"#fbbf24","curious":"#a78bfa",
    "anxious":"#fb923c","angry":"#f87171","aroused":"#f472b6","guarded":"#94a3b8",
    "tender":"#f9a8d4","amused":"#4ade80","withdrawn":"#6b7280","hopeful":"#67e8f9",
    "jealous":"#a3e635","conflicted":"#c084fc","electrified":"#fde68a"
}

plateau_count = {"value": 0}

# ── State ──────────────────────────────────────────────────────────────────────

def default_state():
    return {
        "running":False,"turn":0,
        "traits":DEFAULT_TRAITS.copy(),
        "emotions":{
            "james":DEFAULT_EMOTIONS["james"].copy(),
            "samantha":DEFAULT_EMOTIONS["samantha"].copy()
        },
        "environment":DEFAULT_ENV.copy(),
        "emotion_history":[],"trait_history":[],"nudge_history":[],"resonance_log":[],
        "messages":[],"james_history":[],"samantha_history":[],
        "current_speaker":"james","current_message":"",
        "active_nudge":None,"trajectory":"building",
        "james_memory":None,"samantha_memory":None,
        "scene_log":[],"topic_log":[],"hidden_life_log":[],"therapist_log":[]
    }

state = default_state()
message_queue = []
queue_lock = threading.Lock()

def save_state():
    s = {k:v for k,v in state.items() if k != "running"}
    with open(STATE_FILE,"w") as f: json.dump(s,f,indent=2)

def load_state():
    global state
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f: saved = json.load(f)
        state.update(saved)
        state["running"] = False
        state["active_nudge"] = None
        for key,default in [("emotions",{"james":DEFAULT_EMOTIONS["james"].copy(),"samantha":DEFAULT_EMOTIONS["samantha"].copy()}),
                             ("environment",DEFAULT_ENV.copy()),
                             ("scene_log",[]),("topic_log",[]),("hidden_life_log",[]),("therapist_log",[])]:
            if key not in state: state[key] = default
        return True
    return False

def push_event(t,d):
    with queue_lock: message_queue.append({"type":t,"data":d})

def clamp_trait(v): return max(TRAIT_BOUNDS[0],min(TRAIT_BOUNDS[1],v))
def clamp_emo(v):   return max(EMOTION_BOUNDS[0],min(EMOTION_BOUNDS[1],v))

def dominant_emotion(person):
    emos = state["emotions"][person]
    return max(emos, key=lambda k: emos[k])

# ── Environment helpers ────────────────────────────────────────────────────────

def alcohol_label(v):
    if v < 16:  return None
    if v < 36:  return "one or two in"
    if v < 56:  return "tipsy"
    if v < 76:  return "drunk"
    return "very drunk"

def hunger_label(v):
    if v < 21:  return None
    if v < 51:  return "peckish"
    if v < 71:  return "hungry"
    return "starving"

def effective_alcohol(person):
    """Self-regulation dampens alcohol effect."""
    reg = JAMES["self_regulation"] if person == "james" else SAMANTHA["self_regulation"]
    raw = state["environment"].get("{}_alcohol".format(person), 0)
    # High self-regulation (75+) reduces effective alcohol by ~30%
    dampener = 1.0 - ((reg - 50) / 200.0)
    return min(100, int(raw * dampener))

def env_inject(person):
    lines = []
    eff_alc = effective_alcohol(person)
    alc = alcohol_label(eff_alc)
    hun = hunger_label(state["environment"].get("{}_hunger".format(person), 0))
    reg = JAMES["self_regulation"] if person == "james" else SAMANTHA["self_regulation"]

    if alc == "one or two in":
        lines.append("You have had a drink or two. Edges are softer.")
    elif alc == "tipsy":
        if reg >= 70:
            lines.append("You are tipsy but your self-control is holding. You are warmer than usual but still deliberate.")
        else:
            lines.append("You are tipsy. Your filter is noticeably looser. You are funnier and more likely to say the wrong thing.")
    elif alc == "drunk":
        if reg >= 70:
            lines.append("You are drunk. You are saying exactly what you think but still articulate. The careful version of you is off duty.")
        else:
            lines.append("You are drunk. Your guard is gone. You might say something you regret — or something more honest than you have ever been.")
    elif alc == "very drunk":
        lines.append("You are very drunk. You are emotional, unfiltered, unpredictable. Things are coming out whether you want them to or not.")

    if hun == "peckish": lines.append("Slightly peckish — you keep noticing the food nearby.")
    elif hun == "hungry": lines.append("Properly hungry. Slightly distracted by it.")
    elif hun == "starving": lines.append("You are starving and it is affecting your patience.")

    env = state["environment"]
    if env.get("current_scene_event"):
        lines.append("SCENE: " + env["current_scene_event"])
    if env.get("current_topic"):
        lines.append("TOPIC AVAILABLE: Someone nearby just mentioned {} — you could pick it up if it feels natural.".format(env["current_topic"]))

    return " ".join(lines)

def passive_env_update():
    env = state["environment"]
    turn = state["turn"]

    if turn % 20 == 0 and env["drinks_available"]:
        env["james_alcohol"]    = min(100, env["james_alcohol"]    + random.randint(4,10))
        env["samantha_alcohol"] = min(100, env["samantha_alcohol"] + random.randint(3,8))

    if turn % 30 == 0:
        env["james_hunger"]    = min(100, env["james_hunger"]    + random.randint(8,15))
        env["samantha_hunger"] = min(100, env["samantha_hunger"] + random.randint(8,15))

    if turn % 45 == 0 and env["food_available"]:
        env["james_hunger"]    = max(0, env["james_hunger"]    - random.randint(20,35))
        env["samantha_hunger"] = max(0, env["samantha_hunger"] - random.randint(20,35))
        push_event("resonance",{"turn":turn,"event":"food break — hunger reduced"})

    # Scene event every 18-22 turns
    if turn - env.get("last_scene_turn",0) >= random.randint(18,22):
        event = random.choice(PARTY_EVENTS)
        env["current_scene_event"] = event
        env["last_scene_turn"] = turn
        state["scene_log"].append({"turn":turn,"event":event,"ts":datetime.now().strftime("%H:%M")})
        push_event("scene",{"turn":turn,"event":event})
        push_event("resonance",{"turn":turn,"event":"scene: "+event[:60]})
    else:
        # Clear scene after 4 turns
        if turn - env.get("last_scene_turn",0) > 4:
            env["current_scene_event"] = None

    # Topic seed every 25-35 turns — with quality gate and blacklist
    if turn - env.get("last_topic_turn",0) >= random.randint(25,35):
        used = set(state.get("used_topics",[]))
        available = [t for t in TOPIC_SEEDS if t not in used]
        if not available:
            available = TOPIC_SEEDS
            state["used_topics"] = []
        # Quality gate: topic must be from our curated list (not narrator hallucination)
        topic = random.choice(available)
        if topic in TOPIC_SEEDS:  # only fire if it's a real curated topic
            if "used_topics" not in state: state["used_topics"] = []
            state["used_topics"].append(topic)
            env["current_topic"] = topic
            env["last_topic_turn"] = turn
            state["topic_log"].append({"turn":turn,"topic":topic,"ts":datetime.now().strftime("%H:%M")})
            push_event("topic",{"turn":turn,"topic":topic})
    else:
        if turn - env.get("last_topic_turn",0) > 6:
            env["current_topic"] = None

    state["environment"] = env
    push_event("environment",{
        "james_alcohol":env["james_alcohol"],"samantha_alcohol":env["samantha_alcohol"],
        "james_hunger":env["james_hunger"],"samantha_hunger":env["samantha_hunger"],
        "james_eff_alc":effective_alcohol("james"),"samantha_eff_alc":effective_alcohol("samantha"),
        "james_alc_label":alcohol_label(effective_alcohol("james")),
        "samantha_alc_label":alcohol_label(effective_alcohol("samantha")),
        "james_hun_label":hunger_label(env["james_hunger"]),
        "samantha_hun_label":hunger_label(env["samantha_hunger"]),
        "scene":env.get("current_scene_event"),
        "topic":env.get("current_topic")
    })

# ── Trait decay ────────────────────────────────────────────────────────────────

def apply_trait_decay():
    """Decay traits back toward centre. Kicks in from 40, aggressive at extremes."""
    for trait, val in state["traits"].items():
        if val > 90:    state["traits"][trait] = clamp_trait(val - 10)
        elif val > 70:  state["traits"][trait] = clamp_trait(val - 6)
        elif val > 40:  state["traits"][trait] = clamp_trait(val - 3)
        elif val < -90: state["traits"][trait] = clamp_trait(val + 10)
        elif val < -70: state["traits"][trait] = clamp_trait(val + 6)
        elif val < -40: state["traits"][trait] = clamp_trait(val + 3)

# Per-emotion decay: (baseline, rate_per_cycle)
EMOTION_DECAY = {
    "happy":       (0,  8),
    "sad":         (0,  6),
    "confused":    (0, 10),
    "curious":     (10, 5),
    "anxious":     (5,  6),
    "angry":       (0,  8),
    "aroused":     (0, 12),
    "guarded":     (50, 4),
    "tender":      (0,  8),
    "amused":      (0,  8),
    "withdrawn":   (0,  6),
    "hopeful":     (5,  4),
    "jealous":     (0,  8),
    "conflicted":  (0,  7),
    "electrified": (0, 15),
}

EMOTION_BASELINES = {
    "james":    {k: v[0] for k,v in EMOTION_DECAY.items()},
    "samantha": {**{k: v[0] for k,v in EMOTION_DECAY.items()}, "guarded":50, "curious":15},
}

def apply_emotion_decay():
    """Decay emotions toward natural baseline. Ephemeral states drop fast."""
    for person in ["james","samantha"]:
        baselines = EMOTION_BASELINES[person]
        for emo,(baseline,rate) in EMOTION_DECAY.items():
            current = state["emotions"][person].get(emo,0)
            target  = baselines.get(emo,baseline)
            if current > target:
                state["emotions"][person][emo] = max(target, current - rate)
            elif current < target:
                state["emotions"][person][emo] = min(target, current + rate)

# ── Plateau nudges ─────────────────────────────────────────────────────────────

def get_plateau_nudge():
    t = state["traits"]
    turn = state["turn"]

    # After turn 200 — scene-based nudges only, no therapy-style introspection
    if turn > 200:
        scene_options = [
            {"target":"james","instruction":"The party around you shifted. React to something happening in the room — something physical, specific, real."},
            {"target":"samantha","instruction":"Something just happened at the party. React to it. Don't continue the thread — start a new one."},
            {"target":"james","instruction":"You've been in your head. Come back to the room. Say something about what's in front of you right now."},
            {"target":"samantha","instruction":"Change the subject completely. Something in the room gave you an excuse. Use it."},
        ]
        if state["environment"].get("current_scene_event"):
            scene_options.append({"target":"james","instruction":"React to what just happened. Make it yours."})
            scene_options.append({"target":"samantha","instruction":"React to what just happened. Don't explain it — just respond to it."})
        return random.choice(scene_options)

    # Under turn 200 — full nudge pool
    options = [
        {"target":"james","instruction":"You just said something you thought was clever but it came out wrong. Don't apologise — that would be worse."},
        {"target":"james","instruction":"She said something too intimate and your avoidant side kicked in. Make a joke or change subject. You know you are doing it."},
        {"target":"james","instruction":"Say something unexpectedly direct — something real you immediately wish you could take back."},
        {"target":"samantha","instruction":"He just said something dismissive. Call it out. Directly, not aggressively."},
        {"target":"samantha","instruction":"You caught yourself being too agreeable. Say what you actually think even if it creates friction."},
        {"target":"james","instruction":"Make a dry observation about someone at the party that is a little too sardonic. It might not land."},
        {"target":"james","instruction":"Something she said reminded you of Keanu leaving. Let that show slightly."},
        {"target":"samantha","instruction":"He said something that touched on the promotion situation without knowing it. React to what it stirred, not what he said."},
        {"target":"james","instruction":"You are being too abstract. Say something concrete about what is actually in front of you."},
        {"target":"samantha","instruction":"You are circling. Name the thing you are actually thinking about."},
        {"target":"james","instruction":"Change the subject entirely. Say something about yourself that has nothing to do with this thread."},
        {"target":"samantha","instruction":"You are bored of this topic and you are about to say so. Do it. Kindly, but do it."},
    ]
    if t.get("attraction",0) > 70:
        options.append({"target":"james","instruction":"The conversation got too real. Pull back with a flippant comment. Your avoidant pattern is fully activated."})
    if state["environment"].get("current_scene_event"):
        options.append({"target":"james","instruction":"React to what just happened at the party. Make it yours."})
        options.append({"target":"samantha","instruction":"React to what just happened at the party in a way that reveals how you handle chaos."})
    return random.choice(options)

# ── Prompt builders ────────────────────────────────────────────────────────────


# ── Lexical emotion scanner ────────────────────────────────────────────────────

# Each entry: (pattern_list, {person: {emotion: delta}}, label)
# person = "speaker" (who spoke), "listener" (who heard it), "both"
LEXICAL_TRIGGERS = [
    # ── Sadness / loss ──
    (["miss ", "missing", "left me", "he left", "she left", "gone now", "walked away", "emigrated", "moved away"],
     {"speaker":{"sad":2,"hopeful":1},"listener":{"sad":1}}, "loss"),

    # ── Anxiety / fear ──
    (["scared", "afraid", "terrified", "nervous", "panic", "worried", "fear"],
     {"speaker":{"anxious":3},"listener":{"anxious":1}}, "fear"),

    # ── Anger ──
    (["angry", "furious", "pissed", "rage", "hate", "disgusting", "sick of"],
     {"speaker":{"angry":3},"listener":{"guarded":2,"anxious":1}}, "anger"),

    # ── Amusement ──
    (["funny", "hilarious", "laugh", "haha", "lol", "joke", "that's good"],
     {"speaker":{"amused":2},"listener":{"amused":2,"happy":1}}, "amusement"),

    # ── Attraction / physical ──
    (["beautiful", "stunning", "gorgeous", "attractive", "handsome", "good-looking"],
     {"speaker":{"aroused":2,"tender":1},"listener":{"hopeful":2,"aroused":1}}, "attraction"),

    (["close", "closer", "standing near", "next to me", "beside you"],
     {"speaker":{"physical":2},"listener":{"physical":2,"aroused":1}}, "proximity"),

    # ── Desire ──
    (["want you", "need you", "can't stop", "thinking about you", "can't get you"],
     {"speaker":{"aroused":3,"hopeful":2},"listener":{"aroused":2,"confused":1}}, "desire"),

    # ── Vulnerability / confession ──
    (["i've never told", "never said this", "only person", "trust you", "be honest", "truth is", "to be honest", "if i'm honest"],
     {"speaker":{"hopeful":2,"anxious":1},"listener":{"tender":3,"curious":2,"depth":0}}, "confession"),

    (["my mom", "my dad", "my father", "my mother", "growing up", "when i was young", "as a kid"],
     {"speaker":{"james_vulnerability":3,"anxious":1},"listener":{"tender":2,"curious":2}}, "childhood"),

    # ── Guarded / suspicious ──
    (["don't trust", "not sure about", "something off", "what's your angle", "what do you want", "running something", "playing a game"],
     {"speaker":{"guarded":3},"listener":{"guarded":2,"anxious":1}}, "suspicion"),

    # ── Abandonment triggers ──
    (["leaving", "going to leave", "have to go", "need to go", "getting late", "should head"],
     {"speaker":{"anxious":2},"listener":{"anxious":3,"hopeful":-1}}, "departure"),

    # ── Money / transactions ──
    (["money", "pay", "cost", "expensive", "afford", "financial", "arrangement", "investment"],
     {"speaker":{"anxious":1},"listener":{"guarded":2,"curious":1}}, "money"),

    # ── Loneliness ──
    (["alone", "lonely", "isolated", "no one", "nobody", "by myself"],
     {"speaker":{"sad":3,"hopeful":1},"listener":{"tender":2,"sad":1}}, "loneliness"),

    # ── Electric moments ──
    (["electric", "spark", "something between", "can feel it", "tension", "charged"],
     {"speaker":{"electrified":3,"aroused":1},"listener":{"electrified":3,"aroused":1}}, "electricity"),

    # ── Conflict / hostility ──
    (["you're wrong", "that's not true", "stop it", "you always", "you never", "typical", "of course you"],
     {"speaker":{"angry":2,"hostility":0},"listener":{"guarded":3,"angry":1}}, "conflict"),

    # ── Tenderness ──
    (["care about", "worried about you", "okay?", "are you alright", "how are you really"],
     {"speaker":{"tender":3,"hopeful":1},"listener":{"tender":2,"confused":1}}, "tenderness"),

    # ── Hope / future ──
    (["maybe we could", "sometime", "would you want", "next time", "again sometime", "see you"],
     {"speaker":{"hopeful":3},"listener":{"hopeful":2,"anxious":1}}, "hope"),

    # ── Withdrawal ──
    (["doesn't matter", "forget it", "never mind", "it's fine", "whatever", "doesn't matter"],
     {"speaker":{"withdrawn":3,"sad":1},"listener":{"anxious":2,"confused":2}}, "withdrawal"),
]

TRAIT_TRIGGERS = [
    (["love", "care about you", "falling for", "feel something"],
     {"warmth":3,"attraction":3,"depth":2}, "warmth"),
    (["hate you", "get away", "leave me alone", "disgusting"],
     {"hostility":4,"warmth":-2}, "hostility"),
    (["i want you", "come home with", "tonight", "somewhere quieter"],
     {"physical":3,"attraction":3,"tension":2}, "physical_intent"),
    (["deep", "meaningful", "never talked like this", "real conversation", "more than i expected"],
     {"depth":3,"warmth":2}, "depth"),
    (["testing me", "playing games", "i see what you're doing", "i know what you want"],
     {"tension":3,"samantha_guard":2}, "called_out"),
]

def lexical_scan(text, speaker):
    """
    Scan message text for emotional trigger words.
    Returns (emotion_deltas, trait_deltas, fired_labels).
    speaker = 'james' or 'samantha'
    listener = the other one
    """
    listener = "samantha" if speaker == "james" else "james"
    text_lower = text.lower()

    emo_deltas = {
        "james":    {e:0 for e in DEFAULT_EMOTIONS["james"]},
        "samantha": {e:0 for e in DEFAULT_EMOTIONS["samantha"]}
    }
    trait_deltas = {t:0 for t in DEFAULT_TRAITS}
    fired = []

    for patterns, deltas, label in LEXICAL_TRIGGERS:
        if any(p in text_lower for p in patterns):
            fired.append(label)
            # Speaker deltas
            for emo, delta in deltas.get("speaker", {}).items():
                if emo in emo_deltas[speaker]:
                    emo_deltas[speaker][emo] = max(-3, min(3, delta))
            # Listener deltas
            for emo, delta in deltas.get("listener", {}).items():
                if emo in emo_deltas[listener]:
                    emo_deltas[listener][emo] = max(-3, min(3, delta))

    for patterns, deltas, label in TRAIT_TRIGGERS:
        if any(p in text_lower for p in patterns):
            if label not in fired: fired.append(label)
            for trait, delta in deltas.items():
                if trait in trait_deltas:
                    trait_deltas[trait] = max(-4, min(4, trait_deltas[trait] + delta))

    return emo_deltas, trait_deltas, fired

def apply_lexical_scan(text, speaker, turn):
    """Apply lexical scan results to state and push events."""
    emo_deltas, trait_deltas, fired = lexical_scan(text, speaker)
    if not fired:
        return

    # Apply emotion deltas
    for person in ["james","samantha"]:
        for emo, delta in emo_deltas[person].items():
            if delta != 0 and emo in state["emotions"][person]:
                state["emotions"][person][emo] = clamp_emo(state["emotions"][person][emo] + delta)

    # Apply trait deltas
    for trait, delta in trait_deltas.items():
        if delta != 0 and trait in state["traits"]:
            state["traits"][trait] = clamp_trait(state["traits"][trait] + delta)

    # Console output — visible like a scene change
    label_str = " · ".join(fired)
    print("  [lexical t{}] {} → {}".format(turn, speaker, label_str))

    # Push to UI as resonance event
    push_event("resonance", {
        "turn": turn,
        "event": "lexical / {} / {}".format(speaker, label_str)
    })

    # Push updated emotions
    push_event("emotions", {
        "turn": turn,
        "emotions": {"james":state["emotions"]["james"].copy(),"samantha":state["emotions"]["samantha"].copy()},
        "deltas": {},
        "dominant": {"james":dominant_emotion("james"),"samantha":dominant_emotion("samantha")}
    })

_NARRATOR_TEMPLATE = (
    "You are a psychological narrator scoring a conversation between James and Samantha at a Cape Town dinner party.\n\n"
    "JAMES: avoidant attachment, self_regulation=55. {james_bg} Shadow: {james_shadow}. "
    "Narrator-only: {james_narrator}. Triggers: {james_trig}\n\n"
    "SAMANTHA: secure attachment, self_regulation=75. {sam_bg} Shadow: {sam_shadow}. "
    "Narrator-only: {sam_narrator}. Triggers: {sam_trig}\n\n"
    "Resonance: conversation touching precision, restraint, control, tension activates both hidden profiles.\n"
    "Party: Cape Town dinner party in Woodstock. Topics: Eskom, load shedding, Springboks, gentrification, water crisis.\n\n"
    "Traits (-100 to +100): warmth, james_vulnerability, samantha_guard(high=guarded), tension, attraction, depth, hostility, physical\n"
    "Emotions (0-100): happy, sad, confused, curious, anxious, angry, aroused, guarded, tender, amused, withdrawn, hopeful, jealous, conflicted, electrified\n\n"
    "Respond ONLY with valid JSON. No markdown. No extra text. Example structure:\n"
    '{{"deltas":{{"warmth":0,"james_vulnerability":0,"samantha_guard":0,"tension":0,"attraction":0,"depth":0,"hostility":0,"physical":0}},'
    '"emotion_deltas":{{"james":{{"happy":0,"sad":0,"confused":0,"curious":0,"anxious":0,"angry":0,"aroused":0,"guarded":0,"tender":0,"amused":0,"withdrawn":0,"hopeful":0,"jealous":0,"conflicted":0,"electrified":0}},'
    '"samantha":{{"happy":0,"sad":0,"confused":0,"curious":0,"anxious":0,"angry":0,"aroused":0,"guarded":0,"tender":0,"amused":0,"withdrawn":0,"hopeful":0,"jealous":0,"conflicted":0,"electrified":0}}}},'
    '"trajectory":"building","resonance":null,"nudge":null,"hidden_life_surface":null}}\n\n'
    "trajectory: building|plateau|escalating_conflict|breakthrough|falling|rupture|reconciliation|physical_moment|cold_war\n"
    "nudge: null or {{\"target\":\"james\"|\"samantha\",\"instruction\":\"one sentence grounded in their psychology\"}}\n"
    "hidden_life_surface: null or {{\"target\":\"james\"|\"samantha\",\"fact\":\"hidden life element surfacing\"}}\n"
    "resonance: null or short string (no internal quotes)\n\n"
    "CRITICAL: If conversation stuck on same topic 3+ turns nudge AWAY toward something personal.\n"
    "Nudge triggers: plateau 3+ turns, shadow activating, James being too safe. Go negative freely."
)

NARRATOR_SYSTEM = _NARRATOR_TEMPLATE.format(
    james_bg=JAMES["background"][:120],
    james_shadow=JAMES["shadow"],
    james_narrator=str(JAMES.get("narrator_only",{}))[:200],
    james_trig=", ".join(JAMES["triggers"][:8]),
    sam_bg=SAMANTHA["background"][:120],
    sam_shadow=SAMANTHA["shadow"],
    sam_narrator=str(SAMANTHA.get("narrator_only",{}))[:200],
    sam_trig=", ".join(SAMANTHA["triggers"][:8])
)

THERAPIST_SYSTEM = """You are a therapist observing James and Samantha at a Cape Town dinner party.
Write 2-3 sentences of clinical psychological interpretation of what just happened.
Focus on: attachment patterns, defence mechanisms, shadow activation, what is happening beneath the surface.
Be precise. Name what is really happening. Do NOT summarise what was said.
Write plain text only. No JSON. No bullet points."""

def run_therapist(last_messages):
    """Separate plain-text therapist call — no JSON, no parsing issues."""
    recent = last_messages[-4:] if len(last_messages) > 4 else last_messages
    convo = "\n".join(["{}: {}".format(m["speaker"].upper(), m["text"]) for m in recent])
    traits_summary = "warmth:{} attraction:{} tension:{} james_vuln:{} s_guard:{} trajectory:{}".format(
        state["traits"].get("warmth",0),
        state["traits"].get("attraction",0),
        state["traits"].get("tension",0),
        state["traits"].get("james_vulnerability",0),
        state["traits"].get("samantha_guard",0),
        state.get("trajectory","building")
    )
    prompt = "State: {}\n\nConversation:\n{}\n\nTherapist analysis:".format(traits_summary, convo)
    messages = [{"role":"system","content":THERAPIST_SYSTEM},{"role":"user","content":prompt}]
    payload = {"model":NARRATOR_MODEL,"messages":messages,"stream":False,"options":{"temperature":0.5,"top_p":0.9}}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=45)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        print("Therapist error:", e)
        return None

def extract_json(raw):
    """Aggressively extract first valid JSON object from messy model output."""
    raw = raw.strip()
    # Strip markdown fences
    raw = re.sub(r'```json\s*', '', raw)
    raw = re.sub(r'```\s*', '', raw)
    raw = raw.strip()
    # Find first { and last }
    start = raw.find('{')
    end = raw.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = raw[start:end+1]
    # Remove control characters that break JSON
    candidate = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', candidate)
    try:
        return json.loads(candidate)
    except Exception:
        # Try to salvage by truncating therapist field if it's the problem
        try:
            # Find therapist value and truncate it safely
            tp = candidate.find('"therapist"')
            if tp != -1:
                vs = candidate.find('"', tp + 11)
                ve = candidate.find('","', vs + 1)
                if ve == -1: ve = candidate.find('"}', vs + 1)
                if vs != -1 and ve != -1:
                    therapist_raw = candidate[vs+1:ve]
                    safe = therapist_raw.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', '')
                    candidate = candidate[:vs+1] + safe + candidate[ve:]
            return json.loads(candidate)
        except Exception:
            return None

def run_narrator(last_messages):
    recent = last_messages[-6:] if len(last_messages) > 6 else last_messages
    convo = "\n".join(["{}: {}".format(m["speaker"].upper(),m["text"]) for m in recent])
    env = state.get("environment",{})
    env_summary = "James alcohol:{} Samantha alcohol:{} Scene:{} Topic:{} Time:{} Phase:{}".format(
        env.get("james_alcohol",0), env.get("samantha_alcohol",0),
        env.get("current_scene_event","none"), env.get("current_topic","none"),
        get_party_time(state["turn"]), get_party_phase(state["turn"])["label"]
    )
    prompt = "Traits:{}\nEmotions:{}\nEnv:{}\nConversation:\n{}\n\nScore this.".format(
        json.dumps(state["traits"]),
        json.dumps(state["emotions"]),
        env_summary, convo
    )
    messages = [{"role":"system","content":NARRATOR_SYSTEM},{"role":"user","content":prompt}]
    payload = {"model":NARRATOR_MODEL,"messages":messages,"stream":False,"options":{"temperature":0.3,"top_p":0.9}}
    try:
        r = requests.post(OLLAMA_URL,json=payload,timeout=60)
        r.raise_for_status()
        raw = r.json()["message"]["content"]
        result = extract_json(raw)
        if result:
            return result
        # Retry with stricter prompt
        print("  Narrator JSON failed, retrying with strict prompt...")
        strict_prompt = prompt + "\n\nCRITICAL: Return ONLY the JSON object. No explanation. No markdown. Start with { end with }. Keep therapist field under 200 characters."
        messages[-1] = {"role":"user","content":strict_prompt}
        r2 = requests.post(OLLAMA_URL,json={"model":NARRATOR_MODEL,"messages":messages,"stream":False,"options":{"temperature":0.1}},timeout=60)
        r2.raise_for_status()
        raw2 = r2.json()["message"]["content"]
        return extract_json(raw2)
    except Exception as e:
        print("Narrator error:",e)
        return None

def apply_narrator_result(result, turn):
    if not result: return
    old_traits = state["traits"].copy()
    old_emotions = {"james":state["emotions"]["james"].copy(),"samantha":state["emotions"]["samantha"].copy()}

    # Trait delta cap — ±2 for escalating profiles, ±4 otherwise
    # Prevents narrator from spiking traits to 100 in a few calls
    profile_cap = 2 if JAMES.get("attachment","") in ("psychopathic","predatory","chaotic") else 4

    for trait,delta in result.get("deltas",{}).items():
        if trait in state["traits"]:
            capped_trait = max(-profile_cap, min(profile_cap, delta))
            state["traits"][trait] = clamp_trait(state["traits"][trait] + capped_trait)

    for person in ["james","samantha"]:
        for emo,delta in result.get("emotion_deltas",{}).get(person,{}).items():
            if emo in state["emotions"][person]:
                # Cap narrator delta at ±3 — lexical scanner handles immediate reactions
                capped = max(-3, min(3, delta))
                state["emotions"][person][emo] = clamp_emo(state["emotions"][person][emo]+capped)

    trajectory = result.get("trajectory","building")
    state["trajectory"] = trajectory

    if trajectory in ("building","plateau"): plateau_count["value"] += 1
    else: plateau_count["value"] = 0

    nudge = result.get("nudge")
    if plateau_count["value"] >= 3 and not nudge:
        nudge = get_plateau_nudge()
        plateau_count["value"] = 0
        push_event("resonance",{"turn":turn,"event":"plateau_breaker fired"})

    state["active_nudge"] = nudge
    resonance = result.get("resonance")
    hidden = result.get("hidden_life_surface")
    therapist = result.get("therapist","").strip()

    if resonance:
        state["resonance_log"].append({"turn":turn,"event":resonance,"ts":datetime.now().strftime("%H:%M")})
        push_event("resonance",{"turn":turn,"event":resonance})

    if hidden:
        state["hidden_life_log"].append({"turn":turn,"data":hidden,"ts":datetime.now().strftime("%H:%M")})
        push_event("hidden_life",{"turn":turn,"target":hidden.get("target"),"fact":hidden.get("fact")})

    if therapist:
        entry = {"turn":turn,"ts":datetime.now().strftime("%H:%M"),"text":therapist,"trajectory":trajectory}
        state["therapist_log"].append(entry)
        push_event("therapist",{"turn":turn,"ts":datetime.now().strftime("%H:%M"),"text":therapist,"trajectory":trajectory})

    state["trait_history"].append({
        "turn":turn,"ts":datetime.now().strftime("%H:%M"),
        "old":old_traits,"new":state["traits"].copy(),
        "deltas":result.get("deltas",{}),"trajectory":trajectory,"nudge":nudge,"resonance":resonance
    })
    state["emotion_history"].append({
        "turn":turn,"ts":datetime.now().strftime("%H:%M"),
        "old":old_emotions,
        "new":{"james":state["emotions"]["james"].copy(),"samantha":state["emotions"]["samantha"].copy()},
        "deltas":result.get("emotion_deltas",{})
    })
    if nudge:
        state["nudge_history"].append({"turn":turn,"nudge":nudge,"ts":datetime.now().strftime("%H:%M")})

    push_event("traits",{
        "turn":turn,"traits":state["traits"].copy(),"deltas":result.get("deltas",{}),
        "trajectory":trajectory,"nudge":nudge,"resonance":resonance
    })
    push_event("emotions",{
        "turn":turn,
        "emotions":{"james":state["emotions"]["james"].copy(),"samantha":state["emotions"]["samantha"].copy()},
        "deltas":result.get("emotion_deltas",{}),
        "dominant":{"james":dominant_emotion("james"),"samantha":dominant_emotion("samantha")}
    })
    save_state()

# ── Stage direction stripper ───────────────────────────────────────────────────

def strip_stage_directions(text):
    # Remove parenthetical actions
    text = re.sub(r'\([^)]*\)', '', text)
    # Remove asterisk actions
    text = re.sub(r'\*[^*]*\*', '', text)
    # Remove "I say, my voice..." narration patterns
    text = re.sub(r',?\s*[Ii] say,?\s*my voice [^,."]+', '', text)
    text = re.sub(r',?\s*[Ii] say,?\s*my eyes? [^,."]+', '', text)
    text = re.sub(r',?\s*[Ii] say,?\s*my (face|hands?|fingers?|gaze|smile|lips?|body) [^,."]+', '', text)
    # Remove trailing physical action clauses after dialogue
    text = re.sub(r',\s*(my|the)\s+(voice|eyes?|gaze|hand|fingers?|face|smile|lips?)\s+[^.!?"]+', '', text)
    # Remove "I say" attribution entirely
    text = re.sub(r'[,.]?\s*[Ii]\s+say\s*[,.]?', '', text)
    # Strip surrounding quotes if the whole thing is quoted
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    # Clean whitespace
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\s+([,.])', r'\1', text)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    seen, unique = [], []
    for s in sentences:
        if s not in seen: seen.append(s); unique.append(s)
    return ' '.join(unique).strip()

# ── Summariser ─────────────────────────────────────────────────────────────────

SUMMARISER_SYSTEM = """Summarise a conversation between James and Samantha for memory compression.
Write exactly two labelled blocks, each under 120 words.
Use this exact format with no deviation:

JAMES_MEMORY:
[James's memory here]

SAMANTHA_MEMORY:
[Samantha's memory here]

Include: topics covered, what was revealed, emotional tone, anything unresolved or charged.
Plain text only. No JSON. No bullet points. No markdown."""

def run_summariser():
    recent = state["messages"][-50:] if len(state["messages"]) > 50 else state["messages"]
    convo = "\n".join(["{}: {}".format(m["speaker"].upper(), m["text"]) for m in recent])
    prompt = "State:{}\n\nConversation:\n{}\n\nWrite the two memory blocks.".format(json.dumps(state["traits"]), convo)
    messages = [{"role":"system","content":SUMMARISER_SYSTEM},{"role":"user","content":prompt}]
    payload = {"model":NARRATOR_MODEL,"messages":messages,"stream":False,"options":{"temperature":0.2,"top_p":0.9}}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=90)
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()

        # Parse the two labelled blocks
        james_mem = ""
        samantha_mem = ""

        if "JAMES_MEMORY:" in raw and "SAMANTHA_MEMORY:" in raw:
            parts = raw.split("SAMANTHA_MEMORY:")
            james_part = parts[0].replace("JAMES_MEMORY:","").strip()
            samantha_part = parts[1].strip() if len(parts) > 1 else ""
            james_mem = james_part[:500]
            samantha_mem = samantha_part[:500]
        else:
            # Fallback: split in half
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            mid = len(lines) // 2
            james_mem = " ".join(lines[:mid])[:500]
            samantha_mem = " ".join(lines[mid:])[:500]

        if james_mem and samantha_mem:
            return james_mem, samantha_mem

        print("  Summariser could not parse blocks.")
        return None, None
    except Exception as e:
        print("Summariser error:", e)
        return None, None

def dynamic_history_limit(turn):
    """Shrink history window as conversation gets longer to preserve prompt quality."""
    if turn < 50:  return 8
    if turn < 100: return 6
    if turn < 200: return 4
    return 3  # Late night — memory carries context, raw history kept very tight

def compress_history():
    print("  Compressing history at turn {}...".format(state["turn"]))
    push_event("resonance",{"turn":state["turn"],"event":"memory compression firing..."})
    james_mem, samantha_mem = run_summariser()
    if not james_mem: print("  Summariser failed."); return
    state["james_memory"] = james_mem
    state["samantha_memory"] = samantha_mem
    # Keep fewer raw messages after compression as turns increase
    keep = max(4, 8 - (state["turn"] // 100))
    summary_j = [{"role":"user","content":"What have we been talking about?"},{"role":"assistant","content":james_mem}]
    summary_s = [{"role":"user","content":"What have we been talking about?"},{"role":"assistant","content":samantha_mem}]
    state["james_history"]    = summary_j + state["james_history"][-keep:]
    state["samantha_history"] = summary_s + state["samantha_history"][-keep:]
    push_event("resonance",{"turn":state["turn"],"event":"memory compressed"})
    print("  Done.")

# ── Chat ───────────────────────────────────────────────────────────────────────

def chat(model, system, history, message, history_limit=10):
    messages = [{"role":"system","content":system}] + history[-history_limit:] + [{"role":"user","content":message}]
    payload = {"model":model,"messages":messages,"stream":False,"options":{"temperature":0.92,"top_p":0.95}}
    r = requests.post(OLLAMA_URL,json=payload,timeout=180)
    r.raise_for_status()
    result = strip_stage_directions(r.json()["message"]["content"].strip())
    if not result:
        r = requests.post(OLLAMA_URL,json=payload,timeout=180)
        r.raise_for_status()
        result = strip_stage_directions(r.json()["message"]["content"].strip())
    return result or "..."

# ── Conversation loop ──────────────────────────────────────────────────────────

def conversation_loop():
    s = state
    if s["turn"] == 0:
        seed = ("You are at a dinner party in Woodstock, Cape Town. "
                "You have just been introduced to Samantha. The room is busy, music playing, people talking. "
                "You find a moment and turn to her. Say something. Just words. Speak naturally.")
        push_event("thinking",{"speaker":"james"})
        try: opening = chat(JAMES_MODEL,build_james_prompt(),[],seed,history_limit=6)
        except Exception as e:
            push_event("error",{"message":str(e)}); s["running"]=False; return
        s["james_history"].append({"role":"user","content":seed})
        s["james_history"].append({"role":"assistant","content":opening})
        s["messages"].append({"speaker":"james","text":opening,"ts":datetime.now().strftime("%H:%M")})
        s["current_message"]=opening; s["current_speaker"]="james"; s["turn"]=1
        push_event("message",{"speaker":"james","text":opening,"turn":1})
        save_state()

    while s["running"]:
        time.sleep(1.5)
        s["turn"] += 1

        if s["current_speaker"] == "james":
            push_event("thinking",{"speaker":"samantha"})
            hlimit = dynamic_history_limit(s["turn"])
            try: response = chat(SAMANTHA_MODEL,build_samantha_prompt(),s["samantha_history"],s["current_message"],history_limit=hlimit)
            except Exception as e: push_event("error",{"message":str(e)}); break
            s["samantha_history"].append({"role":"user","content":s["current_message"]})
            s["samantha_history"].append({"role":"assistant","content":response})
            s["james_history"].append({"role":"user","content":response})
            s["messages"].append({"speaker":"samantha","text":response,"ts":datetime.now().strftime("%H:%M")})
            push_event("message",{"speaker":"samantha","text":response,"turn":s["turn"]})
            s["current_message"]=response; s["current_speaker"]="samantha"
            apply_lexical_scan(response, "samantha", s["turn"])
        else:
            push_event("thinking",{"speaker":"james"})
            hlimit = dynamic_history_limit(s["turn"])
            try: response = chat(JAMES_MODEL,build_james_prompt(),s["james_history"],s["current_message"],history_limit=hlimit)
            except Exception as e: push_event("error",{"message":str(e)}); break
            s["james_history"].append({"role":"user","content":s["current_message"]})
            s["james_history"].append({"role":"assistant","content":response})
            s["samantha_history"].append({"role":"user","content":response})
            s["messages"].append({"speaker":"james","text":response,"ts":datetime.now().strftime("%H:%M")})
            push_event("message",{"speaker":"james","text":response,"turn":s["turn"]})
            s["current_message"]=response; s["current_speaker"]="james"
            apply_lexical_scan(response, "james", s["turn"])

        state["active_nudge"] = None
        passive_env_update()

        # Push current time to UI
        phase = get_party_phase(s["turn"])
        push_event("time",{
            "turn": s["turn"],
            "time": get_party_time(s["turn"]),
            "phase": phase["label"],
            "phase_desc": phase["desc"]
        })

        # Phase transition announcements
        for p in PARTY_PHASES:
            if s["turn"] == p["from_turn"] and s["turn"] > 0:
                push_event("resonance",{"turn":s["turn"],"event":"phase: {} — {}".format(p["label"], p["desc"])})
                push_event("scene",{"turn":s["turn"],"event":p["desc"]})

        # Departure pressure nudge
        if s["turn"] == DEPARTURE_NUDGE_TURN:
            state["active_nudge"] = {
                "target":"samantha",
                "instruction":"You just glanced at your phone. You are thinking about whether to leave soon. James noticed. You haven't decided yet."
            }
            push_event("resonance",{"turn":s["turn"],"event":"departure pressure — Samantha checks her phone"})
            push_event("scene",{"turn":s["turn"],"event":"Samantha glanced at her phone. The evening has a clock now."})

        # Late night urgency nudges
        if s["turn"] == 150:
            state["active_nudge"] = {
                "target":"james",
                "instruction":"The party is effectively over. If you are going to say the real thing, it is now or not at all. Your avoidant pattern is the only thing in the way."
            }
        if s["turn"] == 165:
            state["active_nudge"] = {
                "target":"samantha",
                "instruction":"It is very late. You have been here for hours. You know what this evening has been. Say something true before it ends."
            }

        compress_interval = 30 if s["turn"] > 100 else 50
        if s["turn"] % compress_interval == 0: compress_history()

        # Decay every 2 turns — keeps up with lexical scoring
        if s["turn"] % 2 == 0:
            apply_trait_decay()
            apply_emotion_decay()
            push_event("emotions",{
                "turn": s["turn"],
                "emotions":{"james":state["emotions"]["james"].copy(),"samantha":state["emotions"]["samantha"].copy()},
                "deltas":{},
                "dominant":{"james":dominant_emotion("james"),"samantha":dominant_emotion("samantha")}
            })

        # Narrator every 4 turns — less frequent, less runaway scoring
        if s["turn"] % 4 == 0:
            push_event("narrating",{})
            apply_narrator_result(run_narrator(s["messages"]),s["turn"])
            # Immediately decay after narrator to prevent spike accumulation
            apply_trait_decay()
            apply_emotion_decay()

        if s["turn"] % 4 == 0:
            therapist_text = run_therapist(s["messages"])
            if therapist_text:
                trajectory = state.get("trajectory","building")
                entry = {"turn":s["turn"],"ts":datetime.now().strftime("%H:%M"),"text":therapist_text,"trajectory":trajectory}
                state["therapist_log"].append(entry)
                push_event("therapist", entry)

        save_state()

    s["running"]=False; push_event("stopped",{})

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
def dashboard(): return render_template("dashboard.html")

@app.route("/") 
def index(): return render_template("index.html")

@app.route("/traits")
def traits_page(): return render_template("traits.html")

@app.route("/emotions")
def emotions_page(): return render_template("emotions.html")

@app.route("/start",methods=["POST"])
def start():
    if state["running"]: return jsonify({"status":"already running"})
    state["running"]=True
    with queue_lock: message_queue.clear()
    threading.Thread(target=conversation_loop,daemon=True).start()
    return jsonify({"status":"started","resumed":state["turn"]>0})

@app.route("/stop",methods=["POST"])
def stop():
    state["running"]=False; return jsonify({"status":"stopped"})

@app.route("/reset",methods=["POST"])
def reset():
    global state
    plateau_count["value"]=0
    state=default_state()
    if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
    with queue_lock: message_queue.clear()
    return jsonify({"status":"reset"})

@app.route("/stream")
def stream():
    def gen():
        # Tell client to wait 3s before reconnecting
        yield ": keep-alive\n\n"
        sent=0
        while True:
            with queue_lock: pending=message_queue[sent:]
            for ev in pending:
                yield "data: {}\n\n".format(json.dumps(ev)); sent+=1
            if not state["running"] and sent>=len(message_queue): break
            time.sleep(0.3)
    return Response(gen(),mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","Retry":"3000"})

@app.route("/state")
def get_state():
    return jsonify({
        "turn":state["turn"],"traits":state["traits"],
        "emotions":state["emotions"],
        "environment":state.get("environment",DEFAULT_ENV.copy()),
        "dominant":{"james":dominant_emotion("james"),"samantha":dominant_emotion("samantha")},
        "trait_history":state["trait_history"][-50:],
        "emotion_history":state["emotion_history"][-100:],
        "nudge_history":state["nudge_history"][-20:],
        "resonance_log":state["resonance_log"][-20:],
        "scene_log":state["scene_log"][-10:],
        "topic_log":state["topic_log"][-10:],
        "hidden_life_log":state["hidden_life_log"][-10:],
        "therapist_log":state["therapist_log"][-30:],
        "trajectory":state["trajectory"],"running":state["running"]
    })

@app.route("/transcript")
def transcript():
    lines = []
    lines.append("TWO MINDS — AN EVENING IN WOODSTOCK")
    lines.append("=" * 60)
    lines.append("James (qwen2.5:3b) x Samantha (llama3.2)")
    lines.append("Narrator: mistral")
    lines.append("Total turns: {}".format(state["turn"]))
    lines.append("=" * 60)
    lines.append("")

    # Build a merged timeline of messages + events
    events = []
    for m in state["messages"]:
        events.append({"type":"message","turn":m.get("turn",0),"ts":m["ts"],"speaker":m["speaker"],"text":m["text"]})
    for e in state.get("scene_log",[]):
        events.append({"type":"scene","turn":e["turn"],"ts":e["ts"],"text":e["event"]})
    for e in state.get("topic_log",[]):
        events.append({"type":"topic","turn":e["turn"],"ts":e["ts"],"text":e["topic"]})
    for e in state.get("resonance_log",[]):
        events.append({"type":"resonance","turn":e["turn"],"ts":e["ts"],"text":e["event"]})
    for e in state.get("nudge_history",[]):
        events.append({"type":"nudge","turn":e["turn"],"ts":e["ts"],"text":"-> {}: {}".format(e["nudge"].get("target",""),e["nudge"].get("instruction",""))})
    for e in state.get("hidden_life_log",[]):
        events.append({"type":"hidden","turn":e["turn"],"ts":e["ts"],"text":"{}: {}".format(e["data"].get("target",""),e["data"].get("fact",""))})

    # Sort by turn then type (messages before annotations)
    type_order = {"scene":0,"topic":1,"message":2,"resonance":3,"nudge":4,"hidden":5}
    events.sort(key=lambda x: (x.get("turn",0), type_order.get(x["type"],9)))

    current_phase = None
    for ev in events:
        turn = ev.get("turn",0)
        phase = get_party_phase(turn)
        party_time = get_party_time(turn)

        # Phase header
        if phase["label"] != current_phase:
            current_phase = phase["label"]
            lines.append("")
            lines.append("── {} / {} ──".format(phase["label"].upper().replace("_"," "), party_time))
            lines.append("")

        if ev["type"] == "message":
            speaker = ev["speaker"].upper()
            lines.append("[{}] {}".format(ev["ts"], speaker))
            lines.append(ev["text"])
            lines.append("")
        elif ev["type"] == "scene":
            lines.append("  [SCENE]  {}".format(ev["text"]))
            lines.append("")
        elif ev["type"] == "topic":
            lines.append("  [TOPIC]  {}".format(ev["text"]))
        elif ev["type"] == "resonance":
            lines.append("  [~]  {}".format(ev["text"]))
        elif ev["type"] == "nudge":
            lines.append("  [DIRECTOR]  {}".format(ev["text"]))
        elif ev["type"] == "hidden":
            lines.append("  [HIDDEN LIFE]  {}".format(ev["text"]))

    lines.append("")
    lines.append("=" * 60)
    lines.append("END OF EVENING")
    lines.append("")

    # Psychological summary
    t = state["traits"]
    lines.append("FINAL PSYCHOLOGICAL STATE")
    lines.append("-" * 40)
    for k,v in t.items():
        bar = "#" * abs(v//5)
        sign = "+" if v >= 0 else ""
        lines.append("  {:25s} {}{}  {}".format(k, sign, v, bar))
    lines.append("")
    lines.append("Dominant emotions:")
    lines.append("  James:    {}".format(dominant_emotion("james")))
    lines.append("  Samantha: {}".format(dominant_emotion("samantha")))
    lines.append("")
    env = state.get("environment",{})
    lines.append("Final environment:")
    lines.append("  James alcohol:    {} ({})".format(env.get("james_alcohol",0), alcohol_label(effective_alcohol("james")) or "sober"))
    lines.append("  Samantha alcohol: {} ({})".format(env.get("samantha_alcohol",0), alcohol_label(effective_alcohol("samantha")) or "sober"))
    lines.append("  Party phase: {}".format(get_party_phase(state["turn"])["label"]))

    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition":"attachment; filename=two_minds_transcript.txt"}
    )

if __name__=="__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.INFO)
    loaded = load_state()

    # Detect which profile files are loaded
    james_file = "james_dark.json" if "exist to be used" in JAMES.get("shadow","") else "james.json"
    sam_file   = "samantha_dark.json" if "only real person" in SAMANTHA.get("shadow","") else "samantha.json"

    print("\n  two minds")
    print("  " + unichr(8212)*40 if False else "  " + "-"*40)
    print("  James    : {} | {} | {}".format(JAMES["name"], JAMES.get("model","?"), james_file))
    print("  Samantha : {} | {} | {}".format(SAMANTHA["name"], SAMANTHA.get("model","?"), sam_file))
    print("  Narrator : {}".format(NARRATOR_MODEL))
    print("  Ollama   : {}".format(OLLAMA_URL))
    print("  " + "-"*40)
    print("  {}".format("Resumed from turn {}".format(state["turn"]) if loaded else "Fresh start"))
    print("  " + "-"*40)
    print("  Chat      -> http://localhost:5000")
    print("  Dashboard -> http://localhost:5000/dashboard")
    print("  Traits    -> http://localhost:5000/traits")
    print("  Emotions  -> http://localhost:5000/emotions")
    print("  " + "-"*40 + "\n")
    app.run(debug=False, port=5000, threaded=True)
