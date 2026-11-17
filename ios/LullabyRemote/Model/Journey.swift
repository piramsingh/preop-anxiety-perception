import SwiftUI

/// One stop on the child's journey. Finishing it earns its sticker.
struct Milestone: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    var symbol: String
    let stepKeys: [String]
    var optional = false

    /// The journey, in order. Step keys match STEPS in companion/lullaby/content.py.
    static let known: [Milestone] = [
        Milestone(id: "hello", title: "Hello", symbol: "hand.wave.fill", stepKeys: ["greet"]),
        Milestone(id: "nickname", title: "Nickname", symbol: "tag.fill", stepKeys: ["ask_name", "got_name"]),
        Milestone(id: "story", title: "Story", symbol: "book.fill", stepKeys: ["ask_story"]),
        Milestone(id: "part1", title: "Part 1", symbol: "book.pages.fill", stepKeys: ["chapter1"]),
        Milestone(id: "breathing", title: "Breathing", symbol: "wind", stepKeys: ["breathing"]),
        Milestone(id: "mask", title: "Mask", symbol: "facemask.fill", stepKeys: ["mask"], optional: true),
        Milestone(id: "goodbye", title: "Goodbye", symbol: "heart.fill", stepKeys: ["promise"]),
        Milestone(id: "part2", title: "Part 2", symbol: "sun.max.fill", stepKeys: ["chapter2"]),
    ]

    /// Flow lines ("ask again") belong to the milestone they help along.
    static let flowOwner = ["again_name": "nickname", "no_name": "nickname",
                            "again_story": "story", "tap_story": "story"]
}

/// The journey as it stands right now, worked out from the Mac's state.
struct Journey: Equatable {
    enum Status: Equatable { case earned, running, listening, next, later }

    struct Stop: Identifiable, Equatable {
        var milestone: Milestone
        var steps: [PanelState.Step]
        var status: Status
        var phase: String
        var id: String { milestone.id }
        var earned: Bool { status == .earned }
    }

    var stops: [Stop] = []
    /// The step the presenter most likely wants next.
    var nextStep: PanelState.Step?
    /// The robot says "You earned the brave badge" at the end of the last part.
    var braveEarned = false
    /// The robot asked for a story and none is picked yet: show the pictures.
    var wantsStoryPick = false

    var earnedIDs: [String] { stops.filter(\.earned).map(\.id) }
    var earnedCount: Int { earnedIDs.count }

    func stop(_ id: String) -> Stop? { stops.first { $0.id == id } }

    init(_ s: PanelState) {
        let done = Set(s.session.done)
        var milestones = Milestone.known
        // A step this app doesn't know yet still gets a place on the path.
        let covered = Set(milestones.flatMap(\.stepKeys))
        for step in s.steps where !covered.contains(step.key) {
            milestones.append(Milestone(id: step.key, title: step.label, symbol: "star.fill", stepKeys: [step.key]))
        }

        func isEarned(_ m: Milestone) -> Bool {
            switch m.id {
            case "nickname":
                done.contains("got_name") || (done.contains("ask_name") && done.contains("ask_story"))
            case "story":
                (done.contains("ask_story") && !s.session.theme.isEmpty) || done.contains("chapter1")
            default:
                m.stepKeys.allSatisfy(done.contains)
            }
        }

        let runningID: String? = {
            guard s.isTalking else { return nil }
            if let step = s.steps.first(where: { $0.label == s.label }) {
                return milestones.first { $0.stepKeys.contains(step.key) }?.id
            }
            if let flow = FlowLine.key(forServerLabel: s.label) { return Milestone.flowOwner[flow] }
            return nil
        }()
        let listeningID: String? = s.listening.map { $0 == "nickname" ? "nickname" : "story" }

        let earned = milestones.map(isEarned)
        let lastEarned = earned.lastIndex(of: true) ?? -1
        // Next is the first stop after the furthest sticker, so a skipped optional stop
        // (mask practice) never holds the journey back.
        var nextIndex = earned.indices.first { $0 > lastEarned }
        if lastEarned == -1 { nextIndex = earned.isEmpty ? nil : 0 }

        for (i, var m) in milestones.enumerated() {
            let steps = m.stepKeys.compactMap { key in s.steps.first { $0.key == key } }
            guard !steps.isEmpty else { continue }
            if m.id == "story", let symbol = Palette.symbol(forTheme: s.session.theme) { m.symbol = symbol }
            let status: Status =
                if listeningID == m.id { .listening }
                else if runningID == m.id { .running }
                else if earned[i] { .earned }
                else if i == nextIndex && !s.isBusy { .next }
                else { .later }
            stops.append(Stop(milestone: m, steps: steps, status: status, phase: steps[0].phase))
        }

        if let i = nextIndex, i < milestones.count {
            let keys = milestones[i].stepKeys
            nextStep = s.steps.first { keys.contains($0.key) && !done.contains($0.key) }
        }
        braveEarned = done.contains("chapter2")
        wantsStoryPick = s.session.theme.isEmpty && !done.contains("chapter1")
            && (done.contains("ask_story") || s.listening == "story")
    }
}

extension PanelState {
    func blockedReason(_ step: Step) -> String? {
        if step.needsTheme && session.theme.isEmpty { return "Pick a story first" }
        if step.key == "got_name" && session.robotName.isEmpty { return "Add a nickname first" }
        return nil
    }

    func isRunning(_ step: Step) -> Bool { isTalking && label == step.label }

    /// The label to show while talking: flow lines arrive as "Dr. Juni: again name".
    var displayLabel: String {
        if let key = FlowLine.key(forServerLabel: label),
           let line = FlowLine.all.first(where: { $0.key == key }) { return line.label }
        return label
    }

    var themeInfo: Theme? { themes.first { $0.key == session.theme } }
}

/// The one accent in use, tinted to the chosen story.
struct Palette: Equatable {
    /// Solid fills that carry white text (4.5:1 or better in both appearances).
    let fill: Color
    /// Icons and tinted text on the app's own backgrounds; lighter in dark mode.
    let ink: Color

    private init(_ l: (Double, Double, Double), dark d: (Double, Double, Double)) {
        fill = Color(red: l.0, green: l.1, blue: l.2)
        ink = Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(red: d.0, green: d.1, blue: d.2, alpha: 1)
                : UIColor(red: l.0, green: l.1, blue: l.2, alpha: 1)
        })
    }

    static let standard = Palette((0.40, 0.34, 0.84), dark: (0.70, 0.66, 1.00))
    static let princess = Palette((0.72, 0.24, 0.56), dark: (0.97, 0.62, 0.85))
    static let dinosaurs = Palette((0.10, 0.50, 0.32), dark: (0.47, 0.86, 0.64))
    static let heroes = Palette((0.11, 0.42, 0.86), dark: (0.55, 0.76, 1.00))

    static func forTheme(_ key: String?) -> Palette {
        switch key {
        case "princess": .princess
        case "dinosaurs": .dinosaurs
        case "heroes": .heroes
        default: .standard
        }
    }

    static func symbol(forTheme key: String) -> String? {
        switch key {
        case "princess": "crown.fill"
        case "dinosaurs": "lizard.fill"
        case "heroes": "bolt.shield.fill"
        default: nil
        }
    }
}

extension EnvironmentValues {
    @Entry var palette = Palette.standard
}
