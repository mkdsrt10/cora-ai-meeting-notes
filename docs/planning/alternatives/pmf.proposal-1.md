# Cora: Positioning + PMF Proposal 1
Angle: "The open, local-first plugin platform built around meetings." Flagship: Rehearse (roleplay). Beachhead: builder-operators.
Date: 2026-10-16. Evidence base: research_pmf / research_competitors / research_producthunt (confidence tags carried over; unverified items are marked).

## 0. Verdict up front

- The angle is defensible only in a narrow form. "No one has plugins" is false (screenpipe pipes + store, Anarlog plugin SDK, Fireflies AI Skills, Granola Recipes/MCP, Zoom/Notion agents). Using it will get the launch called out within minutes.
- The honest unclaimed ground is two things combined: (1) a code-level, local-data plugin runtime over structured meeting objects (speakers, people, transcript, notes, action items) with write-back and cross-meeting state, and (2) a flagship that uses it: rehearse your next hard conversation against an AI playing that specific person, built from your last real meeting with them. Gong AI Trainer does real-call roleplay only for enterprise sales; Yoodli, Second Nature, Hyperbound, Peopling and Mindtools use synthetic scenarios.
- Hard truth: today Cora has no plugin system (one hard-wired coaching module; nothing loads third-party code), 0 stars, and is unsigned. The platform claim is a roadmap, not a fact. Launch copy must lead with the thing that works (Rehearse) and describe the platform as "plugins are files you can read, edit and share", not as an ecosystem.
- Recommendation: ship "Plugin API v0" scoped to what a solo founder can finish (manifest + permissions + prompt/template tier + one sandboxed code tier), 3-4 first-party plugins, and treat third-party plugin authors as a 90-day outcome, not a launch claim.

## 1. ICP

### Primary persona: "Builder-operator" (beachhead)
Technical founder / head of eng / EM / senior PM / solo consultant, on a Mac, 10-30 meetings a week, of which 3-10 are 1:1s or high-stakes conversations (investor updates, performance feedback, customer escalations, co-founder talks). Already uses Claude/ChatGPT/Cursor daily, has opinions about data ownership, and is comfortable cloning a repo or running a notarized app with a BYO API key.

Why this group: they are the HN / GitHub / Product Hunt audience; they are the only group that can both use and author plugins; price anchors ($8-15/mo) exist; and the OSS peers (Meetily, screenpipe, Anarlog) all grew from this audience.

### Jobs-to-be-done
1. "Before a hard conversation, let me practice it against a realistic version of this person, not a generic scenario." (Rehearse)
2. "After meetings, turn what was said into my systems (todo app, roadmap, decision log) by rules I wrote, without a SaaS reading my calls." (rules/export plugins)
3. "Let me own my meeting corpus as files/DB I can query from my own agents (MCP) and extend." (platform)
4. "Tell me how I come across over time (pace, filler, talk ratio, storytelling) from real calls." (coach plugin)
5. Secondary: "Record without a bot and without a legal exposure story I have to explain to participants."

### Triggers (moments they go looking)
- An upcoming difficult 1:1 / performance review / fundraising call / firing.
- A new manager promotion ("I now do 1:1s all week and no one trained me").
- A privacy event: notetaker lawsuits (Otter, Fireflies, Granola), tl;dv exposure (HN, 633 points, Aug 2026), a customer or university banning bots.
- Granola/Otter price or training-opt-out friction; being told "we can't use that bot on this call".
- Wanting a personal "meeting agent" they control after seeing Claude Skills / MCP.

### Where they hang out
HN (Show HN), GitHub trending, r/LocalLLaMA (lead with the MLX pipeline + ASR benchmark; <=10% self-promo), r/macapps (App Pile with [OS] prefix; Tier 1 not yet eligible), r/selfhosted (Friday megathread only, weak fit), X/LinkedIn builder circles, Indie Hackers, MCP/Claude Code communities, Obsidian/Raycast power-user circles, YC/founder Slacks. Indian founder communities as a secondary pool (Hinglish accuracy proof).

### Explicit non-ICP for launch
Regulated professionals (lawyers, therapists, DoD, HIPAA entities). Pain is strongest (NYC Bar Op. 2025-6, CMMC/FedRAMP, APA consent) but Anarlog and Meetily already target them, selling needs BAAs/attestations/EHR integration, and Gemini cloud ASR contradicts the local-only promise. Keep `enterprise_lockdown` as a message pillar and design-partner conversation later; make no HIPAA/CMMC/SOC 2 claims while the audit is in progress.
Also not now: sales teams (Gong/Hyperbound territory), teams needing shared todos/knowledge base (needs multi-user sync, conflicts with local-first).

