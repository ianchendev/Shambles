import Foundation

/// Everything that fails between the panel and the credential logic.
public enum ShamblesError: Error, Equatable, Sendable {
    case executableNotFound(String)
    case commandFailed(exitCode: Int32, message: String)
    case malformedOutput(String)
    /// The CLI speaks a contract this build does not understand. Distinct from
    /// a decode failure because the remedy is different and actionable.
    case unsupportedContract(found: Int, supported: Int)

    /// What to put in front of a person. No exception text, no "Error:" prefix.
    public var message: String {
        switch self {
        case .executableNotFound(let path):
            return "Couldn't find the shambles command at \(path)."
        case .commandFailed(_, let message):
            return message.isEmpty ? "The shambles command failed." : message
        case .malformedOutput:
            return "Couldn't read the reply from the shambles command."
        case .unsupportedContract(let found, let supported):
            return found > supported
                ? "This app is older than your shambles command. Update the app."
                : "Your shambles command is out of date. Update it."
        }
    }
}

/// The seam between the panel and the credential logic.
///
/// A protocol rather than a concrete type because the real implementation
/// spawns a subprocess: a view model that did that directly could not be
/// tested without a Python install, a real home directory and real
/// credentials. Everything above this line sees Swift values only.
public protocol ShamblesService: Sendable {
    func list() async throws -> Snapshot
    func switchTo(provider: String, account: String) async throws -> SwitchOutcome
}

/// What came back from a switch.
///
/// `needsLogin` is not a failure: a profile that has been added but never
/// signed into is exactly how a new account starts, and the panel should show
/// the vendor's command rather than an error.
public struct SwitchOutcome: Decodable, Sendable, Equatable {
    public let ok: Bool
    public let provider: String?
    public let switchedTo: String?
    public let needsLogin: Bool?
    public let warnings: [String]?
    public let error: SwitchError?

    public struct SwitchError: Decodable, Sendable, Equatable {
        public let code: String
        public let message: String
    }

    public init(ok: Bool, provider: String?, switchedTo: String?,
                needsLogin: Bool?, warnings: [String]?, error: SwitchError?) {
        self.ok = ok
        self.provider = provider
        self.switchedTo = switchedTo
        self.needsLogin = needsLogin
        self.warnings = warnings
        self.error = error
    }
}

/// Talks to the `shambles` command and decodes its contract.
///
/// A subprocess rather than an embedded interpreter or a local server. The CLI
/// has to exist regardless -- a Windows tray app manages a different Claude
/// Code install from the one inside WSL, and only a CLI running inside WSL can
/// reach that one -- so the shells consume what already had to be built.
///
/// The boundary stays observable by hand: whatever the panel shows,
/// `shambles list --json` prints the same thing, which separates a rendering
/// bug from a logic bug without a debugger.
public struct CLIService: ShamblesService {
    public let executableURL: URL
    public let arguments: [String]

    public init(executableURL: URL, arguments: [String] = []) {
        self.executableURL = executableURL
        self.arguments = arguments
    }

    public func list() async throws -> Snapshot {
        let data = try run(arguments + ["list", "--json"])
        let snapshot: Snapshot
        do {
            snapshot = try Snapshot.makeDecoder().decode(Snapshot.self, from: data)
        } catch {
            // A version this build predates can fail to decode before the
            // version check runs, so recover the number first and report the
            // actionable error rather than the parse failure.
            if let version = Self.peekVersion(data), version != Snapshot.supportedVersion {
                throw ShamblesError.unsupportedContract(
                    found: version, supported: Snapshot.supportedVersion)
            }
            throw ShamblesError.malformedOutput(String(describing: error))
        }
        guard snapshot.version == Snapshot.supportedVersion else {
            throw ShamblesError.unsupportedContract(
                found: snapshot.version, supported: Snapshot.supportedVersion)
        }
        return snapshot
    }

    public func switchTo(provider: String, account: String) async throws -> SwitchOutcome {
        // A refused switch exits non-zero *and* prints its reason as JSON on
        // stdout. Decode the payload before judging the status: the message
        // explains what to do, the exit code only says something went wrong.
        let (data, status, stderr) = try capture(
            arguments + ["switch", provider, account, "--json"])
        if let outcome = try? Snapshot.makeDecoder()
            .decode(SwitchOutcome.self, from: data) {
            return outcome
        }
        guard status == 0 else {
            throw ShamblesError.commandFailed(exitCode: status, message: stderr)
        }
        throw ShamblesError.malformedOutput("switch produced no readable result")
    }

    static func peekVersion(_ data: Data) -> Int? {
        let object = try? JSONSerialization.jsonObject(with: data)
        return (object as? [String: Any])?["version"] as? Int
    }

    private func run(_ arguments: [String]) throws -> Data {
        let (data, status, stderr) = try capture(arguments)
        guard status == 0 else {
            throw ShamblesError.commandFailed(exitCode: status, message: stderr)
        }
        return data
    }

    /// Run the command and hand back everything, judging nothing.
    ///
    /// Separate from `run` because the two commands disagree about what a
    /// non-zero exit means: for `list` it is simply a failure, but `switch`
    /// pairs it with a JSON explanation worth reading.
    private func capture(_ arguments: [String]) throws -> (Data, Int32, String) {
        guard FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            throw ShamblesError.executableNotFound(executableURL.path)
        }

        let process = Process()
        process.executableURL = executableURL
        process.arguments = arguments

        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err

        do {
            try process.run()
        } catch {
            throw ShamblesError.executableNotFound(executableURL.path)
        }

        // Read before waiting. A pipe buffer that fills while the process is
        // still writing deadlocks both sides.
        let stdout = out.fileHandleForReading.readDataToEndOfFile()
        let stderr = err.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        return (stdout, process.terminationStatus,
                String(data: stderr, encoding: .utf8)?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? "")
    }
}

/// A service backed by fixed JSON, for tests and SwiftUI previews.
public struct StubService: ShamblesService {
    public let result: Result<Snapshot, ShamblesError>

    public init(_ snapshot: Snapshot) { self.result = .success(snapshot) }
    public init(failing error: ShamblesError) { self.result = .failure(error) }

    public func list() async throws -> Snapshot {
        try result.get()
    }

    public func switchTo(provider: String, account: String) async throws -> SwitchOutcome {
        SwitchOutcome(ok: true, provider: provider, switchedTo: account,
                      needsLogin: false, warnings: [], error: nil)
    }
}
