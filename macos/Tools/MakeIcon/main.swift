import AppKit
import CoreGraphics

// Draws the app icon and writes an .iconset, which `iconutil` turns into
// AppIcon.icns. Generated rather than committed as binaries so the design is
// reviewable in a diff — a change to the icon shows up as a change to this
// file, not as an opaque blob.
//
// The mark is two overlapping discs: one filled, one outlined. Two accounts,
// one of them live. It has to survive 16pt in the Finder sidebar, so there is
// no fine detail and no text — anything thinner than a couple of points
// disappears at that size.

let sizes = [16, 32, 64, 128, 256, 512, 1024]
let outputDirectory = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1] : "./AppIcon.iconset"

try? FileManager.default.createDirectory(
    atPath: outputDirectory, withIntermediateDirectories: true)

func draw(size: Int) -> Data? {
    let side = CGFloat(size)
    guard let context = CGContext(
        data: nil, width: size, height: size, bitsPerComponent: 8,
        bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }

    // macOS rounds its own icon masks, but a squircle drawn here keeps the
    // artwork correct if the icon is ever shown unmasked.
    let inset = side * 0.06
    let plate = CGRect(x: inset, y: inset, width: side - inset * 2,
                       height: side - inset * 2)
    let plateRadius = plate.width * 0.22
    context.addPath(CGPath(roundedRect: plate, cornerWidth: plateRadius,
                           cornerHeight: plateRadius, transform: nil))
    context.setFillColor(CGColor(red: 0.106, green: 0.118, blue: 0.141, alpha: 1))
    context.fillPath()

    let radius = side * 0.20
    let offset = side * 0.115
    let centre = CGPoint(x: side / 2, y: side / 2)

    // Back disc: the account you are not on. Outlined, so it reads as absent
    // rather than merely darker — a fill difference alone vanishes in dark
    // mode and at small sizes.
    let back = CGRect(x: centre.x - offset - radius, y: centre.y - radius,
                      width: radius * 2, height: radius * 2)
    context.setLineWidth(max(1, side * 0.045))
    context.setStrokeColor(CGColor(red: 0.62, green: 0.66, blue: 0.72, alpha: 1))
    context.strokeEllipse(in: back)

    // Front disc: the live account. Knocked out of the back one first so the
    // two stay distinct where they overlap.
    let front = CGRect(x: centre.x + offset - radius, y: centre.y - radius,
                       width: radius * 2, height: radius * 2)
    context.setBlendMode(.clear)
    context.fillEllipse(in: front.insetBy(dx: -side * 0.035, dy: -side * 0.035))
    context.setBlendMode(.normal)
    context.setFillColor(CGColor(red: 0.85, green: 0.55, blue: 0.35, alpha: 1))
    context.fillEllipse(in: front)

    guard let image = context.makeImage() else { return nil }
    let rep = NSBitmapImageRep(cgImage: image)
    rep.size = NSSize(width: side, height: side)
    return rep.representation(using: .png, properties: [:])
}

// The iconset naming Apple expects: each logical size at 1x and 2x.
for size in sizes {
    guard let data = draw(size: size) else { continue }
    let base = size <= 512 ? "icon_\(size)x\(size).png" : nil
    if let base {
        try? data.write(to: URL(fileURLWithPath: "\(outputDirectory)/\(base)"))
    }
    let half = size / 2
    if half >= 16 {
        try? data.write(to: URL(fileURLWithPath:
            "\(outputDirectory)/icon_\(half)x\(half)@2x.png"))
    }
}

print("wrote \(outputDirectory)")
