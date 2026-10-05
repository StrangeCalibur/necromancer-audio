// SPDX-License-Identifier: MIT
// Native installer engine. The shipping helper has no alternate filesystem root,
// arbitrary source path, ad-hoc acknowledgement or failure-injection interface.
import Foundation
import CryptoKit
import Darwin
import Security

let label = "audio.necromancer.mbox2.transport"
let state = "Library/Application Support/Necromancer Audio/Mbox2"
let service = state + "/mbox_service"
let driver = "Library/Audio/Plug-Ins/HAL/NecromancerMbox2.driver"
let daemon = "Library/LaunchDaemons/" + label + ".plist"
let receipt = state + "/install-receipt.json"
let journal = state + "/pending-transaction.json"
let logs = "Library/Logs/Necromancer Audio"
let targets = [service, driver, daemon]
let executables: Set<String> = [service, driver + "/Contents/MacOS/NecromancerMbox2"]
let files = executables.union([daemon, driver + "/Contents/Info.plist",
    driver + "/Contents/_CodeSignature/CodeResources"]).union(
    ["LICENSE", "libASPL-LICENSE", "libASPL-LICENSE.apple2012", "libASPL-LICENSE.apple2020"].map {
        driver + "/Contents/Resources/" + $0
    })
let fm = FileManager.default

