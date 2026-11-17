import Foundation

/// Mirrors `Director.state()` in companion/lullaby/director.py (decoded with snake_case keys).
struct PanelState: Decodable, Sendable, Equatable {
    var mode: String
    var robotError: String?
    var activity: String          // idle | talking | recovery
    var label: String
    var line: String
    var session: Session
    var steps: [Step]
    var themes: [Theme]
    var reactions: [Reaction]
    var parent: [ParentSlot]
    var parentPlayback: ParentPlayback?
    var history: [String]
    var voice: VoiceStatus
    var listening: String?        // "nickname" | "story" while the robot's mic is on
    var auto: String?             // "intro" while the automatic intro runs
    var heard: Heard?

    struct Heard: Decodable, Sendable, Equatable {
        var purpose: String
        var text: String
        var result: String?
    }

    struct Session: Decodable, Sendable, Equatable {
        var kid: String
        var age: String
        var robotName: String
        var theme: String
        var done: [String]
    }

    struct Step: Decodable, Sendable, Equatable, Identifiable {
        var key: String
        var label: String
        var phase: String
        var hint: String
        var needsTheme: Bool
        var lines: [String]
        var id: String { key }
    }

    struct Theme: Decodable, Sendable, Equatable, Identifiable {
        var key: String
        var label: String
        var emoji: String
        var id: String { key }
    }

    struct Reaction: Decodable, Sendable, Equatable, Identifiable {
        var key: String
        var label: String
        var id: String { key }
    }

    struct ParentSlot: Decodable, Sendable, Equatable, Identifiable {
        var slot: String
        var label: String
        var recorded: Bool
        var id: String { slot }
    }

    struct ParentPlayback: Decodable, Sendable, Equatable {
        var slot: String
        var state: String         // playing | paused
        var position: Double
        var duration: Double
    }

    struct VoiceStatus: Decodable, Sendable, Equatable {
        var engine: String
        var problem: String?
    }

    var isTalking: Bool { activity == "talking" }
    var isQuiet: Bool { activity == "recovery" }
    var isAuto: Bool { auto != nil }
    /// Something is running that a tap shouldn't interrupt (only Stop should).
    var isBusy: Bool { isTalking || isAuto || listening != nil }

    func canRun(_ step: Step) -> Bool {
        if step.needsTheme && session.theme.isEmpty { return false }
        if step.key == "got_name" && session.robotName.isEmpty { return false }
        return true
    }
}

/// Lines the robot uses to ask again or move on (FLOW_LINES in content.py).
struct FlowLine: Identifiable, Sendable {
    let key: String
    let label: String
    var id: String { key }

    let symbol: String

    static let all = [
        FlowLine(key: "again_name", label: "Ask nickname again", symbol: "arrow.counterclockwise"),
        FlowLine(key: "no_name", label: "No nickname, that's okay", symbol: "hand.thumbsup.fill"),
        FlowLine(key: "again_story", label: "Ask story again", symbol: "arrow.counterclockwise"),
        FlowLine(key: "tap_story", label: "Tap a picture", symbol: "hand.tap.fill"),
    ]

    /// The Mac labels a flow line "Dr. Juni: again name" while it is spoken.
    static func key(forServerLabel label: String) -> String? {
        guard label.hasPrefix("Dr. Juni: ") else { return nil }
        let key = label.dropFirst("Dr. Juni: ".count).replacingOccurrences(of: " ", with: "_")
        return all.contains { $0.key == key } ? key : nil
    }
}

extension PanelState.Reaction {
    /// A picture for each quick line (REACTIONS in content.py).
    var symbol: String {
        switch key {
        case "great": "star.fill"
        case "okay": "heart.fill"
        case "yes": "checkmark"
        case "silly": "face.smiling.inverse"
        case "breath": "wind"
        case "high5": "hand.raised.fill"
        case "quiet_nod": "arrow.up.and.down"
        default: "text.bubble.fill"
        }
    }
}

extension PanelState.ParentSlot {
    /// "Message 1 (e.g. 'I'm right outside')" becomes a title and an example.
    var title: String { label.components(separatedBy: " (").first ?? label }
    var example: String? {
        guard let open = label.range(of: "(e.g. ") else { return nil }
        return String(label[open.upperBound...]).trimmingCharacters(in: CharacterSet(charactersIn: ")'"))
    }
}
