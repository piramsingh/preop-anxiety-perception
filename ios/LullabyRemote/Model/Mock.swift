#if DEBUG
import Foundation

/// Canned states for screenshots and layout work: `-LullabyMock talking` and friends.
/// Nothing here reaches the Mac or the robot.
enum Mock {
    /// Keeps the sticker celebration on screen (for screenshots).
    static let holdsCelebration = UserDefaults.standard.string(forKey: "LullabyMock") != nil

    static func earnsAfterLaunch(_ name: String) -> String? {
        switch name {
        case "celebrate": "breathing"
        case "brave": "chapter2"
        default: nil
        }
    }

    static func state(_ name: String) -> PanelState {
        var s = base
        let intro = ["greet", "ask_name", "got_name", "ask_story", "chapter1", "breathing"]
        func session(done: [String], robot: String = "Sparkle", theme: String = "dinosaurs") {
            s.session = .init(kid: "Maya", age: "", robotName: robot, theme: theme, done: done)
        }
        switch name {
        case "fresh":
            break
        case "ready":
            session(done: [], robot: "", theme: "")
        case "talking":
            session(done: Array(intro.prefix(4)))
            s.activity = "talking"; s.label = "Story · Part 1"; s.auto = "intro"
            s.line = "Once upon a time, there was Tiny Rex the dinosaur."
        case "listening":
            session(done: ["greet", "ask_name"], robot: "", theme: "")
            s.listening = "nickname"; s.auto = "intro"
        case "intro":
            session(done: ["greet"], robot: "", theme: "")
            s.activity = "talking"; s.label = "Nickname"; s.auto = "intro"
            s.line = "Can you give me one? What nickname should I have?"
        case "pick":
            session(done: Array(intro.prefix(4)), theme: "")
            s.auto = "intro"
            s.heard = .init(purpose: "story", text: "um the one with", result: nil)
        case "heard":
            session(done: Array(intro.prefix(3)), theme: "")
            s.heard = .init(purpose: "nickname", text: "sparkle", result: "Sparkle")
        case "midway", "princess", "heroes":
            session(done: intro, theme: name == "midway" ? "dinosaurs" : name)
        case "celebrate":
            session(done: Array(intro.prefix(5)))
        case "parent":
            session(done: intro + ["promise"])
            s.activity = "recovery"
            s.parentPlayback = .init(slot: "1", state: "playing", position: 4.2, duration: 9)
        case "brave":
            session(done: intro + ["mask", "promise"])
        case "done":
            session(done: intro + ["mask", "promise", "chapter2"])
        default:
            session(done: intro)
        }
        if s.session.theme.isEmpty {
            for i in s.steps.indices where s.steps[i].needsTheme { s.steps[i].lines = [] }
        }
        return s
    }

    private static func step(_ key: String, _ label: String, _ hint: String, _ lines: [String],
                             phase: String = "Before surgery", theme: Bool = false) -> PanelState.Step {
        .init(key: key, label: label, phase: phase, hint: hint, needsTheme: theme, lines: lines)
    }

    private static let base = PanelState(
        mode: "robot", robotError: nil, activity: "idle", label: "", line: "",
        session: .init(kid: "", age: "", robotName: "", theme: "", done: []),
        steps: [
            step("greet", "Hello", "Child facing the robot.",
                 ["Hi Maya! I'm Dr. Juni, and I'm so happy to meet you.",
                  "I'm a little robot, and I'm going to keep you company today."]),
            step("ask_name", "Nickname", "Listens automatically.",
                 ["Dr. Juni is my grown-up name. But my best friends give me nicknames!",
                  "Can you give me one? What nickname should I have?"]),
            step("got_name", "Say nickname", "Check spelling.",
                 ["Sparkle! I love it!", "That's my name now. Thank you, Maya."]),
            step("ask_story", "Pick a story", "Listens automatically. Pictures work too.",
                 ["Do you want to hear a story? You get to pick!",
                  "Princesses, dinosaurs, or superheroes?"]),
            step("chapter1", "Story · Part 1", "About 1 min. Ends at the nap.",
                 ["Dinosaurs! Roar! Great choice.",
                  "Once upon a time, there was Tiny Rex the dinosaur.",
                  "Tiny Rex loved stomping through the jungle."], theme: true),
            step("breathing", "Breathing", "Breathe along.",
                 ["Let's practice super breaths together, just like Tiny Rex.",
                  "Smell the flower.", "Now blow out the birthday candles."], theme: true),
            step("mask", "Mask practice", "Optional. Child holds the mask.",
                 ["Want to try a practice mask, like Tiny Rex's sleepy mask?",
                  "Hold it on your face like a superhero. Now big breath in.", "And out."], theme: true),
            step("promise", "Goodbye", "At the OR doors.",
                 ["Maya, soon it's time for your nap, just like Tiny Rex.",
                  "I'll be right here when you wake up, and I'll tell you what happened to Tiny Rex.",
                  "That's a promise.", "See you soon, Maya!"], theme: true),
            step("chapter2", "Story · Part 2", "Once awake and calm. Ends quiet mode.",
                 ["Hi Maya. It's me, Sparkle. You woke up! I told you I'd be here.",
                  "Remember Tiny Rex? Here's what happened next."],
                 phase: "After surgery", theme: true),
        ],
        themes: [.init(key: "princess", label: "Princesses", emoji: "👑"),
                 .init(key: "dinosaurs", label: "Dinosaurs", emoji: "🦖"),
                 .init(key: "heroes", label: "Superheroes", emoji: "🦸")],
        reactions: [.init(key: "great", label: "You're doing great"),
                    .init(key: "okay", label: "It's okay to be scared"),
                    .init(key: "yes", label: "Yes!"),
                    .init(key: "silly", label: "Silly robot"),
                    .init(key: "breath", label: "One big breath"),
                    .init(key: "high5", label: "Antenna high five"),
                    .init(key: "quiet_nod", label: "Nod (no talking)")],
        parent: [.init(slot: "1", label: "Message 1 (e.g. 'I'm right outside')", recorded: true),
                 .init(slot: "2", label: "Message 2 (e.g. 'You were so brave')", recorded: true),
                 .init(slot: "3", label: "Message 3 (e.g. 'See you really soon')", recorded: false)],
        parentPlayback: nil, history: [],
        voice: .init(engine: "ElevenLabs", problem: nil),
        listening: nil, auto: nil, heard: nil)
}
#endif