struct SetupError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
    init(_ message: String) { self.message = message }
}
func require(_ condition: Bool, _ message: String) throws {
    if !condition { throw SetupError(message) }
}
func metadata(_ path: URL) throws -> stat? {
    var info = stat()
    if lstat(path.path, &info) == 0 { return info }
    if errno == ENOENT { return nil }
    throw SetupError("Cannot inspect " + path.lastPathComponent + ": " + String(cString: strerror(errno)))
}
func exists(_ path: URL) throws -> Bool { try metadata(path) != nil }
func noLinks(_ path: URL, boundary: URL) throws {
    let base = boundary.path
    var current = path
    try require(current.path == base || current.path.hasPrefix(base == "/" ? "/" : base + "/"), "Path escaped its allowed root.")
    while true {
        if let st = try metadata(current) { try require(st.st_mode & S_IFMT != S_IFLNK, "A symbolic link blocks installation.") }
        if current.path == base { break }
        current.deleteLastPathComponent()
    }
}
func checksum(_ path: URL) throws -> String {
    try require((try metadata(path)?.st_mode ?? 0) & S_IFMT == S_IFREG, "Expected a regular payload file.")
    return SHA256.hash(data: try Data(contentsOf: path)).map { String(format: "%02x", $0) }.joined()
}
struct Entry: Codable, Equatable { let sha256: String; let mode: UInt16 }
struct Manifest: Codable, Equatable {
    let schema: Int
    let version: String
    let architecture: String
    let minimum_macos: String
    let signing: String
    let midi_enabled: Bool
    let source_sha256: String
    let compiler: String?
    let sdk: String?
    let dependency: [String: String]?
    let developer_tools: [String: String]?
    let notarized: Bool?
    let files: [String: Entry]
    func validate() throws {
        try require(schema == 1 && architecture == "arm64" && minimum_macos == "26.4", "Unsupported package format or platform.")
        try require(!version.isEmpty && ["ad-hoc", "identity-signed"].contains(signing), "Invalid package version or signing metadata.")
        try require(Set(files.keys) == supportedFiles, "The package must contain exactly the supported audio files.")
        for (name, entry) in files {
            try require(entry.mode == (executables.contains(name) ? 0o755 : 0o644) &&
                entry.sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil, "Invalid payload checksum or permissions.")
        }
    }
}
// Use a distinct name to avoid shadowing Manifest.files inside validate().
let supportedFiles = files
func readManifest(_ path: URL) throws -> Manifest {
    try noLinks(path, boundary: URL(fileURLWithPath: "/"))
    let st = try metadata(path)
    try require(st != nil && st!.st_mode & S_IFMT == S_IFREG && st!.st_size <= 262144, "Missing or invalid installation manifest.")
    let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: path))
    try manifest.validate()
    return manifest
}
func pathsUnder(_ root: URL) throws -> [(String, Bool)] {
    if !(try exists(root)) { return [] }
    var result: [(String, Bool)] = []
    func walk(_ dir: URL) throws {
        for url in try fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) {
            let st = try metadata(url)!
            let kind = st.st_mode & S_IFMT
            try require(kind == S_IFREG || kind == S_IFDIR, "Unexpected payload file type.")
            result.append((String(url.path.dropFirst(root.path.count + 1)), kind == S_IFDIR))
            if kind == S_IFDIR { try walk(url) }
        }
    }
    try walk(root)
    return result
}
func verify(_ base: URL, _ manifest: Manifest, exact: Bool) throws {
    try noLinks(base, boundary: URL(fileURLWithPath: "/"))
    for (name, entry) in manifest.files {
        let url = base.appendingPathComponent(name)
        try noLinks(url, boundary: base)
        try require(try checksum(url) == entry.sha256, "A payload file is missing or changed: " + URL(fileURLWithPath: name).lastPathComponent)
    }
    let inspected = exact ? base : base.appendingPathComponent(driver)
    let prefix = exact ? "" : driver + "/"
    let expected = exact ? supportedFiles : Set(supportedFiles.filter { $0.hasPrefix(prefix) })
    var allowedDirs = Set<String>()
    for name in expected {
        var parent = URL(fileURLWithPath: "/" + name).deletingLastPathComponent()
        while parent.path != "/" { allowedDirs.insert(String(parent.path.dropFirst())); parent.deleteLastPathComponent() }
    }
    let actual = try pathsUnder(inspected)
    try require(Set(actual.filter { !$0.1 }.map { prefix + $0.0 }) == expected, "Unmanaged or missing payload files found.")
    try require(actual.filter { $0.1 }.allSatisfy { allowedDirs.contains(prefix + $0.0) }, "Unexpected payload directory found.")
}
func verifyDaemon(_ base: URL, _ manifest: Manifest) throws {
    let object = try PropertyListSerialization.propertyList(from: Data(contentsOf: base.appendingPathComponent(daemon)), options: [], format: nil)
    guard let plist = object as? [String: Any], let args = plist["ProgramArguments"] as? [String] else { throw SetupError("Invalid service configuration.") }
    let fields: Set<String> = ["Label", "ProgramArguments", "MachServices", "RunAtLoad", "KeepAlive", "ThrottleInterval", "ProcessType", "Umask", "StandardOutPath", "StandardErrorPath"]
    try require(Set(plist.keys) == fields && plist["Label"] as? String == label && args.prefix(2) == ["/" + service, "--serve-capture"], "Unexpected service configuration.")
    var tail = Array(args.dropFirst(2))
    if tail.first == "--location-id" {
        try require(tail.count >= 2 && UInt32(tail[1]) != nil, "Invalid USB location selection.")
        tail.removeFirst(2)
    }
    try require(tail == (manifest.midi_enabled ? ["--enable-midi"] : []) &&
        (plist["MachServices"] as? [String: Bool]) == [label: true] && plist["Umask"] as? Int == 0o027 &&
        plist["RunAtLoad"] as? Bool == true && plist["KeepAlive"] as? [String: Bool] == ["SuccessfulExit": false] &&
        plist["ThrottleInterval"] as? Int == 10 && plist["ProcessType"] as? String == "Interactive" &&
        plist["StandardOutPath"] as? String == "/" + logs + "/mbox2.log" &&
        plist["StandardErrorPath"] as? String == "/" + logs + "/mbox2.err.log", "Unexpected service options.")
}
@discardableResult
func command(_ executable: String, _ arguments: [String], checked: Bool = true) throws -> Int32 {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    // Output is bounded by the system commands used here and kept out of product diagnostics.
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    try process.run(); process.waitUntilExit()
    if checked { try require(process.terminationStatus == 0, "A system operation failed: " + URL(fileURLWithPath: executable).lastPathComponent) }
    return process.terminationStatus
}
struct Journal: Codable {
    let schema: Int
    let transaction: String
    let had_previous: Bool
    let was_running: Bool
    let new_manifest: Manifest?
}
final class Installer {
    let root: URL
    let source: URL
    let live: Bool
    var testRunning = false
    var testFailure = ""
    init(root: URL = URL(fileURLWithPath: "/"), source: URL) {
        self.root = root; self.source = source
        self.live = root.path == "/"
    }
    func path(_ name: String) throws -> URL {
        let result = root.appendingPathComponent(name)
        try noLinks(result, boundary: root)
        return result
    }
    func protected(_ url: URL) throws {
        guard live else { return }
        var current = url
        while current.path != root.path {
            if let st = try metadata(current) { try require(st.st_uid == 0 && st.st_mode & 0o022 == 0, "Installation paths must be protected by the administrator.") }
            current.deleteLastPathComponent()
        }
    }
    func mkdir(_ url: URL, mode: mode_t = 0o755) throws {
        try noLinks(url, boundary: root)
        if try exists(url) {
            try require(try metadata(url)!.st_mode & S_IFMT == S_IFDIR, "Expected an installation directory.")
            try protected(url); return
        }
        try mkdir(url.deletingLastPathComponent())
        try fm.createDirectory(at: url, withIntermediateDirectories: false)
        try require(chmod(url.path, mode) == 0, "Cannot protect an installation directory.")
    }
    func sync(_ url: URL) throws {
        let fd = open(url.path, O_RDONLY | O_NOFOLLOW)
        try require(fd >= 0, "Cannot flush installation state.")
        defer { close(fd) }
        try require(fsync(fd) == 0, "Cannot flush installation state.")
    }
    func write(_ url: URL, data: Data, mode: mode_t) throws {
        try mkdir(url.deletingLastPathComponent())
        let temp = url.appendingPathExtension("next")
        try noLinks(temp, boundary: root)
        let fd = open(temp.path, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW, mode)
        try require(fd >= 0, "A pending file blocks this operation. Use Recover.")
        defer { close(fd) }
        let stream = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
        try stream.write(contentsOf: data)
        try require(fchmod(fd, mode) == 0 && fsync(fd) == 0, "Cannot flush a payload file.")
        try require(rename(temp.path, url.path) == 0, "Cannot replace a payload file.")
        try sync(url.deletingLastPathComponent())
    }
    func writeJSON<T: Encodable>(_ name: String, _ value: T) throws {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try write(path(name), data: encoder.encode(value), mode: 0o600)
    }
    func running() throws -> Bool {
        if !live { return testRunning }
        return try command("/bin/launchctl", ["print", "system/" + label], checked: false) == 0
    }
    func stop() throws {
        if !live { testRunning = false; return }
        try command("/bin/launchctl", ["bootout", "system/" + label])
    }
    func start() throws {
        if !live {
            if testFailure == "start" { testFailure = ""; throw SetupError("Injected service start failure.") }
            testRunning = true; return
        }
        try command("/bin/launchctl", ["bootstrap", "system", "/" + daemon])
    }
    func restartAudio() throws {
        if live { try command("/usr/bin/killall", ["coreaudiod"], checked: false) }
    }
    func installed(ignoreOrphan: Bool = false) throws -> Manifest? {
        try require(!(try exists(path(journal))), "An interrupted installation needs Recover before another change.")
        if !ignoreOrphan { try require(!(try exists(path(journal + ".next"))), "An incomplete installation needs Recover.") }
        if !(try exists(path(receipt))) {
            for name in targets { try require(!(try exists(path(name))), "An existing prototype or unmanaged installation is present. Its files have been preserved; migration is required.") }
            return nil
        }
        try protected(path(receipt))
        let current = try readManifest(path(receipt))
        try verify(root, current, exact: false)
        for (name, entry) in current.files {
            let url = try path(name); try protected(url)
            try require(try metadata(url)!.st_mode & 0o777 == entry.mode, "Installed file permissions have changed.")
        }
        return current
    }
    func trustedPackage(_ base: URL, _ manifest: Manifest) throws {
        guard live else { return }
        try require(manifest.signing == "identity-signed", "This setup app requires a Developer ID signed payload.")
        var code: SecStaticCode?
        try require(SecStaticCodeCreateWithPath(URL(fileURLWithPath: CommandLine.arguments[0]) as CFURL, [], &code) == errSecSuccess, "Cannot identify the setup helper.")
        var info: CFDictionary?
        try require(SecCodeCopySigningInformation(code!, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess, "Cannot read the setup signature.")
        guard let team = (info as? [String: Any])?[kSecCodeInfoTeamIdentifier as String] as? String,
              team.range(of: "^[A-Z0-9]{10}$", options: .regularExpression) != nil else { throw SetupError("A Developer ID signature is required.") }
        let rule = "anchor apple generic and certificate leaf[subject.OU] = \"" + team + "\""
        for item in [base.appendingPathComponent(service), base.appendingPathComponent(driver)] {
            try command("/usr/bin/codesign", ["--verify", "--strict", "-R=" + rule, item.path])
        }
    }
    func verifyPackage() throws -> Manifest {
        let new = try readManifest(source.appendingPathComponent("manifest.json"))
        try require(!new.midi_enabled, "This setup app supports the audio-only package.")
        try verify(source.appendingPathComponent("payload"), new, exact: true)
        try verifyDaemon(source.appendingPathComponent("payload"), new)
        try trustedPackage(source.appendingPathComponent("payload"), new)
        return new
    }
    func preflight(install: Bool) throws -> (Manifest?, Manifest?) {
        for name in targets + [receipt, logs] { try protected(path(name)) }
        for leaf in ["mbox2.log", "mbox2.err.log"] {
            let url = try path(logs + "/" + leaf); try protected(url)
            if let st = try metadata(url) { try require(st.st_mode & S_IFMT == S_IFREG, "An unexpected log file blocks installation.") }
        }
        let old = try installed()
        if !install { try require(old != nil, "No managed driver is installed."); return (old, nil) }
        let new = try verifyPackage()
        return (old, new)
    }
    func guardMutation() throws {
        if live {
            try require(geteuid() == 0, "Administrator authentication is required.")
            let os = ProcessInfo.processInfo.operatingSystemVersion
            try require(os.majorVersion > 26 || (os.majorVersion == 26 && os.minorVersion >= 4), "macOS 26.4 or newer is required.")
            // Verify the containing app's resource seal before trusting its embedded manifest.
            let app = source.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            try require(app.pathExtension == "app", "Run the helper from its setup app.")
            try command("/usr/bin/codesign", ["--verify", "--strict", "-R=anchor apple generic", app.path])
        }
    }
    func withLock<T>(_ body: () throws -> T) throws -> T {
        let url = try path(state + "/.installer.lock")
        try mkdir(url.deletingLastPathComponent()); try protected(url)
        let fd = open(url.path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        try require(fd >= 0, "Cannot acquire installation lock.")
        defer { close(fd) }
        var st = stat(); try require(fstat(fd, &st) == 0 && st.st_mode & S_IFMT == S_IFREG, "Invalid installation lock.")
        try require(flock(fd, LOCK_EX | LOCK_NB) == 0, "Another installation is running.")
        return try body()
    }
    func copyPayload(_ from: URL, _ manifest: Manifest) throws {
        for (name, entry) in manifest.files.sorted(by: { $0.key < $1.key }) {
            try write(path(name), data: Data(contentsOf: from.appendingPathComponent(name)), mode: mode_t(entry.mode))
        }
    }
    func removePayload() throws {
        for name in targets + [receipt] {
            let url = try path(name)
            if try exists(url) { try fm.removeItem(at: url); try sync(url.deletingLastPathComponent()) }
        }
    }
    func clearJournal() throws {
        let url = try path(journal)
        if try exists(url) { try fm.removeItem(at: url) }
        try sync(path(state))
    }
    func recoveryValidation(_ old: Manifest?, _ new: Manifest?) throws {
        var allowedDirs = Set<String>()
        for name in supportedFiles {
            var url = URL(fileURLWithPath: "/" + name).deletingLastPathComponent()
            while url.path != "/" { allowedDirs.insert(String(url.path.dropFirst())); url.deleteLastPathComponent() }
        }
        for (name, isDir) in try pathsUnder(path(driver)) {
            let full = driver + "/" + name
            try require(isDir ? allowedDirs.contains(full) : (supportedFiles.contains(full) || supportedFiles.contains(String(full.dropLast(5))) && full.hasSuffix(".next")), "Recovery found unmanaged driver contents.")
        }
        for name in supportedFiles {
            let url = try path(name); try protected(url)
            if try exists(url) {
                let hashes = [old, new].compactMap { $0?.files[name]?.sha256 }
                try require(try hashes.contains(checksum(url)), "Recovery found an unknown installed file.")
            }
            let temp = try path(name + ".next"); try protected(temp)
            if let st = try metadata(temp) { try require(st.st_mode & S_IFMT == S_IFREG, "Recovery found an invalid temporary file.") }
        }
        let url = try path(receipt); try protected(url)
        if try exists(url) { let value = try readManifest(url); try require(value == old || value == new, "Recovery found an unknown receipt.") }
        let temp = try path(receipt + ".next"); try protected(temp)
        if let st = try metadata(temp) { try require(st.st_mode & S_IFMT == S_IFREG, "Recovery found an invalid temporary receipt.") }
    }
    func recover() throws -> [String: Any] {
        try guardMutation()
        return try withLock { try recoveryBody() }
    }
    private func recoveryBody() throws -> [String: Any] {
            let url = try path(journal); try protected(url)
            if !(try exists(url)) {
                let orphan = try path(journal + ".next"); try protected(orphan)
                try require((try metadata(orphan)?.st_mode ?? 0) & S_IFMT == S_IFREG, "No interrupted installation was found.")
                let old = try installed(ignoreOrphan: true)
                try fm.removeItem(at: orphan); try sync(orphan.deletingLastPathComponent())
                return ["recovered": true, "installed": old != nil, "version": old?.version ?? "", "coreaudio_restarted": false]
            }
            try require(try metadata(url)!.st_size <= 262144, "Invalid recovery journal.")
            let data = try JSONDecoder().decode(Journal.self, from: Data(contentsOf: url))
            try require(data.schema == 1 && data.transaction.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil, "Invalid recovery journal.")
            try data.new_manifest?.validate()
            let backup = try path(state + "/Recovery/" + data.transaction)
            let old = data.had_previous ? try readManifest(backup.appendingPathComponent("manifest.json")) : nil
            if let old { try protected(backup); try verify(backup.appendingPathComponent("payload"), old, exact: true) }
            try recoveryValidation(old, data.new_manifest)
            if try running() { try stop() }
            try removePayload()
            for name in supportedFiles.union([receipt]) {
                let temp = try path(name + ".next"); if try exists(temp) { try fm.removeItem(at: temp) }
            }
            if let old {
                try copyPayload(backup.appendingPathComponent("payload"), old)
                try writeJSON(receipt, old); try verify(root, old, exact: false)
                if data.was_running { try start() }
            }
            try restartAudio(); try clearJournal()
            let staging = try path(state + "/.staging-" + data.transaction)
            if try exists(staging) { try fm.removeItem(at: staging) }
            return ["recovered": true, "installed": old != nil, "version": old?.version ?? "", "hardware_audio_verified": false]
    }
    func transact(install: Bool) throws -> [String: Any] {
        try guardMutation(); _ = try preflight(install: install)
        return try withLock {
            let (old, new) = try preflight(install: install)
            let wasRunning = try running()
            try require(!wasRunning || old != nil, "An unmanaged service already owns this driver.")
            let transaction = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
            let staging = try path(state + "/.staging-" + transaction)
            let backup = try path(state + "/Recovery/" + transaction)
            try mkdir(staging, mode: 0o700)
            if let new {
                try fm.copyItem(at: source.appendingPathComponent("payload"), to: staging.appendingPathComponent("payload"))
                try verify(staging.appendingPathComponent("payload"), new, exact: true)
                try trustedPackage(staging.appendingPathComponent("payload"), new)
            }
            if let old {
                try mkdir(backup, mode: 0o700)
                for name in old.files.keys {
                    let target = backup.appendingPathComponent("payload/" + name)
                    try mkdir(target.deletingLastPathComponent())
                    try write(target, data: Data(contentsOf: path(name)), mode: mode_t(old.files[name]!.mode))
                }
                try write(backup.appendingPathComponent("manifest.json"), data: Data(contentsOf: path(receipt)), mode: 0o600)
                try verify(backup.appendingPathComponent("payload"), old, exact: true)
                try sync(backup); try sync(backup.deletingLastPathComponent())
            }
            try writeJSON(journal, Journal(schema: 1, transaction: transaction, had_previous: old != nil, was_running: wasRunning, new_manifest: new))
            do {
                if wasRunning { try stop() }
                try removePayload()
                #if SETUP_TEST
                if testFailure == "interrupt" { Darwin.exit(99) }
                #endif
                if let new {
                    try copyPayload(staging.appendingPathComponent("payload"), new)
                    try mkdir(path(logs))
                    for leaf in ["mbox2.log", "mbox2.err.log"] {
                        let log = try path(logs + "/" + leaf)
                        if !(try exists(log)) { try write(log, data: Data(), mode: 0o640) }
                    }
                    try verify(root, new, exact: false); try writeJSON(receipt, new); try start()
                }
                try restartAudio(); try clearJournal(); try fm.removeItem(at: staging)
            } catch {
                let original = error.localizedDescription
                do { _ = try recoveryBody() } catch {
                    throw SetupError("Installation failed and recovery needs attention. The protected journal and backup were retained. " + error.localizedDescription)
                }
                throw SetupError("Installation failed; the previous driver state was restored. " + original)
            }
            return ["installed": new != nil, "version": new?.version ?? "", "coreaudio_restarted": true, "hardware_audio_verified": false]
        }
    }

}

let args = Array(CommandLine.arguments.dropFirst())
do {
    guard let action = args.first, ["verify-package", "plan", "status", "install", "uninstall", "recover"].contains(action) else { throw SetupError("Choose verify-package, plan, status, install, uninstall or recover.") }
    let helper = URL(fileURLWithPath: CommandLine.arguments[0])
    var source = helper.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Resources/Release")
    var root = URL(fileURLWithPath: "/")
    var failure = ""
    #if SETUP_TEST
    var i = 1
    while i < args.count {
        try require(i + 1 < args.count, "Missing test argument.")
        switch args[i] {
        case "--test-root": root = URL(fileURLWithPath: args[i + 1]); try require(root.resolvingSymlinksInPath().path != "/", "Tests cannot use the live system root.")
        case "--source": source = URL(fileURLWithPath: args[i + 1])
        case "--test-failure": failure = args[i + 1]
        default: throw SetupError("Unknown test argument.")
        }
        i += 2
    }
    try require(root.path != "/", "A temporary test root is required.")
    #else
    try require(args.count == 1, "Unknown setup argument.")
    #endif
    let installer = Installer(root: root, source: source); installer.testFailure = failure
    let result: [String: Any]
    switch action {
    case "verify-package":
        let package = try installer.verifyPackage()
        result = ["package_verified": true, "version": package.version, "signing": package.signing, "installation_performed": false]
    case "status":
        let pending = try exists(installer.path(journal)) || exists(installer.path(journal + ".next"))
        if pending { result = ["installed": false, "needs_recovery": true] }
        else { let old = try installer.installed(); result = ["installed": old != nil, "version": old?.version ?? "", "needs_recovery": false] }
    case "plan":
        let (old, new) = try installer.preflight(install: true)
        result = ["preflight": true, "version": new!.version, "replaces": old?.version ?? "", "signing": new!.signing,
                  "restarts_coreaudio": true, "initializes_usb_on_start": true, "firmware_write": false]
    case "recover": result = try installer.recover()
    default: result = try installer.transact(install: action == "install")
    }
    let encoded = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
    print(String(data: encoded, encoding: .utf8)!)
} catch {
    let data = try! JSONSerialization.data(withJSONObject: ["error": error.localizedDescription], options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
    Darwin.exit(1)
}
