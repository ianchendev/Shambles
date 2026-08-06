import XCTest
@testable import ShamblesKit

/// Decoding fixtures produced by the Python side.
///
/// These are the cross-language half of the contract test. The Python suite
/// asserts the shape it emits; this asserts the shape Swift accepts. Neither
/// side has to run the other's code for both to stay in step.
final class ContractTests: XCTestCase {

    /// Verbatim output of `shambles list --json`.
    static let sample = """
    {"version": 1, "groups": [
      {"provider": "claude", "display_name": "Claude Code",
       "surfaces": [{"id": "terminal", "label": "Terminal", "detail": "Claude Code CLI"},
                    {"id": "vscode", "label": "VS Code", "detail": "anthropic.claude-code"}],
       "accounts": [
         {"name": "Work", "email": "work@example.com", "display_name": "Liam",
          "plan": "default_claude_max_5x", "active": true, "state": "live",
          "needs_login": false, "login_hint": null,
          "usage": [{"label": "5h", "used_percent": 21, "resets_at_ms": 4102444800000, "stale": false},
                    {"label": "7d", "used_percent": null, "resets_at_ms": 1, "stale": false}]},
         {"name": "Personal", "email": "personal@example.com", "display_name": null,
          "plan": null, "active": false, "state": "closed",
          "needs_login": true, "login_hint": "Run 'claude', then /login.",
          "usage": []}]},
      {"provider": "codex", "display_name": "Codex",
       "surfaces": [{"id": "terminal", "label": "Terminal", "detail": "Codex CLI"},
                    {"id": "vscode", "label": "VS Code", "detail": "openai.chatgpt"},
                    {"id": "chatgpt", "label": "ChatGPT", "detail": "inside ChatGPT.app"}],
       "accounts": []}]}
    """.data(using: .utf8)!

    func testSnakeCaseFieldsDecodeIntoCamelCaseProperties() throws {
        let snapshot = try Snapshot.makeDecoder().decode(Snapshot.self, from: Self.sample)
        let work = snapshot.groups[0].accounts[0]
        XCTAssertEqual(snapshot.version, 1)
        XCTAssertEqual(snapshot.groups[0].displayName, "Claude Code")
        XCTAssertEqual(work.needsLogin, false)
        XCTAssertEqual(work.plan, "default_claude_max_5x")
    }

    func testSurfacesArriveInOrderSoThePillsReadConsistently() throws {
        let snapshot = try Snapshot.makeDecoder().decode(Snapshot.self, from: Self.sample)
        XCTAssertEqual(snapshot.groups[0].surfaces.map(\.id), ["terminal", "vscode"])
        XCTAssertEqual(snapshot.groups[1].surfaces.map(\.id),
                       ["terminal", "vscode", "chatgpt"])
    }

    func testAWindowWithNoFigureDecodesAsNilRatherThanZero() throws {
        // Zero would render as "0% used", which is the opposite of "unknown".
        let snapshot = try Snapshot.makeDecoder().decode(Snapshot.self, from: Self.sample)
        let windows = snapshot.groups[0].accounts[0].usage
        XCTAssertEqual(windows[0].usedPercent, 21)
        XCTAssertNil(windows[1].usedPercent)
    }

    func testOptionalFieldsTolerateNull() throws {
        let snapshot = try Snapshot.makeDecoder().decode(Snapshot.self, from: Self.sample)
        let personal = snapshot.groups[0].accounts[1]
        XCTAssertNil(personal.displayName)
        XCTAssertNil(personal.plan)
        XCTAssertEqual(personal.loginHint, "Run 'claude', then /login.")
    }

    func testAGroupWithNoAccountsIsValid() throws {
        let snapshot = try Snapshot.makeDecoder().decode(Snapshot.self, from: Self.sample)
        XCTAssertTrue(snapshot.groups[1].accounts.isEmpty)
    }

    func testAFutureContractVersionIsRecoverableFromRawJSON() {
        // The panel must be able to say "update Shambles" even when the new
        // shape fails to decode.
        let future = #"{"version": 99, "groups": [{"unknown": true}]}"#.data(using: .utf8)!
        XCTAssertEqual(CLIService.peekVersion(future), 99)
    }
}
