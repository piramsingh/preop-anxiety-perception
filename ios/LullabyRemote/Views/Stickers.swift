import SwiftUI

/// A sticker: an SF Symbol in a soft round badge. Earned ones are filled, like a real sticker
/// on a sheet; the rest are an empty outline waiting for theirs.
struct StickerBadge: View {
    enum Look { case earned, current, waiting }

    @Environment(\.palette) private var palette
    let symbol: String
    var look: Look = .earned
    var size: CGFloat = 52

    var body: some View {
        ZStack {
            switch look {
            case .earned:
                Circle()
                    .fill(LinearGradient(colors: [palette.fill.mix(with: .white, by: 0.18), palette.fill],
                                         startPoint: .top, endPoint: .bottom))
                Circle().strokeBorder(.white.opacity(0.9), lineWidth: max(2, size * 0.055))
            case .current:
                Circle().fill(palette.ink.opacity(0.14))
                Circle().strokeBorder(palette.ink, lineWidth: 2.5)
            case .waiting:
                Circle().fill(Color.card)
                Circle().strokeBorder(Color.soft,
                                      style: StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
            }
            Image(systemName: symbol)
                .font(.system(size: size * 0.42, weight: .semibold))
                .foregroundStyle(look == .earned ? AnyShapeStyle(.white)
                                 : look == .current ? AnyShapeStyle(palette.ink)
                                 : AnyShapeStyle(Color.soft))
        }
        .frame(width: size, height: size)
        .shadow(color: look == .earned ? .black.opacity(0.14) : .clear, radius: size * 0.06, y: size * 0.04)
        .accessibilityHidden(true)
    }
}

/// The row of stickers on the Now card: the whole journey at a glance. Opens the sticker book.
struct StickerStrip: View {
    let journey: Journey
    let kid: String
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(kid.isEmpty ? "Stickers" : "\(kid)'s stickers")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Text("\(journey.earnedCount) of \(journey.stops.count)")
                        .font(.subheadline)
                        .foregroundStyle(Color.soft)
                        .contentTransition(.numericText())
                    Image(systemName: "chevron.right")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
                HStack(spacing: 0) {
                    ForEach(journey.stops) { stop in
                        StickerBadge(symbol: stop.milestone.symbol, look: look(stop.status), size: 32)
                            .frame(maxWidth: .infinity)
                    }
                }
            }
            .frame(minHeight: 64)
            .contentShape(.rect)
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel("Sticker book, \(journey.earnedCount) of \(journey.stops.count) stickers")
    }

    private func look(_ status: Journey.Status) -> StickerBadge.Look {
        switch status {
        case .earned: .earned
        case .running, .listening, .next: .current
        case .later: .waiting
        }
    }
}

/// Big stickers to show the child. No counts to beat, nothing to lose: just what's on the page.
struct StickerBookSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.palette) private var palette
    let journey: Journey
    let kid: String

    private let columns = [GridItem(.adaptive(minimum: 96), spacing: 14)]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    BraveBadge(earned: journey.braveEarned, size: 132)
                        .padding(.top, 8)
                    VStack(spacing: 4) {
                        Text("Brave badge").font(.title2.weight(.bold))
                        Label(journey.braveEarned ? "Earned" : "Waiting at the end of the story",
                              systemImage: journey.braveEarned ? "checkmark.seal.fill" : "book.closed")
                            .font(.body)
                            .foregroundStyle(Color.soft)
                    }
                    LazyVGrid(columns: columns, spacing: 18) {
                        ForEach(journey.stops) { stop in
                            VStack(spacing: 8) {
                                StickerBadge(symbol: stop.milestone.symbol,
                                             look: stop.earned ? .earned : .waiting, size: 80)
                                    .rotationEffect(.degrees(stop.earned ? tilt(stop.id) : 0))
                                Text(stop.milestone.title).font(.body.weight(.medium))
                            }
                            .frame(maxWidth: .infinity)
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel("\(stop.milestone.title) sticker, \(stop.earned ? "earned" : "not yet")")
                        }
                    }
                }
                .padding(20)
            }
            .background(Color.page)
            .navigationTitle(kid.isEmpty ? "Sticker book" : "\(kid)'s sticker book")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .safeAreaInset(edge: .bottom) { SheetStopBar() }
        }
        .presentationDetents([.large])
    }

    /// A small fixed tilt per sticker, as if stuck on by hand.
    private func tilt(_ id: String) -> Double {
        Double(abs(id.unicodeScalars.reduce(0) { $0 + Int($1.value) }) % 13) - 6
    }
}

/// The badge at the end of the journey.
struct BraveBadge: View {
    @Environment(\.palette) private var palette
    let earned: Bool
    var size: CGFloat = 132

