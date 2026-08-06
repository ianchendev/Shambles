import XCTest
@testable import ShamblesKit

/// The view model holds presentation state and nothing else.
///
/// These tests run headless — no window, no menu bar, no Python — which is the
/// entire reason the service is a protocol rather than a concrete subprocess
/// runner.
@available(macOS 14, *)
@MainActor
final class AccountsViewModelTests: XCTestCase {

    func snapshot(groups: [Group] = []) throws -> Snapshot {
        try Snapshot.makeDecoder().decode(Snapshot.self, from: ContractTests.sample)
    }

    func testStartsIdleSoNothingLoadsUntilTheMenuOpens() {
        let model = AccountsViewModel(service: StubService(Snapshot(version: 1, groups: [])))
        XCTAssertEqual(model.state, .idle)
        XCTAssertTrue(model.groups.isEmpty)
    }

    func testRefreshPublishesTheGroupsItWasGiven() async throws {
        let model = AccountsViewModel(service: StubService(try snapshot()))
        await model.refresh()
        XCTAssertEqual(model.groups.map(\.provider), ["claude", "codex"])
        XCTAssertNil(model.errorMessage)
    }

    func testGroupsArePassedThroughUntouched() async throws {
        // The panel renders `state` and `needsLogin` as given. Recomputing
        // either here would duplicate a rule that only Python has tests for.
        let model = AccountsViewModel(service: StubService(try snapshot()))
        await model.refresh()
        let accounts = model.groups[0].accounts
        XCTAssertEqual(accounts.map(\.state), ["live", "closed"])
        XCTAssertEqual(accounts.map(\.needsLogin), [false, true])
    }

    func testAFailureBecomesAReadableMessageRatherThanAnException() async {
        let model = AccountsViewModel(
            service: StubService(failing: .commandFailed(exitCode: 1, message: "no profiles")))
        await model.refresh()
        XCTAssertEqual(model.errorMessage, "no profiles")
        XCTAssertTrue(model.groups.isEmpty)
    }

    func testAMissingExecutableNamesThePathSoItCanBeFixed() async {
        let model = AccountsViewModel(
            service: StubService(failing: .executableNotFound("/usr/local/bin/shambles")))
        await model.refresh()
        XCTAssertEqual(model.errorMessage,
                       "Couldn't find the shambles command at /usr/local/bin/shambles.")
    }

    func testAnOlderCLITellsTheUserWhichSideToUpdate() async {
        let model = AccountsViewModel(
            service: StubService(failing: .unsupportedContract(found: 0, supported: 1)))
        await model.refresh()
        XCTAssertEqual(model.errorMessage,
                       "Your shambles command is out of date. Update it.")
    }

    func testANewerCLITellsTheUserTheOtherSide() async {
        let model = AccountsViewModel(
            service: StubService(failing: .unsupportedContract(found: 2, supported: 1)))
        await model.refresh()
        XCTAssertEqual(model.errorMessage,
                       "This app is older than your shambles command. Update the app.")
    }

    func testRefreshingAfterAFailureRecovers() async throws {
        let failing = AccountsViewModel(service: StubService(failing: .malformedOutput("x")))
        await failing.refresh()
        XCTAssertNotNil(failing.errorMessage)

        let working = AccountsViewModel(service: StubService(try snapshot()))
        await working.refresh()
        XCTAssertNil(working.errorMessage)
    }
}
