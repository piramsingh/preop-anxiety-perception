import Foundation
import Observation
import SwiftUI

/// Talks to the Lullaby app on the Mac (`uv run lullaby --lan`) and keeps its state fresh.
@MainActor
@Observable
final class Remote {
    enum Link: Equatable {
        case connecting
        case connected
        case offline(String)
    }

    private(set) var state: PanelState?
    private(set) var link: Link = .connecting
    /// A short message for the presenter after a failed action ("Robot is talking").
    private(set) var notice: String?
    /// Bumped on each event so views can play matching haptics.
    private(set) var started = 0
    private(set) var stopped = 0
    private(set) var failed = 0
    private(set) var heardCount = 0
    /// Which button is waiting on the Mac, for an instant pressed look.
    private(set) var pending: String?

    var server: String {
        didSet { UserDefaults.standard.set(server, forKey: "server"); restart() }
    }

    private var poller: Task<Void, Never>?
    private var noticeTask: Task<Void, Never>?
    private let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 4
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()
    /// Listening waits for the child to answer, so it gets a longer timeout than other calls.
    private let slowSession: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 25
        return URLSession(configuration: c)
    }()
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    static let defaultServer = "http://Pirams-Macbook-Pro.local:8890"

    init() {
        server = UserDefaults.standard.string(forKey: "server") ?? Self.defaultServer
    }

    #if DEBUG
    /// `-LullabyMock <name>` shows a canned state and never touches the network.
    let mock = UserDefaults.standard.string(forKey: "LullabyMock")
    #else
    let mock: String? = nil
    #endif

    // MARK: polling

    func start() {
        guard poller == nil else { return }
        #if DEBUG
        if let mock {
            if state == nil && link == .connecting { startMock(mock) }
            return
        }
        #endif
        poller = Task { [weak self] in
            var delay: Duration = .milliseconds(500)
            while !Task.isCancelled {
                guard let self else { return }
                let ok = await self.refresh()
                // Back off gently while the Mac is unreachable; snap back once it answers.
                delay = ok ? .milliseconds(500) : min(delay * 2, .seconds(4))
                try? await Task.sleep(for: delay)
            }
        }
    }

    func stopPolling() {
        poller?.cancel()
        poller = nil
    }

    private func restart() {
        stopPolling()
        state = nil
        link = .connecting
        start()
    }

    @discardableResult
    func refresh() async -> Bool {
        guard let url = URL(string: server + "/api/state") else {
            link = .offline("That address doesn't look right.")
            return false
        }
        do {
            let (data, response) = try await session.data(from: url)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                throw URLError(.badServerResponse)
            }
            let new = try decoder.decode(PanelState.self, from: data)
            if new != state { state = new }
            link = .connected
            return true
        } catch {
            link = .offline(Self.describe(error))
            return false
        }
    }

    // MARK: actions

    /// Steps and lines that ask the child something; the robot's mic listens once they finish.
    static let asks = ["ask_name": "nickname", "ask_story": "story",
                       "again_name": "nickname", "again_story": "story"]

    func runStep(_ key: String) {
        send("/api/step/\(key)", id: "step.\(key)", starts: true)
        if let purpose = Self.asks[key] { listenAfterTalking(purpose) }
    }
    func react(_ key: String) { send("/api/react/\(key)", id: "react.\(key)", starts: true) }
    func flow(_ key: String) {
        send("/api/flow/\(key)", id: "flow.\(key)", starts: true)
        if let purpose = Self.asks[key] { listenAfterTalking(purpose) }
    }

    /// Listen through the robot's microphone for the child's answer.
    func listen(_ purpose: String) {
        guard mock == nil else { return }
        guard let url = URL(string: server + "/api/listen/robot?purpose=\(purpose)") else { return }
        Task {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            do {
                let (data, response) = try await slowSession.data(for: req)
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    if let new = try? decoder.decode(PanelState.self, from: data) {
                        state = new
                        if new.heard?.result != nil { heardCount += 1 }
                    }
                } else {
                    let detail = (try? JSONDecoder().decode([String: String].self, from: data))?["detail"]
                    show(detail ?? "Couldn't listen.")
                }
            } catch {
                show("Listening timed out.")
            }
        }
    }

    /// Wait for the robot to finish asking, then listen. Gives up if a Stop or another
    /// step takes over.
    private func listenAfterTalking(_ purpose: String) {
        Task {
            let deadline = Date.now.addingTimeInterval(30)
            var sawTalking = false
            while Date.now < deadline {
                try? await Task.sleep(for: .milliseconds(250))
                guard let s = state else { continue }
                if s.isTalking { sawTalking = true; continue }
                if sawTalking {
                    if s.label.isEmpty && s.activity == "idle" { listen(purpose) }
                    return
                }
            }
        }
    }
    func startIntro() { send("/api/intro", id: "intro", starts: true) }
    func quietMode() { send("/api/recovery", id: "quiet", starts: true) }
    func playParent(_ slot: String) { send("/api/parent/\(slot)/play", id: "parent.\(slot)", starts: true) }
    func pauseParent() { send("/api/parent/pause", id: "parent.pause") }
    func endSession() { send("/api/end", id: "end") }
    func reconnectRobot() { send("/api/reconnect", id: "reconnect") }

    func stop() {
        stopped += 1  // haptic on press, not on the round trip
        send("/api/stop", id: "stop")
    }

    func say(_ text: String) { send("/api/say", id: "say", body: ["text": text], starts: true) }

    func updateSession(kid: String? = nil, robotName: String? = nil, theme: String? = nil) {
        var body: [String: String] = [:]
        if let kid { body["kid"] = kid }
        if let robotName { body["robot_name"] = robotName }
        if let theme { body["theme"] = theme }
        send("/api/session", id: "session", body: body)
    }

    private func send(_ path: String, id: String, body: [String: String]? = nil, starts: Bool = false) {
        #if DEBUG
        if mock != nil {
            if let theme = body?["theme"] { state?.session.theme = theme }
            return
        }
        #endif
        guard let url = URL(string: server + path) else { return }
        pending = id
        Task {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            if let body {
                req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                req.httpBody = try? JSONEncoder().encode(body)
            }
            do {
                let (data, response) = try await session.data(for: req)
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                if code == 200 {
                    if let new = try? decoder.decode(PanelState.self, from: data) { state = new }
                    if starts { started += 1 }
                } else {
                    let detail = (try? JSONDecoder().decode([String: String].self, from: data))?["detail"]
                    show(detail ?? "The Mac said no (\(code)).")
                }
            } catch {
                show(Self.describe(error))
            }
            if pending == id { pending = nil }
        }
    }

    #if DEBUG
    private func startMock(_ name: String) {
        if name == "offline" {
            link = .offline("The Mac isn't running Lullaby with --lan.")
            return
        }
        state = Mock.state(name)
        link = .connected
        // Earn the last sticker a moment after launch, so the celebration can be seen.
        if let key = Mock.earnsAfterLaunch(name) {
            Task {
                try? await Task.sleep(for: .seconds(1.2))
                state?.session.done.append(key)
            }
        }
    }
    #endif

    private func show(_ message: String) {
        failed += 1
        notice = message
        noticeTask?.cancel()
        noticeTask = Task {
            try? await Task.sleep(for: .seconds(3))
            if !Task.isCancelled { notice = nil }
        }
    }

    private static func describe(_ error: Error) -> String {
        switch (error as? URLError)?.code {
        case .cannotFindHost, .dnsLookupFailed: "Can't find the Mac. Same Wi-Fi?"
        case .cannotConnectToHost: "The Mac isn't running Lullaby with --lan."
        case .timedOut: "The Mac isn't answering."
        case .notConnectedToInternet: "This iPhone isn't on Wi-Fi."
        default: "Can't reach the Mac."
        }
    }
}
