import SwiftUI
import ShamblesKit
import ShamblesUI

/// The menu bar app.
///
/// `.menuBarExtraStyle(.window)` rather than the default menu style, which
/// settles the NSMenu-versus-custom-panel question: menu items cannot hold
/// progress bars, and the quota gauges are the reason the panel exists in this
/// shape. The window style gives a real SwiftUI view without hand-rolling an
/// NSPanel and its click-outside, keyboard and multi-screen behaviour.
///
/// Resident but inert. There is no timer and no polling: the panel reads from
/// disk when it opens and not otherwise. A background process that wrote on a
/// schedule would turn the race with a running Claude Code session -- which
/// rewrites ~/.claude.json on its own schedule, with no lock to wait on --
/// from a moment into a permanent condition.
@available(macOS 14, *)
@main
struct ShamblesApp: App {
    @State private var model = AccountsViewModel(service: CLIService.discovered())

    var body: some Scene {
        MenuBarExtra("Shambles", systemImage: "person.2.circle") {
            PanelView(model: model) { group, account in
                // Switching lands here once the flow is designed. Wired as a
                // closure so the view stays free of any knowledge of how a
                // switch is performed.
                print("switch \(group.provider) -> \(account.name)")
            }
        }
        .menuBarExtraStyle(.window)
    }
}

extension CLIService {
    /// Locate the `shambles` command.
    ///
    /// A bundled copy wins over one on PATH, so the app and the CLI it talks
    /// to ship as a matched pair and cannot drift into a contract mismatch.
    /// The PATH lookup is the fallback for a development checkout.
    static func discovered() -> CLIService {
        let bundled = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Resources/shambles")
        if FileManager.default.isExecutableFile(atPath: bundled.path) {
            return CLIService(executableURL: bundled)
        }
        for candidate in ["/usr/local/bin/shambles",
                          "/opt/homebrew/bin/shambles",
                          NSHomeDirectory() + "/.local/bin/shambles"] {
            if FileManager.default.isExecutableFile(atPath: candidate) {
                return CLIService(executableURL: URL(fileURLWithPath: candidate))
            }
        }
        return CLIService(executableURL: URL(fileURLWithPath: "/usr/local/bin/shambles"))
    }
}
