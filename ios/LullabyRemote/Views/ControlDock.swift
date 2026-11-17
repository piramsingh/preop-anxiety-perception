import SwiftUI

/// The one thing the presenter most likely wants next, shown above the dock.
struct PrimaryAction {
    let title: String
    let symbol: String
    var prominent = true
    let run: () -> Void
}

/// Always under the thumb: the next action, then Quiet, Stop and Say.
struct ControlDock: View {
    @Environment(Remote.self) private var remote
    @Environment(\.palette) private var palette
    @Environment(\.dynamicTypeSize) private var typeSize
    let primary: PrimaryAction?
    let say: () -> Void

    private var connected: Bool { remote.state != nil }
    private var busy: Bool {
        remote.state.map { $0.isBusy || $0.isQuiet || $0.parentPlayback != nil } ?? false
    }

    var body: some View {
        VStack(spacing: 10) {
            if let primary {
                Group {
                    if primary.prominent {
                        primaryButton(primary).buttonStyle(.glassProminent).tint(palette.fill)
                    } else {
                        primaryButton(primary).buttonStyle(.glass)
                    }
                }
                .transition(.opacity.combined(with: .scale(scale: 0.96)))
            }
            GlassEffectContainer(spacing: 10) {
                HStack(spacing: 10) {
                    Button {
                        remote.quietMode()
                    } label: {
                        side("Quiet", "moon.zzz.fill")
                    }
                    .buttonStyle(.glass)
                    .disabled(!connected || remote.state?.isQuiet == true)
                    .accessibilityHint("Calm, slow movement and no talking")

                    Button {
                        remote.stop()
                    } label: {
                        Label("Stop", systemImage: "stop.fill")
                            .font(.title3.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 48)
                    }
                    .buttonStyle(.glassProminent)
                    .tint(busy ? .red : .gray)
                    .disabled(!connected)
                    .keyboardShortcut(.escape, modifiers: [])
                    .accessibilityHint("Stops speech and movement right away")

                    Button(action: say) {
                        side("Say", "text.bubble.fill")
                    }
                    .buttonStyle(.glass)
                    .disabled(!connected)
                }
            }
        }
        .frame(maxWidth: 520)
        .padding(.horizontal, 16)
        .padding(.bottom, 8)
        .animation(.calm, value: busy)
        .animation(.calm, value: primary?.title)
    }

    private func primaryButton(_ p: PrimaryAction) -> some View {
        Button(action: p.run) {
            Label(p.title, systemImage: p.symbol)
                .font(.title3.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .frame(maxWidth: .infinity, minHeight: 48)
        }
    }

    private func side(_ title: String, _ symbol: String) -> some View {
        // At the largest text sizes the words would crowd out Stop: show the pictures alone.
        Group {
            if typeSize.isAccessibilitySize {
                Label(title, systemImage: symbol).labelStyle(.iconOnly)
            } else {
                Label(title, systemImage: symbol)
            }
        }
        .font(.body.weight(.semibold))
        .lineLimit(1)
        .frame(minWidth: typeSize.isAccessibilitySize ? 48 : 72, minHeight: 48)
    }
}
