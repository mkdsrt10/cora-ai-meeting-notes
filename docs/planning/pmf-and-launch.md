# Cora: PMF Definition and Product Hunt Launch Plan (final)

Status: decision-ready, written 2026-10-16 (Fri). Branch context: `production`; public repo `mkdsrt10/cora-ai-meeting-notes` (MIT, 0 stars, created 2026-09-26).
Basis: pmf.proposal-2 (winner), grafts from proposals 1 and 3, research_producthunt / research_pmf / research_competitors, and the sibling design drafts (plugin SDK, transcription-gemini, notes-templates, look-and-feel, phone-capture). Evidence labels: V verified, L likely, U unverified, as in the research files. Nothing here is validated demand; section 9 says how to find out, and the kill rules are fixed in advance.

---

## 0. Decisions in one screen

| # | Decision | Recommendation |
|---|---|---|
| 1 | Hero | **Rehearse**: practice the next hard conversation against an AI that plays the other person, grounded in what that person actually said in your recorded meetings. Plugins are the "how", never the headline. |
| 2 | Beachhead | Engineering managers, founders, product leads on Mac with many 1:1s and feedback talks. Hinglish is a proof point, not a segment. |
| 3 | PH tagline | "Rehearse your next hard conversation, from real meetings" (56 chars). Test against 2 alternates by Oct 30. |
| 4 | Dates | **Show HN Tue 2026-11-17 (8-10am ET). Product Hunt Thu 2026-11-19, 12:01am PT.** Fallback Tue Dec 1 / Thu Dec 3. Hard stop Dec 8 / Dec 10, else Jan 12 / Jan 14 (avoid Dec 21-Jan 4). |
| 5 | Go/no-go checkpoints | **Fri Nov 6** (slip decision) and **Fri Nov 13** (final). Never ship past a failed Never-Cut gate (section 12.1). |
| 6 | Pricing | Free and MIT at launch, BYO keys, no accounts, no default telemetry. Pro is a post-day-90 question. |
| 7 | Claims | No HIPAA, CMMC, DoD or SOC 2 claims. "Local by default" and "lockdown blocks all outbound including plugins" only after the CI test passes. Never "nothing leaves your Mac" next to a cloud engine. |
| 8 | Launch scope | Rehearse (text), plugin API v0 (declarative tier), 3 first-party plugins, notes templates as files, look-and-feel P0, notarized DMG. **Deferred: phone capture/Tailscale, windowed-Gemini upgrade, Tier 1 UI frames, voice rehearsal, team/KB/roadmap plugins.** See section 2.3. |

Owner decisions still open are listed in section 20.

---

# PART 1: PMF

## 1. Positioning decision

| Option | Verdict |
|---|---|
| "Local open-source meeting notes" | Rejected. Crowded (Meetily ~31.8k stars, Anarlog ~9.5k); Humla launched on PH as exactly this and got 9 upvotes, #144, not featured (L). |
| "Plugin platform for meetings" | Rejected as headline. Screenpipe has pipes plus a store, Anarlog has a plugin SDK, Fireflies has AI Skills, Granola has Recipes and MCP. Claiming novelty invites a takedown in the first HN comments. Hyprnote's "VSCode for Meeting Notes" Show HN got 18 points (V). Keep as the "how". |
| "Most accurate transcripts / Hinglish" | Rejected as headline. Proof point only; vendor WERs are not comparable and we have no results yet. |
| **"Get better at the conversations that matter, practiced on your real meetings"** | **Chosen.** Concrete, demoable in 3 seconds, novel versus the field we found, and it gives the platform a reason to exist. |

**Reconciling with PH's "Novel" criterion.** The PH research says to lead with the platform plus one memorable plugin. We do the same thing in a different order: the memorable plugin is the headline and the platform is the second sentence ("every part of it is a plugin you can read, edit and share"). This also resolves the split-message problem flagged in proposal 1.

**Honest whitespace statement (L, single search sweep, re-check weekly):** roleplay tools use synthetic scenarios (Yoodli, Second Nature, Hyperbound, Peopling). Gong AI Trainer builds roleplay from real calls but only for enterprise sales. We found no private, individual, non-sales tool that rehearses from your own meetings. The most realistic substitute is "Claude/ChatGPT plus a notetaker's MCP", and test T1 tests against it directly.

## 2. ICP

**Primary: "Maya", engineering manager, head of product or technical founder.** Mac daily driver. 6-15 recurring 1:1s a week plus ad-hoc hard conversations (performance, scope cuts, compensation, co-founder disagreements). Already uses Granola or Otter for notes and asks Claude to "help me prepare" but retypes context each time. Can open a DMG, paste an API key, read a README, and mildly cares where audio goes. Price anchors: Granola Business $14, Meetily Pro $10, Yoodli Pro $8.

**Triggers:** a performance review, layoff or reorg talk within 48 hours; a hard 1:1 just went badly; first management role; a notetaker privacy story (tl;dv exposure story reached 633 HN points, Aug 2026, V); a company or university blocking bots.

