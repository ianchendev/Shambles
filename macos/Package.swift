// swift-tools-version: 6.0
import PackageDescription

// Deployment target is macOS 14, not 26. Liquid Glass is used where available
// and falls back to a material below it, so the app still runs for people who
// have not upgraded -- which, for a utility whose whole job is to be there
// when you need it, matters more than looking current.
let package = Package(
    name: "Shambles",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "ShamblesKit", targets: ["ShamblesKit"]),
    ],
    targets: [
        .target(name: "ShamblesKit"),
        .testTarget(
            name: "ShamblesKitTests",
            dependencies: ["ShamblesKit"],
            // A golden file produced by the real `shambles list --json`. It is
            // what makes the contract genuinely cross-language: if Python
            // changes the shape, this stops decoding here rather than in
            // someone's menu bar.
            resources: [.copy("Fixtures")]),
    ]
)
