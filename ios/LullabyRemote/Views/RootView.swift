import SwiftUI

/// The presenter's home: what Dr. Juni is doing now and the child's journey. Less-used things
/// (lines, visit details, the Mac's address) are one level deeper. Stop is on every screen.
struct RootView: View {
    @Environment(Remote.self) private var remote
    @Environment(\.horizontalSizeClass) private var sizeClass

    enum Sheet: Identifiable, Equatable {
        case say, visit, settings, stickers, milestone(String)
        var id: String {
            switch self {
            case .say: "say"
            case .visit: "visit"
            case .settings: "settings"
            case .stickers: "stickers"
            case .milestone(let id): "milestone.\(id)"
            }
        }
    }

    @State private var sheet: Sheet?
    @State private var confirmEnd = false
    @State private var celebrating: Milestone?
    @State private var celebrations = 0
    @State private var showBrave = false
    @State private var celebrationTask: Task<Void, Never>?

    private var journey: Journey? { remote.state.map(Journey.init) }
    private var palette: Palette { .forTheme(remote.state?.session.theme) }
    private var wide: Bool { sizeClass == .regular }

    var body: some View {
        NavigationStack {
            Group {
                if wide {
                    HStack(spacing: 0) {
                        home
                        if let state = remote.state { sidePane(state) }
                    }
                } else {
                    home
                }
            }
            .background(backdrop)
            .navigationTitle(title)
            .toolbar { toolbar }
            .overlay(alignment: .top) { NoticeBanner() }
            .overlay {
                if let celebrating {
                    StickerCelebration(milestone: celebrating, kid: remote.state?.session.kid ?? "")
                        .id(celebrating.id)
                        .transition(.opacity)
                        .allowsHitTesting(false)
                }
            }
            .confirmationDialog("End this visit?", isPresented: $confirmEnd, titleVisibility: .visible) {
                Button("End visit and delete recordings", role: .destructive) {
                    showBrave = false
                    remote.endSession()
                }
            } message: {
                Text(endMessage)
            }
        }
        .sheet(item: $sheet) { sheet in
            Group {
                switch sheet {
                case .say: SaySheet(focusOnAppear: !Self.debugSheetRequested)
                case .visit: VisitSheet()
                case .settings: SettingsSheet()
                case .stickers:
                    if let journey { StickerBookSheet(journey: journey, kid: remote.state?.session.kid ?? "") }
                case .milestone(let id): MilestoneSheet(stopID: id)
                }
            }
            .environment(\.palette, palette)
            .tint(palette.ink)
        }
        .environment(\.palette, palette)
        .tint(palette.ink)
        .animation(.calm, value: palette)
        .onChange(of: remote.state) { old, new in noticeStickers(old: old, new: new) }
        .sensoryFeedback(.impact(weight: .light), trigger: remote.started)
        .sensoryFeedback(.impact(weight: .heavy), trigger: remote.stopped)
        .sensoryFeedback(.error, trigger: remote.failed)
        .sensoryFeedback(.success, trigger: remote.heardCount)
        .sensoryFeedback(.success, trigger: celebrations)
        .onAppear(perform: openDebugSheet)
    }

    // MARK: home

