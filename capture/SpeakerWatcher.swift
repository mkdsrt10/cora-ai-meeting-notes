import Foundation
import Cocoa
import ApplicationServices

// Cora Native Accessibility Speaker Watcher
// Monitors active meeting applications (Google Meet in Chrome/Brave/Edge/Safari, Zoom, Teams, Slack)
// via macOS Accessibility APIs (AXUIElement) to track who is speaking in real time with exact names.

struct SpeakerEvent: Codable {
    let start_sec: Double
    var end_sec: Double
    let speaker_name: String
    let source_app: String
}

var timeline: [SpeakerEvent] = []
var currentSpeaker: String? = nil
var currentSpeakerStart: Double = 0.0
var currentApp: String = ""
var outputFile: URL? = nil
let startTime = Date()

func elapsedSeconds() -> Double {
    return Date().timeIntervalSince(startTime)
}

func formatTimestamp(_ seconds: Double) -> String {
    let s = Int(seconds)
    let m = s / 60
    let sec = s % 60
    return String(format: "%02d:%02d", m, sec)
}

func flushCurrentSpeaker(at time: Double) {
    guard let spk = currentSpeaker else { return }
    let duration = time - currentSpeakerStart
    if duration >= 0.5 { // ignore micro-glitches under 500ms
        timeline.append(SpeakerEvent(
            start_sec: currentSpeakerStart,
            end_sec: time,
            speaker_name: spk,
            source_app: currentApp
        ))
    }
    currentSpeaker = nil
}

func updateSpeaker(_ name: String, from app: String) {
    let now = elapsedSeconds()
    let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !cleanName.isEmpty else { return }

    if currentSpeaker == cleanName {
        return // Still the same speaker talking
    }

    // New speaker started
    flushCurrentSpeaker(at: now)
    currentSpeaker = cleanName
    currentSpeakerStart = now
    currentApp = app
    
    let line = "[\(formatTimestamp(now))] SPEAKER_ACTIVE: \(cleanName) (\(app))"
    print(line)
    fflush(stdout)
}

func saveTimeline() {
    flushCurrentSpeaker(at: elapsedSeconds())
    guard let outURL = outputFile else { return }

    struct FormattedTurn: Codable {
        let start: String
        let end: String
        let start_sec: Double
        let end_sec: Double
        let speaker_name: String
        let source_app: String
    }

    let formatted = timeline.map {
        FormattedTurn(
            start: formatTimestamp($0.start_sec),
            end: formatTimestamp($0.end_sec),
            start_sec: round($0.start_sec * 10) / 10,
            end_sec: round($0.end_sec * 10) / 10,
            speaker_name: $0.speaker_name,
            source_app: $0.source_app
        )
    }

    if let data = try? JSONEncoder().encode(formatted) {
        try? data.write(to: outURL)
        print("Saved speaker timeline (\(formatted.count) turns) to \(outURL.path)")
    }
}

// Signal handler for graceful stop
signal(SIGINT) { _ in
    saveParticipantsIfChanged()
    saveTimeline()
    exit(0)
}
signal(SIGTERM) { _ in
    saveParticipantsIfChanged()
    saveTimeline()
    exit(0)
}

// Regex patterns to identify speaking indicators across meeting apps
let speakingRegex = try! NSRegularExpression(
    pattern: #"(?:(?:speaking:\s*|is speaking|speaking\b)(.*))|(?:^(.*?)\s*\((?:is\s*)?speaking\))"#,
    options: [.caseInsensitive]
)

