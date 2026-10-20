# Cora look-and-feel for launch (track: look-and-feel), revision 2

Status: revised after three adversarial reviews. Date: 2026-10-17. Branch: `production`. No repo files were modified while writing this.
Scope: renderer UI (`src/ui/web`), floater (`src/ui/floater.html`, `floater.js`), window chrome and menu (`src/main.js`, new `src/main/menu.js`), brand assets, Product Hunt gallery and video. The phone PWA is specified briefly in section 10 and is P1.
Out of scope: plugin API, notes-template engine, Gemini ASR internals, remote listener internals, signing and notarization. This doc consumes their contracts and names every assumption as a **gate** (section 12.3).

---

## 0. What changed from revision 1 (review disposition)

Accepted (all `must_fix` items are resolved in the section shown):

| Review point | Resolution | Section |
|---|---|---|
| "Stays on this Mac" is false for cloud ASR, cloud notes, MCP, sync | Privacy state is computed server-side from the resolved settings plus MCP and sync state. Chip copy is narrowed ("Local only", "Local · Claude connected", "Locked down", names cloud engines). It is explained as a state indicator, never a compliance claim. | 5.4 |
| Floater "glass capsule" is impossible in a transparent panel | Opaque dark capsule. The dead `backdrop-filter` is removed. No vibrancy anywhere in P0. | 6.8 |
| Floater drawer / toast audit | Re-audited. The drawer is **not** clipped (`expand-floater` clamps 40-800 and `floater.js:132` already calls it with 84/46). The toast **is** clipped (`top:-30px` on a body whose window is 46px tall). LF-12 is re-scoped to the real bug. | 1, 6.8 |
| Icon path and signing dependency | Icon is `src/icon.icns` and `src/icon.png` (not `build/`). Signing dependency is stated as a gate. | 9, 12.3 |
| Window chrome unchecked against `main.js` | Drag-region audit table, `show:true` kept, no splash, no vibrancy, fallback read from `config.json` in main. LF-4 re-costed. | 5.1 |
| Distinctiveness thin | One signature, committed: **the Ring** (the brand mark whose ring colour is the live privacy state). Everything else uses plain conventions on purpose. | 2 |
| Teal semantically overloaded | Teal is reserved for privacy state only and linted. Primary action is neutral ink. | 2.2, 3.1 |
| Dark tokens not valid CSS, wrong contrast, build script | Both selector blocks written out; contrast computed and shown; no build script; a lint asserts the two blocks are identical; a no-dependency contrast script is the gate. | 3.1, 13 |
| Scope too big; day totals wrong | Honest totals. P0 is a "Launch Look" slice of 20.75 agent-days with a 9.75-day Tier A cut line. Section 12. | 12 |
| Cloud engine auto-save contradicts local-by-default | Cloud engine, provider, key changes always go through a confirm dialog that names what leaves the Mac. Only benign prefs auto-save. | 6.5 |
| CSP vs plugin iframe; PWA `style-src 'self'` | Plugin iframe prerequisites listed as plugin-track gates; P0 plugin UI is host-rendered. Kit emits no `style=""` attributes anywhere. | 4, 12.3 |
| Shortcuts false; ⌘⇧R is Force Reload and Zoom's | No global shortcut exists. P0 builds a real application menu and advertises only shortcuts that ship in the same commit. Global record shortcut is opt-in, unset by default, P1. | 5.3 |
| Splash can never show | Splash dropped from P0 (startup ordering would need restructuring). | 5.1 |
| Keyboard and AT traps (disabled install, disabled tooltips, hover-only) | `aria-disabled` plus visible reason text; acknowledgement checkbox; reveal on focus. Own work package with launch gate. | 6.10, 12 |
| Reduced motion, timers, chat live region | Specified, including JS motion and static equivalents. | 6.10, 8, 7 |
| CI assumptions false (no Playwright, no `npm run lint`) | Test plan rewritten around what CI actually runs: `node --test`, a contrast script and `lint-ui.js` additions. Playwright is dropped (not P1). | 13 |
| Launch assets depend on P1 items | Gallery and video rewritten to what P0 delivers. Phone, palette, consent dialog, citations are v2 assets. | 11 |
| Lockdown claims outrun enforcement | Captions limited to what Python enforces. "Blocks every outbound path" waits for GATE-1 and GATE-2. | 11.4, 12.3 |
| Demo and sample flow wrong | Sample is a bundled transcript-only fixture loaded by a new copy-from-bundle endpoint; MCP, export, sync, retention exclusion has its own work item; OCR checker prints counts only and runs locally. | 6.6, 11.3 |
| Rehearse depends on an unbuilt endpoint | `ChatPanel` is built against a scripted fixture stream first. Launch date is gated on the real endpoint, not on UI. | 7 |
| Real fonts/MIME/cache | Audit items 17 and 18 dropped (wrong). P0 uses the system font, so no font work. | 1, 3.2 |

Rejected or modified, with reasons:

- **Remove dark mode entirely** (implied by the scope review): rejected. The app already ships dark tokens; the cost is two hand-written token blocks. What is cut is bespoke dark art, a dark gallery and dark-specific polish. Gallery is light only.
- **Keep Inter, ship one wght-only file** (review 1): modified further. P0 uses the system font (SF Pro), which is native and zero work. Inter is a P1 option only if the owner wants it (section 3.2 gives the corrected subset command).
- **Contenteditable title** (draft): rejected in favour of the review-2 alternative. The existing input-based `title-editor.js` is already accessible; it is restyled only.
- **Persona/user bubbles in Rehearse**: replaced by transcript-style turns (accepted from review 1), which also reuses the transcript component.
- **Gate `Sync to VM` behind `developer_mode`**: moved to P1. The button is already hidden unless sync is configured (`cloud.py` `configured`), and the capture uses a throwaway data dir. A new `developer_mode` setting adds audit surface, so it is only worth it if the owner wants it.
- **Playwright pixel-diff baselines**: rejected for P0 and P1 (Chromium cannot render `hiddenInset`; rasterisation differs per macOS version; new devDependency). Replaced by Node unit tests, a contrast script and a scripted manual capture checklist.
- **Full README/website asset package** (review 3): partially accepted. The README hero loop is cut from the video; a separate website is not this track.

---

## 1. Audit of the current UI (corrected)

Read: 8 screenshots, `styles.css` (936 lines), `index.html` (702 lines), `floater.html`, `main.js`, `package.json`, renderers.

| # | Finding | Evidence and status | Fix |
|---|---|---|---|
| 1 | Large gap between speaker label and text in the transcript | `.notepad-readonly{white-space:pre-wrap}` (`styles.css:368`); `renderCleanTranscript()` builds rows from a multi-line template literal. Plausible root cause, **not yet proven**: `.timeline-turn-head` is a flex row with `justify-content:space-between`, which could also create a wide gap. | Verify in the Browser pane first (toggle `white-space`, toggle flex). Then `white-space:normal` on `#notepadTranscript` and build rows without inter-element whitespace. Check every turn host: view mode, edit mode, find-in-transcript marks. |
| 2 | Raw `[ ]` in action items | `renderMarkdownSubset()` (`detail.js:316`) lacks task syntax; default prompt asks for `- [ ]` (`notes.py:27`) | Task rows (6.2) |
| 3 | "Ask anything... COMING SOON" disabled row | `index.html:337-340` | Remove for launch (P0 minimum). Replace with `ChatPanel` only if LF-10 lands. Never ship a half-working composer. |
| 4 | Every meeting says READY TO COACH (coral) | `views.py:351` sets `ready_for_coaching` when the plugin has not run; plugin is off by default; coral reads as an error | UI-only: `stagePill()` (`core.js`) shows nothing when ready. Backend values unchanged (no plugin-track coupling). |
| 5 | Serif/sans mismatch in Settings | `.settings-title` uses Source Serif 4/Georgia (`styles.css:458`) | Remove the serif. |
| 6 | Emoji + line icons + pixel icons | `pixel-icons.js` in nav; emoji in actions | One inline-SVG set for the surfaces in the P0 screens (about 22 icons), emoji lint advisory. |
| 7 | "Sync to VM" in the topbar | already hidden unless sync `configured` (`detail.js:356`) | Low first-impression impact. Deferred to P1. |
| 8 | Empty states do not sell | People, Memory, Home | Section 6.7 |
| 9 | Dashboard-era chrome | "Home" h1 + subtitle, blurred topbar, 6-control filter bar | Remove topbar; per-view header. |
| 10 | Home list looks washed out | possible mid fade-in capture; `.session-row p{font-size:9px}` and 10px pills are unreadable | 12px floor. |
| 11 | 9-12px type | `.session-row p`, `.kicker`, `.sidebar-section-label`, `.legend` | 12px floor, status text 12px. |
| 12 | Perf telemetry in the sidebar ("LOCAL USAGE") | `folders.js loadLocalStats()` | Move to Settings (P1; for P0 just hide the card). |
| 13 | Token names lie (`--amber:#2f6fed`, `--violet:#2f6fed`) | `styles.css` header | Compat alias block (3.4); the new tokens carry honest names. |
| 14 | Dead CSS | grep-based list only; dynamic class names in JS are missed by grep | **P1, last**: purge only classes absent from both a grep and a runtime class-usage trace. See 14.2. |
| 15 | Generic app icon with baked white margin; tray uses a 2048px colour PNG resized to 16px | `src/icon.png`, `main.js:1018-1020`. The Dock icon is `src/icon.icns` (`package.json build.mac.icon`), so **inspect the icns first** before claiming the margin bug applies to what users see. | Section 9 |
| 16 | `window.prompt()` for "Who is speaking?" | `transcript.js` | `<dialog>` primitive |
| 17 | ~~Static files `no-store`~~ | **Dropped.** `createWindow` already calls `session.clearCache()` (`main.js:308`) so cache headers buy nothing across launches; the read is loopback. | none |
| 18 | ~~`.woff2` MIME on Python 3.10~~ | **Dropped.** `mimetypes.guess_type('x.woff2')` returns `font/woff2` locally; the bundled runtime is 3.11; Chromium does not reject fonts on MIME. | none (P0 ships no webfont) |
| 19 | Floater toast clipped | `.toast{position:absolute;top:-24px}` / `.show{top:-30px}` (`floater.html:204-223`); window is 46px tall, so the toast is above the window and invisible | Fold "Saved" into the pill (6.8) |
| 20 | Floater drawer clipped | **Not a bug.** `floater.js:132` calls `expandFloater(drawerOpen ? 84 : 46)`; `main.js:218` clamps 40-800 | none |
| 21 | Floater `backdrop-filter` does nothing | transparent frameless panel; there is nothing behind the page to blur | Remove; opaque capsule |
| 22 | No application menu | `grep globalShortcut\|setApplicationMenu` finds nothing; Electron's default menu is active, where Cmd+Shift+R is Force Reload | Section 5.3 |
| 23 | Main window created `show:true`, 1080x850, no min size, no state persistence | `main.js:292-304` | Section 5.1 |

