"""Seed comprehensive demo data: taxonomy + vibe recipes + ~150 jokes + 4 packs.

Idempotent — every row uses `update_or_create` keyed on slug or text. Reverse
removes the jokes/packs seeded here but leaves taxonomy in place (deleting
formats/tones/themes would cascade into existing user submissions and is
intentionally a no-op).

Aligned with `parts/flow.jsx` from the design package: 6 formats, 12 themes,
8 categories + 1 added (puns), 12 vibes (already seeded in migration 0013;
this migration populates their filter recipes).
"""
from django.db import migrations


# ============================================================================
# Taxonomy — canonical values aligned with the design's vocabulary
# ============================================================================

FORMATS = [
    # (slug, name, description)
    ('oneliner', 'One-liner',         'A single self-contained line.'),
    ('setup',    'Setup → Punchline', 'Two-beat: setup, then punchline.'),
    ('knock',    'Knock-knock',       'Conversational call-and-response.'),
    ('story',    'Story',             'Long-form, slow burn.'),
    ('anti',     'Anti-joke',         "Refuses to land. That's the joke."),
    ('observ',   'Observational',     'Quote-style commentary.'),
]

AGE_RATINGS = [
    # (slug, name, description, min_age)
    ('kid-safe',        'Kid-safe',         'Safe for children of any age.',                 0),
    ('family-friendly', 'Family-friendly',  'Group-chat safe; no edge.',                     0),
    ('teen',            'Teen',             'Some innuendo or sharper edges.',               13),
    ('adult',           'Adult',            'Adult-only humor.',                             18),
    ('mature',          'Mature',           'Heavy themes; reserved for darker categories.', 18),
]

# ContextTag — design calls these "themes" (what the joke is about)
THEMES = [
    ('work',    'Work',    'Workplace, meetings, corporate life.'),
    ('family',  'Family',  'Parents, kids, in-laws.'),
    ('food',    'Food',    'Eating, cooking, coffee, restaurants.'),
    ('tech',    'Tech',    'Programming, gadgets, internet, AI.'),
    ('school',  'School',  'Classrooms, teachers, students.'),
    ('dating',  'Dating',  'Romance, dating apps, relationships.'),
    ('animals', 'Animals', 'Pets, wildlife, animal humor.'),
    ('science', 'Science', 'Physics, chemistry, biology.'),
    ('travel',  'Travel',  'Flying, hotels, road trips.'),
    ('money',   'Money',   'Banking, taxes, paychecks.'),
    ('weather', 'Weather', 'Climate, seasons, storms.'),
    ('mondays', 'Mondays', 'Start-of-week energy.'),
    ('puns',    'Puns',    'Wordplay-driven humor.'),
]

# Tone — design calls these "categories" (how the joke feels)
CATEGORIES = [
    ('wholesome',     'Wholesome',     'Group-chat safe; warm.'),
    ('office-proper', 'Office-proper', 'Standup-ready; no edge.'),
    ('dad',           'Dad',           'Eye-roll territory.'),
    ('kid-safe',      'Kid-safe',      'School-pickup safe.'),
    ('nerd',          'Nerd',          'Code/math/science humor.'),
    ('surreal',       'Surreal',       'Logic optional.'),
    ('dark',          'Dark',          'Black coffee, no sugar.'),
    ('edgy',          'Edgy',          'Group-chat unhinged.'),
    ('puns',          'Puns',          'Wordplay supreme.'),
]


# ============================================================================
# Vibe filter recipes — each curated humor flavor as filters over the taxonomy
# ============================================================================

VIBE_RECIPES = {
    'office':    {'themes': ['work'],          'categories': ['office-proper']},
    'dad':       {'categories': ['dad']},
    'puns':      {'categories': ['puns']},
    'dark':      {'categories': ['dark']},
    'nerd':      {'categories': ['nerd'],      'themes': ['tech', 'science']},
    'surreal':   {'categories': ['surreal']},
    'wholesome': {'categories': ['wholesome']},
    'observ':    {'formats': ['observ']},
    'oneliner':  {'formats': ['oneliner']},
    'date':      {'themes': ['dating']},
    'kids':      {'categories': ['kid-safe']},
    'absurd':    {'categories': ['surreal']},
}


# ============================================================================
# Demo joke catalog — 154 jokes covering the full filter matrix
# ============================================================================

# Schema for each entry:
#   text: required — used for the canonical text field + search_vector
#   format: required — slug from FORMATS
#   age: required — slug from AGE_RATINGS
#   cats: list of slugs from CATEGORIES (Tone)
#   themes: list of slugs from THEMES (ContextTag)
#   setup, punchline: for format='setup'
#   lines: for format='knock' (list of strings)