### Secondary segment (do not split launch focus): Hinglish / Indian-English professionals
Real, demo-able accuracy gap (Otter has no Hindi; Zoom thread on dropped code-switched words; vendor WER 27-70%, all unverified for meetings). Founder-fit is high, willingness to pay is low and PH audience won't care. Use as a proof-point (published benchmark), not a second beachhead.

## 2. Value proposition and proof points

Core promise: "Your meetings, on your Mac, as a platform you can build on, starting with rehearsing the next one."

Three layers (in the order they are shown):
1. Rehearse (the hook): pick a person and an upcoming topic; Cora builds a persona from your last real conversations with them (their phrasing, objections, how you tend to react) and you practice by voice or text; you get feedback on delivery metrics Cora already computes (pace, pauses, filler, pitch) plus a rubric.
2. Plugins you can read (the platform): a plugin is a folder: manifest + prompt + optional code, with declared permissions. Same shape as Claude Skills / pipe.md so authors already know it. Outputs are structured objects, not just text.
3. Local, bot-free, honest data flow (the trust floor): local by default; optional BYO-key Gemini for accuracy, labelled; `enterprise_lockdown` blocks every outbound path including plugins; no training on your data; no public share links.

### Proof points to build before launch (each must be reproducible, no real meeting data)
| Claim | Proof asset | Status |
|---|---|---|
| Rehearse is grounded in a real conversation | 45-60s demo using the fictional-data seeder (tools/seed_demo_data.py); before/after of persona fidelity | Needs building |
| Plugins are real and portable | 3-4 first-party plugins + "build a plugin in 10 minutes" repo; at least 1 plugin by a non-founder | Needs building |
| Local-first + lockdown | "What leaves your machine" table; automated test that lockdown blocks plugin network | Needs building (SOC 2 evidence too) |
| Accuracy | Published benchmark (benchmark tool exists, commit 6424d28): Gemini vs Chirp 3 vs Sarvam vs local Tara/Whisper on synthetic or consented audio, same normalization | Tool exists; corpus needed |
| Notarized, one-click install | Signed DMG, clean-machine test | Launch blocker, not started |

Do not claim: "only/first extensible meeting tool", "most accurate", "private" while cloud ASR is on, any compliance certification.

## 3. Why now
- Capture is solved and commoditised; the fight moved to what happens after capture (context layer, agents, MCP). MCP is now table stakes (Granola, Otter, Read, Circleback free tier, Meetily Pro), so extensibility is moving to the AI assistant layer. Cora must offer what a Claude skill on someone else's MCP cannot: local execution, UI surface, write-back, cross-meeting state, in-meeting hooks.
- Trust crisis in cloud notetakers: class actions against Otter, Fireflies (BIPA), Granola; university bans; 65% consent-gap survey (law-firm sponsored); tl;dv exposure on HN. Bot-free + local is an easy story to tell in late 2026.
- Roleplay is the best-funded adjacent category (Yoodli $40M B, Second Nature $22M, Hyperbound ~$17-18M) with a visible gap: not grounded in your own non-sales meetings.
- Frontier-model voice and long-context make persona-from-transcripts viable on a BYO key or local model.
- Window is closing: Wispr ($2B) entering meeting notes, Granola moving to enterprise context, Notion agents triggered on meeting notes (Jul 2026).

## 4. Competitor framing (honest)

