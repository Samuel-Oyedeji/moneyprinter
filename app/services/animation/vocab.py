"""The paper-story kit's vocabulary, mirrored from remotion/src/types.ts.

The storyboard prompt lists these options and the compiler drops anything
outside them, so an LLM typo can never reach the renderer.
"""

SKIES = ("day", "dusk", "night", "storm", "parchment", "room")
GROUNDS = ("hills", "town", "field", "sea", "none")
EXTRAS = ("sun", "moon", "stars", "clouds", "rain", "snow", "window", "tree")
CAMERAS = ("drift", "push", "pull", "pan-left", "pan-right", "rise", "still")
TRANSITIONS = ("tear", "cut")

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