Peers set the bar: Granola is document-first, Linear is dense and keyboard-first, Raycast is command-first. We copy principles, not pixels, and we deliberately keep the frame plain so one distinctive element can carry the brand (section 2).

---

## 2. Visual direction

One sentence: **the notes are the product, the chrome gets out of the way, and the Ring tells you where your data is going.**

### 2.1 Principles

1. **Document first.** A meeting is a page. Header, tabs and actions together stay under 120px; notes start above the fold at 800px window height.
2. **Status is silent when fine.** A row shows a badge only for things that need attention.
3. **Calm density.** 13px UI, 15px reading text, 12px floor (including badges), 4px grid, hairlines instead of boxes, no nested cards.
4. **Plain by design, distinctive in one place.** Neutral paper, system font, ink buttons: deliberately the conventional frame. Craft time goes to the Ring, the notes page and the floater.
5. **Honest empty states** that show the product and offer a one-click way to fill them (record, load sample).
6. **No advertised feature that is not built.** A keycap, tab, nav item or chip appears in the same commit as the behaviour. The old doc violated this with ⌘⇧R and ⌥⌘P.
7. **Colour never carries meaning alone.** Every state has text or an icon.

### 2.2 The signature: the Ring

The brand mark is an open ring (a "C", aperture facing right where the conversation enters) with a dot in the opening. The **ring colour is the live privacy state**:

| State | Ring | Dot | Where the word appears |
|---|---|---|---|
| Local only | teal `--private` | ink | "Local only" |
| Local, Claude/MCP connected | amber `--cloud` | ink | "Local · Claude connected" |
| Cloud service in use | amber `--cloud` | ink | "Cloud: Gemini transcription" |
| Locked down | slate `--lock` | ink | "Locked down" |

Appearances (P0, three only, so the system stays cheap):

1. Sidebar header: 20px Ring plus the chip text; click opens Settings > Data & privacy.
2. Settings engine cards: Ring top-left of each card in that card's state.
3. Floater: the recording dot sits inside a 12px Ring in state colour.

The Ring is also the app icon and tray glyph (monochrome in the tray). Rendering check done: the SVG below was rasterised (Quick Look) at 256px and the arc geometry is correct (centre 32,32, r=20, opening about ±45°). The 16px risk is the dot (about 1.8px). Rule: the dot is drawn at 20px and above; the tray template and any 16-18px use is the ring only.

```svg
<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" fill="none">
  <path d="M45.5 17.5A20 20 0 1 0 45.5 46.5" stroke="currentColor" stroke-width="8" stroke-linecap="round"/>
  <circle cx="47" cy="32" r="3.6" fill="var(--ink, #1B1A17)"/>
</svg>
```

Teal rule, enforced: `--private*` tokens are referenced only from the privacy chip, the Ring, the engine cards and "Local" provenance labels. `scripts/lint-ui.js` fails if `var(--private` appears in any other selector. Primary buttons, focus, selection, checkboxes, links, active nav and "You" are neutral ink.

---

## 3. Tokens

### 3.1 Colour (`src/ui/web/tokens.css`, loaded before `styles.css`)

Both dark selector blocks are written out in full. `scripts/lint-ui.js` gains a check that the `@media (prefers-color-scheme: dark)` block and the `[data-theme="dark"]` block have identical declarations. No build script.

```css
:root{
  color-scheme: light dark;
  /* surfaces */
  --bg:#FAFAF8; --surface:#FFFFFF; --surface-2:#F4F3EF; --surface-3:#ECEAE4;
  --line:#E8E6DF;            /* decorative hairlines only, never a control boundary */
  --line-control:#8A867C;    /* input, switch track, checkbox: >=3:1 (WCAG 1.4.11) */
  /* text */
  --ink:#1B1A17; --ink-2:#4A473F; --ink-3:#66625A; --ink-inverse:#FFFFFF;
  /* action: neutral ink */
  --action:#1B1A17; --action-hover:#34322D; --action-text:#FFFFFF;
  /* privacy state (teal is reserved, see 2.2) */
  --private:#0F7B6C; --private-soft:#E3F3F0; --private-line:#A9D8D0;
  --cloud:#B45309;   --cloud-soft:#FDF1E1;
  --lock:#475569;    --lock-soft:#E8ECF1;
  /* danger and recording share one red */
  --danger:#B3261E; --danger-soft:#FCE9EA; --danger-text:#FFFFFF; --rec:var(--danger);
  /* neutral highlight (search match, selection) */
  --mark:#DCE4F7; --select:#E4E2DA;
  /* speakers: no teal, amber, orange or red (those carry meaning). "You" is ink. */
  --sp-1:#2F5BD3; --sp-2:#B4306B; --sp-3:#7A3FC9; --sp-4:#52606D; --sp-5:#5E6B1F;
  --overlay:rgba(20,19,16,.42);
}
:root[data-theme="light"]{ color-scheme: light; }
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg:#0F100E; --surface:#171815; --surface-2:#1E1F1B; --surface-3:#272823;
    --line:#2A2B26; --line-control:#6B6C64;
    --ink:#ECEBE6; --ink-2:#B4B1A7; --ink-3:#9C998F; --ink-inverse:#0F100E;
    --action:#ECEBE6; --action-hover:#FFFFFF; --action-text:#0F100E;
    --private:#3DB8A5; --private-soft:#12302B; --private-line:#1F5C52;
    --cloud:#E9A24B; --cloud-soft:#33260F; --lock:#9FB0C3; --lock-soft:#1F2630;
    --danger:#F0636A; --danger-soft:#3A1B1D; --danger-text:#0F100E;
    --mark:#26324F; --select:#2C2D27;
    --sp-1:#7FA2FF; --sp-2:#F07BAE; --sp-3:#B48BFF; --sp-4:#9AA8B5; --sp-5:#B5C25A;
    --overlay:rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#0F100E; --surface:#171815; --surface-2:#1E1F1B; --surface-3:#272823;
  --line:#2A2B26; --line-control:#6B6C64;
  --ink:#ECEBE6; --ink-2:#B4B1A7; --ink-3:#9C998F; --ink-inverse:#0F100E;
  --action:#ECEBE6; --action-hover:#FFFFFF; --action-text:#0F100E;
  --private:#3DB8A5; --private-soft:#12302B; --private-line:#1F5C52;
  --cloud:#E9A24B; --cloud-soft:#33260F; --lock:#9FB0C3; --lock-soft:#1F2630;
  --danger:#F0636A; --danger-soft:#3A1B1D; --danger-text:#0F100E;
  --mark:#26324F; --select:#2C2D27;
  --sp-1:#7FA2FF; --sp-2:#F07BAE; --sp-3:#B48BFF; --sp-4:#9AA8B5; --sp-5:#B5C25A;
  --overlay:rgba(0,0,0,.6);
}
```

The `color-scheme` declarations answer the `<meta name="color-scheme">` finding: scrollbars, selects and autofill follow the toggle in the browser path. In Electron the theme comes from `nativeTheme.themeSource` (5.2), so `prefers-color-scheme` is already correct.

Contrast, computed from sRGB relative luminance (script in section 13 recomputes these on every CI run). Values in the draft that failed are corrected here.

| Pair | Light | Dark | Rule |
|---|---|---|---|
| `--ink` on `--bg` | 16.65 | n/a (see script) | text 4.5 |
| `--ink-2` on `--bg` | 8.87 | 7.0+ | text 4.5 |
| `--ink-3` on `--bg` / `--surface-2` / `--surface-3` | 5.81 / 5.47 / 5.05 | 6.69 / 5.81 / 5.21 | text 4.5 (draft `#77736A` was 4.52 / **4.26** / **3.93**) |
| `--action-text` on `--action` | 17.4 | 15.98 | text 4.5 |
| `--danger-text` on `--danger` (Stop pill, rec badge) | 6.54 | 6.08 | text 4.5 (draft `#E5484D` with white was **3.91**) |
| `--danger` text on `--bg` / on `--danger-soft` | 6.25 / 5.6 | 6.08 / 4.95 | text 4.5 |
| `--private` text on `--bg` / on `--private-soft` | 4.94 / 4.51 | 7.81 / 5.80 | text 4.5 |
| `--cloud` text on `--bg` / on `--cloud-soft` | 4.81 / 4.51 | 8.84 / 6.83 | text 4.5 |
| `--lock` on `--bg` | 7.25 | 8.61 | text 4.5 |
| `--line-control` on `--surface` / `--bg` | 3.63 / 3.48 | 3.36 (surface) / 3.59 (bg) | non-text 3.0 (draft `--line-strong` was **1.51**) |
| `--sp-1..5` on `--surface` | 5.8-6.5 | 6.9-7.3 | text 4.5 |
| Focus outline `--ink` on `--bg` | 16.65 | high | non-text 3.0 |

`--line` (1.2:1) is decorative and may never be the only boundary of an interactive control. Under `@media (prefers-contrast: more)`, `--ink-3` maps to `--ink-2` and `--line` to `--line-control`. There is no translucent surface in P0 (no vibrancy), so the translucent-contrast problem does not arise.

**Focus:** `outline:2px solid var(--ink); outline-offset:2px` on `:focus-visible`, with `border-radius:inherit` (the old `styles.css:70` rule forces `border-radius:4px` and squares pill buttons). Outline is not clipped by `box-shadow` overrides, and inside `overflow:hidden` ancestors use `outline-offset:-2px`.

### 3.2 Type

P0 uses the system font: `font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif`. This is what the app already renders (Inter was never shipped, so today it silently falls back to this). No webfont, no MIME, cache or CSP work. No serif anywhere.

