import SwiftUI
import ShamblesKit

/// The panel, and nothing but the rendering of it.
///
/// Every rule this file appears to apply was already decided in Python:
/// `account.state`, `account.needsLogin`, `window.usedPercent == nil`,
/// `window.stale`. Nothing here recomputes any of them, and adding arithmetic
/// on a date or a percentage to this file would create a second copy of a
/// tested rule -- the drift the layering exists to prevent.
///
/// Provider names are never hardcoded. The panel renders whatever groups and
/// surfaces the contract contains, so a third provider needs no change here.
@available(macOS 14, *)
public struct PanelView: View {
    @State private var model: AccountsViewModel
    private let onSelect: (AccountGroup, Account) -> Void

    public init(model: AccountsViewModel,
                onSelect: @escaping (AccountGroup, Account) -> Void = { _, _ in }) {
        _model = State(initialValue: model)
        self.onSelect = onSelect
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch model.state {
            case .idle, .loading:
                LoadingRow()
            case .failed(let message):
                MessageRow(text: message, tone: .red)
            case .loaded(let snapshot):
                if snapshot.groups.allSatisfy({ $0.accounts.isEmpty }) {
                    MessageRow(text: "No accounts saved yet.", tone: .secondary)
                }
                ForEach(snapshot.groups) { group in
                    if group.id != snapshot.groups.first?.id {
                        Divider().padding(.vertical, 2)
                    }
                    GroupSection(group: group) { onSelect(group, $0) }
                }
            }
        }
        .padding(.vertical, 6)
        .frame(width: 356)
        .panelBackground()
        .task { await model.refresh() }
    }
}

// MARK: - AccountGroup

@available(macOS 14, *)
struct GroupSection: View {
    let group: AccountGroup
    let onSelect: (Account) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Text(group.displayName).font(.system(size: 13, weight: .medium))
                Spacer(minLength: 8)
                // The pills carry the one thing a person cannot guess: that
                // this single switch moves every application listed. Without
                // them "why did VS Code change too" needs explaining.
                ForEach(group.surfaces) { SurfacePill(surface: $0) }
            }
            .padding(.horizontal, 12)
            .padding(.top, 5)
            .padding(.bottom, 4)

            ForEach(group.accounts) { account in
                AccountRow(account: account) { onSelect(account) }
            }
        }
    }
}

@available(macOS 14, *)
struct SurfacePill: View {
    let surface: Surface

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: Self.symbol(for: surface.id))
                .font(.system(size: 9))
            Text(surface.label).font(.system(size: 10))
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 5)
        .padding(.vertical, 1)
        .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 5))
        .help(surface.detail)
    }

    /// Icons are looked up by id with a fallback, never switched on
    /// exhaustively, so an unknown surface from a newer CLI still renders.
    static func symbol(for id: String) -> String {
        switch id {
        case "terminal": return "terminal"
        case "vscode": return "chevron.left.forwardslash.chevron.right"
        case "chatgpt", "desktop": return "macwindow"
        default: return "app.dashed"
        }
    }
}

// MARK: - Account

@available(macOS 14, *)
struct AccountRow: View {
    let account: Account
    let onSelect: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 7) {
                    Image(systemName: statusSymbol)
                        .font(.system(size: 12))
                        .foregroundStyle(statusColor)
                        .frame(width: 14)
                    Text(account.name)
                        .font(.system(size: 13))
                        .foregroundStyle(account.active ? Color.accentColor : .primary)
                    Spacer(minLength: 6)
                    if let plan = account.plan {
                        PlanBadge(plan: plan)
                    }
                }
                HStack(spacing: 8) {
                    // A closed window is the handoff point, so the row shows
                    // the command instead of details that no longer matter.
                    if account.needsLogin, let hint = account.loginHint {
                        Text(hint)
                            .font(.system(size: 10))
                            .foregroundStyle(.red)
                            .lineLimit(1)
                    } else {
                        Text(account.email ?? "Unknown account")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                        Spacer(minLength: 6)
                        ForEach(account.usage) { UsageGauge(window: $0) }
                    }
                }
                .padding(.leading, 21)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
            .contentShape(.rect)
            .background(rowBackground)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }

    var statusSymbol: String {
        if account.active { return "checkmark.circle.fill" }
        return account.needsLogin ? "exclamationmark.circle" : "circle"
    }

    var statusColor: Color {
        if account.active { return .accentColor }
        return account.needsLogin ? .red : .secondary
    }

    var rowBackground: Color {
        if account.active { return Color.accentColor.opacity(0.12) }
        return hovering ? Color.primary.opacity(0.06) : .clear
    }
}

@available(macOS 14, *)
struct PlanBadge: View {
    let plan: String

    var body: some View {
        Text(Self.pretty(plan))
            .font(.system(size: 10))
            .foregroundStyle(.tint)
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(.tint.opacity(0.14), in: .rect(cornerRadius: 5))
    }

    /// Turns a rate-limit tier into something a person recognises.
    ///
    /// The accurate plan field is `organizationRateLimitTier`, which arrives
    /// as `default_claude_max_5x`. The credential store's own
    /// `subscriptionType` is not used: it read "team" for a Max 5x account.
    static func pretty(_ raw: String) -> String {
        var text = raw
        for prefix in ["default_claude_", "default_", "claude_"] where text.hasPrefix(prefix) {
            text = String(text.dropFirst(prefix.count))
            break
        }
        return text
            .split(separator: "_")
            .map { $0.count <= 3 ? $0.uppercased() : $0.capitalized }
            .joined(separator: " ")
    }
}

// MARK: - Usage

@available(macOS 14, *)
struct UsageGauge: View {
    let window: UsageWindow

    var body: some View {
        HStack(spacing: 4) {
            if window.stale {
                Image(systemName: "clock").font(.system(size: 9))
                    .foregroundStyle(.tertiary)
            }
            Text(window.label).font(.system(size: 10)).foregroundStyle(.tertiary)
            Capsule()
                .fill(.quaternary)
                .frame(width: 22, height: 4)
                .overlay(alignment: .leading) {
                    if let percent = window.usedPercent {
                        Capsule().fill(fill)
                            .frame(width: 22 * CGFloat(min(percent, 100)) / 100, height: 4)
                    }
                }
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(textStyle)
                .frame(width: 26, alignment: .trailing)
        }
    }

    /// A window whose reset time has passed arrives with no figure. Showing a
    /// stale percentage would misinform the decision the user is about to
    /// make, so it renders as a dash.
    var label: String {
        guard let percent = window.usedPercent else { return "—" }
        return "\(percent)%"
    }

    var fill: Color {
        if window.stale { return .secondary }
        return (window.usedPercent ?? 0) >= 80 ? .orange : .accentColor
    }

    var textStyle: Color {
        if window.stale || window.usedPercent == nil { return .secondary }
        return (window.usedPercent ?? 0) >= 80 ? .orange : .primary
    }
}

// MARK: - Placeholders

@available(macOS 14, *)
struct LoadingRow: View {
    var body: some View {
        HStack(spacing: 7) {
            ProgressView().controlSize(.small)
            Text("Reading accounts…").font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
    }
}

@available(macOS 14, *)
struct MessageRow: View {
    let text: String
    let tone: Color

    var body: some View {
        Text(text)
            .font(.system(size: 12))
            .foregroundStyle(tone)
            .padding(.horizontal, 12).padding(.vertical, 8)
    }
}