| Player | What they have | Where Cora should not pretend | Where Cora can differ |
|---|---|---|---|
| screenpipe (22k stars, YC S26) | Pipes = scheduled markdown agents with permission frontmatter, pipe store, meeting-summary pipe, sandboxed; source-available commercial license, sign-in, $25+/mo | Owns the "pipe store" story; broader (screen+audio) | Meeting-native structured objects (people, speakers, action items), MIT/true OSS, no account, roleplay on real conversations |
| Anarlog/Hyprnote (9.5k, YC S25, MIT) | plugin.json + plugin-sdk, renderer-injected (bad plugin can freeze app), targets law/finance/health | Local-first OSS niche is theirs | Out-of-process permissioned plugins, lockdown story, flagship app-level plugin |
| Granola ($1.5B) | Recipes (static prompts), templates, read-only API/MCP, Spaces; litigation exposure | Templates and MCP are parity | Code + write-back + local; no cloud account |
| Fireflies AI Skills | 200+ prompt apps, user-built, scheduled, pushed to Jira/Asana/CRM | Prompt-app breadth, team features | Local, open, individual-owned data |
| Meetily (31.8k, MIT) | Largest OSS local notes; extension points (webhooks/CLI/API/MCP) paywalled in $10 Pro; no marketplace | Star count and distribution | Extensibility free and file-based; plugin UX |
| Gong AI Trainer / Yoodli / Second Nature / Hyperbound | Funded roleplay; Gong builds from real calls (sales only, enterprise price) | Sales-team roleplay; polish of scored scenarios | Individual, non-sales, private, specific person, runs on your own recordings |
| Zoom / Teams / Notion agents | Cloud-locked extensibility | Reach | Platform-agnostic, bot-free, local |
| Claude/ChatGPT + vendor MCP | "Roleplay my last 1:1" prompt on any MCP server | This is the biggest substitute | Be portable: plugins expose as MCP tools; Cora is the runtime, not a silo |

Framing line for copy: "Not another Granola alternative. Meeting notes are the part everyone has. Cora is what you build on top of them."

## 5. Pricing / business model

- Core and all first-party plugins: free, MIT, local. BYO API keys (Gemini paid tier only; free tier may train with human review, so warn or block).
- Do not paywall extensibility (Meetily/Granola/Jamie/Otter all gate API/MCP; free file-based plugins is a differentiator).
- Optional paid later (decide after PMF signal, not before launch): Cora Pro ~$8-12/mo (below Granola Business $14, near Meetily $10, Yoodli Pro $8): hosted-key proxy for Gemini, E2E-encrypted sync between Mac Studio/iPhone/laptop, signed plugin registry with review, team plugin registry. Teams/enterprise later: self-hosted support, audit log export, policy packs.
- Anything paid must pass the lockdown test: paid features are additive cloud conveniences, never required.
- Hypothesis, unverified: builder-operators will pay $8-12 for sync/hosted convenience but not for the core. Test via waitlist-at-install (see 7), not a price page at launch.

## 6. Positioning statement, taglines, pitch

Positioning statement: For founders, engineering managers and PMs who run their work through conversations and want to own that data, Cora is the open-source, local-first plugin platform built around meetings. Unlike cloud notetakers that lock you into their prompts and bots, or local recorders that stop at a transcript, Cora gives plugins structured access to your people, transcripts and action items on your own Mac, and ships with Rehearse: practice your next hard conversation against an AI playing the other person, built from your real last meeting with them.

Tagline options (PH limit 60 chars; counts checked):
1. "Rehearse your next hard 1:1 from your last real one" (52)
2. "Open-source meeting notes, extended by plugins" (46)
3. "The local-first plugin platform for your meetings" (49)
4. "Practice tough talks with an AI that knows the person" (53)
5. "Your meetings, on your Mac, with plugins" (40)
Recommendation: lead with #1 on Product Hunt (concrete, Novel), use #3 in README/repo description. A/B with 10 builders before locking (PH CEO advice). Avoid "AI-powered", "revolutionary".

One-sentence pitch: "Cora records your meetings on your Mac, keeps everything local, and lets plugins act on it, starting with an AI that plays the person you're about to have a hard conversation with."

## 7. Riskiest assumptions and cheapest tests (ranked by risk x cost-to-be-wrong)

