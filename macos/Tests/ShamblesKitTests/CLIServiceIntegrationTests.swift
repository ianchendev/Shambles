import XCTest
@testable import ShamblesKit

/// Runs the real `shambles` command through the real service.
///
/// Everything else in this suite decodes captured bytes. This actually spawns
/// the process, reads its pipes and decodes what comes back, which is the only
/// test that would catch a broken argument order, a stray print on stdout, or
/// an exit code the service mishandles.
///
/// Skips when no Python checkout is present, so a machine with only Xcode
/// still runs the rest of the suite.
@available(macOS 14, *)
final class CLIServiceIntegrationTests: XCTestCase {

    /// The repo's virtualenv, two levels up from this package.
    func pythonURL() throws -> URL {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // ShamblesKitTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // macos
            .deletingLastPathComponent()   // repo root
        let candidate = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: candidate.path) else {
            throw XCTSkip("no .venv/bin/python; run the Python suite's setup first")
        }
        return candidate
    }

    /// A synthetic home. Never the real one — these tests must not be able to
    /// see, let alone move, a live credential.
    func makeHome() throws -> URL {
        let home = FileManager.default.temporaryDirectory
            .appendingPathComponent("shambles-it-" + UUID().uuidString)
        let work = home.appendingPathComponent(".shambles/claude/Work")
        try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)

        let future = Int(Date().timeIntervalSince1970 * 1000) + 30 * 86_400_000
        let credential = #"{"claudeAiOauth":{"accessToken":"t","refreshTokenExpiresAt":\#(future)}}"#
        try credential.write(to: work.appendingPathComponent("credential"),
                             atomically: true, encoding: .utf8)
        try "Work\n".write(to: home.appendingPathComponent(".shambles/claude/active"),
                           atomically: true, encoding: .utf8)
        try #"{"oauthAccount":{"emailAddress":"work@example.com","organizationRateLimitTier":"default_claude_max_5x"}}"#
            .write(to: home.appendingPathComponent(".claude.json"),
                   atomically: true, encoding: .utf8)
        return home
    }

    func makeService(home: URL) throws -> CLIService {
        CLIService(executableURL: try pythonURL(),
                   arguments: ["-m", "shambles", "--home", home.path])
    }

    func testTheRealCommandProducesADecodableSnapshot() async throws {
        let home = try makeHome()
        defer { try? FileManager.default.removeItem(at: home) }

        let snapshot = try await makeService(home: home).list()
        XCTAssertEqual(snapshot.version, Snapshot.supportedVersion)

        let claude = try XCTUnwrap(snapshot.groups.first { $0.provider == "claude" })
        let work = try XCTUnwrap(claude.accounts.first { $0.name == "Work" })
        XCTAssertTrue(work.active)
        XCTAssertEqual(work.email, "work@example.com")
        XCTAssertFalse(work.needsLogin)
        XCTAssertEqual(claude.surfaces.map(\.id), ["terminal", "vscode"])
    }

    func testTheViewModelDrivesTheRealCommandEndToEnd() async throws {
        let home = try makeHome()
        defer { try? FileManager.default.removeItem(at: home) }

        let model = await AccountsViewModel(service: try makeService(home: home))
        await model.refresh()

        let error = await model.errorMessage
        let groups = await model.groups
        XCTAssertNil(error)
        XCTAssertEqual(groups.map(\.provider), ["claude", "codex"])
    }

    func testAMissingExecutableIsReportedRatherThanCrashing() async {
        let service = CLIService(
            executableURL: URL(fileURLWithPath: "/nonexistent/shambles"))
        do {
            _ = try await service.list()
            XCTFail("expected a failure")
        } catch let error as ShamblesError {
            XCTAssertEqual(error, .executableNotFound("/nonexistent/shambles"))
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testANonZeroExitBecomesACommandFailure() async throws {
        // An unknown subcommand makes argparse exit 2 and write to stderr.
        let service = CLIService(executableURL: try pythonURL(),
                                 arguments: ["-m", "shambles", "definitely-not-a-command"])
        do {
            _ = try await service.list()
            XCTFail("expected a failure")
        } catch let error as ShamblesError {
            guard case .commandFailed = error else {
                return XCTFail("expected commandFailed, got \(error)")
            }
        }
    }
}
