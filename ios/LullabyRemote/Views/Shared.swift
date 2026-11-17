import SwiftUI

extension Animation {
    /// The app's default motion: quick and critically damped.
    static let calm = Animation.spring(duration: 0.35, bounce: 0)
}

extension Color {
    /// Card surfaces on the grouped background; adapts to light and dark mode.
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
    static let cardInset = Color(uiColor: .tertiarySystemGroupedBackground)
    /// Supporting text. Stronger than the system's secondary label, to keep 4.5:1 on cards.
    static let soft = Color.primary.opacity(0.68)
    static let page = Color(uiColor: .systemGroupedBackground)
}

/// Feedback the instant a finger lands (not on release): a quick, critically damped press.
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .animation(.spring(duration: 0.2, bounce: 0), value: configuration.isPressed)
    }
}

struct SectionHeader: View {
    let title: String
    var symbol: String?
    init(_ title: String, symbol: String? = nil) { self.title = title; self.symbol = symbol }

    var body: some View {
        HStack(spacing: 8) {
            if let symbol { Image(systemName: symbol).foregroundStyle(Color.soft) }
            Text(title)
        }
        .font(.title3.weight(.bold))
        .padding(.leading, 4)
        .accessibilityAddTraits(.isHeader)
    }
}

/// A round 48pt play control used on the journey and in step lists.
struct PlayCircle: View {
    @Environment(\.palette) private var palette
    var prominent = false
    var symbol = "play.fill"

    var body: some View {
        Image(systemName: symbol)
            .font(.body.weight(.semibold))
            .foregroundStyle(prominent ? Color.white : palette.ink)
            .frame(width: 48, height: 48)
            .background(prominent ? AnyShapeStyle(palette.fill) : AnyShapeStyle(palette.ink.opacity(0.14)),
                        in: .circle)
            .contentShape(.circle)
    }
}

/// A live symbol that only keeps moving when the person hasn't asked for less motion.
struct LiveSymbol: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let name: String
    var pulse = false

    var body: some View {
        if reduceMotion {
            Image(systemName: name)
        } else if pulse {
            Image(systemName: name).symbolEffect(.pulse, options: .repeating)
        } else {
            Image(systemName: name).symbolEffect(.variableColor.iterative, options: .repeating)
        }
    }
}

/// Stop, for the bottom of every sheet: one tap away wherever the presenter is.
struct SheetStopBar: View {
    @Environment(Remote.self) private var remote

    var body: some View {
        let busy = remote.state.map { $0.isBusy || $0.isQuiet || $0.parentPlayback != nil } ?? false
        Button {
            remote.stop()
        } label: {
            Label("Stop", systemImage: "stop.fill")
                .font(.title3.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.glassProminent)
        .tint(busy ? .red : .gray)
        .disabled(remote.state == nil)
        .accessibilityHint("Stops speech and movement right away")
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
        .animation(.calm, value: busy)
    }
}

/// A brief message after a failed action, dropping in from the top where it's read.
struct NoticeBanner: View {
    @Environment(Remote.self) private var remote

    var body: some View {
        Group {
            if let notice = remote.notice {
                Label(notice, systemImage: "exclamationmark.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .glassEffect(.regular.tint(.orange.opacity(0.25)), in: .capsule)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .accessibilityAddTraits(.isStaticText)
            }
        }
        .animation(.calm, value: remote.notice)
        .padding(.top, 4)
    }
}
