import SwiftUI

@main
struct LullabyRemoteApp: App {
    @State private var remote = Remote()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(remote)
                .onChange(of: scenePhase, initial: true) { _, phase in
                    // Keep the screen awake while presenting; poll only while visible.
                    UIApplication.shared.isIdleTimerDisabled = phase == .active
                    if phase == .active { remote.start() } else { remote.stopPolling() }
                }
        }
    }
}
