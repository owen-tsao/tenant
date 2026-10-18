// A transparent local renderer. No microphone, audio output, server or browser automation.
import AppKit
import WebKit

func emit(_ value: [String: Any]) {
    if let bytes = try? JSONSerialization.data(withJSONObject: value),
       let text = String(data: bytes, encoding: .utf8) {
        FileHandle.standardOutput.write(Data((text + "\n").utf8))
    }
}

final class OrbHost: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var latest: [String: Any]?
    var ready = false
    var lastInput = Date()
    var watchdog: Timer?
    var input = Data()
    let args = CommandLine.arguments

    func option(_ name: String) -> String? {
        guard let index = args.firstIndex(of: name), args.count > index + 1 else { return nil }
        return args[index + 1]
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let assets = option("--assets"), assets.hasPrefix("/"),
              FileManager.default.fileExists(atPath: assets + "/index.html") else {
            fail("Orb assets are missing."); return
        }
        let controller = WKUserContentController()
        controller.addUserScript(WKUserScript(source: "console.error = function(...v) {window.webkit.messageHandlers.tenantOrb.postMessage({type:'error', message:v.map(String).join(' ')});};", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        controller.add(self, name: "tenantOrb")
        let config = WKWebViewConfiguration()
        config.userContentController = controller
        let screen = NSScreen.screens.first(where: { $0 != NSScreen.screens.first }) ?? NSScreen.main!
        let area = screen.visibleFrame
        let side = min(820.0, area.height * 0.86, area.width * 0.75)
        let rect = NSRect(x: area.midX - side / 2, y: area.midY - side / 2, width: side, height: side)
        window = NSWindow(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        window.title = "Tenant Live Orb"
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]
        web = WKWebView(frame: NSRect(origin: .zero, size: rect.size), configuration: config)
        web.navigationDelegate = self
        web.underPageBackgroundColor = .clear
        // WebKit's macOS background flag is required in addition to transparent CSS.
        web.setValue(false, forKey: "drawsBackground")
        window.contentView = web
        let root = URL(fileURLWithPath: assets, isDirectory: true)
        web.loadFileURL(root.appendingPathComponent("index.html"), allowingReadAccessTo: root)
        window.orderFrontRegardless()
        FileHandle.standardInput.readabilityHandler = { handle in
            let bytes = handle.availableData
            DispatchQueue.main.async { [weak self] in self?.receive(bytes) }
        }
        watchdog = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            // No abandoned overlay if the audio owner stalls or dies.
            if Date().timeIntervalSince(self.lastInput) > 3 { NSApp.terminate(nil) }
        }
        if let seconds = option("--seconds"), let timeout = Double(seconds), timeout > 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + min(timeout, 60)) { NSApp.terminate(nil) }
        }
    }

    func receive(_ bytes: Data) {
        if bytes.isEmpty { NSApp.terminate(nil); return }
        input.append(bytes)
        if input.count > 65536 { fail("Invalid orb input."); return }
        while let end = input.firstIndex(of: 10) {
            let line = input[..<end]
            input.removeSubrange(...end)
            guard let value = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any],
                  let level = value["level"] as? Double, level.isFinite, (0...1).contains(level),
                  let position = value["playhead_seconds"] as? Double, position.isFinite, position >= 0,
                  let playing = value["playing"] as? Bool else { fail("Invalid orb sample."); return }
            latest = ["level": level, "playhead_seconds": position, "playing": playing]
            lastInput = Date()
            if ready { publish() }
        }
    }

    func publish() {
        guard let sample = latest, let data = try? JSONSerialization.data(withJSONObject: sample),
              let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.tenantOrb.sample(" + json + ")") { _, error in
            if error != nil { self.fail("The orb could not consume the audio sample.") }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let value = message.body as? [String: Any] else { return }
        if value["type"] as? String == "diagnostic" {
            FileHandle.standardError.write(Data((String(describing: value) + "\n").utf8)); return
        }
        if value["type"] as? String == "error" {
            FileHandle.standardError.write(Data((String(describing: value) + "\n").utf8))
            fail("The supplied orb did not render."); return
        }
        if value["type"] as? String == "ready", !ready,
           value["webgl"] as? Bool == true, value["transparent"] as? Bool == true {
            ready = true
            publish()
            emit(["type": "ready", "webgl": true, "transparent": !window.isOpaque,
                  "width": window.frame.width, "height": window.frame.height,
                  "x": window.frame.origin.x, "y": window.frame.origin.y])
            if let path = option("--snapshot") {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    self.web.takeSnapshot(with: nil) { image, error in
                        guard let image = image, error == nil, let tiff = image.tiffRepresentation,
                              let bitmap = NSBitmapImageRep(data: tiff),
                              let png = bitmap.representation(using: .png, properties: [:]) else { return }
                        try? png.write(to: URL(fileURLWithPath: path))
                    }
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        fail("The local orb page could not load.")
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { fail("The orb renderer exited.") }
    func fail(_ message: String) { emit(["type": "error", "message": message]); NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) {
        FileHandle.standardInput.readabilityHandler = nil
        watchdog?.invalidate()
        window?.orderOut(nil)
    }
}

let app = NSApplication.shared
let host = OrbHost()
app.setActivationPolicy(.accessory)
app.delegate = host
app.run()
