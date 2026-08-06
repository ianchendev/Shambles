import Foundation
import Observation

/// Presentation state for the panel — and nothing else.
///
/// The division that keeps this honest: **this holds how the panel is doing,
/// not what is true about your accounts.** Loading, failed, which row is busy —
/// those live here. Whether an account can be switched to, how many days are
/// left, whether a quota figure is worth showing — those were decided in
/// Python and arrive already decided.
///
/// The tripwire is arithmetic. If a computation on a date or a percentage
/// appears in this file, a rule has been duplicated and only the Python copy
/// has tests.
@available(macOS 14, *)
@MainActor
@Observable
public final class AccountsViewModel {
    public enum State: Equatable {
        case idle
        case loading
        case loaded(Snapshot)
        case failed(String)
    }

    public private(set) var state: State = .idle

    private let service: ShamblesService

    public init(service: ShamblesService) {
        self.service = service
    }

    /// Every group in the current snapshot, or nothing while loading or failed.
    public var groups: [Group] {
        if case .loaded(let snapshot) = state { return snapshot.groups }
        return []
    }

    public var errorMessage: String? {
        if case .failed(let message) = state { return message }
        return nil
    }

    /// Re-read everything. Called when the menu is about to open, never on a
    /// timer: a resident process that polls would turn a race with a running
    /// Claude Code session into a permanent one, and there is no lock to wait
    /// on. Reading on demand keeps the window as small as the menu is open.
    public func refresh() async {
        state = .loading
        do {
            state = .loaded(try await service.list())
        } catch let error as ShamblesError {
            state = .failed(error.message)
        } catch {
            state = .failed("Couldn't reach the shambles command.")
        }
    }
}