    var body: some View {
        ZStack {
            if earned {
                Circle().fill(palette.ink.opacity(0.14)).frame(width: size * 1.28, height: size * 1.28)
                Circle()
                    .fill(LinearGradient(colors: [palette.fill.mix(with: .white, by: 0.22), palette.fill],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                Circle().strokeBorder(.white.opacity(0.9), lineWidth: size * 0.05)
            } else {
                Circle().fill(Color.card)
                Circle().strokeBorder(Color.soft,
                                      style: StrokeStyle(lineWidth: 2, dash: [6, 6]))
            }
            Image(systemName: "medal.star.fill")
                .font(.system(size: size * 0.46, weight: .semibold))
                .foregroundStyle(earned ? AnyShapeStyle(.white) : AnyShapeStyle(Color.soft))
        }
        .frame(width: size, height: size)
        .shadow(color: earned ? .black.opacity(0.16) : .clear, radius: 8, y: 4)
        .accessibilityHidden(true)
    }
}

/// A short, gentle moment when a sticker is earned. Never takes touches, so Stop stays live.
struct StickerCelebration: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.palette) private var palette
    let milestone: Milestone
    let kid: String
    @State private var landed = false

    var body: some View {
        VStack(spacing: 14) {
            ZStack {
                if !reduceMotion {
                    ForEach(0..<8, id: \.self) { i in
                        let angle = Double(i) / 8 * 2 * .pi
                        Image(systemName: "sparkle")
                            .font(.system(size: i.isMultiple(of: 2) ? 18 : 12, weight: .bold))
                            .foregroundStyle(palette.ink)
                            .offset(x: cos(angle) * (landed ? 84 : 30), y: sin(angle) * (landed ? 84 : 30))
                            .opacity(landed ? 0.85 : 0)
                    }
                }
                StickerBadge(symbol: milestone.symbol, size: 112)
                    .rotationEffect(.degrees(landed || reduceMotion ? -6 : -24))
                    .scaleEffect(landed || reduceMotion ? 1 : 0.5)
            }
            .frame(width: 200, height: 190)
            Text("\(milestone.title) sticker")
                .font(.title2.weight(.bold))
            Label(kid.isEmpty ? "Added to the sticker book" : "Added to \(kid)'s sticker book",
                  systemImage: "checkmark.seal.fill")
                .font(.body)
                .foregroundStyle(Color.soft)
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, 28)
        .padding(.vertical, 24)
        .glassEffect(.regular, in: .rect(cornerRadius: 40))
        .padding(24)
        .opacity(landed ? 1 : 0)
        .onAppear {
            // The one place with a little bounce: the sticker landing.
            withAnimation(reduceMotion ? .easeOut(duration: 0.2) : .spring(duration: 0.55, bounce: 0.3)) {
                landed = true
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isStaticText)
    }
}

/// The end of the journey: the brave badge, every sticker, and a calm hand-back to the grown-up.
struct BraveMoment: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.palette) private var palette
    let journey: Journey
    let session: PanelState.Session
    let done: () -> Void
    @State private var landed = false

    var body: some View {
        ScrollView {
            VStack(spacing: 22) {
                BraveBadge(earned: true, size: 150)
                    .scaleEffect(landed || reduceMotion ? 1 : 0.6)
                    .padding(.top, 36)
                    .padding(.bottom, 14)
                VStack(spacing: 8) {
                    Text(session.kid.isEmpty ? "Brave badge" : "\(session.kid)'s brave badge")
                        .font(.largeTitle.weight(.bold))
                    Text(session.robotName.isEmpty ? "The whole journey, start to finish."
                         : "The whole journey with \(session.robotName), start to finish.")
                        .font(.title3)
                        .foregroundStyle(Color.soft)
                }
                HStack(spacing: 6) {
                    ForEach(journey.stops.filter(\.earned)) { stop in
                        StickerBadge(symbol: stop.milestone.symbol, size: 36)
                    }
                }
                .padding(.top, 4)
            }
            .multilineTextAlignment(.center)
            .padding(.horizontal, 24)
            .frame(maxWidth: .infinity)
        }
        .scrollBounceBehavior(.basedOnSize)
        .safeAreaInset(edge: .bottom) {
            Button(action: done) {
                Label("Back to the journey", systemImage: "arrow.uturn.backward")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.glass)
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
        .background {
            ZStack {
                Color.page
                LinearGradient(colors: [palette.ink.opacity(0.30), .clear], startPoint: .top, endPoint: .center)
            }
            .ignoresSafeArea()
        }
        .opacity(landed ? 1 : 0)
        .onAppear {
            withAnimation(reduceMotion ? .easeOut(duration: 0.2) : .spring(duration: 0.6, bounce: 0.25)) {
                landed = true
            }
        }
    }
}
