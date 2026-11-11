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

func findSpeakingInText(_ text: String) -> String? {
    let patterns = [
        #"^(.+?),.*\bactive speaker\b"#,
        #"^(.+?)\s+is speaking[.!]?$"#,
        #"^(.+?)\s*\((?:is\s+)?speaking\)$"#,
        #"^speaking:\s*(.+)$"#,
    ]
    for pattern in patterns {
        if let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]),
           let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let range = Range(match.range(at: 1), in: text) {
            let name = String(text[range]).trimmingCharacters(in: .whitespacesAndNewlines)
            if isValidPersonName(name) { return name }
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
    if ["participant", "unknown", "someone", "you", "everyone"].contains(lower) { return false }
    let uiWords = Set(["video", "audio", "settings", "microphone", "camera", "mute", "unmute", "share", "recording"])
    let words = Set(lower.components(separatedBy: CharacterSet.letters.inverted).filter { !$0.isEmpty })
    if !words.isDisjoint(with: uiWords) { return false }
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
    if text.contains(",") && (text.contains("audio") || text.contains("Video") || text.contains("speaker")) {
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
    if let regex = try? NSRegularExpression(pattern: #"^View (.+?)(?:['’]s)? profile$"#, options: [.caseInsensitive]),
       let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
       let range = Range(match.range(at: 1), in: text) {
        let name = String(text[range])
        if isValidPersonName(name) { return name }
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
                if isValidPersonName(speaker) && !knownParticipants.contains(speaker) {
                    knownParticipants.insert(speaker)
                    saveParticipantsIfChanged()
                }
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

var emittedMeetingTitles = Set<String>()
func emitMeetingTitleOnce(_ title: String) {
    let clean = title.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !clean.isEmpty, !emittedMeetingTitles.contains(clean) else { return }
    emittedMeetingTitles.insert(clean)
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

var browserCaptureWarnings: [String: String] = [:]

func captureStatusURL() -> URL? {
    guard let participantFile = participantsFile else { return nil }
    if participantFile.path.hasSuffix("_participants.json") {
        return URL(fileURLWithPath: participantFile.path.replacingOccurrences(of: "_participants.json", with: "_capture_status.json"))
    }
    return participantFile.deletingLastPathComponent().appendingPathComponent("capture_status.json")
}

func recordBrowserCapture(_ browser: String, errorCode: Int?, detail: String? = nil) {
    let message: String
    if let code = errorCode {
        switch code {
        case 12:  // Chromium: "Executing JavaScript through AppleScript is turned off"
            message = "Participant names unavailable in \(browser): turn on View › Developer › Allow JavaScript from Apple Events in \(browser). Speaker turns are still recorded."
        case -1743:  // errAEEventNotPermitted
            message = "Participant names unavailable in \(browser): allow Cora under System Settings › Privacy & Security › Automation › \(browser)."
        default:
            message = "Browser meeting capture unavailable in \(browser) (AppleScript \(code)\(detail.map { ": \($0)" } ?? "")). Accessibility capture is still attempted."
        }
    } else {
        message = ""
    }
    guard browserCaptureWarnings[browser] != message else { return }
    browserCaptureWarnings[browser] = message
    if !message.isEmpty { print("CAPTURE_WARNING: \(message)"); fflush(stdout) }
    let warnings = browserCaptureWarnings.values.filter { !$0.isEmpty }.sorted()
    if let url = captureStatusURL(), let data = try? JSONEncoder().encode(warnings) {
        try? data.write(to: url, options: .atomic)
    }
}

// Raw JS avoids the previous nested newline/selector escaping errors.
// NOTE: this script is flattened onto ONE line before it reaches the browser
// (see scanBrowserGoogleMeet), so it must contain no `//` line comments; use
// /* block comments */ only. tests/test_speaker_watch_js.py checks that.
// Whether a call is live in a Meet or Slack tab comes from liveCall(), the
// snippet shared with the Node detector (src/meeting-detector.js). Edit
// capture/live-call-snippet.js, never the region below; `make build-native`
// regenerates it and test/js/live-call-snippet-drift.test.js guards it.
// BEGIN live-call-snippet (generated from capture/live-call-snippet.js by scripts/gen-live-call-snippet.js; do not edit)
let liveCallSnippetJS = #"""
function liveCall() {
  /* Answers {live, label} for the current tab. Slack hosts get the huddle
     rules; anything else (Meet) gets the leave-call rules. */
  const host = typeof location !== 'undefined' && location.hostname ? String(location.hostname).toLowerCase() : '';
  const text = el => String((el && (el.getAttribute('aria-label') || el.innerText)) || '').trim();
  const buttons = root => Array.from(root.querySelectorAll('button, [role="button"]'));
  if (host === 'slack.com' || host.endsWith('.slack.com')) {
    /* Expanded huddle: participant tiles. Older layouts: a huddle dialog
       holding a Leave/End huddle button, or such a button anywhere. Collapsed
       to the bottom mini-bar: a non-empty huddle_details_title. The content
       container alone does not count as live; the speaker watcher uses it
       only to scope where names are read. */
    const isLeave = b => /^(?:leave|end)(?: the)? huddle/i.test(text(b));
    const isHuddleRoot = r => /huddle/i.test(r.getAttribute('aria-label') || r.getAttribute('data-qa') || r.getAttribute('data-testid') || '');
    const mini = document.querySelector('[data-qa="huddle_details_title"]');
    const live = !!document.querySelector('[data-qa^="huddle_peer_tile_userId_"]')
      || Array.from(document.querySelectorAll('[role="dialog"], [data-qa*="huddle"], [data-testid*="huddle"]')).some(r => isHuddleRoot(r) && buttons(r).some(isLeave))
      || buttons(document).some(isLeave)
      || String((mini && mini.innerText) || '').trim() !== '';
    return { live, label: 'Slack Huddle' };
  }
  if (host === 'zoom.us' || host.endsWith('.zoom.us')) {
    /* Zoom web client: joined means the footer Leave/End control exists; the
       pre-join screen and the /j/ launch page have only Join/Launch buttons. */
    const live = !!document.querySelector('button.footer__leave-btn')
      || buttons(document).some(b => /^(?:leave|end)(?: the)?(?: meeting)?$/i.test(text(b)));
    return { live, label: 'Zoom' };
  }
  /* Meet: joined means a Leave call control exists; the green room has none.
     Only "Leave call" counts: other controls say Leave too (Leave feedback). */
  const live = !!document.querySelector('button[aria-label^="Leave call"], [data-tooltip^="Leave call"]')
    || buttons(document).some(b => /^(?:leave|end)(?: the)? call/i.test(text(b)));
  return { live, label: 'Google Meet' };
}
"""#
// END live-call-snippet

let googleMeetSnapshotJS = #"""
(() => {
    \#(liveCallSnippetJS)
    const names = new Set();
    const speaking = new Set();
    const clean = value => (value || '').trim();
    const explicitName = label => {
        const match = clean(label).match(/^More options for (.+)$/i);
        return match ? match[1].trim() : '';
    };
    const tileName = tile => {
        if (!tile) return '';
        const control = tile.querySelector('[aria-label^="More options for "]');
        const explicit = explicitName(control && control.getAttribute('aria-label'));
        if (explicit) return explicit;
        const name = tile.getAttribute('data-self-name') || tile.getAttribute('data-participant-name');
        if (name) return clean(name);
        return clean((tile.innerText || '').split(/\n/)[0]);
    };
    /* Slack in a browser: accept only a huddle dialog/container with a leave */
    /* control. A DM tab title and message authors are not call participants. */
    const host = typeof location !== 'undefined' ? location.hostname : 'meet.google.com';
    const slack = host === 'app.slack.com' || host.endsWith('.slack.com');
    /* Zoom web client: names from video tiles and the participants panel; */
    /* the active-speaker tile gives the current speaker. */
    if (host === 'zoom.us' || host.endsWith('.zoom.us')) {
        const zoomName = el => clean(el && el.innerText).replace(/\s*\((?:host|co-host|me|guest)[^)]*\)\s*$/i, '');
        document.querySelectorAll('.participants-item__display-name, .video-avatar__avatar-name, [class*="avatar-name"]').forEach(el => {
            const name = zoomName(el);
            if (name && name.length <= 60) names.add(name);
        });
        const activeTile = document.querySelector('.speaker-active-container__video-frame .video-avatar__avatar-name, [class*="speaker-active"] [class*="avatar-name"]');
        if (activeTile && zoomName(activeTile)) { names.add(zoomName(activeTile)); speaking.add(zoomName(activeTile)); }
        const live = !!document.querySelector('.footer__leave-btn, button[aria-label^="Leave"]');
        return JSON.stringify({active: live, participants: [...names], speaking_names: [...speaking], meeting_title: document.title});
    }
    let scope = document;
    let slackTitle = '';
    if (slack) {
        /* Slack huddle UI (2026-11): one tile per participant,
           data-qa="huddle_peer_tile_userId_<id>", inside
           data-qa="huddle_window_content_container"; names appear as
           aria-label "<Name>'s profile" and as avatar alt text; the huddle's own
           title sits in data-qa="huddle_window_titlebar_title". Older layouts
           expose a dialog labelled "Huddle" with a "Leave huddle" button and
           "View <Name> profile" labels; both shapes are accepted. A DM tab
           without a huddle has neither, so it is never a live call. */
        const tiles = [...document.querySelectorAll('[data-qa^="huddle_peer_tile_userId_"]')];
        const isLeave = button => /^(?:leave|end)(?: the)? huddle/i.test(button.getAttribute('aria-label') || button.innerText || '');
        const roots = [...document.querySelectorAll('[role="dialog"], [data-qa*="huddle"], [data-testid*="huddle"]')];
        const dialog = roots.find(root => /huddle/i.test(root.getAttribute('aria-label') || root.getAttribute('data-qa') || root.getAttribute('data-testid') || '') &&
            [...root.querySelectorAll('button, [role="button"]')].some(isLeave));
        /* Prefer the content container by data-qa, then the tiles' grid, then the
           dialog; never the first class match in document order (that is the
           title bar's resize button, which holds no names). */
        const container = document.querySelector('[data-qa="huddle_window_content_container"]')
            || (tiles[0] && typeof tiles[0].closest === 'function' ? tiles[0].closest('[data-qa="huddle_grid_component"], [class*="p-huddle_window_content"]') : null)
            || dialog || null;
        /* Collapsed huddle (bottom mini-bar, or popped out to its own window):
           no tiles in this tab, only data-qa="huddle_details_title" reading
           "Huddle with <Name>[, <Name> and <Name>]". A DM huddle names the
           other party there; "Huddle in #channel" names nobody. */
        const miniEl = document.querySelector('[data-qa="huddle_details_title"]');
        const miniTitle = clean(miniEl && miniEl.innerText);
        /* Live or not is the shared liveCall() decision; the rest only gathers names. */
        if (!liveCall().live) return JSON.stringify({active: false, participants: [], speaking_names: [], meeting_title: ''});
        scope = container || document;
        const profileRe = /^(?:View )?(.+?)(?:['’]s)? profile$/i;
        scope.querySelectorAll('[aria-label]').forEach(el => {
            const match = clean(el.getAttribute('aria-label')).match(profileRe);
            if (match) names.add(match[1].trim());
        });
        tiles.forEach(tile => {
            tile.querySelectorAll('img[alt]').forEach(img => {
                const alt = clean(img.alt);
                if (alt && alt.length <= 60 && !/avatar|image|photo|emoji/i.test(alt)) names.add(alt);
            });
            const label = clean(tile.getAttribute('aria-label'));
            if (/speaking/i.test(label)) {
                const who = label.replace(/\s*(?:is\s+)?speaking.*$/i, '').trim();
                if (who) { names.add(who); speaking.add(who); }
            }
        });
        const titleEl = document.querySelector('[data-qa="huddle_window_titlebar_title"]');
        slackTitle = clean(titleEl && titleEl.innerText) || miniTitle;
        if (!tiles.length && miniTitle) {
            const withMatch = miniTitle.match(/^Huddle with (.+)$/i);
            if (withMatch) {
                withMatch[1].split(/,\s*|\s+and\s+/).map(clean).forEach(name => { if (name && name.length <= 60) names.add(name); });
            }
        }
    }
    scope.querySelectorAll('[data-participant-id]').forEach(tile => {
        const name = tileName(tile);
        if (name && name.length <= 60 && !name.includes(':')) names.add(name);
    });
    scope.querySelectorAll('[aria-label^="More options for "]').forEach(el => {
        const name = explicitName(el.getAttribute('aria-label'));
        if (name) names.add(name);
    });
    scope.querySelectorAll('[aria-label]').forEach(el => {
        const label = clean(el.getAttribute('aria-label'));
        const match = label.match(/^(.+?) is speaking[.!]?$/i) ||
                      label.match(/^(.+?)\s*\((?:is\s+)?speaking\)$/i) ||
                      label.match(/^speaking:\s*(.+)$/i);
        if (match) { names.add(match[1].trim()); speaking.add(match[1].trim()); }
        else if (/^(?:is )?speaking$/i.test(label)) {
            const name = tileName(el.closest('[data-participant-id]'));
            if (name) { names.add(name); speaking.add(name); }
        }
    });
    const title = document.querySelector('[data-meeting-title], [data-call-title]');
    const active = liveCall().live;
    return JSON.stringify({active, participants: [...names], speaking_names: [...speaking], meeting_title: slackTitle || (title ? title.innerText.trim() : document.title)});
})()
"""#

func scanBrowserGoogleMeet(browserName: String) {
    let escapedJS = googleMeetSnapshotJS.replacingOccurrences(of: "\\", with: "\\\\")
                                         .replacingOccurrences(of: "\"", with: "\\\"")
                                         .replacingOccurrences(of: "\n", with: " ")
    let scriptText = """
    tell application "\(browserName)"
        set js to "\(escapedJS)"
        set snapshots to ""
        -- A window without tabs (PWA, devtools, picture-in-picture) or one tab
        -- refusing JS must not abort the whole scan, hence the nested trys.
        repeat with w in windows
            try
                repeat with t in tabs of w
                    set u to URL of t
                    if u starts with "https://meet.google.com/" or u starts with "https://app.slack.com/" or u contains "zoom.us/wc/" then
                        try
                            set snapshots to snapshots & (execute t javascript js) & linefeed
                        on error number n
                            set snapshots to snapshots & "ERR:" & n & linefeed
                        end try
                    end if
                end repeat
            end try
        end repeat
        return snapshots
    end tell
    """
    guard let appleScript = NSAppleScript(source: scriptText) else { return }
    var error: NSDictionary?
    let result = appleScript.executeAndReturnError(&error)
    let lines = (result.stringValue ?? "").components(separatedBy: .newlines)
    let tabErrors = lines.filter { $0.hasPrefix("ERR:") }.compactMap { Int($0.dropFirst(4)) }
    let scriptError = error.map { $0["NSAppleScriptErrorNumber"] as? Int ?? 0 }
    let anySnapshot = lines.contains { $0.hasPrefix("{") }
    let scriptMessage = error.flatMap { $0["NSAppleScriptErrorMessage"] as? String }
    recordBrowserCapture(browserName, errorCode: scriptError ?? (anySnapshot ? nil : tabErrors.first), detail: scriptMessage)
    guard error == nil else { return }
    let snapshots = lines.compactMap { line -> [String: Any]? in
        guard let data = line.data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    for parsed in snapshots where parsed["active"] as? Bool == true {

    if let title = parsed["meeting_title"] as? String, let cleanTitle = extractMeetingTitle(from: title, appName: browserName) {
        emitMeetingTitleOnce(cleanTitle)
    }
    let ownName = ProcessInfo.processInfo.environment["CORA_SELF_NAME"] ?? ""
    func resolveName(_ raw: String) -> String {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.lowercased() == "you" && !ownName.isEmpty ? ownName : value
    }
    if let parts = parsed["participants"] as? [String] {
        for p in parts {
            let clean = resolveName(p)
            if isValidPersonName(clean) && !knownParticipants.contains(clean) {
                knownParticipants.insert(clean)
                saveParticipantsIfChanged()
            }
        }
    }
    if let speaking = parsed["speaking_names"] as? [String], speaking.count == 1 {
        let name = resolveName(speaking[0])
        if isValidPersonName(name) { updateSpeaker(name, from: "Browser meeting") }
    }
}
}

func hasLeaveHuddleControl(_ element: AXUIElement, depth: Int = 0) -> Bool {
    if depth > 28 { return false }
    for attr in [kAXTitleAttribute, kAXDescriptionAttribute] {
        var value: AnyObject?
        AXUIElementCopyAttributeValue(element, attr as CFString, &value)
        if let text = value as? String {
            let lower = text.lowercased()
            if lower.contains("leave huddle") || lower.contains("leave the huddle") || lower.contains("end huddle") { return true }
        }
    }
    var value: AnyObject?
    AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &value)
    return (value as? [AXUIElement] ?? []).contains { hasLeaveHuddleControl($0, depth: depth + 1) }
}

func findSlackHuddleRoot(_ element: AXUIElement, depth: Int = 0) -> AXUIElement? {
    if depth > 28 { return nil }
    var labels: [String] = []
    for attr in [kAXTitleAttribute, kAXDescriptionAttribute] {
        var value: AnyObject?
        if AXUIElementCopyAttributeValue(element, attr as CFString, &value) == .success, let text = value as? String {
            labels.append(text.lowercased())
        }
    }
    var roleValue: AnyObject?
    AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleValue)
    let role = roleValue as? String ?? ""
    if ["AXGroup", "AXWindow", "AXDialog", "AXWebArea"].contains(role),
       labels.contains(where: { $0.contains("huddle") && !$0.contains("start a huddle") && !$0.contains("start huddle") && !$0.contains("huddle history") }), hasLeaveHuddleControl(element) {
        return element
    }
    var childrenValue: AnyObject?
    if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenValue) == .success,
       let children = childrenValue as? [AXUIElement] {
        for child in children {
            if let root = findSlackHuddleRoot(child, depth: depth + 1) { return root }
        }
    }
    return nil
}

func scanMeetingApps() {
    let targetAppNames = ["Brave Browser", "Google Chrome", "Arc", "Safari", "Microsoft Edge", "zoom.us", "Microsoft Teams", "Slack"]
    let running = NSWorkspace.shared.runningApplications.filter {
        guard let name = $0.localizedName else { return false }
        return targetAppNames.contains(where: { name.localizedCaseInsensitiveCompare($0) == .orderedSame })
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

                let slack = appName == "Slack" || (isBrowser && (title.localizedCaseInsensitiveContains("Slack") || title.localizedCaseInsensitiveContains("Huddle")))
                if slack {
                    if let huddle = findSlackHuddleRoot(win),
                       let speaker = traverseElement(huddle, appName: appName, dumping: dumpingThisPass) {
                        updateSpeaker(speaker, from: appName)
                    }
                    if dumpingThisPass { print("[AX-DUMP] Slack huddle capture: inspected active huddle containers in \(appName)") }
                    continue
                }
                let isMeetingWindow: Bool
                if isBrowser {
                    isMeetingWindow = title.localizedCaseInsensitiveContains("Meet")
                } else if appName.localizedCaseInsensitiveContains("zoom") {
                    isMeetingWindow = title.localizedCaseInsensitiveContains("Meeting")
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

if CommandLine.arguments.contains("--self-test") {
    precondition(extractParticipantName("More options for Jane R.T.") == "Jane R.T.")
    precondition(extractParticipantName("Video settings") == nil)
    precondition(!isValidPersonName("Video settings"))
    precondition(!isValidPersonName("Participant"))
    precondition(extractParticipantName("View Jane Doe profile") == "Jane Doe")
    precondition(extractParticipantName("Audio settings") == nil)
    precondition(findSpeakingInText("Jane Doe is speaking") == "Jane Doe")
    precondition(findSpeakingInText("Speaking: Jane Doe") == "Jane Doe")
    precondition(findSpeakingInText("Jane Doe (speaking)") == "Jane Doe")
    precondition(findSpeakingInText("Jane Doe, Computer audio unmuted, active speaker") == "Jane Doe")
    precondition(findSpeakingInText("Speaking") == nil)
    print("Speaker watcher parser checks passed")
    exit(0)
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