| # | Assumption | Why risky | Cheapest test (before ~Nov 13) | Pass bar / kill signal |
|---|---|---|---|---|
| 1 | People want to rehearse real conversations against a persona built from their own meetings, and the persona is good enough to feel real | Core hook; not validated; substitute is a Claude prompt | Concierge: take 8-10 builders' consented own transcripts, run a manual/scripted persona session (prototype script, no UI), watch them use it; ask "would you do this again before the next hard 1:1?" | >=6/10 say the persona felt like the person and ask to repeat; <3 = demote Rehearse, lead with another plugin |
| 2 | Builder-operators will switch capture tool (or add Cora) for plugins, not just notes | Notes parity is crowded; Humla got 9 upvotes | 15-20 problem interviews (founders/EMs from X, HN, YC Slack): ask for last 3 hard conversations and how they prepared; show a 60s clickless Rehearse mock; record unprompted pull ("can I have it?") | >=8 ask for access; fewer than 4 = rethink beachhead |
| 3 | Third parties will author plugins | Zero evidence of demand for a meeting plugin SDK (research gap); Obsidian meeting plugins get 10-900 downloads | Publish plugin-authoring doc + 3 example repos 2 weeks pre-launch; DM 20 plugin-minded devs; count how many commit to build one | >=3 commit and >=1 ships by launch; none = launch as an app with plugin-shaped internals and say so; do not claim ecosystem |
| 4 | "Plugin platform" wording lands better than "meeting notes + roleplay" | PH "Novel" and HN skepticism (Hyprnote "VSCode for Meeting Notes" got 18 pts) | 5-second tests + tagline poll (n=30-50 from target communities) on 3 taglines; Show-HN-style draft shared in 2-3 builder channels | Platform framing wins or ties; if roleplay-only wins, headline Rehearse and put platform below fold |
| 5 | Local-first trust story survives scrutiny given Gemini cloud ASR default on production branch | HN/LocalLLaMA will press; SOC 2/HIPAA exposure; contradicts local default | Write "what leaves your machine" table; red-team: does lockdown test cover Gemini + every plugin path? Show to 3 privacy-minded devs | Zero ways to be surprised; any leak found = fix before any launch asset ships. Cloud ASR must be explicit opt-in, labelled |
| 6 | Plugin security model is credible (permission manifests, out-of-process) | Anarlog's plugin can freeze app; plugins are an exfiltration vector; SOC 2 control gap | Threat-model doc + automated tests: plugin without `network` scope cannot connect; lockdown blocks plugin outbound; token/Host/Origin model unchanged | Tests green in CI; if sandbox slips, ship prompt-only plugins (no arbitrary code) at launch |
| 7 | Unsigned/non-notarized install doesn't kill conversion | Gatekeeper "Open Anyway" flow; Homebrew closed; STIG-managed Macs block | Clean-machine browser-download install by 3 non-technical testers on macOS 15 and 26 | Notarized DMG installs in <3 min without terminal; else slip launch to Dec 1/3 (per PH research) |
| 8 | Hinglish accuracy is a credible proof point | Vendor WERs not comparable | Run existing benchmark tool on 1-2h consented/synthetic Hinglish audio | Clear, reproducible gap vs a baseline; otherwise drop from launch copy |
| 9 | Willingness to pay | Only anchors, no data | Optional "notify me about sync / hosted key" checkbox at install and in README; 5 pricing questions inside interviews | >=5% of activated users opt in or >=3 interviewees name a number >=$8 |
| 10 | Legal/consent: recording and persona-from-voice raises BIPA/consent risk | speakers.py may create voiceprints (unassessed); roleplay persona of a named third party | Code review of speakers.py embeddings; add consent notice template; keep persona text-derived (style from transcript, no voice cloning) in v1; counsel check | No voice cloning of third parties in v1; documented retention/deletion; flag to owner |

Order of execution: 1 and 2 first (week 1, parallel, they decide the headline), 5/6/7 gate launch regardless, 3 and 4 shape messaging.

## 8. Success metrics

