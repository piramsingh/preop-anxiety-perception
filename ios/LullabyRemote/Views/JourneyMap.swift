import SwiftUI

/// The visit as a path of stickers: earned, now, next and still to come.
struct JourneyMap: View {
    @Environment(Remote.self) private var remote
    let state: PanelState
    let journey: Journey
    let open: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(journey.stops.enumerated()), id: \.element.id) { i, stop in
                let startsPhase = i == 0 || journey.stops[i - 1].phase != stop.phase
                let endsPhase = i == journey.stops.count - 1 || journey.stops[i + 1].phase != stop.phase
                if startsPhase {
                    SectionHeader(stop.phase, symbol: i == 0 ? nil : "moon.stars.fill")
                        .padding(.top, i == 0 ? 0 : 20)
                        .padding(.bottom, 14)
                }
                StopRow(state: state, stop: stop, isLast: endsPhase,
                        open: { open(stop.id) },
                        play: { remote.runStep($0) })
            }
        }
    }
}

extension Journey.Stop {
    /// What a tap on play runs: the first part not done yet, or the first part again.
    func stepToPlay(done: [String]) -> PanelState.Step? {
        steps.first { !done.contains($0.key) } ?? steps.first
    }
}

private struct StopRow: View {
    @Environment(\.palette) private var palette
    let state: PanelState
    let stop: Journey.Stop
    let isLast: Bool
    let open: () -> Void
    let play: (String) -> Void

    private var live: Bool { stop.status == .running || stop.status == .listening }
    private var featured: Bool { live || stop.status == .next }

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(spacing: 0) {
                StickerBadge(symbol: stop.milestone.symbol, look: look, size: 52)
                if !isLast {
                    connector.frame(maxHeight: .infinity)
                }
            }
            .frame(width: 52)
            .padding(.top, featured ? 10 : 0)

            HStack(spacing: 8) {
                Button(action: open) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(stop.milestone.title)
                            .font(.headline)
                            .foregroundStyle(.primary)
                        statusLabel
                        if let hint {
                            Text(hint)
                                .font(.subheadline)
                                .foregroundStyle(Color.soft)
                                .multilineTextAlignment(.leading)
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
                    .contentShape(.rect)
                }
                .buttonStyle(PressableStyle())
                .accessibilityHint("Shows the script")

                trailing
            }
            .padding(featured ? 12 : 0)
            .padding(.leading, featured ? 4 : 0)
            .background {
                if featured {
                    RoundedRectangle(cornerRadius: 22).fill(Color.card)
                    RoundedRectangle(cornerRadius: 22).strokeBorder(palette.ink.opacity(live ? 1 : 0.45), lineWidth: 2)
                }
            }
            .padding(.bottom, isLast ? 0 : (featured ? 18 : 26))
        }
        .fixedSize(horizontal: false, vertical: true)
        .animation(.calm, value: stop.status)
    }

    private var look: StickerBadge.Look {
        switch stop.status {
        case .earned: .earned
        case .running, .listening, .next: .current
        case .later: .waiting
        }
    }

    @ViewBuilder private var connector: some View {
        if stop.earned {
            Capsule().fill(palette.ink).frame(width: 4).padding(.vertical, 4)
        } else {
            Line()
                .stroke(Color.soft, style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [2, 7]))
                .frame(width: 4)
                .padding(.vertical, 6)
        }
    }

    @ViewBuilder private var statusLabel: some View {
        switch stop.status {
        case .earned:
            Label("Sticker earned", systemImage: "checkmark.seal.fill")
                .font(.subheadline).foregroundStyle(Color.soft)
        case .running:
            Label("Now", systemImage: "waveform")
                .font(.subheadline.weight(.semibold)).foregroundStyle(palette.ink)
        case .listening:
            Label("Listening", systemImage: "mic.fill")
                .font(.subheadline.weight(.semibold)).foregroundStyle(palette.ink)
        case .next:
            Label("Next", systemImage: "arrow.forward.circle.fill")
                .font(.subheadline.weight(.semibold)).foregroundStyle(palette.ink)
        case .later:
            EmptyView()
        }
    }

    /// Why it can't run yet, or what the grown-up should do. Earned stops stay quiet.
    private var hint: String? {
        guard !stop.earned, stop.status != .listening, let step = stop.stepToPlay(done: state.session.done) else { return nil }
        if stop.status == .later, let blocked = state.blockedReason(step) { return blocked }
        return step.hint
    }

    @ViewBuilder private var trailing: some View {
        if stop.status == .running {
            LiveSymbol(name: "waveform")
                .font(.title3).foregroundStyle(palette.ink).frame(width: 48, height: 48)
                .accessibilityLabel("Talking")
        } else if stop.status == .listening {
            LiveSymbol(name: "mic.fill", pulse: true)
                .font(.title3).foregroundStyle(palette.ink).frame(width: 48, height: 48)
                .accessibilityLabel("Listening")
        } else if let step = stop.stepToPlay(done: state.session.done), state.canRun(step), !state.isBusy {
            Button { play(step.key) } label: {
                if stop.earned {
                    // Playing a finished part again is rare: keep it quiet, still a full target.
                    Image(systemName: "arrow.counterclockwise")
                        .font(.body.weight(.medium))
                        .foregroundStyle(Color.soft)
                        .frame(width: 48, height: 48)
                        .contentShape(.rect)
                } else {
                    PlayCircle(prominent: stop.status == .next)
                }
            }
            .buttonStyle(PressableStyle())
            .accessibilityLabel(stop.earned ? "Play \(step.label) again" : "Play \(step.label)")
        }
    }
}

