import SwiftUI

/// Type a line for Dr. Juni to say.
struct TypeLineField: View {
    @Environment(Remote.self) private var remote
    @Environment(\.palette) private var palette
    var focusOnAppear = false
    var sent: () -> Void = {}
    @State private var text = ""
    @FocusState private var focused: Bool

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField("What should Dr. Juni say?", text: $text, axis: .vertical)
                    .font(.body)
                    .lineLimit(1...5)
                    .focused($focused)
                    .padding(.vertical, 13)
                Button {
                    remote.say(trimmed)
                    text = ""
                    sent()
                } label: {
                    PlayCircle(prominent: true, symbol: "arrow.up")
                }
                .buttonStyle(PressableStyle())
                .disabled(trimmed.isEmpty || remote.state?.isBusy != false)
                .accessibilityLabel("Say it")
            }
            .padding(.leading, 18)
            .padding(.trailing, 6)
            .padding(.vertical, 6)
            .background(Color.card, in: .rect(cornerRadius: 30))
            Text("A new line takes a moment the first time, while the robot's voice is made.")
                .font(.subheadline)
                .foregroundStyle(Color.soft)
                .padding(.horizontal, 4)
        }
        .onAppear { if focusOnAppear { focused = true } }
    }
}

/// One-tap lines for the moment: encouragement, ask-again lines, and parent messages.
struct LinesPanel: View {
    @Environment(Remote.self) private var remote
    @Environment(\.palette) private var palette
    let state: PanelState
    var acted: () -> Void = {}

    private let columns = [GridItem(.adaptive(minimum: 150), spacing: 10)]

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Quick lines")
                LazyVGrid(columns: columns, spacing: 10) {
                    ForEach(state.reactions) { r in
                        Button {
                            remote.react(r.key)
                            acted()
                        } label: {
                            HStack(spacing: 10) {
                                Image(systemName: r.symbol)
                                    .foregroundStyle(palette.ink)
                                    .frame(width: 24)
                                Text(r.label)
                                    .font(.body.weight(.medium))
                                    .foregroundStyle(.primary)
                                    .multilineTextAlignment(.leading)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .frame(maxWidth: .infinity, minHeight: 64)
                            .background(Color.card, in: .rect(cornerRadius: 20))
                        }
                        .buttonStyle(PressableStyle())
                        .disabled(state.isBusy)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Ask again")
                VStack(spacing: 0) {
                    ForEach(Array(FlowLine.all.enumerated()), id: \.element.id) { i, f in
                        if i > 0 { Divider().padding(.leading, 52) }
                        Button {
                            remote.flow(f.key)
                            acted()
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: f.symbol).foregroundStyle(palette.ink).frame(width: 24)
                                Text(f.label).font(.body).foregroundStyle(.primary)
                                Spacer(minLength: 0)
                                if Remote.asks[f.key] != nil {
                                    Image(systemName: "mic").foregroundStyle(Color.soft)
                                        .accessibilityLabel("Listens after")
                                }
                            }
                            .padding(.horizontal, 16)
                            .frame(minHeight: 56)
                            .contentShape(.rect)
                        }
                        .buttonStyle(PressableStyle())
                        .disabled(state.isBusy)
                    }
                }
                .background(Color.card, in: .rect(cornerRadius: 22))
            }

            ParentMessages(state: state)
        }
    }
}