func findSpeakingInText(_ text: String) -> String? {
    let lower = text.lowercased()

    // Zoom pattern: "<Name>, Computer audio unmuted, Video off, active speaker"
    if lower.contains("active speaker") {
        let parts = text.split(separator: ",")
        if let first = parts.first {
            let candidate = String(first).trimmingCharacters(in: .whitespacesAndNewlines)
            if !candidate.isEmpty && candidate.count < 50 {
                return candidate
            }
        }
    }

    // Google Meet / Teams patterns: "<Name> is speaking" or "<Name> (speaking)"
    if lower.contains("speaking") {
        let cleaned = text.replacingOccurrences(of: "(speaking)", with: "", options: .caseInsensitive)
                          .replacingOccurrences(of: "is speaking", with: "", options: .caseInsensitive)
                          .replacingOccurrences(of: "speaking:", with: "", options: .caseInsensitive)
                          .trimmingCharacters(in: .whitespacesAndNewlines)
        if !cleaned.isEmpty && cleaned.count < 50 && !cleaned.contains("\n") {
            return cleaned
        }
    }

    let nsText = text as NSString
    let matches = speakingRegex.matches(in: text, options: [], range: NSRange(location: 0, length: nsText.length))
    for match in matches {
        for i in 1...match.numberOfRanges - 1 {
            let r = match.range(at: i)
            if r.location != NSNotFound {
                let candidate = nsText.substring(with: r).trimmingCharacters(in: .whitespacesAndNewlines)
                if !candidate.isEmpty && candidate.count < 50 {
                    return candidate
                }
            }
        }
    }
    return nil
}

// Each person's video-tile AXTabGroup exposes a description like "Kihu,
// Computer audio unmuted, Video off" — and, per findSpeakingInText() above,
// gains an ", active speaker" suffix while they're actually talking (this
// took setting AXEnhancedUserInterface and catching a live speaker turn in
// a DEBUG=1 dump to find — an earlier belief that Zoom exposed no speaking
// state at all was wrong, just untested against the right moment). This
// roster still matters on its own even now that live speaking state works:
// it's the fallback the Python side uses to name the mic-vs-system-audio
// "You/Participant" split's "not you" bucket on a 2-person call whenever
// the active-speaker text doesn't fire (e.g. this permission/flag not yet
// in effect, or a moment AX just misses).
func isValidPersonName(_ text: String) -> Bool {
    var trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    while trimmed.hasPrefix("!") || trimmed.hasPrefix("*") || trimmed.hasPrefix("#") || trimmed.hasPrefix("@") || trimmed.hasPrefix("-") || trimmed.hasPrefix("•") {
        trimmed = String(trimmed.dropFirst()).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    if trimmed.count < 3 || trimmed.count > 35 { return false }
    if trimmed.contains(":") || trimmed.contains("/") || trimmed.contains("@") || trimmed.contains(",") || trimmed.contains("–") || trimmed.contains("_") || trimmed.contains("#") || trimmed.contains("$") || trimmed.contains("%") { return false }
    if trimmed.rangeOfCharacter(from: .decimalDigits) != nil { return false }
    
    let lower = trimmed.lowercased()
    let badTokens = [
        "notetaker", "note taker", "meeting notes", "tldv", "read.ai", "otter.ai", "otter", "fireflies",
        "fathom", "granola", "fellow", "airgram", "tactiq", "avoma", "supernormal", "bluedot", "meetgeek",
        "cogram", "circleback", "clibri", "krisp", "vowel", "grain", "transcriber", "recorder", "bot",
        "presentation", "google calendar", "slack", "zoom", "activity", "search", "new message",
        "deployments", "loudspeaker", "keep_outline", "frame_person", "test_speakers", "draw", "keep", "channel"
    ]
    for bad in badTokens {
        if lower.contains(bad) { return false }
    }
    return true
}

func extractParticipantName(_ text: String) -> String? {
    if text.contains("audio") || text.contains("Video") || text.contains("speaker") {
        let parts = text.split(separator: ",")
        if let first = parts.first {
            let name = String(first).trimmingCharacters(in: .whitespacesAndNewlines)
            if isValidPersonName(name) {
                return name
            }
        }
    }
    // Zoom: "View Jane's profile"
    if text.hasPrefix("View ") && text.hasSuffix("'s profile") {
        let raw = text.dropFirst(5).dropLast(10)
        let name = String(raw).trimmingCharacters(in: .whitespacesAndNewlines)
        if isValidPersonName(name) {
            return name
        }
    }
    // Google Meet: "More options for Jane Doe"
    if text.hasPrefix("More options for ") {
        let name = String(text.dropFirst("More options for ".count)).trimmingCharacters(in: .whitespacesAndNewlines)
        if isValidPersonName(name) {
            return name
        }
    }
    return nil
}

var knownParticipants: Set<String> = []
var participantsFile: URL? = nil

func participantsFileURL(from speakersFile: URL) -> URL {
    let path = speakersFile.path
    if path.hasSuffix("_speakers.json") {
        let base = String(path.dropLast("_speakers.json".count))
        return URL(fileURLWithPath: base + "_participants.json")
    }
    return speakersFile.deletingLastPathComponent().appendingPathComponent("participants.json")
}

func saveParticipantsIfChanged() {
    guard let outURL = participantsFile else { return }
    let sorted = knownParticipants.sorted()
    if let data = try? JSONEncoder().encode(sorted) {
        try? data.write(to: outURL)
    }
}

// DEBUG=1 in the environment dumps every non-empty AX attribute string this
// traversal encounters (role + attribute + value, deduped, once every ~5s)
// instead of only ever reporting a match for the narrow "is speaking" regex.
// Added specifically because that regex has never once matched anything
// during a real Zoom call in testing — this makes the *actual* AX tree
// content visible so a real fix (matched to what's really there, not
// assumed) can be written, without needing Xcode/Accessibility Inspector.
let debugDump = ProcessInfo.processInfo.environment["DEBUG"] == "1"
var lastDumpAt: Double = -999
var seenDebugStrings = Set<String>()

func debugPrint(_ role: String, _ attr: String, _ value: String, depth: Int) {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return }
    let key = "\(role)|\(attr)|\(trimmed)"
    guard !seenDebugStrings.contains(key) else { return }
    seenDebugStrings.insert(key)
    let indent = String(repeating: "  ", count: min(depth, 8))
    print("[AX-DUMP]\(indent) role=\(role) \(attr)=\"\(trimmed.prefix(120))\"")
}

