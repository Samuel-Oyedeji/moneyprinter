"""The paper-story kit's vocabulary, mirrored from remotion/src/types.ts.

The storyboard prompt lists these options and the compiler drops anything
outside them, so an LLM typo can never reach the renderer.
"""

OUTDOOR_SKIES = ("day", "dusk", "night", "storm", "dawn")
INTERIORS = ("room", "classroom", "lab", "hall")
SKIES = OUTDOOR_SKIES + ("parchment",) + INTERIORS + ("space", "underwater")
OUTDOOR_GROUNDS = ("hills", "town", "field", "sea", "desert", "forest", "mountains", "city", "beach", "snowfield")
SPACE_GROUNDS = ("lunar", "none")
GROUNDS = OUTDOOR_GROUNDS + ("lunar", "seabed", "none")
LANDMARKS = ("pyramids", "castle", "temple", "lighthouse", "volcano")
# Which extras each kind of setting can show.
SKY_EXTRAS = ("sun", "moon", "stars", "clouds", "rain", "snow", "tree", "birds")
OUTDOOR_EXTRAS = SKY_EXTRAS + LANDMARKS
SPACE_EXTRAS = ("stars", "planet", "earth", "sun", "moon")
UNDERWATER_EXTRAS = ("fish", "bubbles")
EXTRAS = tuple(dict.fromkeys(OUTDOOR_EXTRAS + ("window",) + SPACE_EXTRAS + UNDERWATER_EXTRAS))
# What each setting shows when the storyboard names no extras (mirrors
# defaultExtras in remotion/src/kit/palettes.ts).
DEFAULT_EXTRAS = {
    "day": ("sun", "clouds"),
    "dusk": ("sun", "clouds"),
    "night": ("stars", "moon"),
    "storm": ("clouds", "rain"),
    "dawn": ("sun", "clouds", "birds"),
    "room": ("window",),
    "space": ("stars", "planet"),
    "underwater": ("fish", "bubbles"),
}
CAMERAS = ("drift", "push", "pull", "pan-left", "pan-right", "rise", "still")
# tear/cut, and the ones that happen inside the picture
TRANSITIONS = ("tear", "cut", "fly", "hand", "zoom", "pull")
MOTIVATED_TRANSITIONS = ("fly", "hand", "zoom", "pull")
# Things a zoom can fly into besides a prop in the previous scene.
ZOOM_EXTRAS = ("window", "sun", "moon", "planet", "earth")

# A kind brings its own outfit (robots and animals their own heads too).
KINDS = ("person", "astronaut", "knight", "pharaoh", "robot", "animal")
SPECIES = ("fox", "rabbit", "bear", "cat")
AGES = ("child", "adult", "elder")
BUILDS = ("slim", "average", "broad")
SKINS = ("light", "fair", "tan", "brown", "dark", "deep")
HAIR = (
    "short", "side-part", "spiky", "curly", "afro", "long", "bob",
    "bun", "ponytail", "braids", "balding", "bald", "headscarf",
)
FACIAL_HAIR = ("none", "mustache", "beard", "goatee")
TOPS = ("shirt", "tshirt", "sweater", "suit", "labcoat", "coat", "dress", "robe")
BOTTOMS = ("trousers", "shorts", "skirt")
HATS = ("fedora", "bowler", "tophat", "cap", "crown", "beanie", "straw", "helmet")
ACCESSORIES = ("tie", "bowtie", "glasses", "scarf", "necklace", "belt", "apron", "cape")

EXPRESSIONS = ("smile", "grin", "neutral", "frown", "surprised", "worried", "angry", "sleepy")
PERSON_ACTIONS = (
    "walk", "talk", "point", "wave", "shrug", "think", "cheer",
    "nod", "shake-head", "hop", "turn", "look", "feel",
)
PERSON_ENTERS = ("pop", "walk-in-left", "walk-in-right", "drop", "none")
PERSON_EXITS = ("walk-out-left", "walk-out-right", "fold")

PROPS = (
    "book", "scroll", "letter", "coin", "moneybag", "crown", "sword", "flag",
    "candle", "bottle", "pills", "cup", "flask", "petri-dish", "dish-stack",
    "microscope", "apple", "basket", "bucket", "chest", "key", "clock",
    "hourglass", "globe", "lightbulb", "heart", "star", "trophy", "gift",
    "suitcase", "umbrella", "house", "boat", "rock", "well", "sign",
    "chair", "plant", "phone", "laptop", "arrow",
)
# Props that read well as something a person holds.
HOLDABLE = (
    "book", "scroll", "letter", "coin", "moneybag", "crown", "sword", "flag",
    "candle", "bottle", "cup", "flask", "petri-dish", "apple", "basket",
    "bucket", "key", "clock", "hourglass", "lightbulb", "heart", "star",
    "trophy", "gift", "suitcase", "umbrella", "phone", "laptop", "sign",
)
PROP_ENTERS = ("pop", "drop", "flip", "slide-left", "slide-right", "none")
PROP_ACTIONS = ("hop", "shake", "grow", "nod", "turn", "tilt")
PROP_SIZES = ("small", "medium", "large", "hero")
PROP_LEVELS = ("ground", "table", "air")

PLACES = ("far-left", "left", "center", "right", "far-right")
# Anything the library lacks is built from simple shapes ("custom" prop).
CUSTOM_PROP = "custom"
SHAPE_TYPES = ("rect", "circle", "ellipse", "poly")
NOTE_KINDS = ("title", "stamp", "label")
