import Foundation

/// The wire contract emitted by `shambles list --json`.
///
/// These types are decode-only on purpose. Every value here was decided in
/// Python, where it is covered by the contract test suite; nothing in this
/// package may re-derive one. If Swift ever computes "can I switch to this"
/// from an expiry timestamp, there are two implementations of that rule and
/// only one of them is tested.
public struct Snapshot: Decodable, Sendable, Equatable {
    public let version: Int
    public let groups: [Group]

    public init(version: Int, groups: [Group]) {
        self.version = version
        self.groups = groups
    }
}

/// One credential store, with every application a single switch moves.
///
/// Terminal and VS Code share one store, so they arrive as one group carrying
/// two surfaces. The panel shows those surfaces as pills rather than
/// explaining the coupling in prose.
public struct Group: Decodable, Sendable, Equatable, Identifiable {
    public let provider: String
    public let displayName: String
    public let surfaces: [Surface]
    public let accounts: [Account]

    public var id: String { provider }
}

public struct Surface: Decodable, Sendable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let detail: String
}

public struct Account: Decodable, Sendable, Equatable, Identifiable {
    public let name: String
    public let email: String?
    public let displayName: String?
    public let plan: String?
    public let active: Bool
    /// Opaque to this package. Rendered via `needsLogin`, never interpreted.
    public let state: String
    public let needsLogin: Bool
    /// The exact command to give someone whose window has closed. Supplied by
    /// the provider, because it differs per vendor.
    public let loginHint: String?
    public let usage: [UsageWindow]

    public var id: String { name }
}

/// One quota window.
///
/// `usedPercent` is nil when the figure is known to be worthless -- the window
/// reset after it was recorded. Render nothing in that case; a stale
/// percentage is worse than a blank, because someone decides whether to switch
/// accounts on the strength of it.
public struct UsageWindow: Decodable, Sendable, Equatable, Identifiable {
    public let label: String
    public let usedPercent: Int?
    public let resetsAtMs: Int?
    public let stale: Bool

    public var id: String { label }
}

public extension Snapshot {
    /// The contract version this build understands.
    ///
    /// The app bundle and the CLI ship separately and can drift, so a
    /// mismatch is a real state rather than a defensive nicety. It surfaces as
    /// `ShamblesError.unsupportedContract`, which the panel turns into "update
    /// Shambles" instead of a decode failure or, worse, a silent misrender.
    static let supportedVersion = 1

    /// Decoder configured for the contract's snake_case field names.
    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
