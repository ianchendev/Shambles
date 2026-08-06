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

    static func peekVersion(_ data: Data) -> Int? {
        let object = try? JSONSerialization.jsonObject(with: data)
        return (object as? [String: Any])?["version"] as? Int
    }

    private func run(_ arguments: [String]) throws -> Data {
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

        guard process.terminationStatus == 0 else {
            throw ShamblesError.commandFailed(
                exitCode: process.terminationStatus,
                message: String(data: stderr, encoding: .utf8)?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? "")
        }
        return stdout
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
}