    private var home: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                if let state = remote.state, let journey {
                    if !subtitle.isEmpty {
                        Text(subtitle)
                            .font(.title3)
                            .foregroundStyle(Color.soft)
                            .padding(.leading, 4)
                            .padding(.top, -6)
                            .padding(.bottom, -10)
                    }
                    NowCard(state: state, journey: journey) { sheet = .stickers }
                    if journey.wantsStoryPick && !wide {
                        StoryPicker(state: state, title: "Which story?")
                            .transition(.opacity)
                    }
                    JourneyMap(state: state, journey: journey) { sheet = .milestone($0) }
                } else {
                    OfflineCard { sheet = .settings }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 24)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
            .animation(.calm, value: journey?.wantsStoryPick)
        }
        .scrollEdgeEffectStyle(.soft, for: .all)
        .overlay {
            if showBrave, let state = remote.state, let journey {
                BraveMoment(journey: journey, session: state.session) {
                    withAnimation(.calm) { showBrave = false }
                }
                .transition(.opacity)
            }
        }
        // On iPad the dock sits under the journey, leaving the side pane its full height.
        .safeAreaInset(edge: .bottom) {
            ControlDock(primary: primaryAction) { sheet = .say }
        }
    }

    /// iPad: the visit and every line sit beside the journey instead of in sheets.
    private func sidePane(_ state: PanelState) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader("This visit")
                    VisitFields(state: state)
                }
                StoryPicker(state: state, title: Journey(state).wantsStoryPick ? "Which story?" : "Story")
                LinesPanel(state: state)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .scrollEdgeEffectStyle(.soft, for: .all)
        .scrollDismissesKeyboard(.interactively)
        .frame(width: 400)
        .background(.thinMaterial)
    }

    /// A soft wash of the story's colour behind everything.
    private var backdrop: some View {
        ZStack {
            Color.page
            LinearGradient(colors: [palette.ink.opacity(0.16), .clear], startPoint: .top, endPoint: .center)
        }
        .ignoresSafeArea()
    }

    private var title: String {
        guard let kid = remote.state?.session.kid, !kid.isEmpty else { return "Dr. Juni" }
        return "\(kid)'s visit"
    }

    private var subtitle: String {
        guard let s = remote.state, !s.session.kid.isEmpty else { return "" }
        var parts = ["with \(s.session.robotName.isEmpty ? "Dr. Juni" : s.session.robotName)"]
        if let theme = s.themeInfo { parts.append(theme.label) }
        return parts.joined(separator: " · ")
    }

    private var endMessage: String {
        let kid = remote.state?.session.kid ?? ""
        let who = kid.isEmpty ? "the child's name" : "\(kid)'s name"
        return "This clears \(who), the nickname, the story and the stickers, and deletes the parent's recordings on the Mac. It can't be undone."
    }

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        if !wide {
            ToolbarItem(placement: .topBarTrailing) {
                Button("This visit", systemImage: "person.text.rectangle") { sheet = .visit }
                    .disabled(remote.state == nil)
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Button("Start or continue intro", systemImage: "play.fill") { remote.startIntro() }
                    .disabled(remote.state.map { $0.isBusy } ?? true)
                Button("Sticker book", systemImage: "seal.fill") { sheet = .stickers }
                    .disabled(remote.state == nil)
                Divider()
                Button("Reconnect robot", systemImage: "arrow.triangle.2.circlepath") {
                    remote.reconnectRobot()
                }
                .disabled(remote.state == nil)
                Button("Mac and robot", systemImage: "network") { sheet = .settings }
                Divider()
                Button("End visit…", systemImage: "trash", role: .destructive) { confirmEnd = true }
                    .disabled(remote.state == nil)
            } label: {
                Label("More", systemImage: "ellipsis")
            }
        }
    }

    // MARK: the next action

    private var primaryAction: PrimaryAction? {
        guard let state = remote.state, let journey else {
            if case .offline = remote.link {
                return PrimaryAction(title: "Mac address", symbol: "network", prominent: false) { sheet = .settings }
            }
            return nil
        }
        if state.isBusy || state.parentPlayback?.state == "playing" { return nil }
        if journey.braveEarned {
            return PrimaryAction(title: "End visit…", symbol: "checkmark.circle", prominent: false) { confirmEnd = true }
        }
        // Autopilot until Part 1 and breathing are done: the intro runs by itself and picks up
        // where the visit is. The child's name is optional (Dr. Juni says "friend").
        let done = state.session.done
        if !(done.contains("chapter1") && done.contains("breathing")) {
            let fresh = done.isEmpty
            return PrimaryAction(title: fresh ? "Start intro" : "Continue intro",
                                 symbol: "play.fill") { remote.startIntro() }
        }
        if journey.wantsStoryPick { return nil }
        guard let next = journey.nextStep else { return nil }
        if state.blockedReason(next) != nil {
            if next.key == "got_name" {
                return PrimaryAction(title: "Ask for a nickname", symbol: "play.fill") { remote.runStep("ask_name") }
            }
            return PrimaryAction(title: "Ask for a story", symbol: "play.fill") { remote.runStep("ask_story") }
        }
        return PrimaryAction(title: next.label, symbol: "play.fill") { remote.runStep(next.key) }
    }

    // MARK: stickers

    private func noticeStickers(old: PanelState?, new: PanelState?) {
        // Only steps finishing while we watch: opening the app mid-visit celebrates nothing.
        guard let old, let new, old.session.done != new.session.done else { return }
        let before = Journey(old), after = Journey(new)
        if after.braveEarned && !before.braveEarned {
            celebrations += 1
            celebrating = nil
            withAnimation(.calm) { showBrave = true }
            return
        }
        if !after.braveEarned { showBrave = false }
        let fresh = after.stops.filter { $0.earned && !before.earnedIDs.contains($0.id) }
        guard let stop = fresh.last, fresh.count <= 2 else { return }
        celebrations += 1
        withAnimation(.calm) { celebrating = stop.milestone }
        celebrationTask?.cancel()
        #if DEBUG
        if Mock.holdsCelebration { return }
        #endif
        celebrationTask = Task {
            try? await Task.sleep(for: .seconds(2.6))
            if !Task.isCancelled { withAnimation(.calm) { celebrating = nil } }
        }
    }

    // MARK: debug

    /// `-LullabyShow say|visit|settings|stickers|<milestone id>` opens a sheet at launch (debug builds).
    private static var debugSheetRequested: Bool {
        #if DEBUG
        UserDefaults.standard.string(forKey: "LullabyShow") != nil
        #else
        false
        #endif
    }

    private func openDebugSheet() {
        #if DEBUG
        guard let name = UserDefaults.standard.string(forKey: "LullabyShow") else { return }
        Task {
            try? await Task.sleep(for: .seconds(1))
            switch name {
            case "say": sheet = .say
            case "visit": sheet = .visit
            case "settings": sheet = .settings
            case "stickers": sheet = .stickers
            case "end": confirmEnd = true
            default: sheet = .milestone(name)
            }
        }
        #endif
    }
}
