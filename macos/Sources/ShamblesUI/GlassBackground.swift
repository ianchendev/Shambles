import SwiftUI

/// Liquid Glass where the OS has it, a material where it does not.
///
/// The panel is a utility people reach for when something is wrong with their
/// login, so it has to work on the macOS they already have. macOS 26 gets
/// `glassEffect`; everything back to 14 gets `.regularMaterial`, which is what
/// a menu bar popover looked like before and still reads correctly.
///
/// Gated in one place so the availability check never spreads into layout
/// code.
public struct PanelBackground: ViewModifier {
    public let cornerRadius: CGFloat

    public init(cornerRadius: CGFloat = 12) {
        self.cornerRadius = cornerRadius
    }

    public func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            content.glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
        } else {
            content.background(.regularMaterial,
                               in: .rect(cornerRadius: cornerRadius))
        }
    }
}

public extension View {
    func panelBackground(cornerRadius: CGFloat = 12) -> some View {
        modifier(PanelBackground(cornerRadius: cornerRadius))
    }
}