private struct Line: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.midX, y: rect.minY))
            p.addLine(to: CGPoint(x: rect.midX, y: rect.maxY))
        }
    }
}

/// One milestone up close: its sticker, each part with its script, and listening again.
struct MilestoneSheet: View {
    @Environment(Remote.self) private var remote
    @Environment(\.dismiss) private var dismiss
    @Environment(\.palette) private var palette
    let stopID: String

    var body: some View {
        NavigationStack {
            ScrollView {
                if let state = remote.state, let stop = Journey(state).stop(stopID) {
                    VStack(alignment: .leading, spacing: 20) {
                        HStack(spacing: 16) {
                            StickerBadge(symbol: stop.milestone.symbol,
                                         look: stop.earned ? .earned : .waiting, size: 76)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(stop.milestone.title).font(.largeTitle.weight(.bold))
                                Label(stop.earned ? "Sticker earned" : stop.milestone.optional ? "Optional" : stop.phase,
                                      systemImage: stop.earned ? "checkmark.seal.fill"
                                        : stop.milestone.optional ? "circle.dashed" : "calendar")
                                    .font(.body)
                                    .foregroundStyle(Color.soft)
                            }
                        }
                        if stop.id == "story" {
                            StoryPicker(state: state)
                        }
                        ForEach(stop.steps) { step in
                            StepCard(state: state, step: step)
                        }
                        if let purpose = stop.id == "nickname" ? "nickname" : stop.id == "story" ? "story" : nil {
                            ListenAgainButton(purpose: purpose, state: state)
                        }
                    }
                    .padding(20)
                }
            }
            .background(Color.page)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .safeAreaInset(edge: .bottom) { SheetStopBar() }
        }
        .presentationDetents([.large])
    }
}

private struct StepCard: View {
    @Environment(Remote.self) private var remote
    @Environment(\.palette) private var palette
    let state: PanelState
    let step: PanelState.Step

    var body: some View {
        let done = state.session.done.contains(step.key)
        let blocked = state.blockedReason(step)
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(step.label).font(.title3.weight(.semibold))
                    if let blocked {
                        Label(blocked, systemImage: "info.circle").font(.subheadline).foregroundStyle(Color.soft)
                    } else if done {
                        Label("Done", systemImage: "checkmark.circle.fill").font(.subheadline).foregroundStyle(Color.soft)
                    } else {
                        Text(step.hint).font(.subheadline).foregroundStyle(Color.soft)
                    }
                }
                Spacer(minLength: 0)
                if state.isRunning(step) {
                    LiveSymbol(name: "waveform")
                        .font(.title3).foregroundStyle(palette.ink).frame(width: 48, height: 48)
                        .accessibilityLabel("Talking")
                } else {
                    Button { remote.runStep(step.key) } label: {
                        PlayCircle(prominent: !done, symbol: done ? "arrow.counterclockwise" : "play.fill")
                    }
                    .buttonStyle(PressableStyle())
                    .disabled(blocked != nil || state.isBusy)
                    .accessibilityLabel(done ? "Play \(step.label) again" : "Play \(step.label)")
                }
            }
            if !step.lines.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Array(step.lines.enumerated()), id: \.offset) { _, line in
                        let speaking = state.isRunning(step) && state.line == line
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Image(systemName: speaking ? "waveform" : "quote.opening")
                                .font(.subheadline)
                                .foregroundStyle(speaking ? AnyShapeStyle(palette.ink) : AnyShapeStyle(.tertiary))
                                .frame(width: 20)
                            Text(line)
                                .font(.body)
                                .fontWeight(speaking ? .semibold : .regular)
                                .foregroundStyle(speaking ? Color.primary : Color.soft)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(Color.card, in: .rect(cornerRadius: 22))
    }
}
