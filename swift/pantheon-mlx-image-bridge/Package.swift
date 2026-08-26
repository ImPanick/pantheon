// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "pantheon-mlx-image-bridge",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "pantheon-mlx-inpaint", targets: ["PantheonMLXInpaint"]),
        .executable(name: "pantheon-mlx-colorize", targets: ["PantheonMLXColorize"]),
    ],
    dependencies: [
        .package(url: "https://github.com/xocialize/mlx-lama-swift", branch: "main"),
        .package(url: "https://github.com/xocialize/mlx-ddcolor-swift", branch: "main"),
    ],
    targets: [
        .executableTarget(
            name: "PantheonMLXInpaint",
            dependencies: [
                .product(name: "LaMa", package: "mlx-lama-swift"),
                .product(name: "MIGAN", package: "mlx-lama-swift"),
            ]
        ),
        .executableTarget(
            name: "PantheonMLXColorize",
            dependencies: [
                .product(name: "DDColor", package: "mlx-ddcolor-swift"),
            ]
        ),
    ]
)