// Full, type-agnostic attribute dump for one element — every attribute name
// AX reports for it, whatever the value's actual type (string, bool,
// number, AXValue struct, array, etc.), not just the 4 fixed string
// attributes the normal scan checks. Only called for participant tiles
// (AXTabGroup) and their direct children, since that's specifically where
// a "who's speaking" signal — if AX exposes one at all, in ANY form — would
// have to live. Aimed at the 3+ participant case: mic-vs-system audio can
// only ever say "not you", never which of several others is talking, so if
// that's solvable at all it has to come from something AX exposes here
// that the narrower string-only dump could have missed entirely.
func dumpAllAttributes(_ element: AXUIElement, depth: Int) {
    var namesRef: CFArray?
    guard AXUIElementCopyAttributeNames(element, &namesRef) == .success,
          let names = namesRef as? [String] else { return }
    let indent = String(repeating: "  ", count: min(depth, 8))
    for attrName in names {
        var val: AnyObject?
        guard AXUIElementCopyAttributeValue(element, attrName as CFString, &val) == .success, let v = val else { continue }
        let desc: String
        switch v {
        case let s as String: desc = "\"\(s.prefix(120))\""
        case let n as NSNumber: desc = "\(n)"
        case let arr as NSArray:
            // AXDOMClassList in particular can carry a toggled CSS class
            // (e.g. an "active speaker" ring/border class) that never shows
            // up as visible text anywhere else in the tree — collapsing
            // this to just a count would hide exactly that signal.
            if let strings = arr as? [String], !strings.isEmpty {
                desc = "[\(strings.prefix(20).joined(separator: ", "))]" + (strings.count > 20 ? ", …(\(strings.count) total)" : "")
            } else {
                desc = "<array of \(arr.count)>"
            }
        default: desc = "\(v)"
        }
        print("[AX-FULL]\(indent) \(attrName) = \(desc)")
    }
}