**Where they are:** Hacker News, GitHub, X, LinkedIn, EM and founder communities (check each community's rules; interview first, announce later), r/LocalLLaMA (lead with the benchmark, not a promo).

**Secondary, proof not segment:** Hinglish and Indian-English professionals. Pain is real but evidence is anecdotal and willingness to pay is low. They supply the accuracy benchmark story, word of mouth and plugin authors. No segment-specific features before launch. The Indian-founder channels in section 14 are distribution for the launch, not a market claim.

**Explicitly not now:** regulated professionals (lawyers, clinicians, DoD contractors, HIPAA entities): strongest pain but needs BAAs, attestations and EHR integration, and Anarlog and Meetily already target them. Keep `enterprise_lockdown` as a trust pillar only. Sales teams (Gong, Hyperbound territory). Teams needing shared todos or a company KB (needs multi-user sync, which fights local-first).

## 3. Jobs to be done

1. When a hard conversation is coming, help me walk in prepared instead of avoiding or fumbling it.
2. When one went badly, show me what I did (interrupted, hedged, filled silence) without a manager watching.
3. When I prep for a recurring person, remind me what they said last time, what I promised, what they pushed back on.
4. Keep my meeting content mine: no bot in the room, no vendor training on it, nothing public.
5. Let me bend the tool (my coaching framework, my todo app, my note template) without waiting on a vendor roadmap.

## 4. Value proposition

1. **Outcome:** walk into the hard conversation prepared; learn from the last one.
2. **Mechanism:** your recordings become structured objects (speakers, people, action items, delivery metrics) that plugins can use, on your machine, with your model.
3. **Trust:** no bot, local by default, every outbound path explicit and auditable, lockdown blocks everything including plugins.
4. **Openness:** MIT, plugin API, templates as files. If you disagree with the coach, fork the coach. Expose plugins as MCP tools so Cora is the meeting runtime, not another silo.

Framing line (from proposal 1): "Meeting notes are the part everyone has. Cora is what you build on top of them."

## 5. Proof (each must exist as a launch asset, built only from fictional or consented synthetic data)

| Claim | Proof asset | Gate |
|---|---|---|
| Rehearsal is grounded | Demo with a fictional person, three prior synthetic meetings; every persona line has a provenance link back to the transcript segment it came from. The links are the proof, not "trust the AI". | G3 |
| Delivery coaching | Pace, fillers, talk-to-listen ratio, before and after across two rehearsals (computed locally on the user's speech only). Table stakes, not differentiator. | G3 |
| No bot, local by default, auditable | README "what leaves your machine" table; network-capture result with default settings and lockdown on; CI test that a plugin without a network scope cannot connect and that lockdown blocks plugin egress. | G2, G9 |
| Reproducible accuracy | Publish `tools/asr_bench.py` results including losses, on fictional or consented audio, phrased "on our N-minute set". Single-speaker overfit caveat stated. | Optional |
| Anyone can write the next coach | 10-minute plugin quickstart plus 3 first-party plugins as worked examples. **No ecosystem claim at launch**; phrase as "plugins are files you can read, edit and share". | G4 |

Dropped proof candidates: "most accurate", "first/only extensible meeting tool", any compliance claim.

## 6. Why now

1. Cloud-notetaker consent backlash is concrete (class actions against Otter V, Fireflies BIPA L, Granola L; all allegations, dockets unchecked; say "alleged" or omit). Bot-free capture already won the argument, so we start from "what can you do with it".
2. Roleplay is a funded category (Yoodli, Second Nature, Hyperbound), so interest is proven; grounding in your own meetings is the unclaimed part for individuals.
3. MCP made extensibility normal and then commoditized it. Cora's counter is a runtime with local execution, a UI surface, write-back and cross-meeting state.
4. Incumbents are moving up-market and cloud-ward; the window for an open, individual-first product is short.
5. Apple silicon plus local models are good enough for capture and ASR, and borderline for notes. Roleplay quality is the open question (R2).

## 7. Competitor framing (honest; re-verify every cell before publishing a table)

Principle: name competitors first in our own materials, because HN will.

| Competitor | What they really have | Where Cora honestly differs | Where they win |
|---|---|---|---|
| Screenpipe | Pipes (markdown agents with permissions), store, screen plus audio | Meeting-structured data, practice as first-class, MIT, no account | Distribution, store exists |
| Anarlog / Hyprnote | Early plugin SDK, regulated positioning | Out-of-process permissioned plugins, practice focus | Brand, PH #2 precedent |
| Granola | Recipes, templates, MCP, polish | Open, writable plugins with write-back, local default, interactive rehearsal instead of a one-shot prompt | Polish, brand, enterprise |
| Fireflies AI Skills | 200+ prompt apps, CRM push | Local, open, individual-first | Integrations, teams |
| Meetily | Largest OSS local notes; API/MCP paywalled in Pro | Plugin surface is free | Stars, simplicity |
| Yoodli / Second Nature / Hyperbound / Gong AI Trainer | Funded roleplay; Gong uses real calls for sales | Individual, non-sales, private, your own meetings | Scenario libraries, voice quality, scoring |
| Read.ai Speaker Coach | Cross-meeting delivery metrics | Interactive rehearsal, local, open | Reach |
| Claude/ChatGPT plus notetaker MCP | "Roleplay my last 1:1" works today | Persistent people memory, provenance to transcript lines, purpose-built UI, no vendor sees recordings | Zero install for existing users. **Most realistic substitute.** |

README one-liner: "Screenpipe, Anarlog, Granola and Fireflies all have extension points. Cora is the open, local-first one built around practicing your own conversations."

## 8. Pricing and business model

- **Launch:** everything free and MIT. BYO keys for cloud models (Gemini paid tier or Vertex only; free tier may train on data with human review, L, re-read current terms before publishing). No accounts, no default telemetry.
- **Pro (after day 90 at the earliest, ~$8-12/mo):** managed model access with zero-retention terms, encrypted multi-device sync, signed and reviewed plugin registry. Additive cloud conveniences only; each must pass the lockdown test and never be required.
- **Principle:** never gate a user's access to their own data or the plugin API (Meetily and Granola paywall API/MCP, which is our wedge).
- **Teams/Enterprise:** later or never; only with a paying design partner and a completed SOC 2 Type 2.
- **Marketplace revenue share:** not before 20+ third-party plugins.
- **Pricing signal at launch:** a "Pro supporter / notify me" page that collects **no payment** and a Sean Ellis survey to active users. Fake-door only after day 30.
- **Honest math:** 100 payers at $10 is $1k/mo. Launch and the first 90 days are a credibility and learning phase, not a revenue phase.

## 9. Riskiest assumptions and validation tests

Ordered by fatality. Owner column: F = founder, A = AI agent can prepare, founder runs.

| # | Assumption | Test | Pass bar | Kill / pivot | When | Owner |
|---|---|---|---|---|---|---|
| R1 | Managers and founders want to rehearse conversations repeatedly | **T1 Wizard-of-Oz.** 10 EMs/founders. Each brings their **own consented notes** of one real past conversation (or a fictional one; do not ingest a third party's data into a cloud LLM without their consent). Hand-built persona prompt, 15-minute rehearsal over screen share. Offer a second session a week later unprompted. | 6 of 10 would use it before their next hard conversation AND 4 of 10 do the second session | Fewer than 3 of 10: pivot hero to "post-meeting coaching plus prep brief for the next meeting with this person"; roleplay stays a plugin | Oct 19-29, decide **Oct 30** | F (A builds prompt kit) |
| R3 | Grounding in real meetings beats a good generic scenario | Inside T1, split: half grounded persona, half generic; blind order | Grounded preferred by at least 65% | Under 55%: grounding is not the wedge; reposition around coaching and notes | same | F |
| R2 | A local or BYO-key model can play "the other person" well enough | **T2 bake-off.** Fictional transcripts; 5 blind raters score local Qwen, Gemini paid, a Claude/GPT baseline on realism and usefulness (1-5) | Local median realism at least 3.5 and cloud at least 4 | Local under 3: ship Rehearse with an explicit labelled cloud opt-in as the default path and mark lockdown as "rehearsal disabled"; do not claim local roleplay | Oct 21-24 | A runs, F rates |
| R6 | People can install it | **T5 install funnel.** Notarized DMG to 10 users on clean macOS 15 and 26, via browser download (so quarantine applies) | 9 of 10 reach a first recording in under 10 minutes unaided | Blocker, not a metric: slip to Dec 1/3 | first DMG (~Oct 28) to Nov 5 | F |
| R7 | "Local by default, optional cloud" survives HN scrutiny | **T6 red-team.** 3 privacy-minded reviewers hunt for any outbound path not in the data-flow table; network capture with default settings and with lockdown on | Zero unexplained connections; lockdown shows zero outbound including plugins | Any leak: fix before any launch asset ships | Nov 2-5 | A captures, F reviews |
| R4 | Tagline and demo land | **T3 message test.** 10 people each on 3 taglines (#1, #2, #4 below) plus the 30-second clip; ask a few HN regulars privately for a gut reaction (never ask for votes) | 7 of 10 restate it correctly after one viewing; 3+ unprompted "I want to try it" | "Just another notes app" dominates: rewrite the hero before spending on assets | Oct 26-30 (mock clip from seed data is enough) | F |
| R5 | Developers will write plugins | **T4 author interest.** Publish quickstart draft plus 2 example plugins; DM 20 plugin-minded developers (MCP, Obsidian, local-AI circles); ask for a 50-line plugin in a week | 3+ finish a toy plugin and 1+ proposes their own | 0 finish: say "customizable" instead of "platform" in all copy; stop registry work | Oct 28-Nov 6 | A drafts, F DMs |
| R9 | Notes quality is good enough that users reach the hero | **T8 notes parity.** 5 users, blind-labeled Cora vs Granola notes for the same fictional meeting | At least 40% prefer Cora or call it equal | Under 25%: add a notes-quality item to the P0 list before launch | Nov 3 | A prepares |
| R8 | Hinglish accuracy is a credible proof | **T7 benchmark first, claims later.** 1 hour of consented synthetic or volunteer audio vs Gemini, Chirp 3, Sarvam, local models | Gemini or Sarvam beats local by 10+ WER points on our set, or local wins clearly | Otherwise drop Hinglish from launch copy; also check the Tara weights license before any "local Hinglish model" claim | Oct 26-Nov 6, optional | A |
| R10 | Wispr or Granola do not ship this first | Re-check competitor landscape weekly | n/a | Mitigate with speed and openness | Fridays | A |
| R11 | Consent and voiceprint exposure is manageable | Code review of `speakers.py` and the people matcher for stored embeddings (a grep of `python/` for "embedding" and "voiceprint" found no hits on 2026-10-16, so this looks clean, but confirm by reading); legal review of BIPA, India DPDP consent norms; ship a participant-notice template | No voiceprints; documented retention and delete cascade | Any voiceprint found: remove or gate before launch | Oct 19-30 | A reviews, F asks counsel |

Decision calendar: T1 and T5 start now (they gate everything), T2 and T7 in parallel, T3 once a 30-second cut exists, T4 once the quickstart draft exists. **Oct 30 is the hero decision date**: T1, T2 and T3 results in, owner picks hero A (Rehearse) or fallback B (prep brief plus coaching, roleplay as a plugin). The plan below works for both; the assets in weeks 3-4 change, the gates do not.

Honesty rules carried from proposal 3: never say "nothing leaves your Mac" near a cloud engine; say "private by default" only about the local engine label; red-team the data-flow table (T6); present a benchmark, including losses, as a proof asset rather than a score claim.

## 10. Positioning statement, taglines, pitch

**Positioning statement.** For managers, founders and product leads who run a lot of high-stakes conversations, Cora is a local-first Mac meeting recorder that turns your own past meetings into practice: rehearse the next hard conversation against an AI that plays the other person from what they actually said, and get coaching on how you came across. Unlike generic roleplay tools, your practice is grounded in your real conversations. Unlike cloud notetakers, no bot joins your call and recordings stay on your Mac by default. It is open source with plugins, so you can change the coach, the roleplay and the notes without asking anyone.

**Taglines (limit 60; counted):**

| # | Tagline | Chars | Use |
|---|---|---|---|
| 1 | Rehearse your next hard conversation, from real meetings | 56 | PH tagline, Show HN framing |
| 2 | Practice the conversation before you have it | 44 | Website H1 |
| 3 | Rehearse the hard talk, from your own meetings | 46 | Alternate |
| 4 | Open-source meeting notes you can extend with plugins | 53 | T3 control arm (platform framing); also README repo description |

**One-sentence pitch:** "Cora records your meetings on your Mac, then lets you rehearse your next 1:1 with an AI that plays the other person based on what they actually said last time."

**10-second spoken:** "You know that feedback talk you keep putting off? Cora already has the last three conversations with that person. Practice it first."

If hero B wins on Oct 30: tagline becomes "Walk into every 1:1 knowing what they said last time" (verify count) and the Rehearse demo moves to second place.

## 11. Metrics

No default telemetry. Sources: GitHub, release download counts, an opt-in anonymous usage ping (off by default, documented, disabled under lockdown), weekly user calls.

**Pre-launch (before Nov 17):** T1, T2, T5, T6 complete; 20-50 closed-beta users on the notarized build; 5+ unprompted testimonials (not paid, not coached); 3 first-party plugins; 2+ outside developers have built a toy plugin; video and README ready with fictional data only.

**Launch targets (aspirational, not promised):** PH featured and top 10 (Granola's launches ranked #4-#8; Hyprnote #2 with a YC hunter; Screenpipe #14 and #9). Show HN reaches the front page for hours. Do not optimize for rank.

**30 days after launch:**

| Metric | Target |
|---|---|
| GitHub stars | 800-1,500 (reach, not PMF) |
| Notarized DMG downloads | 1,500+ |
| Activation: first recording completed | 40% of downloads |
| Aha: at least 1 rehearsal | 15% of activated users |
| Retention proxy: 2+ rehearsals on different days within 14 days | 25% of rehearsers |
| External plugin authors with a published repo | 3+ |
| User interviews completed | 20+ (15 recruited from the pre-launch list) |
| Sean Ellis survey to active users | 30%+ "very disappointed" (small n) |
| Open critical privacy or security issues | 0 |

**90 days (through ~Feb 17, 2027), PMF go/pivot:**

| Metric | Target |
|---|---|
| Weekly active users (opt-in or estimated from update checks) | 100-300 |
| Users with 2+ rehearsals in a given week | 100+ (headline number) |
| 4-week retention of activated users | 25%+ |
| Stars | 2,500+ |
| External plugins | 10+, with 3+ used by someone other than the author |
| Design-partner conversations about teams | 3 |

**PMF definition.** Cora has early PMF at day 90 if: (a) at least 25% of activated users are still active after 4 weeks, (b) rehearsal is repeat behaviour (not one-time demo use), and (c) at least 3 external plugins exist that other people use. **Pivot signals:** strong installs but no repeat use (it is a notetaker clone: pivot to hero B or drop platform framing); authors but no users (a toolkit, not a product); users love only the notes (drop roleplay as hero, compete on notes plus openness). If rehearsal repeat usage is under 10% and external plugin authors are under 3, redefine the hero before month 4.

Anti-metrics: PH rank, raw downloads without activation, plugin count from first-party only.

---

# PART 2: LAUNCH PLAN

## 12. Readiness gates

### 12.1 Never-Cut gates (any failure moves the launch; no exceptions)

| Gate | Requirement | Evidence | Owner |
|---|---|---|---|
| **G1 Notarization** | Developer ID signed, hardened runtime, notarized and stapled DMG (and zip for auto-update). Every Mach-O inside is signed: bundled Python `.so`/`.dylib`/python binary, Swift capture helpers, ffmpeg if bundled. Entitlements confirmed by `notarytool` plus a real run (audio-input, plus the JIT / library-validation entitlements Electron and bundled Python need; **U until tested**). Fresh install via browser download on clean macOS 15 and 26: first launch, mic and screen-recording prompts, record a test meeting, update to the next build without permission re-prompts. Today: `identity: null`, `hardenedRuntime: false`, target `dir`, no DMG (V). | `notarytool` log and `stapler validate` output kept as SOC 2 code-integrity evidence; T5 results | A builds pipeline, F enrolls and holds credentials |
| **G2 Lockdown** | `enterprise_lockdown` blocks every outbound path: cloud ASR, cloud notes, plugin network, plugin subprocess egress, MCP server (currently not governed, per plugin SDK draft WP-0), updater check, any usage ping. A socket-blocking test in CI proves it, including a test plugin that declares network scope. Plugin without a network scope cannot connect. Main API loopback token/Host/Origin model unchanged (byte-for-byte `authorize()`). | CI logs as control evidence | A writes, F reviews |
| **G9 Honest data-flow table** | README table "what leaves your machine, per setting" matches measured traffic (T6). | T6 capture archived | A drafts, F signs off |
| **G8 Repo and artifact hygiene** | Release is built from a clean checkout of a tag on the **public** lineage, never from the `production` working tree. The working tree has untracked `transcripts/`, `transcripts_v2/`, `New Recording *.m4a`, plus `recordings/`, `people/`, `voicecoach.db`, `state.json`, `config.json`, `backups/`, `whisper_full_dataset/`; none may reach the repo, git history, the DMG's `files` list or any gallery image. Run a secret and PII scan over the tag and the built DMG contents. | Scan report | A |

### 12.2 Launch-scope gates (can degrade to the cut list in 12.4)

| Gate | Requirement |
|---|---|
| **G3 Rehearse works** | Text rehearsal end to end on seed data: pick person and goal, persona brief with source lines, chat, coach panel, debrief saved as a note, second run with before/after metrics. T2 bar met or cloud opt-in path with exact outbound payload shown. Label: "AI simulation based on your notes, not the real person." No voice cloning, no other-participant voiceprints. Persona derived only from user-recorded transcripts, stored locally, deleted with the person. |
| **G4 Plugins v0** | Declarative tier (manifest, prompt, schema, triggers, host-rendered surfaces), permission scopes (`transcript.read`, `people.read`, `notes.write`, `network.<host>`, `audio.read`), default deny, per-scope consent, audit log. 3 first-party plugins: Rehearse, communication/storytelling coach (migrated from the existing hard-wired coaching module), todo export by user rule set. Quickstart doc plus template repo. Plugins exposed as MCP tools. Tier 1 UI frames only as Developer Preview if the spike finishes; not required. |
| **G5 Look and feel P0** | The look-and-feel draft's P0 list (about 15 agent-days). **UI freeze Thu Nov 12**; asset capture on the notarized RC tag so the gallery matches the downloadable build. |
| **G6 Demo data and assets** | All assets from `tools/seed_demo_data.py` fictional data ("Northwind Labs"); audit of every frame for real names, calendar entries, menu-bar items, file paths, notification banners and `~/` paths. Use a clean macOS user account or throwaway data dir for recording. |
| **G7 Docs and policy** | README rewrite (GIF top, DMG link, data-flow table, plugin quickstart), website with data-flow diagram, privacy policy, terms (have them reviewed; this plan is not legal advice), participant-notice template, FAQ (section 11), CONTRIBUTING and "good first plugin" issues, SECURITY contact, license and third-party notices (confirm Tara weights licence and any bundled model licences before a "local model" claim). |
| **G10 Gemini honesty** | If Gemini ships at all, it ships as the existing opt-in engine labelled "sends audio to Google"; Vertex or paid-tier guidance in docs; disabled under lockdown; never the silent default for any profile. The windowed-Gemini rewrite (about 20 agent-days) is **not** a launch gate. Pass bar G1/G2 in the transcription draft decides whether it is recommended later. |

### 12.3 Scope budget (assumption: solo founder reviewing, AI agents building in parallel; review time is the bottleneck)

| Track | Launch scope | Agent-days (from sibling drafts) | Status |
|---|---|---|---|
| Notarization and release pipeline | G1 | ~4-5 (estimate) | Launch |
| Plugin SDK | WP-0 to WP-6 + WP-8 (docs/CLI scaffold); WP-7 Developer Preview only | ~31 (draft says ~35 incl. WP-7) | Launch, with cut order below |
| Look and feel | P0 only | ~15 | Launch |
| Notes templates | Minimal: templates as files, picker, fix `notes_llm_provider` being ignored by the auto pipeline | partial of ~? (draft) | Launch minimal |
| Gemini windowed rewrite | None | ~20 | **Deferred** |
| Phone capture / Tailscale | None (mention as roadmap only after the loopback model is preserved in that design) | ~18 | **Deferred** |
| Launch marketing and assets | Sections 5-10 | Founder-heavy | Launch |

Total launch-scope agent work is about 55-60 agent-days. That fits 4.5 weeks only with at least 3-4 parallel agent streams and a ruthless freeze; the founder cannot review more than about 2 substantial PRs a day. If by Fri Nov 6 the plugin work is behind, apply the cut order.

### 12.4 Cut order (from proposal 1, reordered for this hero)

1. Tier 1 UI frames (Developer Preview).
2. Voice rehearsal (text only).
3. Roadmap, KB and story-coach plugins (ship Rehearse, comm-coach, todo export).
4. The "external plugin authors" claim (say "customizable").
5. Hinglish proof post.
6. Anything hosted.

Never cut: G1, G2, G9, G8.

## 13. Dated plan: Fri Oct 16 to Fri Nov 27

Owner key: **F** founder, **A** AI coding agent (founder reviews), **F+A** both. Times are PT unless marked IST; the owner's time zone is unconfirmed (section 20), conversions assume IST. PT is UTC-8 from Nov 1.

### Week 0: Fri Oct 16 - Sun Oct 18 (today)

- F: approve section 0 decisions. Enroll in the Apple Developer Program **today** (individual is fastest; an organization needs a D-U-N-S number; enrollment time is U). Create a Developer ID Application certificate as soon as enrollment clears.
- F: Product Hunt: create or warm the personal account (PH says 3+ months ideal, 1 week minimum, and an account under 1 week old cannot post); engage daily with substantive comments. Co-makers (if any) create accounts now. Start the product as a **draft** so its forum thread exists (replaces the retired Coming Soon page).
- F: recruit for T1 (10 EMs/founders) and the closed beta (20-50) from existing network; start a list of 15 interview candidates (section 14 covers channels).
- A: kick off WP-0 (plugin security prerequisites), the notarization pipeline spike, the `speakers.py` voiceprint review (R11), and the repo-hygiene scan (G8).
- A: start Reddit karma building plan for F (genuine participation only).

### Week 1 (T-4w): Oct 19 - 23

- F: T1 sessions begin. Book the second sessions for the following week.
- A: plugin loader (WP-1) and events/recipes (WP-2); notarization pipeline signs everything; first internal DMG; lockdown test harness skeleton (G2); `asr_bench` pass for the optional T7.
- A: look-and-feel P0 starts (tokens, shell, empty states, privacy chip).
- F: publish the website skeleton with data-flow diagram, privacy policy and terms (reviewed); decide on a counsel review for BIPA/DPDP and the consent notice (R11).
- F: share a 30-second mock cut? Not yet; wait until week 2.
- Fri Oct 23: **checkpoint**, notarization pipeline produces a DMG (even if not yet notarized cleanly). Slip signal: if no signed build exists by Oct 30, put the Dec 1/3 plan on standby.

### Week 2 (T-3w): Oct 26 - 30

- A: Rehearse v0 plugin (text), persona brief with provenance links, coach panel; comm-coach migrated; todo-export rule set. Plugin quickstart and template repo drafted. T2 bake-off prepared and run Oct 21-24.
- F: closed beta opens on the first notarized build (~Oct 28); T5 install funnel with 10 users; collect testimonials only if unprompted. Ask beta users to engage with their own PH accounts only if they already use PH; never to vote on request.
- F+A: record a 30-45 second mock demo from seed data; T3 message test (3 taglines, 10 people each). T4: DM 20 plugin-minded developers with the quickstart draft.
- A: README rewrite draft; website; demo seed data additions for the Rehearse story (fictional person, three prior meetings).
- **Fri Oct 30: HERO DECISION.** T1, T2, T3 read out against the bars. Pick hero A or B. Freeze the plugin manifest and API (v0) the same day.

### Week 3 (T-2w): Nov 2 - 6

- A: lockdown CI suite complete (G2); T6 network-capture run with default settings and with lockdown on; data-flow table draft verified against the capture.
- F: T6 red-team with 3 privacy-minded reviewers; T8 notes parity; start benchmark post (optional).
- F+A: PH listing fully filled in as a draft (section 15): name, tagline, description, 3 topics, thumbnail, gallery placeholders, YouTube link placeholder, links, first comment, shoutouts. Prepare Show HN post and first comment, X thread, LinkedIn post, email to interview/beta lists.
- A: look-and-feel P0 at 80%; plugin work enters bug-fix mode; Tier 1 spike decision (cut or Developer Preview).
- F: legal pass on privacy policy, terms, and the participant-notice template.
- **Fri Nov 6: GO/NO-GO #1 (slip decision).** PH must be scheduled at least 10 days ahead, and Nov 6 is the safe date for a Nov 19 launch (PH allows scheduling up to a month ahead). Criteria: G1 produces a stapled DMG that passes a clean-machine install; G2 CI green; T5 at 9/10 or a clear fix list; T6 zero unexplained connections; G8 scan clean. **Any Never-Cut gate failing: reschedule PH to Dec 3 and announce nothing.** Otherwise: schedule PH for Thu Nov 19, 12:01am PT.

### Week 4 (T-1w): Nov 9 - 13

- Mon Nov 9: cut RC tag from the public lineage, notarized and stapled DMG on GitHub Releases (pre-release); verify the auto-update path from the previous build.
- A: bug fixes only; docs; "good first plugin" issues; awesome-cora-plugins list; enable GitHub Discussions.
- Tue-Wed Nov 10-11: capture all gallery images, the demo video and the GIF on the RC tag; run G6 frame audit. Upload video to YouTube (public, captioned).
- **Thu Nov 12: UI freeze.** Fixes only.
- F: line up supporters with the message "check it out and tell us what's missing" (never "upvote"). Send participant-notice and FAQ drafts to 3 reviewers. Post a build-in-public note on X and LinkedIn with the 30-second clip (no launch date push; a "coming next week" teaser is fine).
- **Fri Nov 13: GO/NO-GO #2 (final).** Same criteria as Nov 6, plus G3, G4, G7 complete or on the cut list. If a Never-Cut gate fails: move to Tue Dec 1 / Thu Dec 3 (section 19).
- Check subreddit rules and sidebars again (mirrors may be stale).

### Week 5: Mon Nov 16 (eve of launch)

- A: tag the final release (vX.Y.0), notarized DMG, update the README, website and release notes; verify download link from a clean browser.
- F: final rehearsal of the runbook; sleep. Prepare 5-6 pre-written answers (section 17); do **not** pre-write replies for the comment thread itself.

### Launch week

- **Tue Nov 17: Show HN** (section 16.1). Same day: X thread, LinkedIn story (section 14), publish the benchmark write-up if it exists.
- **Wed Nov 18: r/LocalLLaMA** (benchmark-led, only if the post stands on its own) and **r/macapps** App Pile with the [OS] prefix and PCP format. Reply to everything.
- **Thu Nov 19: Product Hunt** at 12:01am PT (1:31pm IST), runbook in section 16.2.
- **Fri Nov 20:** optionally the r/selfhosted Friday megathread (weak fit for a desktop app; skip if time is short). Start the post-launch work (section 18).

### T+1 week: Nov 20 - 27

- See section 18. Thanksgiving is Thu Nov 26; keep this week low-volume on outbound posts.

## 14. Channel plan

Principle: one clear message per channel, concentrated into about a 48-hour window because GitHub trending rewards star velocity (L). Nothing is posted with tracking links. Never ask for votes anywhere.

| Channel | When | Content and rules |
|---|---|---|
| **Show HN** | Tue Nov 17, 8-10am ET (6:30-8:30pm IST), link the GitHub repo (README is the landing page; DMG link at top) | Title starts with "Show HN"; must be tryable immediately (no signup, no waitlist). Plain, specific title. First comment immediately: why built, architecture, what leaves the machine, known limitations. Engage 4-6 hours. Do not ask friends to upvote or comment; do not delete and resubmit. |
| **Product Hunt** | Thu Nov 19, 12:01am PT | Self-hunted (79% of featured posts are, V). First maker comment within minutes. Reply to every comment through the 24-hour Pacific day. |
| **X** | Nov 17 thread, Nov 19 "we're live, feedback welcome" | 30-second clip first; thread of 6 posts: problem, demo, how it is grounded, what leaves the Mac (the table), plugins, ask for feedback. No upvote language. |
| **LinkedIn** | Nov 17 story, Nov 19 PH link | Founder story: the hard conversation you kept putting off. One image, one clip. |
| **r/LocalLLaMA** | Wed Nov 18 | Lead with the local MLX pipeline and the benchmark write-up, not a promo. Disclose affiliation. Stay under about 10% self-promotion. Needs karma (5 subreddit, 10 Reddit). Rule 4 was revised around late Apr 2026 and the current text is U; read the sidebar first. |
| **r/macapps** | Wed Nov 18 | Repo is under 1 month old with 0 stars, so Tier 1 is closed (L). Use the monthly App Pile thread, `[OS]` prefix, PCP format (Problem, Comparison, Pricing). One self-promo per 30 days. Alternative: Tier 2 needs a developer identity plus a site with privacy policy and terms (we will have both). |
| **r/selfhosted** | Fri Nov 20 megathread, optional | Projects under 3 months old go only in the Friday "New Project" megathread; weak fit. |
| **Indian founder communities** | Nov 17-20, after interviews | Peerlist, r/developersIndia, r/indianstartups, founder Slack/WhatsApp groups, build-in-public circles on X and LinkedIn. Community sizes and rules were **not researched (U)**; produce the actual list from the 15 interviews and read each community's rules before posting. Lead with the benchmark or a story, not a promo. Hinglish stays a proof point. |
| **DevHunt** | A later week | Votes need GitHub login; pricing U ($0 vs $19). |
| **Email** | Nov 17 and Nov 19 | Only to people who asked to hear about it (interview, beta, GitHub watchers); no scraped lists. |

## 15. Product Hunt listing draft

**Name:** Cora
**Tagline (56):** Rehearse your next hard conversation, from real meetings
**Description (about 354 of 500 chars; edit before pasting):**

> Cora records your meetings on your Mac (no bot), then lets you rehearse the next hard 1:1 with an AI that plays the other person from what they actually said, and coaches how you came across. Local by default, MIT, with plugins you can read and edit. Optional bring-your-own-key cloud models are labelled; enterprise lockdown blocks all outbound traffic.

Pre-publication check: "enterprise lockdown blocks all outbound traffic" only goes in after G2 passes. If hero B wins, rewrite the first sentence around the prep brief.

**Topics (max 3):** Productivity, Open Source, Artificial Intelligence (alternate for the third: Meetings, if available).
**Pricing:** Free. **Links:** the GitHub repo or the website, no tracking parameters. **Shoutouts (max 3):** the open-source tools Cora is built on, if the maintainers are on PH.
**Thumbnail:** 240x240 square under 3MB; GIFs do not autoplay, so the first frame must work as a still (the Open C mark from the look-and-feel draft).
**Launch:** scheduled by Nov 6 for Thu Nov 19, 12:01am PT.

**Gallery shot list (1270x760, at least 2 required; use 6; all from the notarized RC tag, seed data only):**

1. Hero: the Rehearse chat mid-conversation with the fictional person; caption "Practice the talk you keep putting off".
2. Provenance: a persona line with its source transcript segment highlighted; caption "Every line traces back to what they actually said".
3. Debrief: before/after across two rehearsals (pace, fillers, talk-to-listen); caption "See what changed between run one and run two".
4. The meeting itself: transcript with speakers, notes and action items for a fictional meeting.
5. Privacy: the "what leaves your machine" panel with the privacy chip and lockdown on; caption "Local by default. Lockdown blocks everything, plugins included".
6. Plugins: a plugin folder (manifest, prompt) next to the plugins list; caption "A plugin is a folder you can read".

**Video storyboard (public YouTube, 45 seconds, captions on, no voiceover needed; result in the first 3 seconds; assumes the final demo script, owner approves):**

| t | Shot |
|---|---|
| 0-3 s | Rehearse chat already running: the fictional person pushes back on a missed deadline. Caption: "Rehearse the hard conversation before you have it." |
| 3-10 s | Cut to the meeting list; the three prior meetings with that person; click Rehearse. |
| 10-20 s | Persona brief with source lines; hover a line to show the transcript segment. |
| 20-32 s | Short exchange; coach panel flags a hedge and over-explaining. |
| 32-38 s | Debrief and the second run's metrics. |
| 38-43 s | Settings: privacy chip, lockdown toggle, data-flow table. Caption: "Local by default. No bot." |
| 43-45 s | Plugin folder, then logo and repo URL. |

Reference the look-and-feel draft's motion and brand notes for the final cut.

**Maker first comment (draft; no upvote language; post the minute the launch goes live):**

> Hi PH, I'm [name], maker of Cora.
>
> I built Cora because I kept putting off hard 1:1s, and every notetaker I tried gave me a summary but did nothing to help me get better at the conversation itself. Cora records your meetings on your Mac (no bot joins), and the part I most want feedback on is Rehearse: you pick a person and a goal, and an AI plays them based on what they actually said in your recorded meetings. Every line links back to the transcript segment it came from, so you can see where the persona comes from.
>
> What it is: a local-first macOS app, MIT licensed, with a plugin system. Rehearse, the communication coach and the todo export are all plugins you can read and edit.
> Who it is for: managers, founders and product leads with a lot of 1:1s.
> About data: local by default. Cloud models are optional, bring-your-own-key, and labelled with exactly what leaves your Mac. Enterprise lockdown blocks all outbound traffic, including plugins. This is not a certified compliance product and I make no HIPAA or SOC 2 claims. You are responsible for recording consent under your local law; there is a participant-notice template in the repo.
> Honest limits: macOS on Apple silicon only for now; a small local model plays a person less convincingly than a cloud model, so Rehearse offers an opt-in cloud model and says so.
>
> I'd love to know: what is the conversation you'd rehearse first, and what's missing? If you build plugins, the quickstart takes about 10 minutes.

## 16. Launch-day runbooks

### 16.1 Show HN (Tue Nov 17)

| Time (ET / IST) | Action |
|---|---|
| Mon night | Verify DMG link from a clean browser; repo README top block current; GitHub issues and Discussions on; auto-update path works. |
| 7:30am ET / 6:00pm IST | Final check: release asset checksum, demo instance, the first comment draft open. Phone silenced except for notifications from HN and GitHub. |
| 8:00-10:00am ET / 6:30-8:30pm IST | Submit "Show HN: Cora – [plain description]" linking the repo. Post the first comment immediately. |
| Hours 0-2 | Reply to every comment within about 10 minutes, concrete and non-defensive. Privacy and Gemini questions get the data-flow table. Do not ask anyone to vote or comment. |
| Hours 2-6 | Keep replying. File GitHub issues for real bugs in public as they come. |
| Hour 6+ | Post the X thread and LinkedIn story. Log stars, downloads, issues. |
| End of day | Triage issues; ship a hotfix only for install-blocking bugs (the notarized build matters more than speed). |

Title candidates (80-char HN limit; count at submission): "Show HN: Cora – rehearse your next hard 1:1 with an AI that knows the person" (76). Backup if hero B: "Show HN: Cora – local-first meeting recorder with a plugin API (MIT)".

**Show HN first comment (draft):** why I built it; architecture in four bullets (Electron UI, Python loopback API with token, Host and Origin checks, local MLX pipeline, plugin host with scoped permissions); the data-flow table inline; what does not work yet (Mac only, small local model limits, no Windows or Linux); how Rehearse is grounded; the lockdown test; the license; a direct ask for what's wrong. Include a link to the benchmark if published.

### 16.2 Product Hunt (Thu Nov 19), hour by hour

PH runs on a 24-hour Pacific cycle. For roughly the first 4 hours, order is reported to be shuffled and counts hidden (L); do not read much into early ranking.

| Time (PT / IST) | Action |
|---|---|
| Wed 8pm PT / Thu 9:30am IST | Verify the scheduled launch exists, links work, video public, gallery correct, DMG link from a clean browser. Co-makers logged in. |
| 11:45pm PT / 1:15pm IST | Open the post and the first comment draft. |
| **12:01am PT / 1:31pm IST** | Launch goes live. Post the first comment immediately. |
| 12:05-1:00am | Post on X ("we're live, feedback welcome") and LinkedIn; send the email to people who asked to hear. Message supporters: "check it out and tell us what's missing". No upvote asks, no contests. |
| 1:00-4:00am PT (2:30-5:30pm IST) | Reply to every comment as it arrives. Replies are written by the founder (PH penalizes low-effort and AI-written comments, L; agents may draft FAQ answers, the founder edits and posts). |
| 4:00am PT (5:30pm IST) | Counts and order become visible. Do not react to rank. |
| 4:00am-8:00am PT | Rest in shifts if a co-maker exists; otherwise check every 30-60 minutes. Watch GitHub issues, a likely install-bug source. |
| 8:00am-12:00pm PT (9:30pm-1:30am IST) | Main US morning traffic; reply promptly, a second round of social posts with real feedback screenshots (with permission). |
| 12:00pm-6:00pm PT | Reply and fix. Collect feature requests as public issues. |
| 6:00pm-11:59pm PT | Final replies; thank commenters individually; no asks. |
| Fri 12:01am PT | Launch day ends. Screenshot the final state. Write the first post-mortem notes while fresh. |

Sleep plan: if the owner is in IST, the launch day runs 1:31pm Thu to 1:31pm Fri IST. A co-maker or trusted friend covers the 5:30-11:30pm IST stretch if they are available. If not, accept slower replies overnight, and say so in a comment.

## 17. FAQ for hard questions (answers to pre-write; each cites a verifiable fact)

1. **"Does my audio go to Google?"** Not by default. Local transcription is the default. Gemini is an optional engine you turn on with your own key; the Settings card says what is sent (audio and, where used, a context block with names and glossary). Use Vertex or the paid tier; the free tier may train on data. Under `enterprise_lockdown`, cloud engines are disabled. The data-flow table lists each setting. Since commit e80bf9e the UI labels cloud transcription honestly and "On this Mac" never uploads audio.
2. **"Why should I trust 'local by default'?"** Open source, a measured network capture with default settings and with lockdown on, and a CI test that fails if anything connects under lockdown. Link the capture.
3. **"What does enterprise lockdown block?"** All outbound paths: cloud ASR, cloud notes, plugin network and subprocess egress, the MCP server, update checks and usage pings. It is a policy switch, not a certification. Do not say more than the CI test covers.
4. **"Is this HIPAA or DoD ready? SOC 2?"** No claims. A SOC 2 Type 2 audit is in progress and not complete; Cora is not a certified scribe; regulated users should check their own policy. Do not volunteer customer details.
5. **"What about consent and recording laws?"** You are responsible for recording consent under your local law. Cora has no bot, so the participants don't see one; the repo has a participant-notice template. Cora does not create voiceprints of other participants (verify R11 before saying this), and Rehearse uses personas derived from text with no voice cloning.
6. **"Isn't a roleplay of a real person creepy?"** Labelled "AI simulation based on your notes, not the real person." Built only from transcripts you recorded; stored locally; deleting the person deletes the persona; no voice cloning; for your own practice.
7. **"Why not just use Claude plus my notetaker's MCP?"** You can, and for casual use that works. Cora adds persistent people memory, provenance back to transcript lines, a purpose-built rehearsal UI, delivery coaching on your own speech, and no vendor sees your recordings. T1 compares the two directly; quote the result honestly, including a loss.
8. **"How is this different from Granola, Screenpipe, Anarlog, Meetily?"** Section 7 table. Concede what they do better.
9. **"Windows or Linux?"** macOS on Apple silicon only today (MLX needs Metal). No dates promised. Contributions welcome.
10. **"Why is it signed / is it safe to open?"** Developer ID signed, notarized and stapled; checksums on the release; build from source documented. Signing credentials live in CI secrets, never in the repo.
11. **"Business model?"** Free and MIT; no accounts. A paid convenience tier may come later (sync, managed model access); core, plugin API and your data will never be gated.
12. **"Plugin security?"** Declared scopes, default deny, per-scope consent, audit log, out-of-process, lockdown blocks plugin egress, main API token model untouched. Say "files you can read, edit and share", not "ecosystem".
13. **"How good is the local model for roleplay?"** Honest answer from T2. If local falls short, say so and point to the opt-in cloud path.
14. **"Hinglish?"** Proof point, with the benchmark results if published; Tara weights licence checked before claiming a local Hinglish model.

## 18. Post-launch plan

| When | Action | Owner |
|---|---|---|
| Fri Nov 20 | Claim the PH product page; embed the PH badge in README and site; start the post-mortem notes. | F |
| Nov 20-24 | Ship 1-2 fixes from launch feedback with a public changelog. Triage install failures first. | A, F reviews |
| Nov 23-27 (Thanksgiving week) | Quiet outbound; interviews only. Convert interested developers to plugin authors: office hours, a small bounty list. | F |
| By Nov 27 | Publish a numbers post-mortem (stars, downloads, activation, PH rank, HN traffic, plugin installs, what broke). | F+A |
| Dec | Run the 15-20 interviews, Sean Ellis survey to active users, and the Pro supporter page (no payment). List on DevHunt. Resume phone capture and the windowed Gemini upgrade if the data supports it. | F+A |
| Dec-Feb | PH relaunch when a plugin directory ships (PH allows relaunches for significant iterations; Open SaaS relaunches about every 3 months). Day-90 PMF review (section 11). | F |

## 19. Slip plan

**Triggers (any one):** G1 not producing a stapled DMG that passes the clean-machine test by Nov 6; G2 CI not green by Nov 6; T5 under 9 of 10 with unresolved blocker; T6 finds an unexplained connection; G8 scan finds data in the tag; hero decision deferred past Nov 6.

**Action:** reschedule PH to **Thu Dec 3**, Show HN to **Tue Dec 1**. Do not announce a date publicly before Nov 13, so a slip costs nothing. Use the extra two weeks for: finishing the failed gate, a second beta round, T7 benchmark post, polishing G5 P1 items, and the windowed Gemini upgrade only if it passed G1. Repeat the checkpoints on Nov 20 (slip decision) and Nov 27 (final), with the Thanksgiving week (Nov 23-27) used for work, not posts.

**Drop-dead:** Dec 8 / Dec 10. After that, avoid Dec 21 - Jan 4 (holiday traffic) and go Tue Jan 12 / Thu Jan 14. If the Dec 3 date also fails, the cause is scope, not time: apply the entire cut list.

**Communicating a slip:** no announcement needed if dates were never public. If beta users know, say what you are fixing and why (notarization or lockdown evidence), not a vague delay.

---

## 20. Owner decisions needed (blocking marked)

1. **Approve the hero** (Rehearse versus platform versus Hinglish accuracy). Blocking by Oct 30.
2. **Time zone and availability** for launch days (assumed IST in the runbooks) and whether a co-maker can cover shifts.
3. **Apple Developer enrollment, today**; individual or organization (D-U-N-S delays). Blocking.
4. Accept **no voice cloning and no other-participant voiceprints** for roleplay and coaching. Blocking for G3.
5. Accept **cloud-opt-in as the default Rehearse path if T2 fails** for the local model.
6. **License:** the repo is MIT (confirmed from the LICENSE file; "Copyright (c) 2026 Mayank Dubey"). Confirm third-party and model licences (Tara weights, any bundled model) before "local model" claims.
7. **Release lineage:** confirm releases are cut from the public lineage and never from the `production` working tree (G8).
8. **Scope:** accept deferring phone capture and the windowed-Gemini rewrite until after launch.
9. **Pro pricing:** park until after day 90, or run a no-payment supporter page at launch.
10. **Counsel:** spend on a short review of privacy policy, terms, BIPA and DPDP exposure, participant notice.
11. **Hinglish proof post:** run T7 and decide after seeing results.

## 21. Risks and watch items

| Risk | Mitigation |
|---|---|
| Rehearse is a nice demo nobody repeats | T1 and the Oct 30 pivot; day-90 retention criteria. |
| Local model too weak to play a person | T2 and a labelled cloud opt-in; never claim local roleplay without evidence. |
| Notarization takes longer than the plan (entitlements U, enrollment time U) | Start today; Nov 6 checkpoint; Dec 1/3 fallback. |
| Scope overload (about 55-60 agent-days plus review) | Cut order in 12.4; UI freeze; review budget of about 2 substantial PRs per day. |
| HN pushes on the Gemini path | Honest labels, data-flow table, T6 capture; opt-in only. |
| PH penalizes vote solicitation or low-effort comments | No asks; founder writes replies. |
| Real data leaks into an asset or the repo | G6 frame audit, G8 scan, fictional seed data only. |
| Competitors ship the same feature first | Weekly re-check; speed and openness. |
| Unverified facts in this plan | PH algorithm details, subreddit rules, DevHunt price, enrollment time, hardened-runtime entitlements, Indian community rules. Re-check each before relying on it. |
| SOC 2 evidence gaps | Keep notarization credentials in CI secrets or Keychain, keep `notarytool` logs, CI lockdown logs, and plugin audit samples as control evidence; document the release process. |

## Appendix: facts relied on and their confidence

- PH: 12:01am PT recommended; tagline 60 chars; description 500 chars; 3 topics; gallery 2+ images at 1270x760; YouTube video; 240x240 thumbnail under 3MB; schedule up to a month ahead; 79% of featured posts self-hunted; no vote asking; Coming Soon pages retired (V/L as in the research file).
- Peer outcomes: Hyprnote PH #2 (457 upvotes, YC hunter), Screenpipe #14 and #9, Humla #144, Meetily 31.8k stars with a 4-point Show HN, Open SaaS HN traffic 3x PH (V/L).
- Gatekeeper and Homebrew: Sequoia removed Control-click override (V); official Homebrew cask closed to unsigned apps from Sept 1, 2026 (V); a self-hosted tap is possible.
- Repo: `identity: null`, `hardenedRuntime: false`, version 0.2.2 in `package.json`; MIT LICENSE; `tools/seed_demo_data.py` and `tools/asr_bench.py` exist; `python/policy.py` provides `lockdown_enabled()`.
- Unverified: PH vote weights, first-4-hours behaviour as of late 2026, current subreddit rule text, DevHunt pricing, Apple enrollment duration, required hardened-runtime entitlements, Indian channel rules, competitor details flagged in the research.