JOKES = [
    # ---------- WORK (14) ----------
    {'text': "Adulthood is just emailing 'Sounds good!' back and forth until one of you dies.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "My therapist said growth is uncomfortable. So is this email.",
     'format': 'observ', 'age': 'teen', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "The reason I look so smart in meetings? I just say 'circle back' a lot.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "Why don't economists ever go to therapy? They're already great at making excuses for everything.",
     'setup': "Why don't economists ever go to therapy?",
     'punchline': "They're already great at making excuses for everything.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['work']},
    {'text': "My out-of-office message says 'I'm out.' It's been three years.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "Boss said think outside the box. I've been in this cubicle for nine years. What box?",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "Why did the scrum master cross the road? Because the standup didn't have time for it.",
     'setup': "Why did the scrum master cross the road?",
     'punchline': "Because the standup didn't have time for it.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['work', 'tech']},
    {'text': "A consultant is someone who borrows your watch to tell you what time it is — then keeps the watch.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['work']},
    {'text': "'Can we hop on a quick call' is the new 'this could've been a war crime.'",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['work']},
    {'text': "My LinkedIn says 'thought leader.' My Google search history says 'why does my finger hurt.'",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "The only thing more cursed than a Monday meeting is the Friday afternoon Slack message that says 'got a sec?'",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work', 'mondays']},
    {'text': "I tell my interns the real workplace lesson: spreadsheets pay, slideshows lie, and free pizza never adds up.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['work']},
    {'text': "I gave my sales team a motivational poster that just says 'Be more like Tuesday.' Q3 is already up.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},
    {'text': "HR called it 'synergy.' The rest of us called it 'Brad finally agreeing with someone.'",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['work']},

    # ---------- FAMILY (12) ----------
    {'text': "I told my wife she was drawing her eyebrows too high. She seemed surprised.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['family']},
    {'text': "I used to hate facial hair. But then it grew on me.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['wholesome', 'puns'], 'themes': ['family', 'puns']},
    {'text': "My kid asked what's for dinner. I said 'regret.' He laughed. He doesn't know yet.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['family']},
    {'text': "Parenting is just yelling 'shoes! shoes! SHOES!' until you give up and carry them.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['family']},
    {'text': "My mother-in-law said I had a face for radio. So I dimmed the lights and now we get along great.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['family']},
    {'text': "Why did the dad bring a ladder to the bar? He heard drinks were on the house.",
     'setup': "Why did the dad bring a ladder to the bar?",
     'punchline': "He heard drinks were on the house.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['family']},
    {'text': "My grandparents don't say 'I love you.' They say 'are you eating enough?' — same thing in dialect.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['family']},
    {'text': "Knock, knock. Who's there? A broken pencil. A broken pencil who? Never mind. It's pointless.",
     'lines': ["Knock, knock.", "Who's there?", "A broken pencil.", "A broken pencil who?", "Never mind. It's pointless."],
     'format': 'knock', 'age': 'kid-safe', 'cats': ['kid-safe'], 'themes': ['family']},
    {'text': "My toddler is the only person who can negotiate snacks like a hostage situation and somehow win every time.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['family']},
    {'text': "I asked my daughter what she wants for her birthday. She said 'your laptop.' I said 'no.' She said 'fine, just the password.'",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['family']},
    {'text': "Marriage is just two people taking turns being the only adult in the relationship.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['family']},
    {'text': "Why did the cookie cry? Because his mom was a wafer so long.",
     'setup': "Why did the cookie cry?",
     'punchline': "Because his mom was a wafer so long.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['family', 'food']},

    # ---------- FOOD (13) ----------
    {'text': "Coffee doesn't ask silly questions. Coffee understands.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['food']},
    {'text': "What's red and bad for your teeth? A brick.",
     'setup': "What's red and bad for your teeth?",
     'punchline': "A brick.",
     'format': 'anti', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['food']},
    {'text': "I'm on a seafood diet. I see food and I eat it.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['food', 'puns']},
    {'text': "My cookbook has a chapter called 'things I swore I'd never reheat.' It's the longest chapter.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['food']},
    {'text': "Why did the espresso file a police report? Because it was mugged.",
     'setup': "Why did the espresso file a police report?",
     'punchline': "Because it was mugged.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['food', 'puns']},
    {'text': "Vegan: someone whose dietary preferences arrive before they do.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['food']},
    {'text': "What do you call cheese that isn't yours? Nacho cheese.",
     'setup': "What do you call cheese that isn't yours?",
     'punchline': "Nacho cheese.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['food', 'puns']},
    {'text': "I named my sourdough Brad. Brad has demands.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['food']},
    {'text': "The first rule of brunch club is no one stays for one mimosa.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['food']},
    {'text': "Coffee is just bean soup we collectively decided to celebrate.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['food']},
    {'text': "Why did the cookie go to the doctor? It was feeling crumby.",
     'setup': "Why did the cookie go to the doctor?",
     'punchline': "It was feeling crumby.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['food', 'puns']},
    {'text': "I tried intermittent fasting. I lasted intermittently — about six minutes.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['food']},
    {'text': "Why did the orange stop rolling down the hill? It ran out of juice.",
     'setup': "Why did the orange stop rolling down the hill?",
     'punchline': "It ran out of juice.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['food', 'puns']},

    # ---------- TECH (12) ----------
    {'text': "My password is the last 8 digits of pi.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['tech', 'science']},
    {'text': "How many programmers does it take to change a lightbulb? None. That's a hardware problem.",
     'setup': "How many programmers does it take to change a lightbulb?",
     'punchline': "None. That's a hardware problem.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['tech']},
    {'text': "There are 10 kinds of people in the world: those who understand binary, and those who don't.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['tech']},
    {'text': "My code only works because I haven't found out why yet.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['tech']},
    {'text': "I'd tell you a UDP joke, but you might not get it.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['tech', 'puns']},
    {'text': "Why do programmers always confuse Halloween with Christmas? Because OCT 31 = DEC 25.",
     'setup': "Why do programmers always confuse Halloween with Christmas?",
     'punchline': "Because OCT 31 = DEC 25.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['tech', 'puns']},
    {'text': "I changed my password to 'incorrect' so when I forget it, the computer tells me.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['tech']},
    {'text': "AI is great at answering questions humans never asked, with a confidence I haven't earned.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['tech']},
    {'text': "Why did the function break up with the variable? It was tired of being passed by reference.",
     'setup': "Why did the function break up with the variable?",
     'punchline': "It was tired of being passed by reference.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['tech', 'puns', 'dating']},
    {'text': "The cloud is just somebody else's computer with better marketing.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['tech']},
    {'text': "I asked my smart speaker for some peace and quiet. She suggested I try the off button — which she also turned off.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['tech']},
    {'text': "What did one byte say to the other? I'm feeling a little off — only 7 of me showed up.",
     'setup': "What did one byte say to the other?",
     'punchline': "I'm feeling a little off — only 7 of me showed up.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['tech', 'puns']},

    # ---------- SCHOOL (10) ----------
    {'text': "Knock, knock. Who's there? Cows go. Cows go who? No, cows go moo.",
     'lines': ["Knock, knock.", "Who's there?", "Cows go.", "Cows go who?", "No, cows go moo."],
     'format': 'knock', 'age': 'kid-safe', 'cats': ['kid-safe'], 'themes': ['school', 'animals']},
    {'text': "Why did the math book look so sad? It had too many problems.",
     'setup': "Why did the math book look so sad?",
     'punchline': "It had too many problems.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['school']},
    {'text': "What's a teacher's favorite nation? Expla-nation.",
     'setup': "What's a teacher's favorite nation?",
     'punchline': "Expla-nation.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['school', 'puns']},
    {'text': "Why did the geometry teacher's plants die? They didn't get enough sun, just shadows.",
     'format': 'oneliner', 'age': 'kid-safe', 'cats': ['kid-safe', 'puns'], 'themes': ['school', 'puns']},
    {'text': "Knock, knock. Who's there? Atch. Atch who? Bless you.",
     'lines': ["Knock, knock.", "Who's there?", "Atch.", "Atch who?", "Bless you."],
     'format': 'knock', 'age': 'kid-safe', 'cats': ['kid-safe'], 'themes': ['school']},
    {'text': "The school nurse can identify which planet you're from by which excuse you tried.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['school', 'family']},
    {'text': "Why did the kid eat his homework? His teacher said it was a piece of cake.",
     'setup': "Why did the kid eat his homework?",
     'punchline': "His teacher said it was a piece of cake.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['school', 'food']},
    {'text': "The student who finishes the test first is either a genius or about to learn a new lesson.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['kid-safe'], 'themes': ['school']},
    {'text': "What did the pencil say to the paper? I dot my i's on you.",
     'setup': "What did the pencil say to the paper?",
     'punchline': "I dot my i's on you.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['surreal', 'puns'], 'themes': ['school', 'puns']},
    {'text': "Why did the equal sign break up with the plus sign? It was too positive.",
     'setup': "Why did the equal sign break up with the plus sign?",
     'punchline': "It was too positive.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['school', 'science', 'dating']},

    # ---------- DATING (11) ----------
    {'text': "I asked my date what their love language was. They sighed, 'subtitles.' I get it.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['dating']},
    {'text': "My dating profile says 'I love long walks.' It does not specify away from problems.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['dating']},
    {'text': "Why don't ghosts go on dates? They don't have the guts.",
     'setup': "Why don't ghosts go on dates?",
     'punchline': "They don't have the guts.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['dating']},
    {'text': "We exchanged numbers. Hers was the wrong one and mine was hopeful.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['dark'], 'themes': ['dating']},
    {'text': "The only relationship I've successfully maintained for years is with my morning coffee.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['dating', 'food']},
    {'text': "Online dating is just shopping for a person who tolerates the parts of yourself you've Marie Kondo-ed away.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['dating']},
    {'text': "What did the calendar say to the date? I'm so over you.",
     'setup': "What did the calendar say to the date?",
     'punchline': "I'm so over you.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['dating', 'puns']},
    {'text': "First date red flag: when they ask 'what's your five-year plan.' Second red flag: they have a slide deck.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['dating', 'work']},
    {'text': "The most romantic thing my partner does is order food without making me look at the menu.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['dating', 'food']},
    {'text': "Knock, knock. Who's there? Olive. Olive who? Olive you. That's why I'm here.",
     'lines': ["Knock, knock.", "Who's there?", "Olive.", "Olive who?", "Olive you. That's why I'm here."],
     'format': 'knock', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['dating']},
    {'text': "I told my crush I was an open book. They said the table of contents needed work.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['dating']},

    # ---------- ANIMALS (13) ----------
    {'text': "What's the difference between a hippo and a Zippo? One is really heavy and the other is a little lighter.",
     'setup': "What's the difference between a hippo and a Zippo?",
     'punchline': "One is really heavy and the other is a little lighter.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['animals']},
    {'text': "Why did the scarecrow win an award? He was outstanding in his field.",
     'setup': "Why did the scarecrow win an award?",
     'punchline': "He was outstanding in his field.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['animals', 'work']},
    {'text': "Why did the chicken cross the road? To get to the other side.",
     'setup': "Why did the chicken cross the road?",
     'punchline': "To get to the other side.",
     'format': 'anti', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['animals']},
    {'text': "What do you call a fish wearing a crown? Your royal hali-ness.",
     'setup': "What do you call a fish wearing a crown?",
     'punchline': "Your royal hali-ness.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['animals', 'puns']},
    {'text': "My cat doesn't ignore me. She's just not that into people.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['animals']},
    {'text': "Why don't seagulls fly over the bay? Because then they'd be bagels.",
     'setup': "Why don't seagulls fly over the bay?",
     'punchline': "Because then they'd be bagels.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['animals', 'food', 'puns']},
    {'text': "Knock, knock. Who's there? A herd. A herd who? A herd cattle had a great lawyer.",
     'lines': ["Knock, knock.", "Who's there?", "A herd.", "A herd who?", "A herd cattle had a great lawyer."],
     'format': 'knock', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['animals']},
    {'text': "What's a dog's favorite breakfast? Pooched eggs.",
     'setup': "What's a dog's favorite breakfast?",
     'punchline': "Pooched eggs.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['animals', 'food', 'puns']},
    {'text': "Squirrels are just rats with better PR.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['animals']},
    {'text': "How do bees brush their hair? With honeycombs.",
     'setup': "How do bees brush their hair?",
     'punchline': "With honeycombs.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['animals', 'puns']},
    {'text': "My dog learned my name before he learned 'no.' That's leadership.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['animals', 'family']},
    {'text': "Owls are just cats trying to be employed.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['animals']},
    {'text': "What do you call a sleeping bull? A bulldozer.",
     'setup': "What do you call a sleeping bull?",
     'punchline': "A bulldozer.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['animals', 'puns']},

    # ---------- SCIENCE (12) ----------
    {'text': "Why don't scientists trust atoms anymore? Because they make up everything.",
     'setup': "Why don't scientists trust atoms anymore?",
     'punchline': "Because they make up everything.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['science', 'puns']},
    {'text': "I'm reading a book about anti-gravity. It's impossible to put down.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['science']},
    {'text': "Why did the biologist break up with the physicist? There was no chemistry.",
     'setup': "Why did the biologist break up with the physicist?",
     'punchline': "There was no chemistry.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'nerd', 'puns'], 'themes': ['science', 'dating', 'puns']},
    {'text': "What did the proton say to the electron? Stop being so negative.",
     'setup': "What did the proton say to the electron?",
     'punchline': "Stop being so negative.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'nerd'], 'themes': ['science']},
    {'text': "Time flies like an arrow. Fruit flies like a banana.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['science']},
    {'text': "What do you call an acid with an attitude? An a-mean-o acid.",
     'setup': "What do you call an acid with an attitude?",
     'punchline': "An a-mean-o acid.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['science', 'puns']},
    {'text': "The speed of light is so fast that nothing in physics has caught up emotionally.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['science']},
    {'text': "Why did the entropy joke not land? It just kept getting worse.",
     'setup': "Why did the entropy joke not land?",
     'punchline': "It just kept getting worse.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['science']},
    {'text': "My therapist said I have unresolved issues with Schrödinger. I both agree and disagree.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['nerd'], 'themes': ['science']},
    {'text': "What do you do with a sick chemist? If you can't helium and you can't curium, you barium.",
     'setup': "What do you do with a sick chemist?",
     'punchline': "If you can't helium and you can't curium, you barium.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'nerd', 'puns'], 'themes': ['science', 'puns']},
    {'text': "Astronomers found a new exoplanet. It's habitable, has water, and already won't return their calls.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['science']},
    {'text': "I would tell a chemistry joke, but I know I wouldn't get a reaction.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['science', 'puns']},

    # ---------- TRAVEL (11) ----------
    {'text': "Knock, knock. Who's there? Europe. Europe who? Wait, no. You're Europe.",
     'lines': ["Knock, knock.", "Who's there?", "Europe.", "Europe who?", "Wait, no. You're Europe."],
     'format': 'knock', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['travel']},
    {'text': "Why don't pirates take baths before they walk the plank? They just wash up on shore.",
     'setup': "Why don't pirates take baths before they walk the plank?",
     'punchline': "They just wash up on shore.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['travel']},
    {'text': "Airline boarding zones are an experiment to see how many people can be wrong about their group at once.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['travel']},
    {'text': "I packed light. The plane lost it anyway. They both made an effort.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['dark'], 'themes': ['travel']},
    {'text': "The hotel breakfast is 'free' the way 'free time' is — depends entirely on what you skipped to get there.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['travel']},
    {'text': "Why don't airplanes ever get tired? They have rest engines.",
     'setup': "Why don't airplanes ever get tired?",
     'punchline': "They have rest engines.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe', 'puns'], 'themes': ['travel', 'puns']},
    {'text': "Travel broadens the mind, especially the mind of the person packing for you.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['travel']},
    {'text': "The only foreign language I'm fluent in is 'frantically pointing at the menu picture.'",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['travel', 'food']},
    {'text': "What's a vampire's favorite mode of transport? Blood vessels.",
     'setup': "What's a vampire's favorite mode of transport?",
     'punchline': "Blood vessels.",
     'format': 'setup', 'age': 'teen', 'cats': ['dad', 'dark'], 'themes': ['travel']},
    {'text': "I asked Google Maps for the scenic route. It chose the one with construction. Same energy.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['travel', 'tech']},
    {'text': "The TSA agent looked at me like I'd packed a goat. I respected it.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['travel']},

    # ---------- MONEY (11) ----------
    {'text': "Why did the man bring a ladder to the bank? He wanted to climb the financial ladder.",
     'setup': "Why did the man bring a ladder to the bank?",
     'punchline': "He wanted to climb the financial ladder.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['money', 'puns']},
    {'text': "My budget app and I aren't on speaking terms.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['money']},
    {'text': "The economy is doing great if you ask the economy.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['money']},
    {'text': "I checked my bank balance. The bank checked it too. We disagreed politely.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['money']},
    {'text': "Why did the dollar bill go to therapy? It had change issues.",
     'setup': "Why did the dollar bill go to therapy?",
     'punchline': "It had change issues.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['money', 'puns']},
    {'text': "'Will it pay off?' asked the man whose entire portfolio is jokes.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['money']},
    {'text': "My financial advisor said diversify. So I bought regret in three different currencies.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['money']},
    {'text': "What did the savings account say to the checking account? You're so lifeless.",
     'setup': "What did the savings account say to the checking account?",
     'punchline': "You're so lifeless.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['money', 'puns']},
    {'text': "Inflation is when 'cheap' becomes a suggestion.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['money']},
    {'text': "I told my kid money doesn't grow on trees. He said yes it does, in stocks. He's grounded but also right.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['money', 'family']},
    {'text': "The richest people I know complain the most about taxes — which checks out, mathematically.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['money']},

    # ---------- WEATHER (11) ----------
    {'text': "Knock, knock. Who's there? Lettuce. Lettuce who? Lettuce in. It's freezing out here.",
     'lines': ["Knock, knock.", "Who's there?", "Lettuce.", "Lettuce who?", "Lettuce in. It's freezing out here."],
     'format': 'knock', 'age': 'kid-safe', 'cats': ['kid-safe'], 'themes': ['weather']},
    {'text': "The forecast said sunny. The forecast lied. It's always lied. We forgive, we never forget.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['weather']},
    {'text': "What did one tornado say to the other? Let's twist again.",
     'setup': "What did one tornado say to the other?",
     'punchline': "Let's twist again.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['weather', 'puns']},
    {'text': "I'm not saying it's cold, but my coffee filed for a restraining order against my hands.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['weather', 'food']},
    {'text': "Why don't clouds ever pay their debts? They always rain check.",
     'setup': "Why don't clouds ever pay their debts?",
     'punchline': "They always rain check.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['weather', 'money', 'puns']},
    {'text': "Weather forecasters are professional fortune tellers with better suits.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['weather']},
    {'text': "What's a cloud's favorite snack? Cotton candy.",
     'setup': "What's a cloud's favorite snack?",
     'punchline': "Cotton candy.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['weather', 'food']},
    {'text': "The wind has been doing my hair for free for forty years. The results are mixed.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['weather', 'family']},
    {'text': "Snow days are nature's way of telling adults: tag, you're it.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['weather', 'family']},
    {'text': "What does a thundercloud wear under its skirt? Thunderwear.",
     'setup': "What does a thundercloud wear under its skirt?",
     'punchline': "Thunderwear.",
     'format': 'setup', 'age': 'kid-safe', 'cats': ['dad', 'kid-safe'], 'themes': ['weather']},
    {'text': "Hot weather plus air conditioning equals the most polarizing relationship in any office.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['office-proper'], 'themes': ['weather', 'work']},

    # ---------- MONDAYS (10) ----------
    {'text': "Mondays are just Sundays with consequences.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['mondays']},
    {'text': "The optimist sees the glass as half full. The Monday person sees the glass as suspicious.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['mondays']},
    {'text': "Why did Monday cross the road? To ruin Tuesday too.",
     'setup': "Why did Monday cross the road?",
     'punchline': "To ruin Tuesday too.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad'], 'themes': ['mondays']},
    {'text': "Coffee is just a Monday in liquid form, and Monday is just regret in calendar form.",
     'format': 'observ', 'age': 'teen', 'cats': ['dark'], 'themes': ['mondays', 'food']},
    {'text': "I have a love/hate relationship with Mondays. The hate part loves the love part.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['mondays']},
    {'text': "Knock, knock. Who's there? Monday. Monday who? Just Monday. That's enough.",
     'lines': ["Knock, knock.", "Who's there?", "Monday.", "Monday who?", "Just Monday. That's enough."],
     'format': 'knock', 'age': 'family-friendly', 'cats': ['dark'], 'themes': ['mondays']},
    {'text': "Mondays are when 'I'll start tomorrow' looks back at me with disappointment.",
     'format': 'observ', 'age': 'teen', 'cats': ['edgy'], 'themes': ['mondays']},
    {'text': "The only thing more reliable than Monday is the snooze button.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['mondays']},
    {'text': "Mondays don't ruin weeks. Weeks ruin themselves; Monday just shows up first.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['mondays']},
    {'text': "My Monday motivation has been on PTO since 2019. Approved every week.",
     'format': 'oneliner', 'age': 'teen', 'cats': ['edgy'], 'themes': ['mondays', 'work']},

    # ---------- PURE PUNS (6) ----------
    {'text': "I used to be a banker, but I lost interest.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['puns', 'money']},
    {'text': "I'm friends with 25 letters of the alphabet. I don't know Y.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['puns']},
    {'text': "I'm reading a book about gravity. It's hard to put down — and impossible if you let go.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['puns', 'science']},
    {'text': "What's the best thing about Switzerland? I don't know, but the flag is a big plus.",
     'setup': "What's the best thing about Switzerland?",
     'punchline': "I don't know, but the flag is a big plus.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['puns', 'travel']},
    {'text': "The future, the present, and the past walked into a bar. Things got tense.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['puns']},
    {'text': "I told my computer I needed a break, and now it won't stop sending me Kit-Kat ads.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['dad', 'puns'], 'themes': ['puns', 'tech']},

    # ---------- MISC / CROSS-THEME (8) ----------
    {'text': "A man walks into a library and asks the librarian for a book on paranoia. She whispers, 'They're right behind you.' He turned around — and to his relief, only a stack of returns. He picked one off the top: 'How to Trust Strangers.' He's been on chapter one for six years.",
     'format': 'story', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['work']},
    {'text': "My grandfather told me he could hold his breath for forty seconds. I asked how. He said: be married to my grandmother. Forty-seven years and counting. He swears it's love.",
     'format': 'story', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['family']},
    {'text': "My kid finally learned to spell 'restaurant' correctly. My phone learned 'definately' was wrong. We're all growing.",
     'format': 'observ', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['school', 'family']},
    {'text': "Two muffins are sitting in an oven. One says, 'sure is hot in here.' The other says, 'I have no opinion. I am a muffin.'",
     'format': 'anti', 'age': 'family-friendly', 'cats': ['surreal'], 'themes': ['food']},
    {'text': "I tried to make a reservation at the most popular restaurant in town. They asked when. I said tonight. They laughed for six minutes and then put me on hold for the same reason.",
     'format': 'story', 'age': 'family-friendly', 'cats': ['wholesome'], 'themes': ['food', 'travel']},
    {'text': "Every smart device in my home now updates itself overnight while I lose sleep wondering what they're saying about me.",
     'format': 'observ', 'age': 'teen', 'cats': ['dark'], 'themes': ['tech']},
    {'text': "Yesterday my daughter told me I'm her best friend. Then she asked for snacks. The strategy is generations old.",
     'format': 'oneliner', 'age': 'family-friendly', 'cats': ['wholesome', 'dad'], 'themes': ['family', 'food']},
    {'text': "Why did the developer go broke? He used up all his cache.",
     'setup': "Why did the developer go broke?",
     'punchline': "He used up all his cache.",
     'format': 'setup', 'age': 'family-friendly', 'cats': ['nerd', 'puns'], 'themes': ['tech', 'money', 'puns']},
]


# ============================================================================
# Joke Pack seed data — 4 demo packs
# ============================================================================

PACKS = [
    {
        'slug': 'office-banter-tuesday',
        'title': 'Office Banter Tuesday',
        'subtitle': 'Standup-ready punchlines, vetted for any meeting room.',
        'description': '10 work-safe jokes engineered to win a Tuesday standup. No edge, no after-effects.',
        'cover_color': '#6A1CF6',
        'is_featured': True,   # the Today screen Weekly Special
        # Selection criterion: format + theme matchers
        'theme_filter': ['work'],
        'cat_filter': ['office-proper'],
        'limit': 10,
    },
    {
        'slug': 'wholesome-classics',
        'title': 'Wholesome Family Classics',
        'subtitle': 'For the group chat that wants to like itself.',
        'description': 'Family-safe jokes you can text your aunt without negotiation.',
        'cover_color': '#FFC965',
        'is_featured': False,
        'theme_filter': ['family'],
        'cat_filter': ['wholesome'],
        'limit': 10,
    },
    {
        'slug': 'punchline-lab',
        'title': 'Punchline Lab — best of puns',
        'subtitle': 'Wordplay supreme. Side effects include groaning.',
        'description': '12 of the highest-density puns in the library. Each one is its own crime.',
        'cover_color': '#CAFD00',
        'is_featured': False,
        'theme_filter': ['puns'],
        'cat_filter': ['puns'],
        'limit': 12,
    },
    {
        'slug': 'kid-rotation',
        'title': 'Kid-safe rotation',
        'subtitle': 'School-pickup safe; tested on actual kindergarteners.',
        'description': '10 jokes you can tell at the school carline without getting a phone call.',
        'cover_color': '#D6F2FF',
        'is_featured': False,
        'cat_filter': ['kid-safe'],
        'limit': 10,
    },
]


# ============================================================================
# Migration operations
# ============================================================================

def _upsert_by_slug_or_name(model, slug, name, **fields):
    """update_or_create that survives existing rows with conflicting unique
    `name` values. Some test/dev rows pre-exist with different slugs but the
    same display name; this helper relinks them rather than failing."""
    obj = model.objects.filter(slug=slug).first()
    if obj is None:
        obj = model.objects.filter(name=name).first()
    if obj is None:
        return model.objects.create(slug=slug, name=name, **fields)
    obj.slug = slug
    obj.name = name
    for k, v in fields.items():
        setattr(obj, k, v)
    obj.save()
    return obj


def seed_taxonomy(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    AgeRating = apps.get_model('jokes', 'AgeRating')
    ContextTag = apps.get_model('jokes', 'ContextTag')
    Tone = apps.get_model('jokes', 'Tone')
    Language = apps.get_model('jokes', 'Language')

    for slug, name, desc in FORMATS:
        _upsert_by_slug_or_name(Format, slug, name, description=desc)
    for slug, name, desc, min_age in AGE_RATINGS:
        _upsert_by_slug_or_name(AgeRating, slug, name, description=desc, min_age=min_age)
    for slug, name, desc in THEMES:
        _upsert_by_slug_or_name(ContextTag, slug, name, description=desc)
    for slug, name, desc in CATEGORIES:
        _upsert_by_slug_or_name(Tone, slug, name, description=desc)
    Language.objects.update_or_create(code='en', defaults={'name': 'English'})


def seed_vibe_recipes(apps, schema_editor):
    Vibe = apps.get_model('jokes', 'Vibe')
    Format = apps.get_model('jokes', 'Format')
    ContextTag = apps.get_model('jokes', 'ContextTag')
    Tone = apps.get_model('jokes', 'Tone')

    fmt_map = {f.slug: f for f in Format.objects.all()}
    th_map = {t.slug: t for t in ContextTag.objects.all()}
    cat_map = {t.slug: t for t in Tone.objects.all()}

    for slug, recipe in VIBE_RECIPES.items():
        try:
            v = Vibe.objects.get(slug=slug)
        except Vibe.DoesNotExist:
            continue
        v.formats.set([fmt_map[f] for f in recipe.get('formats', []) if f in fmt_map])
        v.themes.set([th_map[t] for t in recipe.get('themes', []) if t in th_map])
        v.categories.set([cat_map[c] for c in recipe.get('categories', []) if c in cat_map])


def seed_jokes(apps, schema_editor):
    Joke = apps.get_model('jokes', 'Joke')
    Format = apps.get_model('jokes', 'Format')
    AgeRating = apps.get_model('jokes', 'AgeRating')
    ContextTag = apps.get_model('jokes', 'ContextTag')
    Tone = apps.get_model('jokes', 'Tone')
    Language = apps.get_model('jokes', 'Language')

    fmt_map = {f.slug: f for f in Format.objects.all()}
    ar_map = {a.slug: a for a in AgeRating.objects.all()}
    th_map = {t.slug: t for t in ContextTag.objects.all()}
    cat_map = {t.slug: t for t in Tone.objects.all()}
    en, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})

    for j in JOKES:
        defaults = {
            'setup': j.get('setup', ''),
            'punchline': j.get('punchline', ''),
            'lines': j.get('lines'),
            'format': fmt_map[j['format']],
            'age_rating': ar_map[j['age']],
            'language': en,
        }
        joke, _ = Joke.objects.update_or_create(text=j['text'], defaults=defaults)
        joke.tones.set([cat_map[s] for s in j.get('cats', []) if s in cat_map])
        joke.context_tags.set([th_map[s] for s in j.get('themes', []) if s in th_map])


def seed_packs(apps, schema_editor):
    JokePack = apps.get_model('jokes', 'JokePack')
    JokePackEntry = apps.get_model('jokes', 'JokePackEntry')
    Joke = apps.get_model('jokes', 'Joke')

    for p in PACKS:
        pack, _ = JokePack.objects.update_or_create(
            slug=p['slug'],
            defaults={
                'title': p['title'],
                'subtitle': p['subtitle'],
                'description': p['description'],
                'cover_color': p['cover_color'],
                'is_published': True,
                'is_featured': p['is_featured'],
            },
        )
        # Build the joke pool for this pack from the seed criteria
        qs = Joke.objects.all()
        if p.get('theme_filter'):
            qs = qs.filter(context_tags__slug__in=p['theme_filter']).distinct()
        if p.get('cat_filter'):
            qs = qs.filter(tones__slug__in=p['cat_filter']).distinct()
        jokes = list(qs[:p['limit']])

        # Replace existing entries (idempotent)
        JokePackEntry.objects.filter(pack=pack).delete()
        for order, joke in enumerate(jokes):
            JokePackEntry.objects.create(pack=pack, joke=joke, order=order)


def unseed_jokes(apps, schema_editor):
    """Remove only the jokes seeded by this migration (matched by exact text)."""
    Joke = apps.get_model('jokes', 'Joke')
    Joke.objects.filter(text__in=[j['text'] for j in JOKES]).delete()


def unseed_packs(apps, schema_editor):
    JokePack = apps.get_model('jokes', 'JokePack')
    JokePack.objects.filter(slug__in=[p['slug'] for p in PACKS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('jokes', '0020_add_joke_lines'),
    ]
    operations = [
        migrations.RunPython(seed_taxonomy,     reverse_code=migrations.RunPython.noop),
        migrations.RunPython(seed_vibe_recipes, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(seed_jokes,        reverse_code=unseed_jokes),
        migrations.RunPython(seed_packs,        reverse_code=unseed_packs),
    ]