struct ParentMessages: View {
    @Environment(Remote.self) private var remote
    let state: PanelState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader("Parent messages")
            VStack(spacing: 0) {
                ForEach(Array(state.parent.enumerated()), id: \.element.id) { i, p in
                    if i > 0 { Divider().padding(.leading, 16) }
                    row(p)
                }
            }
            .background(Color.card, in: .rect(cornerRadius: 22))
            Text("Record them in the panel on the Mac. They play on the robot.")
                .font(.subheadline)
                .foregroundStyle(Color.soft)
                .padding(.horizontal, 4)
        }
    }

    private func row(_ p: PanelState.ParentSlot) -> some View {
        let active = state.parentPlayback?.slot == p.slot ? state.parentPlayback : nil
        let playing = active?.state == "playing"
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(p.title).font(.body.weight(.medium))
                    if p.recorded {
                        if let example = p.example {
                            Text("For example “\(example)”").font(.subheadline).foregroundStyle(Color.soft)
                        }
                    } else {
                        Label("Not recorded", systemImage: "mic.slash")
                            .font(.subheadline).foregroundStyle(Color.soft)
                    }
                }
                Spacer(minLength: 0)
                if p.recorded {
                    Button {
                        playing ? remote.pauseParent() : remote.playParent(p.slot)
                    } label: {
                        PlayCircle(symbol: playing ? "pause.fill" : "play.fill")
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .buttonStyle(PressableStyle())
                    .disabled(state.isTalking)
                    .accessibilityLabel(playing ? "Pause \(p.title)" : "Play \(p.title)")
                }
            }
            if let active { ParentProgress(playback: active) }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .frame(minHeight: 68)
    }
}

/// Everything Dr. Juni can say off-script: a typed line, quick lines, ask-again lines and
/// the parent's messages.
struct SaySheet: View {
    @Environment(Remote.self) private var remote
    @Environment(\.dismiss) private var dismiss
    var focusOnAppear = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    TypeLineField(focusOnAppear: focusOnAppear) { dismiss() }
                    if let state = remote.state {
                        LinesPanel(state: state) { dismiss() }
                    }
                }
                .padding(20)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color.page)
            .navigationTitle("Say something")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
            .safeAreaInset(edge: .bottom) { SheetStopBar() }
        }
        .presentationDetents([.large])
    }
}

/// Where the Lullaby app is running, and the robot's link.
struct SettingsSheet: View {
    @Environment(Remote.self) private var remote
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://my-mac.local:8890", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .frame(minHeight: 32)
                    Button("Use the default address") { address = Remote.defaultServer }
                        .frame(minHeight: 32)
                } header: {
                    Text("Mac address")
                } footer: {
                    Text("On the Mac run `uv run lullaby --lan`. This device and the Mac must be on the same Wi-Fi.")
                        .font(.subheadline)
                }
                Section("Status") {
                    Label(status.0, systemImage: status.1).frame(minHeight: 32)
                    if let s = remote.state {
                        Label(s.robotError ?? (s.mode == "robot" ? "Robot connected" : "Preview, no robot"),
                              systemImage: s.robotError != nil ? "exclamationmark.triangle.fill"
                                : s.mode == "robot" ? "checkmark.circle.fill" : "desktopcomputer")
                            .frame(minHeight: 32)
                        Label(s.voice.problem ?? "Voice: \(s.voice.engine)",
                              systemImage: s.voice.problem == nil ? "speaker.wave.2.fill" : "exclamationmark.triangle.fill")
                            .frame(minHeight: 32)
                    }
                    Button {
                        remote.reconnectRobot()
                    } label: {
                        Label("Reconnect robot", systemImage: "arrow.triangle.2.circlepath").frame(minHeight: 32)
                    }
                    .disabled(remote.state == nil)
                }
            }
            .navigationTitle("Mac and robot")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", role: .confirm) {
                        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
                            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                        if !trimmed.isEmpty, trimmed != remote.server {
                            remote.server = trimmed.hasPrefix("http") ? trimmed : "http://" + trimmed
                        }
                        dismiss()
                    }
                }
            }
            .onAppear { address = remote.server }
            .safeAreaInset(edge: .bottom) { SheetStopBar() }
        }
        .presentationDetents([.large])
    }

    private var status: (String, String) {
        switch remote.link {
        case .connected: ("Connected to the Mac", "checkmark.circle.fill")
        case .connecting: ("Connecting…", "antenna.radiowaves.left.and.right")
        case .offline(let why): (why, "wifi.slash")
        }
    }
}
