"""Everything the robot says. All lines are scripted: no live AI talks to the child.

Each step is a list of beats. A beat is (text, motion). Text may use:
  {kid}   the child's name
  {robot} the name the child gave the robot
  {hero}  the story hero's full name, {short} the short name
  {fun}   what the hero loves doing, {place} where the hero gets fixed

Motions are named in robot.py (MOTIONS). An empty text means "move only".
Wording rules: never promise it won't hurt, never mention needles,
keep the medical steps generic so they fit most day-surgery visits.
"""

from dataclasses import dataclass

ROBOT_NAME = "Dr. Juni"  # the robot's own name; the child can add a nickname


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    emoji: str
    hero: str
    short: str
    fun: str
    place: str
    picked: str  # what the robot says when the child picks this theme


THEMES: dict[str, Theme] = {
    t.key: t
    for t in [
        Theme("trucks", "Monster trucks", "🛻", "Big Red the monster truck", "Big Red",
              "zooming over giant mud hills", "the Truck Doctor's garage",
              "Monster trucks! Vroom vroom! Great choice."),
        Theme("princess", "Princesses", "👑", "Princess Luna", "Princess Luna",
              "dancing around the castle garden", "the castle doctor's tower",
              "A princess story! How royal. Great choice."),
        Theme("dinosaurs", "Dinosaurs", "🦖", "Tiny Rex the dinosaur", "Tiny Rex",
              "stomping through the jungle", "the dino doctor's cave",
              "Dinosaurs! Roar! Great choice."),
        Theme("space", "Outer space", "🚀", "Captain Nova the astronaut", "Captain Nova",
              "flying past the stars", "the space station doctor",
              "Outer space! Three, two, one, blast off! Great choice."),
        Theme("animals", "Animals", "🐶", "Biscuit the puppy", "Biscuit",
              "chasing butterflies in the park", "the animal doctor's clinic",
              "Animals! Woof woof! Great choice."),
        Theme("heroes", "Superheroes", "🦸", "Captain Brave", "Captain Brave",
              "flying over the city to help people", "the hero headquarters doctor",
              "Superheroes! Whoosh! Great choice."),
    ]
}


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    phase: str  # shown as a section in the nurse panel
    hint: str  # what the nurse/parent should do
    beats: tuple[tuple[str, str], ...]
    needs_theme: bool = False


