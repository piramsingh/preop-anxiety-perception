import SwiftUI

/// The live status: what Dr. Juni is doing right now, the line being spoken, what the robot's
/// mic heard, and the stickers so far.
struct NowCard: View {
    @Environment(\.palette) private var palette
    let state: PanelState
    let journey: Journey
    let openStickers: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StatusRow(state: state)
            HStack(alignment: .top, spacing: 14) {
                icon
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(state.isBusy ? Color.white : palette.ink)
                    .frame(width: 56, height: 56)
                    .background(state.isBusy ? AnyShapeStyle(palette.fill) : AnyShapeStyle(palette.ink.opacity(0.14)),
                                in: .circle)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.title2.weight(.bold))
                        .contentTransition(.opacity)
                    // Space for two lines is always kept, so the page never jumps (and moves
                    // buttons under a finger) when Dr. Juni starts or stops talking.
                    Text(detail.isEmpty ? " " : detail)
                        .font(.body)
                        .foregroundStyle(Color.soft)
                        .lineLimit(3)
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .topLeading)
                        .contentTransition(.opacity)
                }
            }
            if state.isAuto {
                Label {
                    Text("Intro is running by itself. Stop ends it.")
                } icon: {
                    Image(systemName: "sparkles").foregroundStyle(palette.ink)
                }
                .font(.subheadline.weight(.medium))
                .transition(.opacity)
            }
            if let pb = state.parentPlayback {
                ParentProgress(playback: pb)
            }
            if let heard = state.heard, state.listening == nil {
                HeardRow(heard: heard, themes: state.themes)
            }
            Divider()
            StickerStrip(journey: journey, kid: state.session.kid, open: openStickers)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background {
            ZStack {
                Color.card
                LinearGradient(colors: [palette.ink.opacity(0.20), palette.ink.opacity(0.03)],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
            }
            .clipShape(.rect(cornerRadius: 28))
        }
        .animation(.calm, value: state.line)
        .animation(.calm, value: state.activity)
        .animation(.calm, value: state.listening)
        .animation(.calm, value: state.auto)
        .animation(.calm, value: state.heard)
    }

    private var title: String {
        if let purpose = state.listening {
            return purpose == "nickname" ? "Listening for a nickname" : "Listening for a story"
        }
        switch state.activity {
        case "talking": return state.label.isEmpty ? "Talking" : state.displayLabel
        case "recovery": return state.parentPlayback != nil ? "Parent message" : "Quiet mode"
        default: break
        }
        if state.parentPlayback != nil { return "Parent message" }
        if state.isAuto { return journey.wantsStoryPick ? "Waiting for a story" : "Getting ready" }
        if journey.braveEarned { return "Journey complete" }
        if state.session.kid.isEmpty && journey.earnedCount == 0 { return "Ready when you are" }
        if journey.wantsStoryPick { return "Time to pick a story" }
        if let next = journey.nextStep { return "Next: \(next.label)" }
        return "Ready"
    }

    private var detail: String {
        if !state.line.isEmpty { return "“\(state.line)”" }
        if state.listening != nil { return "The robot's mic is on. It stops when the child goes quiet." }
        if state.isTalking { return "" }
        if state.parentPlayback != nil { return "Playing on the robot." }
        if state.isQuiet { return "Dr. Juni is resting. Stop ends quiet mode." }
        if journey.braveEarned { return "Every part of the story is told." }
        if state.session.kid.isEmpty && journey.earnedCount == 0 {
            return "Start intro runs by itself. Add the child's name first if you have it."
        }
        if journey.wantsStoryPick { return "The child can say it or tap a picture." }
        if let next = journey.nextStep { return state.blockedReason(next) ?? next.hint }
        return ""
    }

    @ViewBuilder private var icon: some View {
        if state.listening != nil {
            LiveSymbol(name: "mic.fill", pulse: true)
        } else if state.isTalking {
            LiveSymbol(name: "waveform")
        } else if state.parentPlayback != nil {
            Image(systemName: "person.2.wave.2.fill")
        } else if state.isQuiet {
            Image(systemName: "moon.zzz.fill")
        } else if state.isAuto {
            LiveSymbol(name: "sparkles")
        } else if journey.braveEarned {
            Image(systemName: "medal.star.fill")
        } else {
            Image(systemName: journey.stops.first { $0.status == .next }?.milestone.symbol ?? "face.smiling")
        }
    }
}