func traverseElement(_ element: AXUIElement, depth: Int = 0, appName: String, dumping: Bool, insideParticipantTile: Bool = false) -> String? {
    if depth > 28 { return nil }

    var roleVal: AnyObject?
    AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleVal)
    let role = (roleVal as? String) ?? "?"

    var isParticipantTile = insideParticipantTile
    var activeSpeaker: String? = nil

    // Check title, description, help, value
    let attrs: [(String, CFString)] = [
        ("description", kAXDescriptionAttribute as CFString),
        ("title", kAXTitleAttribute as CFString),
        ("value", kAXValueAttribute as CFString),
        ("help", kAXHelpAttribute as CFString),
    ]
    for (name, attr) in attrs {
        var val: AnyObject?
        if AXUIElementCopyAttributeValue(element, attr, &val) == .success,
           let strVal = val as? String, !strVal.isEmpty {
            if dumping { debugPrint(role, name, strVal, depth: depth) }
            if let participant = extractParticipantName(strVal) {
                isParticipantTile = true  // this whole subtree is one person's video tile
                if !knownParticipants.contains(participant) {
                    knownParticipants.insert(participant)
                    saveParticipantsIfChanged()
                }
            }
            if activeSpeaker == nil, let speaker = findSpeakingInText(strVal) {
                activeSpeaker = speaker
            }
        }
    }

    // Dump EVERY attribute (any type, not just the 4 checked above) for a
    // participant tile and everything under it — a "who's speaking" signal,
    // if AX exposes one in any form, has to be somewhere in here.
    if dumping && isParticipantTile {
        dumpAllAttributes(element, depth: depth)
    }

    // Check children
    var childrenVal: AnyObject?
    if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenVal) == .success,
       let children = childrenVal as? [AXUIElement] {
        for child in children {
            if let found = traverseElement(child, depth: depth + 1, appName: appName, dumping: dumping, insideParticipantTile: isParticipantTile) {
                if activeSpeaker == nil {
                    activeSpeaker = found
                }
            }
        }
    }
    return activeSpeaker
}

var lastEmittedMeetingTitle: String = ""
func emitMeetingTitleOnce(_ title: String) {
    let clean = title.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !clean.isEmpty, clean != lastEmittedMeetingTitle else { return }
    lastEmittedMeetingTitle = clean
    print("MEETING_TITLE: \(clean)")
    fflush(stdout)
}