STEPS: list[Step] = [
    Step("greet", "Hello", "Before surgery",
         "Child facing the robot.",
         (("", "wake"),
          ("Hi {kid}! I'm Dr. Juni, and I'm so happy to meet you.", "happy"),
          ("I'm a little robot, and I'm going to keep you company today.", "tilt"))),
    Step("ask_name", "Nickname", "Before surgery",
         "Listens automatically.",
         (("Dr. Juni is my grown-up name. But my best friends give me nicknames!", "think"),
          ("Can you give me one? What nickname should I have?", "tilt"))),
    Step("got_name", "Say nickname", "Before surgery",
         "Check spelling.",
         (("{robot}! I love it!", "celebrate"),
          ("That's my name now. Thank you, {kid}.", "nod"))),
    Step("ask_story", "Pick a story", "Before surgery",
         "Listens automatically. Pictures work too.",
         (("Do you want to hear a story? You get to pick!", "happy"),
          ("Monster trucks, princesses, dinosaurs, outer space, animals, or superheroes?",
           "look_around"))),
    Step("chapter1", "Story · Part 1", "Before surgery",
         "About 1 min. Ends at the nap.",
         (("{picked}", "celebrate"),
          ("Once upon a time, there was {hero}.", "happy"),
          ("{short} loved {fun}.", "bounce"),
          ("One day, {short} needed a little fix, so they went to {place}.", "tilt"),
          ("First, a friendly helper gave {short} a special bracelet with their name on it. "
           "Just like the one on your wrist!", "nod"),
          ("Then {short} put on comfy pajamas called a gown.", "wiggle"),
          ("The doctors wore funny hats and masks, so all {short} could see were their eyes. "
           "Peekaboo!", "peekaboo"),
          ("Then came the most important part. A doctor held up a special sleepy mask. "
           "The air in it smelled a little funny, kind of like a balloon.", "think"),
          ("{short} took big, slow breaths. In, and out. In, and out.", "breathe"),
          ("And {short} got sleepier, and sleepier, and had a long, cozy nap.", "sleepy"),
          ("Hmm. What happens when {short} wakes up? That's chapter two!", "think")),
         needs_theme=True),
    Step("breathing", "Breathing", "Before surgery",
         "Breathe along.",
         (("Let's practice super breaths together, just like {short}.", "happy"),
          ("Smell the flower.", "inhale"),
          ("Now blow out the birthday candles.", "exhale"),
          ("Smell the flower.", "inhale"),
          ("Blow out the candles.", "exhale"),
          ("One more. Smell the flower.", "inhale"),
          ("And blow them all out.", "exhale"),
          ("Wow, {kid}, you are a super breather!", "celebrate")),
         needs_theme=True),
    Step("mask", "Mask practice", "Before surgery",
         "Optional. Child holds the mask.",
         (("Want to try a practice mask, like {short}'s sleepy mask?", "tilt"),
          ("Hold it on your face like a superhero. Now big breath in.", "inhale"),
          ("And out.", "exhale"),
          ("Breathe in.", "inhale"),
          ("And out. You did it!", "celebrate")),
         needs_theme=True),
    Step("promise", "Goodbye", "Before surgery",
         "At the OR doors.",
         (("{kid}, soon it's time for your nap, just like {short}.", "tilt"),
          ("I'll be right here when you wake up, and I'll tell you what happened to {short}.",
           "nod"),
          ("That's a promise.", "nod"),
          ("See you soon, {kid}!", "wave")),
         needs_theme=True),
    Step("chapter2", "Story · Part 2", "After surgery",
         "Once awake and calm. Ends quiet mode.",
         (("Hi {kid}. It's me, {robot}. You woke up! I told you I'd be here.", "happy"),
          ("Remember {short}? Here's what happened next.", "tilt"),
          ("{short} woke up in a cozy room. Everything felt a little sleepy and wobbly, "
           "and that was okay.", "sleepy_wake"),
          ("A kind nurse was right there. {short} said, I feel a little sore, "
           "and the nurse helped. You can always tell your nurse how you feel, too.", "nod"),
          ("And guess what? The fix worked! Soon {short} was back to {fun}.", "bounce"),
          ("And you know who else was super brave today? You, {kid}!", "celebrate"),
          ("You earned the brave badge. The end!", "wave")),
         needs_theme=True),
]

STEPS_BY_KEY = {s.key: s for s in STEPS}

# Short lines the nurse can trigger any time the robot is not already talking.
# Lines the automatic onboarding uses when it needs to ask again or move on.
FLOW_LINES: dict[str, tuple[str, str]] = {
    "again_name": ("Hmm, I didn't catch that. What nickname should I have?", "tilt"),
    "no_name": ("That's okay! You can just call me Dr. Juni.", "nod"),
    "again_story": ("Which story do you want? Trucks, princesses, dinosaurs, space, animals, "
                    "or superheroes?", "tilt"),
    "tap_story": ("You can tap a picture on the screen to pick!", "look_around"),
}

REACTIONS: dict[str, tuple[str, str, str]] = {
    # key: (button label, text, motion)
    "great": ("You're doing great", "You're doing so great, {kid}.", "nod"),
    "okay": ("It's okay to be scared", "It's okay to feel scared. I'm right here with you.",
             "tilt"),
    "yes": ("Yes!", "Yes!", "nod"),
    "silly": ("Silly robot", "Boop beep boop! That's my silly robot dance.", "wiggle"),
    "breath": ("One big breath", "Let's take one big breath together. In.", "inhale"),
    "high5": ("Antenna high five", "Antenna high five!", "celebrate"),
    "quiet_nod": ("Nod (no talking)", "", "nod"),
}


def fill(text: str, kid: str, robot: str, theme: Theme | None) -> str:
    values = {"kid": kid or "friend", "robot": robot or ROBOT_NAME}
    if theme:
        values |= {"hero": theme.hero, "short": theme.short, "fun": theme.fun,
                   "place": theme.place, "picked": theme.picked}
    return text.format(**values)