/// Robot and voice status: always an icon and a word, never a colour alone.
private struct StatusRow: View {
    let state: PanelState

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 16) { robot; voice; Spacer(minLength: 0) }
            VStack(alignment: .leading, spacing: 6) { robot; voice }
        }
        .font(.subheadline.weight(.medium))
        .lineLimit(1)
    }

    @ViewBuilder private var robot: some View {
        if let err = state.robotError {
            chip(err, "exclamationmark.triangle.fill", .orange)
        } else if state.mode == "robot" {
            chip("Robot connected", "checkmark.circle.fill", .green)
        } else {
            chip("Preview, no robot", "desktopcomputer", .secondary)
        }
    }

    @ViewBuilder private var voice: some View {
        if let problem = state.voice.problem {
            chip(problem, "exclamationmark.triangle.fill", .orange)
        } else {
            chip(state.voice.engine, "speaker.wave.2.fill", .secondary)
        }
    }

    private func chip(_ text: String, _ symbol: String, _ color: Color) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).foregroundStyle(color)
            Text(text)
        }
        .accessibilityElement(children: .combine)
    }
}

/// What the robot's mic heard, and what it filled in.
private struct HeardRow: View {
    let heard: PanelState.Heard
    let themes: [PanelState.Theme]

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: heard.result == nil ? "ear.trianglebadge.exclamationmark" : "ear")
                .foregroundStyle(heard.result == nil ? Color.orange : Color.green)
            VStack(alignment: .leading, spacing: 2) {
                Text(summary).font(.body.weight(.semibold))
                if !heard.text.isEmpty {
                    Text("Heard “\(heard.text)”").font(.subheadline).foregroundStyle(Color.soft)
                }
            }
        }
        .transition(.opacity)
        .accessibilityElement(children: .combine)
    }

    private var summary: String {
        if let result = heard.result {
            if heard.purpose == "nickname" { return "Nickname: \(result)" }
            let label = themes.first { $0.key == result }?.label
            return label.map { "Story picked: \($0)" } ?? "Story picked"
        }
        return heard.text.isEmpty ? "Didn't hear an answer" : "Didn't catch a \(heard.purpose)"
    }
}

struct ParentProgress: View {
    let playback: PanelState.ParentPlayback

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ProgressView(value: min(playback.position, playback.duration), total: max(playback.duration, 0.1))
            Label("Message \(playback.slot) \(playback.state == "paused" ? "paused" : "playing")",
                  systemImage: playback.state == "paused" ? "pause.fill" : "play.fill")
                .font(.subheadline)
                .foregroundStyle(Color.soft)
        }
    }
}

/// Shown when the Mac can't be reached at all.
struct OfflineCard: View {
    @Environment(Remote.self) private var remote
    let openSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                Image(systemName: connecting ? "antenna.radiowaves.left.and.right" : "wifi.slash")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(Color.soft)
                    .frame(width: 56, height: 56)
                    .background(.quaternary, in: .circle)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(connecting ? "Looking for the Mac" : "Can't reach the Mac")
                        .font(.title2.weight(.bold))
                    if case .offline(let why) = remote.link {
                        Text(why).font(.body).foregroundStyle(Color.soft)
                    }
                }
            }
            Text("On the Mac, start Lullaby so this device can reach it:")
                .font(.body)
                .foregroundStyle(Color.soft)
            Text("uv run lullaby --lan")
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.quaternary, in: .rect(cornerRadius: 12))
            Text("Both need to be on the same Wi-Fi.")
                .font(.body)
                .foregroundStyle(Color.soft)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(Color.card, in: .rect(cornerRadius: 28))
    }

    private var connecting: Bool { remote.link == .connecting }
}
