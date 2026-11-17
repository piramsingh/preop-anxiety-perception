// Renders the app icon: a soft night-sky gradient with a moon and stars.
// Run: swift scripts/make_icon.swift LullabyRemote/Assets.xcassets/AppIcon.appiconset/icon.png
import AppKit

let size = 1024
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = NSSize(width: size, height: size)  // 1 point = 1 pixel
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let rect = NSRect(x: 0, y: 0, width: size, height: size)
NSGradient(colors: [NSColor(srgbRed: 0.24, green: 0.20, blue: 0.58, alpha: 1),
                    NSColor(srgbRed: 0.56, green: 0.48, blue: 0.96, alpha: 1)])!
    .draw(in: rect, angle: 90)
let cfg = NSImage.SymbolConfiguration(pointSize: 520, weight: .regular)
    .applying(.init(paletteColors: [.white, NSColor(srgbRed: 1, green: 0.86, blue: 0.5, alpha: 1)]))
if let sym = NSImage(systemSymbolName: "moon.stars.fill", accessibilityDescription: nil)?
    .withSymbolConfiguration(cfg) {
    let s = sym.size
    sym.draw(in: NSRect(x: (Double(size) - s.width) / 2, y: (Double(size) - s.height) / 2,
                        width: s.width, height: s.height))
}
NSGraphicsContext.restoreGraphicsState()
// App icons must be opaque: copy into an RGB image without alpha.
let ci = CIImage(bitmapImageRep: rep)!
let ctx = CIContext()
try! ctx.writePNGRepresentation(of: ci, to: URL(fileURLWithPath: CommandLine.arguments[1]),
                                format: .RGBA8, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