Optional P1 (owner decision 9): self-host Inter for brand consistency. If done: one `InterVariable.<hash>.woff2` (wght axis only, latin), hashed filename so a change busts any cache; `pyftsubset` with `--layout-features+='tnum,ss01,cv11'` (the `+=` keeps `ccmp,locl,mark,mkmk`; the draft's `=` dropped them and would mis-position combining marks); unicodes must include `U+0300-036F` (combining marks), `U+1E00-1EFF` (Vietnamese and Latin Extended Additional) and `U+2318,U+2325,U+23CE` (shortcut glyphs). Ship `OFL.txt` and list it in the notices file (3.5). A 130 KB budget with opsz plus latin-ext is not realistic; do not promise it.

Scale (`--fs-*`; px / line-height / weight):

| Token | Size | LH | Weight | Use |
|---|---|---|---|---|
| `--fs-display` | 32 | 1.15 | 650 | Onboarding hero, empty-state hero |
| `--fs-title` | 26 | 1.2 | 650 | Meeting title |
| `--fs-h2` | 20 | 1.3 | 620 | View and settings panel titles |
| `--fs-h3` | 15 | 1.4 | 600 | Notes section headers (sentence case) |
| `--fs-read` | 15 | 1.65 | 400 | Notes and transcript text |
| `--fs-ui` | 13 | 1.45 | 450/550 | Buttons, rows, inputs, nav |
| `--fs-small` | 12 | 1.4 | 450 | Meta, helper text, badge text (floor) |

The draft's 11px uppercase `--fs-micro` is removed: badges carry status text, so they obey the 12px floor. Keycaps are 12px.

### 3.3 Spacing, radius, elevation

```css
:root{
  --s-1:4px; --s-2:8px; --s-3:12px; --s-4:16px; --s-5:20px; --s-6:24px; --s-8:32px; --s-10:40px;
  --r-sm:6px; --r-md:8px; --r-lg:12px; --r-xl:16px; --r-pill:999px;
  --shadow-1:0 1px 2px rgba(20,19,16,.08);
  --shadow-2:0 4px 14px rgba(20,19,16,.10), 0 1px 3px rgba(20,19,16,.06);
  --shadow-3:0 18px 50px rgba(20,19,16,.20), 0 2px 8px rgba(20,19,16,.08);
  --ease:cubic-bezier(.2,.8,.2,1); --dur-1:120ms; --dur-2:180ms; --dur-3:260ms;
  --side:236px; --content-max:760px; --wide-max:1120px; --chrome-h:52px;
}
```
Dark shadows reuse the same tokens with a `0 0 0 1px rgba(255,255,255,.05)` inset hairline added in the dark blocks of `components.css`.

### 3.4 Compat alias block (complete)

`styles.css` lines 1-67 are replaced by an alias block so unconverted rules keep working. The old app's `--amber`, `--violet`, `--blue` were all the primary-action blue `#2f6fed`, so they map to `--action`, not to teal. This is a visible recolour (blue buttons become ink), which is intended; LF-1 is therefore **not** invisible and is reviewed with before/after screenshots.

Procedure (so no variable is missed): run `grep -oh 'var(--[a-z0-9-]*' src/ui/web/styles.css src/ui/web/index.html src/ui/web/js/*.js | sort -u`, define every name, and add a lint (`scripts/lint-ui.js`) that fails on any `var(--x)` with no definition in `tokens.css` or the alias block. Known names to cover: `--paper --surface --surface-2 --surface-tint --surface-alt --ink --ink-secondary --ink-muted --hairline --amber --amber-soft --teal --teal-soft --coral --coral-soft --violet --violet-soft --violet2 --blue --shadow --success --text --text2 --muted --dim --panel --border --border2 --radius --red --green`.

```css
:root{
  --paper:var(--bg); --ink-secondary:var(--ink-2); --ink-muted:var(--ink-3); --hairline:var(--line);
  --amber:var(--action); --violet:var(--action); --blue:var(--action); --violet2:var(--action-hover);
  --amber-soft:var(--surface-3); --violet-soft:var(--surface-3);
  --teal:var(--ink-2); --teal-soft:var(--surface-2); --success:var(--ink-2); --green:var(--ink-2);
  --coral:var(--danger); --coral-soft:var(--danger-soft); --red:var(--danger);
  --surface-tint:var(--surface-2); --surface-alt:var(--surface-2);
  --text:var(--ink); --text2:var(--ink-2); --muted:var(--ink-3); --dim:var(--ink-3);
  --panel:var(--surface); --border:var(--line); --border2:var(--line); --radius:var(--r-lg);
  --shadow:var(--shadow-1);
}
```
The old success green becomes neutral ink with a check glyph (no new colour; teal is reserved). The block is removed once every screen is converted (P1).

### 3.5 Icons

Set: Lucide (ISC), 24px grid, `stroke-width:1.75`, rendered at 16/18px. Only the icons the P0 screens use (about 22): `layout-list users brain folder-open refresh-cw sparkles plus-circle pencil pause play square camera mic mic-off square-pen arrow-up-right search chevron-up chevron-down x copy check arrow-left settings-2 lock-keyhole triangle-alert cloud shield-check`. Not a 36-icon rewrite; screens outside P0 keep their glyphs until touched.

- `src/ui/web/icons.js` exports `ic(name,size)` and keeps `window.renderIcons(root)` and the `[data-icon]`/`data-size` API so existing markup works. `pixel-icons.js` is deleted and its script tag replaced. Inline SVG needs no CSP change; colour is `currentColor`.
- The floater cannot import served assets (`file://`, `default-src 'none'`), so it carries its own copy of its 6 paths (comment in both files). The parity check is a 15-line `node --test` that reads both files; it is only added because the Node test runner is added anyway (section 13).
- Licences: `THIRD_PARTY_NOTICES.md` at repo root (Lucide ISC text; Inter OFL text if P1 happens) and an "About > Open-source notices" row in Settings. Required for redistribution.
- Emoji lint (advisory in P0): regex `\p{Extended_Pictographic}` plus glyph-as-icon characters over `src/ui/web/**` and `floater.html`; user data is escaped, not markup, and is exempt.

---

## 4. Component kit: use platform primitives

`src/ui/web/js/ui-kit.js` (after `core.js`; one new entry in the `lint-ui.js` order list), styles in `src/ui/web/components.css`. Chromium in Electron supports the primitives below, which means less code and fewer ARIA bugs than hand-rolled widgets.

| Component | Built on | Notes |
|---|---|---|
| `openDialog({title,body,actions,input})` returns Promise | `<dialog>` + `showModal()` | Focus trap, Esc, inert background for free. Replaces `prompt()`/`confirm()`. |
| `openMenu(anchor,items)` | `popover="auto"` | Roving focus, arrow keys, typeahead, Esc; `role="menu"`; items `{label,icon,hint,disabled,reason,run}`. |
| Task checkbox | `<input type="checkbox">` styled `appearance:none` | Not `button role=checkbox`. |
| `badge(text,{tone,icon})` | span | Tones: neutral, cloud, lock, private, danger. 12px text always. |
| `emptyState({icon,title,body,actions})` | section | Static; art uses tokens (`currentColor` and `var(--*)`), never fixed fills, so dark mode works. |
| `skeleton(lines)` | div | Static tint under reduced motion (8). |
| `toast(msg,{tone,action})` | div `role="status"` | Max 3 stacked; pauses on hover **and focus**. |
| `segmented(items)` | `role="tablist"` | Roving tabindex, Left/Right/Home/End. Meeting tabs and Settings nav use the same pattern, so plugin tabs can join later. |
| `avatar(name)` | span | Initials; hue from `--sp-N` by name hash. AI personas get a dashed ring. |
| `ic(name,size)` | string | from `icons.js` |

Rules for every component:
- **No `style=""` attributes** in strings the kit emits. Dynamic values go through classes or CSSOM (`el.style.setProperty`), which the strict PWA CSP (`style-src 'self'`) allows. `renderMarkdownSubset` and the existing inline styles in `index.html` (80) and JS (about 28) are not touched in P0 for the desktop window (its CSP keeps `'unsafe-inline'`), but any code shared with the PWA must be clean.
- Hit target at least 28px (32px primary). Controls that are disabled by policy use `aria-disabled="true"` with a visible inline reason and `aria-describedby`, **not** the `disabled` attribute and **not** a tooltip (a disabled button is not focusable and shows no tooltip).
- Anything revealed on hover is also revealed on `:focus-visible` and `:focus-within`, and stays a focusable button (row chevron, folder delete).
- The kit does not hand-roll a command palette, install dialog or plugin surfaces in P0.

---

## 5. App shell

### 5.1 Window (`src/main.js:createWindow`)

```js
mainWindow = new BrowserWindow({
  width: 1200, height: 800, minWidth: 960, minHeight: 640,
  title: APP_NAME, icon: ICON_PATH,
  titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 16, y: 18 },
  backgroundColor: nativeTheme.shouldUseDarkColors ? '#0F100E' : '#FAFAF8',
  webPreferences: { /* unchanged: sandbox, contextIsolation, preload; add additionalArguments for boot state (5.2) */ },
  show: true   // unchanged. An opaque token-coloured backgroundColor prevents any white flash, so no ready-to-show / splash is needed.
});
```

Decisions:
- **No vibrancy, no transparency, no splash in P0.** Vibrancy would need `backgroundColor:'#00000000'`, clearing the opaque `html{background}` and body gradient under an `.is-electron` class set before first paint, a theme driven by `nativeTheme`, macOS 15 and 26 validation, and a signed-build check; it would also make sidebar contrast depend on the wallpaper. It is a P2 time-boxed experiment (half a day) and not a dependency of any launch asset. The splash would require creating the window before `verifyOwnServer()` (`main.js:1012-1016`) and would collide with the `did-fail-load` retry loop (`main.js:310-316`, which re-`loadURL`s the dashboard on any failure). Startup ordering stays as is.
- **Escape hatch:** `"ui_chrome": "classic"` in `config.json`, read synchronously in main (the same file `policy.py` reads for lockdown), applied at window creation (standard title bar, no `hiddenInset`), requires restart, documented in README troubleshooting. It is not a Settings control, and the dashboard payload is never involved (it does not exist at window creation).
- **Window state:** persist `{x,y,width,height,maximized}` to `userData/window-state.json` (debounced on `resize`/`move`, validated against `screen.getAllDisplays()` on load, default 1200x800). Full screen hides the traffic lights, so main sends `enter-full-screen`/`leave-full-screen` over IPC and `<html>` toggles `is-fullscreen`, which removes the 52px top inset on the sidebar. Test on a Retina laptop and a non-Retina external display. Closing hides the window (existing handler); unchanged.
- **Drag/no-drag audit** (required for `hiddenInset`; every control in the top 52px is listed and set `-webkit-app-region:no-drag`; the drag region is sticky header chrome that does not overlay scrolling content):

| Zone | Drag? | Interactive children that must be `no-drag` |
|---|---|---|
| Sidebar top 52px (below traffic lights) | drag | Ring/wordmark (not interactive), privacy chip |
| Home header (search, Filter, Record) | drag on empty space only | search input, Filter button, Record button |
| Meeting header row (back link, Copy, Regenerate, overflow) | drag on empty space only | all four |
| Settings view header | drag | none |
| Onboarding overlay top 52px | drag | Skip link |

  In the Browser pane (plain Chromium, no `electronAPI`), the app region properties are inert and the layout is identical (opaque everywhere), so dev screenshots remain valid.

### 5.2 Theme architecture

One source of truth per environment:
- **Electron:** `nativeTheme.themeSource` (`'system'|'light'|'dark'`), set by main from the stored preference and changed through one IPC (`set-theme`). Chromium's `prefers-color-scheme` follows it, so scrollbars, selects and autofill are right and no `data-theme` or `theme-boot.js` is needed. The window `backgroundColor` follows `nativeTheme.shouldUseDarkColors` and updates on `nativeTheme.on('updated')`.
- **Browser and PWA:** `data-theme` on `<html>` from `localStorage.theme` (try/catch; may throw), applied by `boot.js`.
- **Floater:** always dark constants (it floats over arbitrary content, matching macOS HUD convention); documented, not themed.
- **Tray:** `*Template` images; macOS tints them.
- **Existing users:** the `localStorage.theme` key is read once on first launch of the new build, forwarded to `set-theme`, and thereafter ignored in Electron. No existing settings keys are renamed or removed. New keys are optional with defaults. Rollback of the whole look is a revert; no data migration exists to undo.

`src/ui/web/js/boot.js` is a tiny external script in `<head>` (CSP `script-src 'self'`; no inline script). Before first paint it sets `data-electron`, `data-lockdown` (from the preload value, 5.4) and, in the browser only, `data-theme`.

### 5.3 Application menu and shortcuts (new, `src/main/menu.js`)

Current state: no `Menu.setApplicationMenu` and no `globalShortcut` anywhere in `src/`, so Electron's default menu is active (Cmd+R reload, **Cmd+Shift+R Force Reload**, Cmd+Opt+I devtools). Force Reload mid-meeting is a hazard, and Cmd+Shift+R is also Zoom's record shortcut.

P0 builds a real menu: App (About, Settings… `⌘,`, Hide, Quit `⌘Q`), Edit (standard roles), View (Home/People/Memory `⌘1/⌘2/⌘3`, each sends a `navigate` IPC; reload and devtools only when `!app.isPackaged`), Window (minimize, `⌘W` hides as today). No zoom items (so the 960px minimum width is reachable only by resizing, and the old "below 820px bottom tab bar" and "below 1100px icon rail" layouts are **not built**; they were unreachable in Electron).

| Shortcut | Mechanism | Phase |
|---|---|---|
| `⌘,` `⌘1` `⌘2` `⌘3` `⌘W` `⌘Q` | application menu accelerator | P0 |
| `⌘K` command palette, `⌘F` find in transcript | menu item / DOM keydown | P1 (with LF-9) |
| Record toggle | opt-in `globalShortcut`, **unset by default**, chosen in Settings > Preferences, validated at registration with a visible error if taken; the picker warns about `⌘⇧R`, `⌘⇧A`, `⌘⇧M`, `⌘D` (Zoom, Meet, Teams, Force Reload). Suggested `⌃⌥⌘R`. | P1 |
| Pause | none (tray menu and floater button) | n/a |

`keycap(id)` takes an id from a `SHORTCUTS` registry that main also reads; a shortcut that is not registered cannot render a keycap. Floater tooltips show no keycaps. The floater is a non-activating panel and is not keyboard reachable; every floater action (pause, stop, note) already exists in the tray menu (`updateTrayMenu`), which is the keyboard path and is stated in the VoiceOver checklist.

### 5.4 Sidebar and the privacy chip

Sidebar (236px, opaque `--surface-2`; `--chrome-h` top inset under traffic lights):

```
 [traffic lights]
 (Ring) Cora                             <- 15/650
 [ (Ring) Local only            ]        <- chip, 28px high, button, opens Settings > Data & privacy
 Home / People / Memory                  <- rows 32px high, 16px icon, 8px gap, 12px side padding
 FOLDERS                      +          <- 12/600 --ink-3, 20px above
   All notes                     12      <- count right aligned, tabular
   Customers                      6
 --------
 (dot) Ready to record                   <- idle / recording 12:41 / processing (existing banner state)
 Settings                         ⌘,
```

- Search is a real `button` named "Search" opening the existing find (palette in P1). Not a fake input.
- Active item: `--surface-3` fill and a 2px `--ink` bar; no teal.
- "Local usage" card hidden in P0 (moved to Settings > System in P1). Folder delete moves from `x` to a `...` button revealed on focus and hover, opening `openMenu`.
- Plugin group appears only when at least one plugin contributes a view (plugin track). Not built in P0.
- The topbar is removed; each view renders its own sticky header. `#viewTitle` stays as `.sr-only`, and `showView()` moves focus to the new view's heading (`tabindex="-1"`) rather than relying on an aria-live h1.

**Privacy state, honestly derived.** `GET /api/privacy/summary` lives in `python/api/routes/system.py`. It is behind the normal authorize path in `python/api/http.py` (not added to `PUBLIC_PATHS = {"/api/health"}`; same loopback Host, Origin and token checks as every `/api` route). The same object is also embedded as `privacy` in the dashboard payload so the renderer needs **no polling loop and no new event channel**; the renderer refreshes it where it already refreshes the dashboard and after any settings save.

```json
{ "lockdown": false,
  "lockdown_covers": ["asr","notes","vm_sync","log_upload","tracing"],
  "asr":   {"engine":"local|gemini","cloud":false},
  "notes": {"provider":"local_mlx|gemini|anthropic|openai|vertex|ai_studio|custom","cloud":false},
  "mcp":   {"seen_recently":false,"lockdown_enforced":false},
  "sync":  {"vm_sync":false,"log_upload":false},
  "plugins_with_egress": null,
  "retain_audio": true,
  "state": "local|connected|cloud|lockdown|lockdown_partial" }
```

- `asr` and `notes` are the **effective** values (what `pipeline/cloud_asr.py` and the credentials resolver would actually do), so under lockdown they report `cloud:false`.
- `sync` comes from `vm_sync_host`/`vm_sync_dir` and `log_upload_url` being set. `mcp.seen_recently` requires a small heartbeat: `mcp_server.py` writes a last-seen timestamp (settings KV) on each tool call; `seen_recently` means within 24 hours. `mcp.lockdown_enforced` is `false` until GATE-2 (the MCP server currently has no lockdown check). `plugins_with_egress` is `null` ("unknown") until the plugin track defines egress scopes; `null` is treated as empty and the field becomes a list when the plugin track lands.
- `lockdown_covers` states what lockdown enforces today (Python paths only). It is shown in the Data & privacy panel so auditors see the true scope.
- `state` is computed server-side so the renderer, README table and tests cannot disagree: `cloud` if any of `asr.cloud`, `notes.cloud`, `sync.*`, or egress plugins; else `connected` if `mcp.seen_recently`; else `local`. If `lockdown`: `lockdown`, except `lockdown_partial` when MCP was seen and `lockdown_enforced` is false (chip: "Locked down · Claude connected (not covered)").
- Never returns secrets, hosts, paths or key names. Test asserts the JSON contains none of `key`, `host`, `url`, `path`.
- Chip copy is a state indicator and an honest list, not a compliance claim. Popover title: "Where your data goes right now", rows per category. Marketing says "local by default", never "nothing leaves".
- **Lockdown rendering before the payload arrives:** main reads lockdown (env var or `config.json`, same logic as `policy.py`) and passes it via `webPreferences.additionalArguments`; preload exposes read-only `electronAPI.lockdown`; `boot.js` sets `data-lockdown` before first paint. In the browser/PWA, where no preload exists, cloud controls start `aria-disabled` and enable only after the summary says otherwise (**fail closed**). The floater has no cloud controls; the PWA shows a "Locked down" notice only.
- **Lockdown acceptance (not just "disabled"):** the reason is visible text ("Blocked by enterprise lockdown"), the control is reachable by keyboard and described by `aria-describedby`, and an audit test (13) asserts the summary mode and that the route enforces Host/Origin/token like its siblings.

---

## 6. Screens

All measurements are CSS px.

### 6.0 Commit zero: the three fixes that make screenshots look right (LF-0, before any token work)

Standalone commit, low risk, high visibility:
1. Transcript gap (finding 1), after verifying the cause in the browser.
2. Task rows (6.2).
3. Stage badge (finding 4) UI-only, and remove the disabled "Ask anything" row.

### 6.1 Home

```
 [52px sticky header, drag]  Search…                [Filter]  [● Record]
 TODAY                                      <- 12/600 ink-3, 20px above, 6px below
 ┌────────────────────────────────────────────────────────┐
 │ Q4 roadmap review                    (PS)(RM)(DC)  1:21  │  <- row min-height 56, padding 10 12
 │ 11:00 · Planning · Zoom                                  │  <- title 14/600 (20), meta 12 ink-3 (16)
 └────────────────────────────────────────────────────────┘
 YESTERDAY …
```

- Grouped by day (client-side `dayBucket`). `--wide-max`. Row hover `--surface-2`; chevron revealed on hover and focus.
- Badges only when needed (`Recording` red dot with text, `Transcribing…`, `Writing notes…`, `Needs your voice`, `Failed, retry`). Finished meetings show no badge. Stage mapping is UI-only in `stagePill()`; `coached` shows a neutral badge only if the coaching plugin is enabled; backend stage values are unchanged.
- **No notes preview line and no `talk_share` in P0.** `recording_item` does not emit `preview` or talk share; adding fields is out of this track's P0. Before building rows, verify what `/api/dashboard` `recordings[]` really contains (`participant_names` and `meeting_tool` exist at `views.py:387,393`). If `call_summary.overview` is already in the payload, a one-line preview is allowed; otherwise omit.
- The six-control filter bar keeps its existing controls in P0 (restyled with the kit); the single Filter popover and folder-filter removal are P1.
- Skeleton rows while `data===null`; reserved row height. Empty state per 6.7.
- Live row pinned on top while recording, replacing the poll-driven banner text (reuses existing state).

### 6.2 Meeting detail

```
 <- Home                                            [Copy v] [Regenerate v] [...]
 Q4 roadmap review                         <- 26/32, 650; click-to-rename (existing input editor, restyled)
 15 Oct · 11:00 · 21 min · Zoom · Planning   (PS)(RM)(DC)(AR)      <- 13/20, margin-top 6
 Notes   Transcript   People               <- tabs 36px high, 2px ink underline
 ┌ column 760 ───────────────────────────────────────────┐
 │ Overview                                   <- 15/600 ink, margin-top 28, bottom 8
 │ Q4 roadmap review with Priya Shah, …       <- 15/24.75, max 68ch
 │ Action items
 │ [ ] Rahul Mehta · share the revised Q4 timeline · Fri  <- row min-height 32, checkbox 16, radius 4, 1.5px --line-control
 │ Decisions · Open questions
 └────────────────────────────────────────────────────────┘
```

- Actions (replaces five emoji buttons, `index.html:259-267`): `Copy` split menu (notes, transcript, action items), `Regenerate` menu (Re-summarize with a `cloud` badge and the confirm dialog when the provider is cloud; Retranscribe), `...` menu (Open folder, Add to this meeting, Version history, Delete). Visibility logic stays in `loadNotepad()` (`detail.js:139-273`) but sets `aria-disabled` on menu items.
- Tabs `Notes | Transcript | People` (renamed from four). The raw event log becomes a `Turns | Events` toggle inside Transcript. Enhanced/Raw becomes a small segmented control inside Notes. Key phrases move to a disclosure at the foot of Notes (IDs preserved).
- Processing state replaces the candy-stripe bar: three named steps (`Transcribed`, `Identifying speakers`, `Writing notes`) plus text progress, driven by the existing `pipeline_progress` payload. Under reduced motion it is a static current-step highlight with the step name as text.
- Live recording bar uses the floater's visuals (6.8).
- **Task items** (`renderMarkdownSubset`, `detail.js:316-339`): `- [ ]`/`- [x]` render as a native checkbox row; owner split only when `^([^—:]+?)\s[—-]\s(.+)$` matches, else plain text.
  **State key:** `todo_state` is keyed by `(recording_id, item_index)` (`db.py:87-94`), so regeneration would misapply or reset state, which is data loss in a hero screenshot. Fix now, cheaply: add a nullable `item_key TEXT` column through the existing `db.py` migration pattern (first 12 hex of sha1 of the normalised item text); the UI sends both `item_index` and `item_key`; lookup prefers `item_key`. A regenerated item with unchanged text keeps its checked state; changed items start unchecked with no toast needed. (This replaces the draft's "clear on regenerate".)
- Citation chips ("from 02:14") are P1, gated on the templates track emitting `citations`. No chip until the data exists.
- Files: `index.html:246-343` restructured, `detail.js`, `notepad.js`, `detail-actions.js`, `title-editor.js` (restyle only), `search.js` (panel ids), `transcript.js`.

### 6.3 Transcript

- Grid `72px 1fr`; timestamp 12px tabular `--ink-3`; speaker name 13/600 in `--sp-N` (name text is always shown, so colour is never the only cue; "You" in `--ink`); text 15/1.65; 16px between speaker groups; no hairlines.
- Same-speaker consecutive turns are **merged for display** in `groupTurns(segments)`; the edit mode shows per-segment (keeps `data-turn-index`). Merging is a presentation change, but it interacts with find marks and edit mode, so it is P1 together with the audio scrubber (click-to-seek, speed control, scrub). The scrubber is a new feature, not a look: audio is not always retained (`retain_audio`, `transcribe.py:254`; the playback mix is built server-side in `media.py`), so it needs an explicit "Audio not retained for this meeting" state. Sample meetings have no audio at all (6.6).
- P0 transcript = gap fix, 15/1.65 type, speaker colours, `openDialog` instead of `prompt()`, find marks restyled to `--mark` plus a 2px `--ink-2` underline (active match: `--ink` background with `--ink-inverse` text).

### 6.4 People

Meeting People tab and People view: restyle only in P0 (avatar, name, role, rename/merge in a `...` menu). Talk-time bars, card grid and Open threads are P1.

### 6.5 Settings (P0: engine cards and Data & privacy only)

Flat 8-item nav stays; the full regroup, provider list, MCP code tabs and Advanced section are P1. P0 changes:
- Panel titles use `--fs-h2` in the UI font (removes the serif).
- **Engine cards** (Transcription): two radio-semantics cards, Local (Ring teal, "Private. Audio never leaves this Mac.", DEFAULT) and Google Gemini (Ring amber, "Higher accuracy on mixed-language meetings. Audio chunks are uploaded to Google using your key."). Same `transcription_engine` setting (`index.html:409-415` select replaced; `settings.js` handlers adjusted).
- **Confirmation, not auto-save, for anything that sends data out.** Selecting the Gemini card, changing the notes provider to a cloud provider, or saving a cloud key opens `openDialog`: "Send audio to Google?" listing what leaves the Mac (audio chunks of each recording transcribed after this point), to whom (Google Gemini API, your key), what stays (everything already on disk), and how to undo. Buttons: `Cancel` (default focus) and `Use Google Gemini`. Switching back to local needs no confirm. Under lockdown the Gemini card is `aria-disabled` with visible text "Blocked by enterprise lockdown" and a `lock-keyhole` badge.
- Auto-save applies only to benign preferences (name, role, theme). Privacy-bearing and destructive settings (engine, provider, keys, `retain_audio` off) use explicit confirm or the existing Save with Test.
- **Data & privacy panel** (new): "Where your data goes right now", a table fed by the privacy summary: Feature, Where it runs, Leaves the Mac? Rows: Transcription, Notes, Speaker identification (always local), Claude/MCP (seen recently or not; "Not covered by lockdown yet" until GATE-2), Plugins (egress list or "none"), Sync and log upload, Audio kept. It also prints `lockdown_covers`. The same wording feeds README.

### 6.6 Onboarding and the sample meeting (trimmed)

Current: 6 steps, an orphaned Vertex/AI Studio step (`index.html:80-147`), "STEP 1 OF 3" vs "STEP 2 OF 5" contradiction, bare inline-styled inputs.

P0 (three screens, one decision each, no looping animation):
1. **Permissions**: three rows with live status, `Grant` / `Open Settings`, copy explaining why before macOS asks (preserved), automatic re-check every 1.5s while visible (existing status endpoint).
2. **You**: name and role. Meeting types and people leave onboarding (no pipeline reads meeting types today, per `code_notes.json`).
3. **Hear it work**: model download with real progress, then two buttons: `Load a sample meeting` (default) and `Record a test`. First screen after onboarding is never empty.
Delete the orphaned Vertex step markup (the credentials modal `index.html:604-679` stays the canonical form). `Skip setup` link; Esc does not skip. A welcome hero/animation is P2.

**Sample meeting** (corrected design):
- A bundled, **transcript-only** fixture `python/samples/q4-roadmap-review/` (transcript, notes, participants, metadata `sample:true`). Generated once, offline, from `tools/seed_demo_data.py` output and then reviewed by hand; the seed script's pink-noise audio is **not** shipped (it is noise, not speech; redistributing TTS audio raises licence questions). Because there is no audio, the Transcript tab shows "Audio not retained for this meeting".
- Names reconciled with the seed: the user is **Alex Rivera**, attendees Priya Shah, Rahul Mehta, Dana Cruz, customer **Northwind Labs** (the draft used "Acme" and listed Alex as an attendee, both inconsistent with `seed_demo_data.py`).
- `POST /api/samples/load` and `/api/samples/remove` (no parameters, idempotent, no network, no path input) in `python/api/routes/recordings.py`; they **copy from the bundle**, which is a different mechanism from the seed CLI (that refuses a non-empty dir and takes a path). Add `python/samples/**` to the packaged `files` (already covered by `python/**/*`).
- The sample is labelled "Sample" everywhere and its notes carry the caption "Sample output, not a live transcription". It must be excluded from: MCP (`cora_list_recordings`, `cora_get_*`, search in `mcp_server.py`), exports, VM sync, retention sweeps, speaker matching and People learning (sample people are `sample:true` and only visible inside the sample). Own work item, LF-8, with tests (13).

### 6.7 Empty states

Icon in a 48px `--surface-3` circle, 17/600 title, 13 `--ink-2` body (max 44ch), 1-2 actions.

| Screen | Title | Actions |
|---|---|---|
| Home, no meetings | Your first meeting starts here | `Load a sample meeting`, `Record now`; drag-drop import is P1 |
| Home, filters match nothing | Nothing matches | `Clear filters` |
| People | Cora learns who's who | `Open a sample meeting` |
| Memory | Cora's vocabulary | inline add field |
| Notes not ready | Writing your notes… | none (stepper + skeleton) |
| Notes, no summary | No notes yet | `Generate notes` |
| Transcript, none | No transcript | `Retranscribe` |

(The Plugins and Rehearse empty states belong to the plugin surfaces and ship with them.)

### 6.8 Floater (scope cut to what is true)

Real problems: emoji and 9-11px text, toast clipped above the window, a 470px width that is more than needed, `backdrop-filter` that does nothing. Not a problem: the drawer.

- **Opaque dark capsule**: `background:#1B1A17`, 1px `rgba(255,255,255,.10)` border, radius 999, same shadow. The window stays `transparent:true` + `type:'panel'` + `hasShadow:true` (unchanged). No vibrancy, no blur.
- **Size:** prototype before committing. Budget: dot-in-Ring and timer about 64, two level glyphs about 60, four 28px icon buttons plus gaps about 128, Stop pill about 64, padding and dividers about 40, so roughly **360px** (not 300, not 470). Height unchanged: 40px pill plus 3px wrapper padding each side is **46px** (not 44). `expand-floater` is reused as is.
- Buttons (28px, icon only, `aria-label` and `title`): `square-pen`, `camera`, `mic`/`mic-off`, `pause`/`play`, then a red `Stop` pill (`--danger` fill, white text, 6.54:1). The open-Cora arrow is always visible (not hover-only) because it is a focusable button.
- Meters: two 3-bar glyphs labelled `You` and `Sys`. Colour is not the only cue: quiet over 10s renders dashed outline bars and `aria-label="You: quiet"`; clipping renders a tick mark and "loud".
- **States** inside the pill, one element: `recording`, `paused` (amber dot, text "Paused" replaces meters), `muted`, `saving` (spinner, "Saving…"), `done` ("Saved · Open notes", auto-hides after 4s; the timer pauses while the pill has hover **or focus**). The floating `.toast` element is deleted, which fixes finding 19.
- Reduced motion: dot stops breathing (static), transitions instant.
- Ring: the recording dot sits inside a 12px Ring in privacy-state colour (`state` from the dashboard, delivered over the existing floater channel). Under lockdown the Ring is slate.
- Not in P0: a rewritten state machine and its unit tests. The icon swap, toast fix, width, capsule and Ring are about 0.75 day.

### 6.9 Plugin surfaces (what this track styles; contracts belong to the plugin track)

P0 plugin UI is **host-rendered only** (declarative tab content via `renderMarkdownSubset`, actions in the Regenerate menu, settings forms). Anything that needs a third-party iframe depends on plugin-track prerequisites that this doc relies on but does not own: `protocol.registerSchemesAsPrivileged` for `cora-plugin://` before app ready, an explicit `frame-src cora-plugin:` in the page CSP (today `default-src 'self'` makes `frame-src` fall back to `'self'` and would block it), a stricter CSP on plugin responses (`connect-src 'none'`), `sandbox` flags on the frame, and a navigation guard (`security.js isTrustedUrl` trusts only the dashboard and floater URLs; `will-frame-navigate` must be added). The consent dialog (P1) uses an acknowledgement **checkbox** ("I understand this plugin will do the things listed above") that enables the Install button; the draft's "disabled until the scope list scrolls into view" is unreachable by keyboard and screen-reader users and is removed. A plugin-contributed token stylesheet (`cora-plugin://<id>/_tokens.css`) must remain compatible with a frame CSP of `style-src` allowing that scheme; it is not P0.

### 6.10 Accessibility (own work package, launch gate)

The app has about four `aria-` attributes and no `role` attributes in `index.html` today. LF-A11Y (1.5 days) covers:
- Landmarks (`nav`, `main`), a skip link, heading focus on view change.
- Tablist pattern (roving tabindex, arrows) for meeting tabs, Settings nav and the segmented control.
- `aria-disabled` plus visible reason text for lockdown and policy blocks.
- Hover-only affordances revealed on focus (row chevron, folder menu, floater).
- Search trigger is a `button`; sidebar chip and icon-only buttons have accessible names.
- Reduced motion (section 8) including JS-driven motion; no looping welcome animation in P0.
- Toasts `role="status"`; auto-dismiss pauses on hover and focus.
- Contrast script green (section 13).
- **Launch gate:** a keyboard-only pass and a VoiceOver pass over first run, Home, Notes, Settings > Transcription (including the confirm dialog), and Rehearse. Floater actions are verified through the tray menu.

---

## 7. Rehearse (the hero, built so it cannot block the launch look)

Contracts (streaming endpoint, scenario object, `lockdown` flag) belong to the plugin track. Two things are decided here:

1. **`ChatPanel` is built against a scripted fixture stream first** (`ChatPanel.fixtureStream(events)`), so the UI, unit tests and the first capture can be finished while the real `/api/chat/stream` is unbuilt (a repo grep finds no such route today). The **launch date is gated on the real endpoint**, not on the UI: the gallery shot and video beat must show a live response from the local model before launch. Measure first-token latency on the owner's Mac in LF-10; if it is slow, the UI shows "Loading local model… Ns" and the video speed-ramps with a visible tag or uses a pre-warmed model.
2. **Transcript-style turns, not chat bubbles.** Persona and user turns reuse the transcript component (speaker label, text, 16px between turns); persona turns carry a dashed-ring avatar and a persistent `AI` tag; the user is "You" in ink; coach notes are inset blocks with a 3px `--ink-2` left rule and the `sparkles` icon, collapsed after the next user turn. This reinforces the document-first identity and avoids the generic iMessage/ChatGPT look.

```
 <- Q4 roadmap review                                            [End session]
 ┌ Scenario ───────────┐  ┌ AI role-play. Priya Shah is simulated from 3 meetings. ┐
 │ Talking to Priya Shah│  │ It can be wrong. Runs on this Mac.  [Local · Qwen3 4B] │
 │ Goal: ship the API   │  │                                                        │
 │ first                │  │  Priya (AI)   So you're moving the sync date again?   │
 │ Style: Direct …      │  │               Walk me through why.                    │
 │ Difficulty  ──●──    │  │  You          I hear the concern. The …               │
 │ [Start rehearsal]    │  │  ▎Coach: you opened with the apology. Try …           │
 └──────────────────────┘  │  [ Type your reply…                          ] [Send] │
                           └────────────────────────────────────────────────────────┘
```

- Honesty banner (text, not tooltip): "AI role-play. Priya Shah is simulated from 3 meetings. It can be wrong." plus the provider line, which reads "Runs on this Mac" for a local provider and "Sent to Google Gemini" (amber) for a cloud provider. Under lockdown cloud providers are not selectable ("Local only").
- Transport: `fetch` + `ReadableStream` on the same-origin loopback API. **Server framing:** `BaseHTTPRequestHandler` defaults to HTTP/1.0, so do not use chunked encoding or change `protocol_version` for every route. Send `Content-Type: text/event-stream`, `Connection: close`, write `event:`/`data:` lines and flush; EOF ends the stream. One in-flight stream per conversation; `AbortController` on navigation and End; server idle timeout and a cap of 4 concurrent streams belong to the plugin track.
- **Accessibility:** the message list is **not** a live region (per-token appends would make VoiceOver read fragments). It sets `aria-busy="true"` while streaming. A separate visually-hidden `role="status"` node receives the finished message once on `done`. Focus returns to the composer after send.
- Composer: auto-growing textarea 1-6 lines, Enter sends, Shift+Enter newline, Send button becomes Stop while streaming, 4000-char max.
- Debrief on End: "What worked", "Try next time", `Save to notes` through the plugin's `notes:write` scope with provenance tag "Added by Rehearse".
- The meeting-page "Ask about this meeting" dock is **not** P0. If `ChatPanel` slips, the P0 minimum is to remove the disabled row (finding 3), never to ship a half-working composer.
- P2: voice roleplay (the permission handler denies media, `main.js:1000`).

---

## 8. Motion

Tokens: `--dur-1:120ms`, `--dur-2:180ms`, `--dur-3:260ms`, `--ease`. No animation over 400ms; the only loops are the recording dot, spinners, the processing indicator and the skeleton shimmer. The performance rule is "animate transform and opacity where possible"; the shimmer (background-position) and the stepper line are accepted exceptions and are cheap at this size. P0 motion list: view fade-up 6px/220ms, menu and dialog `scale(.97)→1` 140ms, tab underline slide, task check draw (160ms) with strikethrough, toast slide, notes-reveal fade. The 40ms staggered reveal, onboarding transitions and palette motion are P1/P2.

Reduced motion (corrects the draft): the existing global rule (`styles.css:71`, 0.001ms and one iteration) makes spinners, the indeterminate bar and shimmer render static or vanish, so processing would look frozen. Therefore each loop has a static equivalent: spinner becomes the text "Working…", the stepper highlights the current step by weight and an icon, skeletons render as a flat `--surface-3` tint. JS-driven motion (the tab underline computed from rects, the WAAPI check draw) checks `matchMedia('(prefers-reduced-motion: reduce)')` and jumps to the end state, since the CSS override does not touch it. There is no welcome loop in P0, so WCAG 2.2.2 (pause control for animation longer than 5s) is not triggered.

---

## 9. Brand, icon and packaging

- **Mark and wordmark:** the Ring (section 2.2). Wordmark "Cora" in the system font, 650, -0.02em, sentence case (it reads as a person's name). Window title and store copy keep "Cora AI Meeting Notes". Taglines (60-char limit) for owner testing: "Meeting notes that stay on your Mac" (35), "Local-first meeting notes, with rehearsal built in" (50), "Open-source meeting notes you can extend" (40). A/B only inside the closed beta poll (the PH tagline is fixed at submission).
- **App icon:** macOS squircle (Apple template, 824px art in a 1024 canvas with transparent margin), `#171815` to `#0F100E`, the Ring in `#3DB8A5` with the dot in off-white `#F4F3EF`. Deliverables: `src/icon.png` (1024², transparent margins; it is what `src/main/paths.js:50` loads as `ICON_PATH`) and `src/icon.icns` (what `package.json build.mac.icon` packages; generated by `iconutil` from a 16-1024 `.iconset`). The draft said `build/icon.icns`; `build/` holds only `python-runtime`, so that file would never have been packaged. First step of LF-11: inspect the current `.icns`, not just the PNG, to see whether the white margin is real.
- **Tray:** `src/trayTemplate.png` (18x18) and `trayTemplate@2x.png` (36x36), ring only (no dot at this size), alpha only, `*Template` named so macOS tints for both menu bar appearances. Recording state uses `tray.setTitle('● 12:41')`. Replace `main.js:1017-1022`.
- **Thumbnail legibility:** the 240x240 PH thumbnail is the app icon artwork (Ring on the dark squircle, no text). Check it at 48px and 24px (the sizes in PH feeds) in LF-11; if the dot vanishes at 24px, ship the ring-only variant as the thumbnail.
- **Packaging reality:** `package.json` builds target `dir` with `identity:null` and `hardenedRuntime:false`, so there is no signed DMG and no notarization today. This track does not do signing (GATE-3), but states the dependency: the "notarized build" assumptions in the capture plan and the quarantine first-run check require that track. Because P0 uses no vibrancy, the look does not depend on signing; what does need a hardened-runtime build is the tray template check and the permission prompts. `asarUnpack` currently lists only `src/ui/web/**`; the PWA (P1) adds `src/ui/mobile/**` so the Python listener can read it from the filesystem.

---

## 10. Phone PWA (P1, brief; depends on the remote track)

Single-page PWA served by the separate remote listener from `src/ui/mobile/` (so `asarUnpack` gains `src/ui/mobile/**`). Screens: Record (96px button, timer, level ring, honest "keep this screen on" note, status chip), Queue (Saved on this phone, Uploading, On your Mac, Ready; retries on foreground), Notes (read-only, last about 20), Pair (QR with a one-time code, never the long-lived token). The shared tokens are linked, not copied: the listener serves the same `tokens.css` from its static root (no `build-mobile.js`, no generated files). The PWA CSP is `style-src 'self'`, so PWA code and any kit helper it uses must not emit `style=""`. 44px targets, `-apple-system` font, no hover-only affordances, automatic dark via `prefers-color-scheme`. Failure states (mic denied, upload interrupted, token revoked, Mac asleep, quota exceeded) must be explicit text. A `Phone connected` sidebar line uses the dashboard payload, not a new loop. Exact UI work is 2 days once the listener exists.

---

## 11. Product Hunt assets (only what P0 delivers)

Constraints from the research: tagline at most 60 characters, description at most 500, thumbnail 240x240 under 3MB (first frame must stand alone), at least 2 gallery images at 1270x760, YouTube video, maker first comment, lead with what is novel.

### 11.1 Gallery: 4 strong shots first (light theme, 1270x760)

| # | Screen | Caption (max 8 words) | Gate |
|---|---|---|---|
| 1 | Meeting detail, Notes tab, two action items (one checked), fictional "Q4 roadmap review" | **Notes you can trust, written on your Mac** | LF-0, LF-6 |
| 2 | Rehearse mid-conversation with a coach note and the AI banner | **Rehearse the hard conversation** | LF-10 **and the real stream endpoint** |
| 3 | Settings > Transcription engine cards with the confirm dialog, privacy chip visible | **You decide what leaves your Mac** | LF-7a |
| 4 | Transcript tab with a code-switched turn | **Mixed-language meetings, handled** | LF-0; no accuracy claim until `tools/asr_bench.py` results exist |

Shots 5 (command palette with plugin commands) and 6 (phone PWA) are **v2 assets**, produced only after LF-9, LF-13 and the plugin track land. The draft's mixed dark/phone composite is dropped; there is no dark gallery. The Hinglish turn is Latin-script (romanised) Hindi, so no Devanagari or font-fallback verification is needed (Inter was removed from P0 anyway).

### 11.2 Video (45-50 seconds, 1920x1080, captions on)

| t (s) | Visual | Caption |
|---|---|---|
| 0-3 | Finished notes page, an action item ticks | "Meeting notes that stay on your Mac." |
| 3-12 | Fictional call in a test Zoom window, floater with `● 00:12`, record accepted | "Cora notices your meeting and asks first." |
| 12-20 | Home row shows `Transcribing…` then `Writing notes…`; notes appear (speed-ramped, "sped up" tag) | "Transcription and notes run on your Mac." |
| 20-28 | Transcript tab with the code-switched turn; Settings > Transcription cards, confirm dialog, chip changes | "Local by default. Cloud only when you choose." |
| 28-43 | Rehearse, persona streams a reply, user types, coach note, debrief (hero, do not rush) | "Rehearse the hard conversation, built from your real meeting." |
| 43-48 | End card: Ring, "Cora", `github.com/mkdsrt10/cora-ai-meeting-notes`, "Free for macOS" | quiet |

A 75-second v2 adds palette, plugin consent, phone and lockdown beats once those exist. The README hero loop is an 8-second export of seconds 0-8 (no separate production).

### 11.3 Demo data rules (hard constraints)

- Capture uses a throwaway data dir: `VOICECOACH_DATA_DIR=$(mktemp -d)` populated by `tools/seed_demo_data.py` (a CLI that takes a path and refuses non-empty dirs). The bundled in-app sample (6.6) is a separate mechanism.
- `CORA_DEMO=1` (read in `main.js`, scheduled in LF-14): pins the content size to 1270x760, hides the tray icon, hides developer controls, and **refuses to start if `VOICECOACH_DATA_DIR` is unset or points at the real data dir** (guard against capturing real data). It does not change what the product does otherwise.
- The repo root holds real artefacts (`New Recording 121-126.m4a`, `transcripts*/`, `inbox/`, `backups/`); none may appear in any frame. Never open "Show in Finder" on camera (`recording_item` exposes absolute `folder_path`/`folder_uri`; the UI never renders them).
- Hide the menu bar clock and Wi-Fi name; use obviously fake `sk-demo…` strings only in unsubmitted fields; no real Tailscale names; synthesized audio only (macOS `say` or an open-licensed TTS) reading a scripted fictional dialogue; no customer logos; no HIPAA or DoD claims.
- **`tools/check_demo_assets.py`** compares OCR text of each screenshot with real `people.name` values and the owner's real company/customer list. It runs **locally only, never in CI**; it reads the owner's DB read-only; it prints only `OK` or a hit **count** per image, never the matched string or any name; the name list exists in memory only and no list is ever committed; OCR uses macOS Vision locally and is not added to `pyproject.toml`. The owner reviews the run before assets are published.

### 11.4 Claims gate

Captions may say: "Local by default", "Cloud only when you choose", "Enterprise lockdown disables cloud transcription, cloud notes and sync" (this is what `python/policy.py` enforces today). They may **not** say "blocks every outbound path", "Nothing touches our servers" or anything compliance-flavoured until GATE-1 (Electron-main egress) and GATE-2 (MCP lockdown) are done. "Gemini-class accuracy" waits for benchmark output.

---

## 12. Work packages

Effort is in agent-assisted days (an agent writes, the owner reviews and eyeballs). The earlier "about 15 days" total was wrong; the real P0 sum is below.

### 12.1 P0: "Launch Look" slice (20.75 days; Tier A = 9.75)

| ID | Work | Files | Days | Tier | Depends |
|---|---|---|---|---|---|
| LF-0 | Standalone fixes: transcript gap (verify cause first), task rows, `item_key` column and keying, stage-badge UI fix, remove disabled Ask row | `transcript.js`, `detail.js`, `core.js`, `db.py`, `index.html` | 1.0 | A | none |
| LF-1 | Tokens (both dark blocks), complete compat aliases, system font, token-defined lint, contrast script | `tokens.css`, `styles.css`, `index.html`, `scripts/lint-ui.js`, `scripts/check-contrast.js` | 1.0 | A | LF-0 |
| LF-2 | ~22-icon swap, `icons.js`, delete `pixel-icons.js`, notices file, emoji lint (advisory) | `icons.js`, markup, `THIRD_PARTY_NOTICES.md` | 0.75 | A | LF-1 |
| LF-3 | Kit on platform primitives: dialog, menu, toast, badge, emptyState, skeleton | `ui-kit.js`, `components.css` | 1.0 | A | LF-1 |
| LF-4 | Shell: `hiddenInset` opaque window, drag audit, window state, app menu, boot.js, nativeTheme theme IPC, sidebar rewrite, topbar removal, privacy summary route and chip, MCP heartbeat | `main.js`, `main/menu.js`, `preload.js`, `index.html`, `folders.js`, `core.js`, `boot.js`, `system.py`, `mcp_server.py`, `privacy-chip.js` | 2.0 | B | LF-3 |
| LF-5 | Home: day groups, badge language, skeleton, empty state, live row | `sessions.js`, `index.html`, `core.js` | 0.75 | B | LF-3 |
| LF-6 | Meeting detail: header, menus, tabs rename, notes typography, processing steps, People restyle, title editor restyle | `index.html`, `detail.js`, `detail-actions.js`, `notepad.js`, `search.js`, `title-editor.js` | 2.0 | A | LF-3 |
| LF-7a | Settings: sans titles, engine cards with confirm dialog, Data & privacy panel | `index.html`, `settings.js` | 1.25 | A | LF-3, LF-4 (summary) |
| LF-8 | Trimmed onboarding, sample endpoints and bundle, sample exclusion (MCP, export, sync, retention, people) | `index.html`, `onboarding.js`, `recordings.py`, `python/samples/`, `mcp_server.py`, `views.py`, `cloud.py` | 1.5 | B | LF-3 |
| LF-A11Y | Accessibility package and launch gate | markup, `ui-kit.js`, `styles.css` | 1.5 | B | LF-6, LF-7a |
| LF-10 | `ChatPanel` with fixture stream, Rehearse view, honesty banner, debrief | `chat-panel.js`, `components.css`, plugin view host | 2.0 | B | LF-3; real endpoint for launch (GATE-4) |
| LF-11 | Ring, icon (`src/icon.png`, `src/icon.icns`), tray templates, 24/48px legibility check | `src/icon.*`, `src/tray*`, `main.js` | 1.5 | A | none (parallel, start day 1) |
| LF-12 | Floater: icon swap, toast folded into pill, ~360px width prototype, opaque capsule, Ring | `floater.html`, `floater.js`, `main.js` | 0.75 | B | LF-11 |
| LF-14 | `CORA_DEMO` guard, 4 gallery shots, thumbnail, 45-50s video, README loop, `check_demo_assets.py` | `main.js`, `tools/check_demo_assets.py` | 3.0 (Tier A share 1.5: 3 shots plus thumbnail) | A/B | all above |
| LF-16 | `node --test` pure-function tests, contrast script in CI, `lint-ui.js` additions, privacy route tests | `tests/ui/*`, `tests/test_privacy_summary.py`, `tests/test_server_auth.py`, `.github/workflows/ci.yml` | 1.0 | B | LF-1 |

Sum: 1.0+1.0+0.75+1.0+2.0+0.75+2.0+1.25+1.5+1.5+2.0+1.5+0.75+3.0+1.0 = **20.75 days**. Tier A (the cut line if the schedule slips): LF-0, LF-1, LF-2, LF-3, LF-6, LF-7a, LF-11 and a 1.5-day LF-14 share = **9.75 days**. Tier A produces gallery shots 1, 3, 4 and the thumbnail; Tier B adds shot 2 and the video. The critical path is LF-0, LF-1, LF-3, LF-6, LF-14. Lanes that can run in parallel: UI core, brand and floater (LF-11, LF-12), Python (LF-4 route, LF-8 endpoints). This competes with the transcription, plugin, notarization and remote tracks; the owner should treat Tier A as the only part that must not slip.

### 12.2 P1 (first week after launch, or earlier if there is slack)

| ID | Work | Days |
|---|---|---|
| LF-9 | Command palette (`cmdk.js`), shortcut sheet, `⌘K`/`⌘F`, opt-in global record shortcut | 1.5 |
| LF-13 | Phone PWA UI (needs the remote listener) | 2.0 |
| LF-15 | Motion polish (stagger, tab underline, checkbox draw polish) | 0.75 |
| LF-17 | Citation chips (needs templates-track `citations`) | 0.5 |
| LF-18 | Transcript grouping, sticky scrubber with no-audio state, find interplay | 1.5 |
| LF-19 | Filter popover, folder-filter removal, People card grid, talk-share (verify data first) | 1.5 |
| LF-20 | Plugin install and consent dialog (acknowledgement checkbox), plugin tabs and menus (needs plugin host and iframe prerequisites) | 1.5 |
| LF-21 | Settings regroup, provider list, MCP code tabs, Advanced, `developer_mode` and Sync-to-VM gating, Local usage moved to System | 2.0 |
| LF-22 | Dead-CSS purge, last, conditional (14.2) | 1.0 |
| LF-23 | Optional Inter (3.2) | 0.5 |

### 12.3 Gates (owned by other tracks; this doc depends on them)

| Gate | What | Blocks |
|---|---|---|
| GATE-1 | Electron-main egress control under lockdown (`webRequest` filter, `shell.openExternal` allowlist, `will-frame-navigate`). Lockdown is Python-only today (`policy.py`). | Any "blocks every outbound path" claim |
| GATE-2 | `mcp_server.py` lockdown check, plus the sample filter (LF-8) and heartbeat (LF-4) | Same claim; chip `lockdown` (vs `lockdown_partial`) when MCP is used |
| GATE-3 | Signing and notarization (`identity`, `hardenedRuntime`, `dir` target in `package.json`) | Quarantine first-run check; tray template check on a signed build |
| GATE-4 | Plugin track's streaming chat endpoint | Gallery shot 2 and video hero beat (launch date gate) |

---

## 13. Test plan (matches what CI runs)

`.github/workflows/ci.yml:23-29` runs `ruff`, `npx eslint src`, `node scripts/lint-ui.js` and `pytest -m "not mlx"`. There is no `npm run lint`, no Node test runner, no Playwright. This plan adds only no-dependency steps.

1. **Node unit tests** (`node --test tests/ui`, built into Node 22, one new CI step): `renderMarkdownSubset` (task lists, nesting, XSS stays escaped), `renderCleanTranscript` output has no `\n\s*<`, `dayBucket`, `hashHue`, `item_key` normalisation, privacy chip label from `state`, floater/`icons.js` path parity. Pure functions are exported with a `/* global module */` comment and `if (typeof module !== 'undefined') module.exports = {...}` at the bottom (the comment keeps `no-undef` quiet; `lint-ui.js` uses `globals.browser` only).
2. **Contrast script** `scripts/check-contrast.js` (no dependencies, runs in CI): parses `tokens.css`, evaluates a declared list of every foreground/background pair for light and dark (text 4.5, non-text 3.0, including `--ink-3` on `--surface-2`/`--surface-3`, `--danger-text` on `--danger`, `--line-control` boundaries). This replaces axe for contrast (axe does not evaluate every gradient or composited pair). A manual VoiceOver and keyboard pass remains (6.10).
3. **Lint** (`scripts/lint-ui.js` additions): script order entry for `ui-kit.js`/`icons.js`/`boot.js`; every `var(--x)` is defined; the two dark blocks have identical declarations; `var(--private` only in allowlisted selectors; advisory emoji and glyph-icon regex; no `style="` in `ui-kit.js` output strings.
4. **Python tests:** `tests/test_privacy_summary.py` covers the state matrix (local, connected, cloud, lockdown, lockdown_partial), `plugins_with_egress:null` handling, and that the JSON contains none of `key`, `host`, `url`, `path`. `tests/test_server_auth.py`'s route inventory gains `/api/privacy/summary` so Host, Origin and token rejection are asserted exactly like sibling routes. Sample endpoints: idempotent, no parameters, and sample rows absent from MCP list/get/search, export, sync and retention.
5. **Electron smoke (manual P0, scripted P1):** launched with `CORA_DEMO=1` and a temp dir: window size, traffic lights, no white flash, dark and light switching live via `nativeTheme`, two displays, full-screen entry and exit, window position restored. A browser-pane run checks the opaque fallback only (it cannot render `hiddenInset`).
6. **Manual capture checklist** (replaces visual regression): a scripted list of the four gallery screens in light and dark, compared by eye against the previous build before each freeze. Capture uses a build produced after GATE-3 if available.
7. **Perf:** record baseline first-paint and CSS/JS sizes in the LF-1 PR; the budget is baseline plus 20%. No absolute numbers were measured, so none are promised.

---

## 14. Rollout, migration and rollback

1. Short-lived branches off `production`; order each leaving the app shippable: LF-0, LF-1 (reviewed with before/after screenshots because the compat block recolours buttons), LF-11 (parallel), LF-2, LF-3, LF-4, LF-6, LF-5, LF-7a, LF-8, LF-A11Y, LF-12, LF-10, LF-16, then LF-14 on a frozen commit.
2. **14.2 Dead-CSS purge (LF-22, P1, last):** a class is deleted only if absent from both (a) a grep of `index.html` and `js/` including string concatenation and template literals and (b) a runtime class-usage trace (a dev-only `MutationObserver` collecting every class seen while scripted through all screens and states). Its own commit; rollback is a plain `git revert` with no dependency on any other change. Verify with a 30-minute manual before/after screenshot comparison of eight screens.
3. **UI freeze:** 7 days before the PH date, fixes only. If the date moves (research proposes Show HN Tue 2026-11-17 and PH Thu 2026-11-19, with Dec 1/Dec 3 as fallback), the order of work does not change.
4. **Beta:** the closed beta (20-50 users) gets the new UI; a `Send feedback` link opens a prefilled GitHub issue form, with no data attached and no network call from the app.
5. **Persisted state:** `localStorage.theme` migrated once into `nativeTheme` (5.2); no settings keys renamed; `item_key` is a nullable additive column; `ui_chrome` lives only in `config.json`. Rollback is a code revert; no data needs undoing.
6. **SOC 2 evidence:** the `/api/privacy/summary` contract and its tests, the route-inventory test, and the lockdown-rendering checklist are the control evidence for "UI reflects enforcement". The summary's `lockdown_covers` field records the real scope, so the evidence does not overstate it.
7. Changelog entry with a before/after screenshot pair (fictional data).

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| `hiddenInset` drag regions swallow clicks or text selection | Drag audit table (5.1), sticky non-overlapping header, `no-drag` on every child; `ui_chrome:"classic"` fallback via `config.json` |
| Compat aliases recolour the app unexpectedly | Complete alias list plus defined-variable lint; before/after screenshots in the LF-1 PR |
| Chip read as a compliance claim | Server-computed `state` including MCP and sync, `lockdown_covers` disclosure, narrow copy, no compliance language in marketing |
| Under lockdown, MCP and plugins are not blocked | `lockdown_partial` state, claims gate (11.4), GATE-1 and GATE-2 |
| Rehearse endpoint late | Fixture-stream UI, launch date gated on GATE-4, Tier A ships without shot 2 |
| Sample meeting leaks into real exports or MCP | Dedicated exclusion work item and tests (LF-8) |
| Shared kit emitting inline styles breaks the PWA CSP | Kit rule and lint |
| Real data in launch assets | `CORA_DEMO` refuses real data dir, local counts-only OCR checker, synthesized audio |
| Overscope | Tier A cut line (9.75 days); everything else is explicitly P1 or P2 |
| Floater width wrong | 0.25-day prototype before fixing 360px |
| Task state wrongly applied after regenerate | `item_key` text-hash keying in LF-0 |

---

## 16. Decisions needed from the owner

1. **Accent semantics:** teal reserved for privacy state with ink-coloured primary actions (recommended; it makes the Ring a real signature) versus keeping today's blue for actions.
2. **Window chrome:** `hiddenInset` opaque (recommended) versus the standard title bar for launch safety. Vibrancy is not on the table for P0.
3. **Mark:** approve the Ring (geometry rendered and verified; 16px tray uses the ring only) or commission a final mark.
4. **Rehearse in the launch build:** it is the novelty hook and is gated on the real endpoint. Say which fallback gallery shot and video beat replace it if GATE-4 slips (the video then drops to about 30s and the launch loses its hero).
5. **Tier A or full P0:** approve the 9.75-day cut line as the minimum and 20.75 days as the target given the other tracks.
6. **Stage semantics:** hide the "ready" state (recommended); `Coached` badge only when the coaching plugin is enabled.
7. **Onboarding:** drop meeting types and people from the mandatory path (recommended; no consumer today).
8. **Naming:** keep "Memory" or rename to "Vocabulary".
9. **Font:** system font (P0 default, recommended) versus self-hosted Inter (P1, 0.5 day).
10. **Opt-in global record shortcut** in P1 (default unset) versus no global shortcut at all.
11. **Hinglish caption:** only if the benchmark supports it.

Open compliance flags:
- `/api/privacy/summary` is read-only and secret-free, sits behind the standard authorize path, and must be in the route inventory for the audit. It must never be added to `PUBLIC_PATHS`.
- MCP has no lockdown check and Electron-main egress is uncontrolled under lockdown; do not market lockdown beyond what Python enforces.
- The MCP heartbeat adds a timestamp to settings; it must carry no client identity or transcript content.
- The chat stream endpoint must be policy-gated (`policy.require_outbound_allowed()` on cloud providers) and audit-logged; the UI is not the only enforcement point.
- The PWA is a new data-bearing client: no note text in the service worker cache, and revocation per the remote track.
- The bundled sample is fictional but must be reviewed for real names before it ships; `check_demo_assets.py` handles real PII locally and must never print or commit names.
