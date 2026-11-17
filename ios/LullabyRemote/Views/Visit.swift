import SwiftUI

/// The child's name and the robot's nickname.
struct VisitFields: View {
    @Environment(Remote.self) private var remote
    let state: PanelState

    @State private var kid = ""
    @State private var robotName = ""
    @FocusState private var focus: Field?
    private enum Field { case kid, robot }

    var body: some View {
        VStack(spacing: 0) {
            field("Child's first name", prompt: "First name", symbol: "figure.child", text: $kid, field: .kid) {
                remote.updateSession(kid: kid)
            }
            Divider().padding(.leading, 52)
            HStack(spacing: 0) {
                field("Robot's nickname", prompt: "Dr. Juni", symbol: "tag.fill", text: $robotName, field: .robot) {
                    remote.updateSession(robotName: robotName)
                }
                MicButton(purpose: "nickname", state: state).padding(.trailing, 8)
            }
        }
        .background(Color.card, in: .rect(cornerRadius: 22))
        .onAppear(perform: syncFromServer)
        .onChange(of: state.session) { syncFromServer() }
        .onChange(of: focus) { old, _ in
            // Save when a field loses focus, not only on Return.
            if old == .kid, kid != state.session.kid { remote.updateSession(kid: kid) }
            if old == .robot, robotName != state.session.robotName {
                remote.updateSession(robotName: robotName)
            }
        }
        .onDisappear {
            if kid != state.session.kid { remote.updateSession(kid: kid) }
            if robotName != state.session.robotName { remote.updateSession(robotName: robotName) }
        }
    }

    /// Fill the fields from the Mac (e.g. a nickname heard by its mic), except while typing.
    private func syncFromServer() {
        if focus != .kid { kid = state.session.kid }
        if focus != .robot { robotName = state.session.robotName }
    }

    private func field(_ title: String, prompt: String, symbol: String, text: Binding<String>, field: Field,
                       submit: @escaping () -> Void) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .foregroundStyle(Color.soft)
                .frame(width: 24)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 0) {
                Text(title).font(.subheadline).foregroundStyle(Color.soft)
                TextField(title, text: text, prompt: Text(prompt))
                    .font(.title3.weight(.medium))
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                    .focused($focus, equals: field)
                    .onSubmit(submit)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .frame(minHeight: 64)
    }
}

/// The three story pictures. Big enough for a small finger: the one thing the child taps.
struct StoryPicker: View {
    @Environment(Remote.self) private var remote
    let state: PanelState
    var title = "Story"

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title).font(.title3.weight(.bold)).accessibilityAddTraits(.isHeader)
                Spacer()
                MicButton(purpose: "story", state: state)
            }
            .padding(.leading, 4)
            HStack(spacing: 16) {
                ForEach(state.themes) { theme in
                    StoryTile(theme: theme, selected: theme.key == state.session.theme) {
                        remote.updateSession(theme: theme.key)
                    }
                }
            }
        }
    }
}

private struct StoryTile: View {
    @Environment(\.palette) private var palette
    let theme: PanelState.Theme
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                Text(theme.emoji).font(.system(size: 48))
                Text(theme.label)
                    .font(.body.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .foregroundStyle(.primary)
            }
            .padding(.horizontal, 6)
            .frame(maxWidth: .infinity, minHeight: 120)
            .background {
                RoundedRectangle(cornerRadius: 24).fill(Color.card)
                RoundedRectangle(cornerRadius: 24).fill(palette.ink.opacity(selected ? 0.14 : 0))
                RoundedRectangle(cornerRadius: 24).strokeBorder(selected ? palette.ink : .clear, lineWidth: 3)
            }
            .overlay(alignment: .topTrailing) {
                if selected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.white, palette.fill)
                        .padding(8)
                        .transition(.scale.combined(with: .opacity))
                }
            }
        }
        .buttonStyle(PressableStyle())
        .sensoryFeedback(.selection, trigger: selected)
        .accessibilityLabel(theme.label)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .animation(.calm, value: selected)
    }
}

/// Listen again on the robot's mic, for when the child answers late or the presenter wants
/// another try. Listening also starts by itself after the robot asks.
struct MicButton: View {
    @Environment(Remote.self) private var remote
    @Environment(\.palette) private var palette
    let purpose: String
    let state: PanelState

    var body: some View {
        let on = state.listening == purpose
        Button {
            remote.listen(purpose)
        } label: {
            Group {
                if on { LiveSymbol(name: "mic.fill", pulse: true) } else { Image(systemName: "mic") }
            }
            .font(.body.weight(.semibold))
            .foregroundStyle(on ? Color.white : palette.ink)
            .frame(width: 48, height: 48)
            .background(on ? AnyShapeStyle(palette.fill) : AnyShapeStyle(palette.ink.opacity(0.14)), in: .circle)
        }
        .buttonStyle(PressableStyle())
        .disabled(state.isTalking || state.listening != nil || state.mode != "robot")
        .accessibilityLabel(purpose == "nickname" ? "Listen for a nickname" : "Listen for a story")
    }
}

struct ListenAgainButton: View {
    @Environment(Remote.self) private var remote
    let purpose: String
    let state: PanelState

    var body: some View {
        let on = state.listening == purpose
        Button {
            remote.listen(purpose)
        } label: {
            Label(on ? "Listening" : "Listen again", systemImage: on ? "mic.fill" : "mic")
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 40)
        }
        .buttonStyle(.bordered)
        .buttonBorderShape(.capsule)
        .disabled(state.isTalking || state.listening != nil || state.mode != "robot")
    }
}

/// Who the visit is for: name, nickname and story.
struct VisitSheet: View {
    @Environment(Remote.self) private var remote
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                if let state = remote.state {
                    VStack(alignment: .leading, spacing: 24) {
                        VisitFields(state: state)
                        StoryPicker(state: state)
                    }
                    .padding(20)
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color.page)
            .navigationTitle("This visit")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .safeAreaInset(edge: .bottom) { SheetStopBar() }
        }
        .presentationDetents([.large])
    }
}
