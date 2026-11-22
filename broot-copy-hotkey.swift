// A Carbon hotkey needs no Accessibility or Input Monitoring permission.
// Register Cmd+C and Cmd+R while this Broot owns Ghostty's active tmux pane.
import Cocoa
import Carbon.HIToolbox

let pane = ProcessInfo.processInfo.environment["TMUX_PANE"] ?? ""
let tmux = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "/opt/homebrew/bin/tmux"
var hotkey: EventHotKeyRef?
var revealHotkey: EventHotKeyRef?
var checking = false
let signature: OSType = 0x42524350
let statusPath = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : ""
var lastStatus = ""

func status(_ value: String) {
    guard value != lastStatus else { return }
    lastStatus = value
    if !statusPath.isEmpty { try? value.write(toFile: statusPath, atomically: true, encoding: .utf8) }
}

if CommandLine.arguments.contains("--check-registration") {
    let id = EventHotKeyID(signature: signature, id: 1)
    let result = RegisterEventHotKey(UInt32(kVK_ANSI_C), UInt32(cmdKey), id,
                                     GetApplicationEventTarget(), 0, &hotkey)
    if let ref = hotkey { UnregisterEventHotKey(ref) }
    print("Cmd+C registration status: \(result)")
    exit(result == noErr ? 0 : 1)
}

func ghosttyIsFrontmost() -> Bool {
    NSWorkspace.shared.frontmostApplication?.bundleIdentifier == "com.mitchellh.ghostty"
}

func unregister() {
    if let ref = hotkey { UnregisterEventHotKey(ref); hotkey = nil }
    if let ref = revealHotkey { UnregisterEventHotKey(ref); revealHotkey = nil }
    status("inactive")
}

func update() {
    guard ghosttyIsFrontmost(), !pane.isEmpty else { unregister(); return }
    guard !checking else { return }
    checking = true
    DispatchQueue.global().async {
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: tmux)
        process.arguments = ["display-message", "-p", "#{pane_id}"]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        var active = ""
        do {
            try process.run()
            let timeout = DispatchWorkItem { if process.isRunning { process.terminate() } }
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.4, execute: timeout)
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            timeout.cancel()
            if process.terminationStatus == 0 {
                active = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            }
        } catch {}
        let shouldRegister = active == pane
        DispatchQueue.main.async {
            checking = false
            guard shouldRegister, ghosttyIsFrontmost() else { unregister(); return }
            if hotkey == nil {
                let id = EventHotKeyID(signature: signature, id: 1)
                let status = RegisterEventHotKey(UInt32(kVK_ANSI_C), UInt32(cmdKey), id,
                                                GetApplicationEventTarget(), 0, &hotkey)
                if status != noErr {
                    fputs("Broot Cmd+C registration failed: \(status)\n", stderr)
                }
                if status == noErr { lastStatus = "" }
            }
            if revealHotkey == nil {
                let id = EventHotKeyID(signature: signature, id: 2)
                let result = RegisterEventHotKey(UInt32(kVK_ANSI_R), UInt32(cmdKey), id,
                                                GetApplicationEventTarget(), 0, &revealHotkey)
                if result != noErr {
                    fputs("Broot Cmd+R registration failed: \(result)\n", stderr)
                }
            }
            status(hotkey != nil && revealHotkey != nil ? "registered" : "registration-failed")
        }
    }
}

var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
    // Recheck focus. The owning Broot wrapper executes the selected action.
    guard ghosttyIsFrontmost(), let event = event else { return noErr }
    var id = EventHotKeyID(signature: 0, id: 0)
    let result = GetEventParameter(event, EventParamName(kEventParamDirectObject),
                                  EventParamType(typeEventHotKeyID), nil,
                                  MemoryLayout<EventHotKeyID>.size, nil, &id)
    guard result == noErr, id.signature == signature else { return noErr }
    if id.id == 1 { print("copy"); fflush(stdout) }
    if id.id == 2 { print("reveal"); fflush(stdout) }
    return noErr
}, 1, &eventType, nil, nil)
let observer = NSWorkspace.shared.notificationCenter.addObserver(
    forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
) { _ in update() }
let timer = Timer.scheduledTimer(withTimeInterval: 0.12, repeats: true) { _ in update() }
update()
let application = NSApplication.shared
application.setActivationPolicy(.prohibited)
application.run()
