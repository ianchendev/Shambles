import XCTest
@testable import ShamblesKit

/// Decodes output captured from the real `shambles list --json`.
///
/// The other contract tests use a hand-written sample, which proves Swift
/// accepts the shape *I believe* Python emits. This one proves Swift accepts
/// the shape Python **actually** emitted, which is a different claim and the
/// one that matters. Regenerate with:
///
///     python -m shambles list --json --home <fixture home> \
///       > Tests/ShamblesKitTests/Fixtures/snapshot.json
///
/// A field renamed on the Python side fails here, in a unit test, instead of
/// silently rendering an empty row in someone's menu bar.
@available(macOS 14, *)
final class GoldenFixtureTests: XCTestCase {

    func loadFixture() throws -> Data {
        guard let url = Bundle.module.url(
            forResource: "snapshot", withExtension: "json",
            subdirectory: "Fixtures") else {
            throw XCTSkip("fixture not bundled")
        }
        return try Data(contentsOf: url)
    }

    func testRealCLIOutputDecodes() throws {
        let snapshot = try Snapshot.makeDecoder()
            .decode(Snapshot.self, from: try loadFixture())
        XCTAssertEqual(snapshot.version, Snapshot.supportedVersion)
        XCTAssertFalse(snapshot.groups.isEmpty)
    }

    func testEveryGroupCarriesAtLeastOneSurface() throws {
        // A group with no surfaces would render a bare heading, leaving the
        // user unable to tell which applications the switch moves.
        let snapshot = try Snapshot.makeDecoder()
            .decode(Snapshot.self, from: try loadFixture())
        for group in snapshot.groups {
            XCTAssertFalse(group.surfaces.isEmpty, "\(group.provider) has no surfaces")
            XCTAssertFalse(group.displayName.isEmpty)
        }
    }

    func testAnAccountNeedingLoginAlwaysCarriesItsCommand() throws {
        // The lapsed state is the handoff point, so an empty hint would leave
        // someone stuck with no way forward.
        let snapshot = try Snapshot.makeDecoder()
            .decode(Snapshot.self, from: try loadFixture())
        for group in snapshot.groups {
            for account in group.accounts where account.needsLogin {
                XCTAssertNotNil(account.loginHint, "\(account.name) has no hint")
                XCTAssertFalse(account.loginHint?.isEmpty ?? true)
            }
        }
    }

    func testAtMostOneAccountPerGroupIsActive() throws {
        let snapshot = try Snapshot.makeDecoder()
            .decode(Snapshot.self, from: try loadFixture())
        for group in snapshot.groups {
            XCTAssertLessThanOrEqual(
                group.accounts.filter(\.active).count, 1,
                "\(group.provider) reports more than one active account")
        }
    }

    func testTheViewModelRendersTheRealSnapshotWithoutError() async throws {
        let snapshot = try Snapshot.makeDecoder()
            .decode(Snapshot.self, from: try loadFixture())
        let model = await AccountsViewModel(service: StubService(snapshot))
        await model.refresh()
        let groups = await model.groups
        let error = await model.errorMessage
        XCTAssertEqual(groups.count, snapshot.groups.count)
        XCTAssertNil(error)
    }
}