func extractMeetingTitle(from raw: String, appName: String) -> String? {
    var t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    if t.isEmpty { return nil }
    
    // Google Meet in browser
    if t.contains("Google Meet") || t.hasPrefix("Meet - ") || t.contains(" — Google Meet") || t.contains(" - Google Meet") {
        t = t.replacingOccurrences(of: " — Google Meet", with: "")
             .replacingOccurrences(of: " - Google Meet", with: "")
             .trimmingCharacters(in: .whitespacesAndNewlines)
        if t.lowercased().hasPrefix("meet - ") && t.count < 20 {
            return nil // Plain room code like "Meet - abc-defg-hij"
        }
    }
    
    // Zoom
    if t.localizedCaseInsensitiveContains("Zoom Meeting") {
        t = t.replacingOccurrences(of: "Zoom Meeting: ", with: "")
             .replacingOccurrences(of: "Zoom Meeting - ", with: "")
             .replacingOccurrences(of: "Zoom Meeting", with: "")
             .trimmingCharacters(in: .whitespacesAndNewlines)
    }
    
    // Microsoft Teams
    if t.contains("| Microsoft Teams") || t.contains("- Microsoft Teams") {
        t = t.replacingOccurrences(of: "| Microsoft Teams", with: "")
             .replacingOccurrences(of: "- Microsoft Teams", with: "")
             .trimmingCharacters(in: .whitespacesAndNewlines)
    }
    
    // Slack
    if t.contains(" - Slack") {
        t = t.replacingOccurrences(of: " - Slack", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
    }
    
    t = t.trimmingCharacters(in: CharacterSet(charactersIn: " -:|•"))
    if t.count >= 4 && t.count <= 70 && !t.lowercased().contains("untitled") {
        return t
    }
    return nil
}

func scanBrowserGoogleMeet(browserName: String) {
    let scriptText = """
    tell application "\(browserName)"
        set js to "(() => { const names = new Set(); document.querySelectorAll('[data-participant-id]').forEach(el => { const txt = (el.innerText || '').split('\\\\n')[0].trim(); if (txt && txt.length < 40 && !txt.includes(':')) names.add(txt); }); document.querySelectorAll('[aria-label*=\\\"More options for \\\"]').forEach(el => { const label = el.getAttribute('aria-label') || ''; const name = label.replace('More options for ', '').trim(); if (name) names.add(name); }); let speaking = []; document.querySelectorAll('[aria-label*=\\\"speaking\\\"], [aria-label*=\\\"Speaking\\\"]').forEach(el => { speaking.push(el.getAttribute('aria-label')); }); const meetTitleEl = document.querySelector('div[data-meeting-title]') || document.querySelector('[data-call-title]'); const callTitle = meetTitleEl ? meetTitleEl.innerText.trim() : ''; return JSON.stringify({participants: Array.from(names), speaking: speaking, meeting_title: callTitle || document.title}); })()"
        repeat with w in windows
            repeat with t in tabs of w
                if (URL of t) contains "meet.google.com" then
                    return execute t javascript js
                end if
            end repeat
        end repeat
        return "{}"
    end tell
    """
    guard let appleScript = NSAppleScript(source: scriptText) else { return }
    var error: NSDictionary?
    let result = appleScript.executeAndReturnError(&error)
    guard let jsonStr = result.stringValue, jsonStr.count > 5,
          let data = jsonStr.data(using: .utf8),
          let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

    if let title = parsed["meeting_title"] as? String, let cleanTitle = extractMeetingTitle(from: title, appName: browserName) {
        emitMeetingTitleOnce(cleanTitle)
    }

    if let parts = parsed["participants"] as? [String] {
        for p in parts {
            let clean = p.trimmingCharacters(in: .whitespacesAndNewlines)
            if isValidPersonName(clean) && !knownParticipants.contains(clean) {
                knownParticipants.insert(clean)
                saveParticipantsIfChanged()
            }
        }
    }

    if let speaking = parsed["speaking"] as? [String], let firstSpeaking = speaking.first {
        if let spk = findSpeakingInText(firstSpeaking) {
            updateSpeaker(spk, from: "Google Meet")
        }
    }
}

func scanMeetingApps() {
    let targetAppNames = ["Brave Browser", "Google Chrome", "Arc", "Safari", "Microsoft Edge", "zoom.us", "Microsoft Teams", "Slack"]
    let running = NSWorkspace.shared.runningApplications.filter {
        guard let name = $0.localizedName else { return false }
        return targetAppNames.contains(where: { name.localizedCaseInsensitiveContains($0) })
    }

    let now = elapsedSeconds()
    let dumpingThisPass = debugDump && (now - lastDumpAt >= 5.0)
    if dumpingThisPass {
        lastDumpAt = now
        print("[AX-DUMP] --- scan at \(formatTimestamp(now)): \(running.count) candidate app(s): \(running.compactMap { $0.localizedName }) ---")
    }

    for app in running {
        let appName = app.localizedName ?? "App"

        if appName.localizedCaseInsensitiveContains("Brave") ||
           appName.localizedCaseInsensitiveContains("Chrome") ||
           appName.localizedCaseInsensitiveContains("Arc") ||
           appName.localizedCaseInsensitiveContains("Edge") {
            scanBrowserGoogleMeet(browserName: appName)
        }
        let axApp = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetAttributeValue(axApp, "AXEnhancedUserInterface" as CFString, true as CFTypeRef)
        AXUIElementSetAttributeValue(axApp, "AXManualAccessibility" as CFString, true as CFTypeRef)

        var windowsVal: AnyObject?
        let windowsResult = AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &windowsVal)
        if dumpingThisPass && windowsResult != .success {
            print("[AX-DUMP] \(appName): could not read windows (AXError \(windowsResult.rawValue)) — likely missing/blocked Accessibility permission for this specific app")
        }
        if windowsResult == .success, let windows = windowsVal as? [AXUIElement] {
            if dumpingThisPass {
                let titles: [String] = windows.map { win -> String in
                    var t: AnyObject?
                    AXUIElementCopyAttributeValue(win, kAXTitleAttribute as CFString, &t)
                    return (t as? String) ?? "(no title)"
                }
                print("[AX-DUMP] \(appName): \(windows.count) window(s): \(titles)")
            }
            for win in windows {
                var titleVal: AnyObject?
                AXUIElementCopyAttributeValue(win, kAXTitleAttribute as CFString, &titleVal)
                let title = (titleVal as? String) ?? ""

                let isBrowser = appName.localizedCaseInsensitiveContains("Brave") ||
                                appName.localizedCaseInsensitiveContains("Chrome") ||
                                appName.localizedCaseInsensitiveContains("Arc") ||
                                appName.localizedCaseInsensitiveContains("Edge") ||
                                appName.localizedCaseInsensitiveContains("Safari")

                let isMeetingWindow: Bool
                if isBrowser {
                    // In browsers, only scan if it is an actual Google Meet window
                    isMeetingWindow = title.localizedCaseInsensitiveContains("Meet")
                } else if appName.localizedCaseInsensitiveContains("zoom") {
                    // In Zoom app, only scan actual Zoom Meeting windows
                    isMeetingWindow = title.localizedCaseInsensitiveContains("Zoom Meeting") || title.localizedCaseInsensitiveContains("Meeting")
                } else if appName.localizedCaseInsensitiveContains("slack") {
                    // Slack huddles take place in DM or channel windows (e.g. "Jane Doe - Acme Inc - Slack")
                    isMeetingWindow = true
                    let parts = title.components(separatedBy: " - ")
                    if let first = parts.first {
                        let cleanName = first.replacingOccurrences(of: " (DM)", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
                        if isValidPersonName(cleanName) && !knownParticipants.contains(cleanName) {
                            knownParticipants.insert(cleanName)
                            saveParticipantsIfChanged()
                        }
                    }
                } else {
                    isMeetingWindow = title.localizedCaseInsensitiveContains("Huddle") || title.localizedCaseInsensitiveContains("Call")
                }

                if isMeetingWindow {
                    if let cleanTitle = extractMeetingTitle(from: title, appName: appName) {
                        emitMeetingTitleOnce(cleanTitle)
                    }
                    if let speaker = traverseElement(win, depth: 0, appName: appName, dumping: dumpingThisPass) {
                        updateSpeaker(speaker, from: appName)
                        return
                    }
                } else if dumpingThisPass {
                    print("[AX-DUMP] \(appName): window \"\(title)\" skipped — didn't match the meeting-window title filter")
                }
            }
        }
    }
}

// Main execution
let args = CommandLine.arguments
if args.count > 1 {
    outputFile = URL(fileURLWithPath: args[1])
    participantsFile = participantsFileURL(from: outputFile!)
}

print("Cora Native Accessibility Speaker Watcher active.")
if let out = outputFile {
    print("Timeline output target: \(out.path)")
}
if let pOut = participantsFile {
    print("Participants output target: \(pOut.path)")
}
print("Listening for meeting speaker UI changes... (Press Ctrl+C to stop)")
fflush(stdout)

let timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
    scanMeetingApps()
}
RunLoop.current.add(timer, forMode: .default)
RunLoop.current.run()
