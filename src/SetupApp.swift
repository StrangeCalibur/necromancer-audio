// SPDX-License-Identifier: MIT
import AppKit

final class SetupApp: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let status = NSTextField(wrappingLabelWithString: "Checking the installation…")
    let detail = NSTextField(wrappingLabelWithString: "")
    let progress = NSProgressIndicator()
    var buttons: [NSButton] = []
    var diagnostic = ""
    var ready = false
    var installed = false
    var pending = false
    let queue = DispatchQueue(label: "audio.necromancer.setup")

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 620, height: 460),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Necromancer Audio Setup"
        window.center()
        let title = NSTextField(labelWithString: "Bring your Mbox 2 back to life")
        title.font = .systemFont(ofSize: 25, weight: .semibold)
        let scope = NSTextField(wrappingLabelWithString: "Original Mbox 2 • firmware 1.43 • Apple silicon • stereo audio at 48 kHz")
        scope.textColor = .secondaryLabelColor
        let note = NSTextField(wrappingLabelWithString: "Beta preparation candidate. Audio acceptance testing is still in progress. MIDI and S/PDIF are experimental.")
        note.textColor = .secondaryLabelColor
        status.font = .systemFont(ofSize: 17, weight: .medium)
        detail.textColor = .secondaryLabelColor
        let install = button("Install / Update", #selector(installDriver))
        let uninstall = button("Uninstall", #selector(uninstallDriver))
        let recover = button("Recover", #selector(recoverDriver))
        let refresh = button("Refresh", #selector(refreshStatus))
        let copy = button("Copy Diagnostics", #selector(copyDiagnostics))
        buttons = [install, uninstall, recover, refresh, copy]
        let operations = NSStackView(views: [install, uninstall, recover])
        operations.spacing = 10
        let utilities = NSStackView(views: [refresh, copy])
        utilities.spacing = 10
        progress.style = .spinning; progress.isDisplayedWhenStopped = false
        let stack = NSStackView(views: [title, scope, note, status, detail, operations, utilities, progress])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 28)
        ])
        for text in [scope, note, status, detail] { text.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true }
        let menu = NSMenu()
        let item = NSMenuItem(); let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit Necromancer Audio Setup", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu; menu.addItem(item); NSApplication.shared.mainMenu = menu
        window.makeKeyAndOrderFront(nil); NSApplication.shared.activate(ignoringOtherApps: true)
        refreshStatus()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func button(_ title: String, _ action: Selector) -> NSButton {
        NSButton(title: title, target: self, action: action)
    }
    var helper: URL { Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/setup-helper") }
    func run(_ action: String, privileged: Bool = false) -> (Int32, String) {
        do {
            let process = Process(); let output = Pipe()
            if privileged {
                let shellPath = "'" + helper.path.replacingOccurrences(of: "'", with: "'\\''") + "'"
                let command = shellPath + " " + action
                let escaped = command.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
                process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
                process.arguments = ["-e", "do shell script \"" + escaped + "\" with administrator privileges"]
            } else {
                process.executableURL = helper; process.arguments = [action]
            }
            process.standardOutput = output; process.standardError = output
            try process.run()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (process.terminationStatus, String(decoding: data, as: UTF8.self))
        } catch { return (1, error.localizedDescription) }
    }
    func json(_ text: String) -> [String: Any] {
        (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] ?? [:]
    }
    func busy(_ value: Bool) {
        if value { progress.startAnimation(nil); buttons.forEach { $0.isEnabled = false } }
        else {
            progress.stopAnimation(nil)
            buttons[0].isEnabled = ready && !pending
            buttons[1].isEnabled = installed && !pending
            buttons[2].isEnabled = pending
            buttons[3].isEnabled = true; buttons[4].isEnabled = true
        }
    }
    @objc func refreshStatus() {
        busy(true)
        queue.async {
            let (code, text) = self.run("status")
            let current = self.json(text)
            let (planCode, planText) = self.run("plan")
            DispatchQueue.main.async {
                self.installed = current["installed"] as? Bool == true
                self.pending = current["needs_recovery"] as? Bool == true
                self.ready = planCode == 0
                self.diagnostic = "Necromancer Audio Setup\n" + (Bundle.main.object(forInfoDictionaryKey: "NecromancerPrereleaseVersion") as? String ?? "") +
                    "\nInstallation status:\n" + text + "\nInstallation plan:\n" + planText +
                    "\nHardware audio acceptance: unverified by this setup app.\n"
                if self.pending {
                    self.status.stringValue = "An interrupted installation needs recovery"
                    self.detail.stringValue = "Recover restores the previous managed driver state. Save audio work before continuing."
                } else if code != 0 {
                    self.status.stringValue = "Installation needs attention"
                    self.detail.stringValue = current["error"] as? String ?? "Could not inspect the installation. Copy Diagnostics for details."
                } else if planCode != 0 {
                    self.status.stringValue = "This package cannot be installed"
                    self.detail.stringValue = self.json(planText)["error"] as? String ?? "The package did not pass its installation checks."
                } else if self.installed {
                    self.status.stringValue = "Managed driver installed: " + (current["version"] as? String ?? "")
                    self.detail.stringValue = "You can update or remove this driver. Installation status does not confirm audible playback or recording."
                } else {
                    self.status.stringValue = "Ready to install"
                    self.detail.stringValue = "Connect an original Mbox 2 with firmware 1.43 after installation. Existing firmware is required; setup does not update it."
                }
                self.busy(false)
            }
        }
    }
    func apply(_ action: String, title: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = "Save your audio work and close audio applications. This operation restarts Mac audio. Installation starts the Mbox USB service; recovery may restore and start the previous service."
        alert.addButton(withTitle: "Continue"); alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        busy(true); status.stringValue = "Applying driver change…"
        queue.async {
            let (code, text) = self.run(action, privileged: true)
            DispatchQueue.main.async {
                let result = NSAlert()
                result.messageText = code == 0 ? "Driver change completed" : "Driver change stopped"
                result.informativeText = code == 0 ? "Select Mbox 2 — Necromancer Audio in your audio application, then check playback and input at a low listening level." :
                    (self.json(text)["error"] as? String ?? text.trimmingCharacters(in: .whitespacesAndNewlines))
                result.runModal(); self.refreshStatus()
            }
        }
    }
    @objc func installDriver() { apply("install", title: installed ? "Update the managed Mbox driver?" : "Install the Mbox driver?") }
    @objc func uninstallDriver() { apply("uninstall", title: "Remove the managed Mbox driver?") }
    @objc func recoverDriver() { apply("recover", title: "Recover the interrupted installation?") }
    @objc func copyDiagnostics() {
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(diagnostic, forType: .string)
        status.stringValue = "Diagnostics copied"
    }
}
let app = NSApplication.shared
let delegate = SetupApp()
app.setActivationPolicy(.regular); app.delegate = delegate; app.run()