Principle: measure installs, activations, plugin usage and authors, not PH rank (peer OSS tools placed #9-#14 on PH while earning 22k+ stars via HN/GitHub). All telemetry must be opt-in or absent; use GitHub/release counts, voluntary surveys and interviews. Never collect meeting content. Anything requiring telemetry must honor enterprise_lockdown.

### Launch targets (realistic for a solo founder; PH top 5 with ~300-450 upvotes is aspirational, similar to Granola's own launches; 0 stars today)
- PH: featured, top 10 (stretch top 5). Show HN: front page hours (>=100 points stretch). 

### 30 days post-launch (through ~Dec 19)
| Metric | Target | Notes |
|---|---|---|
| GitHub stars | 800-1,500 | Meetily/screenpipe took far longer; Cap-style 5k is outlier |
| Notarized DMG downloads | 1,500-3,000 | GitHub release counts |
| Activated (completed first recording -> notes) | 35% of downloads (survey/opt-in proxy) | |
| Rehearse sessions completed by >=1 session/user | 150-300 users; 25%+ do a 2nd session within 7 days | The hook metric |
| Weekly returning users (self-reported / opt-in) | 150+ | |
| Plugin authors (external, merged or listed plugin) | 3-5 | |
| User interviews done post-launch | 20+; 5 reference-able testimonials | |
| Critical privacy/security issues | 0 open | SOC 2 narrative |
| Waitlist/opt-in for paid sync | 150-300 emails | Pricing signal only |

### 90 days (through ~Feb 17, 2027)
| Metric | Target |
|---|---|
| GitHub stars | 3,000-5,000 (below Meetily/screenpipe; fine) |
| Weekly active users (opt-in estimate) | 500-1,000 |
| 4-week retention of activated users | >=25% (PMF-ish bar for a niche tool: >=40% "very disappointed" on Sean Ellis survey of active users) |
| Rehearse as habit | >=30% of WAU run >=1 rehearsal/month; median 2+ |
| External plugins listed | 10-15; >=5 with >=50 installs; plugin API stable (no breaking change for 60 days) |
| Contributors | 15+ |
| Paid pilot | 50-150 Pro waitlist -> 20-40 paying early adopters if Pro is opened (do not open without sync actually working) |
| Inbound from regulated/enterprise | 3-5 design-partner conversations (no promises on BAA/CMMC) |
| Product Hunt relaunch | When plugin directory ships (PH allows relaunch for significant iterations) |

PMF call criteria at day 90 (go/pivot): GO if retention bar met AND Rehearse is repeat behavior AND >=3 external plugins exist. Pivot signals: strong installs but no repeat use (then it is a notetaker clone), or authors but no users (then a toolkit, not a product), or users love only notes (drop platform framing).

## 9. Sequencing and scope guardrails (solo founder + agents, ~4.5 weeks to proposed Nov 17 Show HN / Nov 19 PH)

- Week 1 (Oct 19-23): enroll Apple Developer ($99), start notarization pipeline (every Mach-O signed); run risk tests 1, 2, 5; freeze plugin manifest v0 (id, version, permissions, hooks, entrypoints) and permission scopes.
- Week 2: plugin loader + permission enforcement + lockdown coverage tests; extract coaching module as first plugin to prove the API; Rehearse v0 (text first, voice if time).
- Week 3: 3 first-party plugins (Rehearse; todo export via user rule set; communication/storyteller coach); plugin authoring guide + template repo; closed beta 20-50; recruit 2-3 outside authors; demo video using fictional data.
- Week 4: README rewrite with data-flow table; PH draft + scheduling (>=10 days ahead); benchmark write-up for HN/LocalLLaMA; 5-second tests; FAQ; seed Reddit karma now.
- Cut list if behind (in order): voice rehearsal (keep text), third plugin, external-author claim, Hinglish proof, hosted anything. Never cut: notarization, lockdown tests, honest data-flow table. If notarization or lockdown tests slip, move to Dec 1/3.
- Defer entirely: shared team todos, company knowledge base, roadmap-tracking plugin, marketplace UI, payments, regulated-market claims, iPhone/Tailscale as launch features (mention as roadmap).

## 10. Compliance guardrails baked into this positioning (SOC 2 / HIPAA / DoD)
- Every plugin outbound call passes through one policy chokepoint; `enterprise_lockdown` denies all plugin network, subprocess-with-network and cloud ASR; test in CI; document as a control with evidence.
- Plugins declare scopes (transcript.read, people.read, notes.write, network.<host>, audio.read); default deny; user consent per scope; plugin never receives raw audio unless scoped; signed/reviewed registry later.
- Main API loopback token/Host/Origin model unchanged; plugin UI runs sandboxed (no CSP loosening of the main renderer).
- Rehearse persona text and sessions stay local; no voice cloning of third parties; named-person personas are private to the user; retention/deletion controls and a participant-notice template.
- Gemini: paid tier/Vertex only recommendation; clear opt-in; never default for regulated profiles.
- No real meeting data in any launch asset; seeded fictional data only; consented, synthetic audio for benchmarks.
- No claims of HIPAA/SOC 2/CMMC compliance in any copy while audit is in progress.

## 11. Owner decisions needed
1. Is Rehearse the PH headline (recommended) or does the platform framing lead? Decide after tests 1 and 4 (by Oct 30).
2. Accept scoping Plugin API v0 and no ecosystem claim at launch?
3. Voice rehearsal at launch or text only?
4. License stance: stay MIT (differentiates from screenpipe's commercial license) and hold the commercial line on sync/hosted/registry only?
5. Gemini default posture on the production branch (opt-in label vs default) given launch scrutiny.
6. Launch date: Nov 17/19 contingent on notarization and lockdown tests; fallback Dec 1/3.
