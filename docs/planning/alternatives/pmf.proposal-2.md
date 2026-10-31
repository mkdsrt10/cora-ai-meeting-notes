# Cora: Positioning + PMF Proposal 2 ("Get better at the conversations that matter")

Status: proposal, 2026-10-17. Angle: practice and coaching built from your own real meetings is the hero. The plugin platform is the "how", not the headline.
Evidence base: discovery/research_pmf.json, research_competitors.json, research_producthunt.json. Confidence labels (verified / likely / unverified) are inherited from those files. Nothing here is validated demand; section 9 says how to find out.

---

## 0. TL;DR

- **Hero:** Cora records your meetings on your Mac, then lets you rehearse the next hard conversation with an AI playing the other person, built from what that person actually said to you last time. It also coaches how you came across.
- **Beachhead:** engineering managers, founders and PMs on Mac who run many 1:1s and feedback conversations. Secondary (post-launch): Hinglish professionals, as an accuracy proof point rather than a segment to sell to.
- **Why this angle:** it is the only whitespace the research found that holds up. Roleplay tools use synthetic scenarios (Yoodli, Second Nature, Hyperbound, Peopling, Mindtools). Gong AI Trainer does build roleplay from real calls, but only for enterprise sales reps. Nobody was found doing private, individual, non-sales practice from your own meetings (research caveat: "likely", from one search sweep).
- **What we must not claim:** "no extensible meeting tool exists" (false: screenpipe, Anarlog, Fireflies AI Skills, Granola Recipes), or "local-first open source" as a differentiator on its own (Meetily 31.8k stars, Anarlog 9.5k; Humla launched on PH as exactly that and got 9 upvotes).
- **Biggest risks:** (1) practice-from-real-meetings is a "nice demo" people never repeat; (2) good roleplay needs a strong LLM, and the local 4B Qwen is likely too weak, which collides with the local-first promise; (3) the plugin platform is invisible to the launch audience unless one plugin is spectacular; (4) unsigned build kills the funnel.
- **Business model:** free OSS core, BYO keys, no hosted anything at launch. Optional Pro (~$8-12/mo) later for convenience layers (managed model access, sync, signed plugin registry), never for access to your own data.
- **90-day bar:** 100+ weekly active users who ran at least 2 rehearsals, 1,000+ stars, 5+ external plugin authors. The 30-day bar is smaller and mostly about learning (section 10).

---

## 1. Positioning decision

### 1.1 The framing choice

| Option | Verdict |
|---|---|
| "Local open-source meeting notes" | Rejected. Crowded; fails PH "Novel" (Humla #144). |
| "Plugin platform for meetings" | Rejected as headline. Screenpipe owns "pipes store"; MCP makes extensibility table stakes; the claim invites a PH/HN takedown. Keep as the "how". |
| "Meeting notes with better accuracy" | Rejected as headline. Vendors' benchmarks are unverified; our own is a proof point, not a story. |
| **"Get better at the conversations that matter, practiced on your real meetings"** | **Chosen.** Concrete, demoable in 3 seconds, novel versus the field, and it gives the platform a reason to exist. |

### 1.2 Positioning statement

For managers, founders and PMs who run a lot of high-stakes conversations (1:1s, feedback, negotiations, board and customer talks), Cora is a local-first Mac meeting recorder that turns your own past meetings into practice: rehearse the next hard conversation against an AI that plays the other person from what they actually said, and get coaching on how you came across. Unlike generic roleplay tools (Yoodli, Second Nature), your practice is grounded in your real conversations. Unlike cloud notetakers (Otter, Fireflies, Granola), no bot joins your call and your recordings stay on your Mac by default. Because it is open source with a plugin system, you can change the coach, the roleplay and the notes without asking anyone's permission.

### 1.3 Tagline options (all at or under 60 chars; PH rule: clear, no hype)

| # | Tagline | Chars |
|---|---|---|
| 1 | Rehearse your next hard conversation, from real meetings | 56 |
| 2 | Practice the conversation before you have it | 44 |
| 3 | Your meetings, turned into practice | 35 |
| 4 | Meeting notes that help you get better at meetings | 50 |
| 5 | Open-source meeting coach that runs on your Mac | 47 |

Recommendation: **#1 for PH and Show HN title**, #2 as the website H1. Test #1, #2 and #4 on 10 people each (section 9, test T3). Char counts are approximate; verify in the PH form.

### 1.4 The one-sentence pitch

"Cora records your meetings on your Mac, then lets you rehearse your next 1:1 with an AI that plays the other person based on what they actually said last time."

Spoken variant (10 seconds): "You know that feedback talk you keep putting off? Cora already has the last three conversations with that person. Practice it first."

### 1.5 Proof points (what must be true and shown by launch)

Only claim what the build demonstrates. Each is a launch asset, built from fictional data (no real meeting data in any asset; use python/tools seed_demo_data.py content).

1. **Grounded rehearsal.** Demo: pick "Priya (fictional)", the roleplay opens with her actual objection patterns from the three previous synthetic meetings; replay shows the exact lines it drew from. Provenance links back to transcript segments are the proof, not "trust the AI".
2. **Delivery coaching on your own speech.** Pace, fillers, talk-to-listen ratio, a before/after across two rehearsals. (Existing plugins/coaching computes local numpy delivery metrics; Read.ai Speaker Coach shows this metric set is table stakes, not the differentiator.)
3. **No bot, local by default, auditable.** A "what leaves your machine" table in the README: nothing by default; opt-in Gemini names exactly which audio/text goes out; enterprise_lockdown blocks all outbound including plugins.
4. **Reproducible accuracy.** Publish the model-benchmark tool results (commit 6424d28) on fictional or consented synthetic Hinglish and English audio. Honest caveat in the post: vendor WERs are not comparable, ours is on our data.
5. **Anyone can write the next coach.** A 10-minute plugin quickstart; 3 first-party plugins as worked examples (roleplay, communication/storytelling coach, todo export by rule set).

---

## 2. Ideal customer profile

### 2.1 Primary persona: "Maya, the first-time-to-fifth-year engineering manager / startup founder"

- Role: EM, head of product, or technical founder; Mac daily driver; 6-15 recurring 1:1s a week plus ad-hoc hard conversations (performance, scope cuts, compensation, a co-founder disagreement).
- Already tried: Granola or Otter for notes. Notes are fine; they do not make her better at the conversation. She asks Claude/ChatGPT to "help me prepare" but has to re-type the context every time.
- Technical enough to paste an API key, run `brew`/open a DMG, read a README, and mildly care where audio goes.
- Willingness to pay: $8-15/mo is the anchor (Granola Business $14, Meetily Pro $10, Yoodli Pro $8). For a tool she keeps open every day, plausible; for a practice-only tool, uncertain (risk R1).

### 2.2 Jobs to be done

1. When I have a hard conversation coming up (tomorrow's performance talk), help me walk in prepared so I stop avoiding it or fumbling it.
2. When a conversation went badly, help me see what I did (interrupted, hedged, filled silence) without a manager having to watch.
3. When I am preparing for a recurring person, remind me what they said last time, what I promised, and what they pushed back on.
4. Keep my meeting content mine: no bot in the room, no vendor training on it, nothing public.
5. Let me bend the tool to my own workflow (my coaching framework, my todo app) without waiting for a vendor roadmap.

### 2.3 Triggers (moments she goes looking)

- Calendar shows a performance review, layoff or reorg conversation, or a board prep within 48 hours.
- A hard 1:1 just went poorly.
- Promotion to first management role; new job.
- News of cloud notetaker lawsuits (Otter, Fireflies, Granola allegations; tl;dv exposure story got 633 HN points) or a company/university blocking AI bots.
- Seeing a coaching recipe (e.g. Granola's) and wanting to own and edit it.

### 2.4 Where they hang out (and which channels the research supports)

| Channel | Use | Constraint from research |
|---|---|---|
| Hacker News (Show HN, GitHub repo link) | Main growth engine for OSS dev tools | Plain title, engage 4-6 hrs, no vote solicitation |
| GitHub trending | Rewards star velocity in ~48 hrs | Concentrate launch traffic |
| Product Hunt | Credibility badge, indexed listing | Editorial "Novel / High Craft"; expect top 5-10 at best, 200-450 upvotes |
| r/LocalLLaMA | Lead with local MLX pipeline + benchmark write-up | ~10% self-promo cap, disclose affiliation, karma needed |
| r/macapps | App Pile thread with [OS] prefix, PCP format | Repo has 0 stars and is under 1 month old, so Tier 1 is closed |
| X / LinkedIn | Founder and EM storytelling | Real identity, post demo clip |
| EM/founder communities (Lenny's, Rands Leadership Slack, YC-adjacent groups, Indian founder groups) | Qualitative interviews first, not announcements | Check each community's rules before posting |
| Toastmasters-type circles | Storytelling coach plugin audience (~265k members, "likely") | Secondary; lower technical fit |

### 2.5 Secondary: Hinglish professionals (proof, not beachhead)

Founders, PMs, consultants in India and the diaspora. Pain is demonstrable (Otter lacks Hindi; Zoom drops code-switched words) but evidence is anecdotal/vendor-sourced and willingness to pay is low (ChatGPT Go free in India for a year). The founder fits this community. Treat it as: (a) the accuracy story that gets HN/LocalLLaMA attention via a reproducible benchmark, and (b) a free-to-try audience that supplies plugin authors and word of mouth. Do not build segment-specific features before launch.

### 2.6 Explicitly not the ICP (now)

- **Regulated professionals** (lawyers, therapists, DoD contractors, HIPAA entities). Strongest pain, but selling needs BAAs, attestations, EHR integrations; Anarlog and Meetily already target them; and cloud-ASR opt-in contradicts a clean local-only claim. Posture: keep enterprise_lockdown as a trust pillar, make **no HIPAA, CMMC or SOC 2 claims** in launch assets (SOC 2 Type 2 is in progress, not complete), and say plainly that Cora is not a certified scribe.
- **Sales reps / revenue teams.** Gong ($1.3-1.6k/user/yr est.) and Hyperbound/Second Nature own it, and Gong AI Trainer already does real-call roleplay. Not a fight for a solo founder.
- **Teams needing shared todos / company KB.** Needs multi-user sync, which pulls against local-first; Fellow, Notion Custom Agents, Granola Spaces compete. Later.

---

## 3. Value proposition (by layer)

1. **Outcome (hero):** walk into the hard conversation prepared; learn from the last one.
2. **Mechanism:** your own recordings become structured objects (speakers, people, action items, delivery metrics) that practice and coaching plugins can use, on your machine, with your model.
3. **Trust:** no bot, local default, explicit and auditable outbound paths, lockdown that blocks everything including plugins.
4. **Openness:** MIT-style OSS, plugin SDK, notes templates as files. If you disagree with the coach, you fork the coach.

What Cora is not: a Granola replacement on polish at launch, an enterprise compliance product, or a hosted service.

---

## 4. Why now

1. **Consent and privacy backlash is concrete.** Class actions against Otter (Aug 2025, verified), Fireflies BIPA (Dec 2025, likely), Granola (Jul 2026, likely; allegations only, dockets unchecked); universities blocking bots; 65% of notetaker-exposed workers not consistently asked (law-firm-sponsored survey, so treat as biased). Bot-free, local capture has already won the mainstream argument, which lets us skip persuading and start from "what can you do with it".
2. **LLM roleplay is finally cheap and good.** Voice/chat roleplay is a funded category (Yoodli $40M Series B, Second Nature $22M, Hyperbound ~$17.5M, several 2026 manager roleplay launches). Interest is proven; the "from your real meetings" grounding is the unclaimed piece for individuals.
3. **MCP and agent skills made extensibility normal, then commoditized it.** Users already ask Claude to "roleplay my last 1:1" via a vendor MCP. Cora's counter: a runtime with live hooks, local execution, a UI surface, write access, and cross-meeting state, and plugins exposed back out as MCP tools so Cora is the meeting runtime, not another silo.
4. **Incumbents are drifting up-market and cloud-ward.** Granola is a "context layer" at $1.5B and Enterprise pricing; Wispr ($2B) is entering meeting notes. A gap opens for an open, individual-first product, but the window is short.
5. **Local models and Apple silicon are good enough** for capture, ASR and (borderline) notes. Roleplay quality is the open question (R2).

---

## 5. Competitive framing (honest)

Principle: never claim a category we do not own; name competitors first in our own materials where the audience will find them anyway (HN will).

| Competitor | What they really have | Where we honestly differ | Where they win |
|---|---|---|---|
| **Screenpipe** (YC S26, ~22k stars, source-available commercial license) | Pipes: scheduled agents as markdown + YAML permissions, store, meeting-summary pipe, screen+audio capture | Meeting-structured data (speakers, people, action items); practice and coaching as first-class; OSI-style license vs commercial license (confirm our license text before claiming); no account | Distribution, store exists, broader capture, agent runtime |
| **Anarlog / Hyprnote** (YC S25, ~9.5k stars, MIT) | Early plugin SDK (renderer-injected JS, plugin.json), targets law/finance/healthcare | Plugins out-of-process with scoped permissions (their own docs say a bad plugin can freeze the app); practice-from-meetings focus | Brand, PH #2 (457 upvotes) precedent, regulated positioning |
| **Granola** (closed, $1.5B) | Recipes (static shareable prompts), templates, MCP, read API on $14 Business, huge polish; a CEO-coaching recipe | Open source; writeable plugins with actions and UI; local by default; interactive rehearsal, not a one-shot prompt | Polish, brand, distribution, enterprise features |
| **Fireflies AI Skills** (200+ prompt apps, scheduled runs, push to CRM/Jira) | Closest to an app store among notetakers; team sharing | Local, open, individual-first, not credit-billed; code-level plugins | Integrations, scale, team features |
| **Meetily** (~31.8k stars, MIT, Pro $10) | Local open-source notes; API/webhooks/MCP paywalled in Pro | Free plugin surface; practice/coaching story | Stars, mindshare, simplicity |
| **Yoodli / Second Nature / Hyperbound / Peopling** | Funded roleplay and coaching; Yoodli $8-20/mo, can critique uploaded recordings | Your own meetings as the scenario source; local; open | Scenario libraries, voice quality, scoring maturity, enterprise sales |
| **Gong AI Trainer** | Real-call roleplay | Individuals, non-sales, local, free | Enterprise sales; we should not compete there |
| **Read.ai Speaker Coach** | Cross-meeting delivery metrics, MCP | Interactive rehearsal vs passive metrics; local; open | 5M+ MAU, bots in cloud meetings |
| **Claude/ChatGPT + a notetaker's MCP** | "Roleplay my last 1:1" works today | Persistent people-memory, provenance to transcript segments, UI built for rehearsal, runs locally with no data to a notetaker vendor | Zero-install for users already in those apps. This is the most realistic substitute, and test T1 should check it directly |

One-line truth for our README: "Screenpipe, Anarlog, Granola and Fireflies all have extension points. We are the open, local-first one built around practicing your own conversations."

---

## 6. Pricing and business model

- **Launch (T0):** everything free and open. BYO keys for any cloud model (Gemini paid tier or Vertex; the free tier may train on data, so default guidance and docs say paid only, and the UI warns on a key it cannot classify). No accounts, no telemetry by default.
- **Possible later Pro ($8-12/mo, annual discount),** only after evidence of habitual use: managed model access (no keys, zero-retention provider terms), encrypted multi-device sync, curated/signed plugin registry with review, priority builds. Anchors: Meetily Pro $10, Granola Business $14, Yoodli Pro $8.
- **Principle: never gate a user's access to their own data or the plugin API.** Meetily and Granola paywall API/MCP, which is a wedge for us.
- **Teams/Enterprise (explicitly later, maybe never):** shared plugin registry, SSO, audit export. Only if a design partner pays for it and SOC 2 Type 2 is actually complete.
- **Plugin marketplace revenue share:** not before there are 20+ third-party plugins. screenpipe's paid-pipe status is unverified; do not copy it on speculation.
- **Honest note:** at ~$10/mo, 100 paying users is $1k/mo. This is a credibility and learning phase, not a revenue phase. If revenue matters early, the only plausible route is design-partner pilots with EMs at small companies, not consumer pricing.

---

## 7. What the hero experience must be (scope guard for the 4-5 week plan)

This proposal does not specify the SDK (see plugin-sdk proposals) but it sets the product bar that the platform work must serve.

**Rehearse MVP (text-first, voice optional):**
1. Pick a person (from people data) and a goal ("give feedback about missed deadlines").
2. Cora builds a persona brief from that person's prior transcript turns: their phrasing, objections, topics they push on, commitments each side made. Show the source lines.
3. Chat roleplay with the AI as that person; a coach side-panel notes hedging, over-explaining, missed openings.
4. End with a short debrief against the user's own goal, saved as a note on the person.
5. Run again; show a before/after on 2-3 metrics.

**Guardrails that are also trust features:**
- Persona built only from transcripts the user recorded; stored locally; deleting the person deletes the persona.
- **No voice cloning and no voiceprint creation of other participants.** BIPA exposure (Fireflies suit is about exactly this) plus ethics. Voice roleplay, if shipped, uses a generic TTS voice. Audit speakers.py for embeddings before launch (research flagged this as unassessed).
- Coaching metrics computed on the user's own speech only.
- Label clearly: "AI simulation based on your notes, not the real person."
- Model: this is the first feature where a local 4B model likely disappoints. Plan: default to a local model with an honest quality warning, one-click opt-in to a BYO-key cloud model, shown with the exact outbound payload; enterprise_lockdown disables the cloud option and the plugin shows "local-only mode".
- Zero real meeting data in demos; use fictional seed data only.

**Cut line if time runs short:** ship Rehearse (text) + one coach plugin + templates; drop voice, drop todo-export, drop second-language benchmark post.

---

## 8. Riskiest assumptions and the cheapest tests

Ordered by how fatal they are. Each test is runnable in under a week by one person, mostly before a line of new code.

| # | Assumption | Why it could be false | Cheapest test | Pass / kill threshold | Cost |
|---|---|---|---|---|---|
| R1 | Managers and founders want to practice conversations, repeatedly, not just once | Practice apps have notoriously low retention; Yoodli's free tier is capped at 5 lifetime roleplays, suggesting churn pressure | **T1: Wizard-of-Oz.** Recruit 10 EMs/founders. For each, take (with consent, their own) notes from one real past conversation, hand-build the persona prompt in Claude, run a 15-min rehearsal over screen share. Offer a second session a week later unprompted. | 6 of 10 say they would use it again before the next hard conversation AND 4 of 10 book/do the second session; fewer than 3 = hero is wrong, fall back to "coach on past meetings" | ~15 hrs, $0 |
| R2 | A local or BYO-key model plays "the other person" well enough to feel real | 4B local model may be flat; cloud model conflicts with local-first promise | **T2: Quality bake-off.** On fictional transcripts, have 5 people blind-rate 3 outputs: local Qwen, Gemini paid, Claude/GPT baseline, on realism and usefulness (1-5). | Median realism of local at least 3.5 and cloud at least 4; if local under 3, ship cloud opt-in as the default rehearsal path with clear disclosure and mark lockdown mode as "rehearsal disabled" | 1 day, a few dollars |
| R3 | Grounding in real meetings matters to users versus a good generic scenario | If a generic "difficult feedback scenario" feels as good, our wedge is imaginary | **T1 variant:** within T1, half get the grounded persona, half a generic one; ask which felt more useful (blind order) | Grounded preferred by at least 65% of participants | included in T1 |
| R4 | The tagline and demo land with the PH/HN audience | "Novel" bar, cold start with 0 stars, Hyprnote's first Show HNs got 18 and 4 points | **T3: Message test.** 10-person tagline and 30s demo clip test (taglines #1, #2, #4); post the demo clip on X/LinkedIn and ask a few HN regulars privately for gut reaction (never ask for votes) | At least 7 of 10 can restate it correctly after 1 viewing; 3+ unprompted "I want to try it"; if "just another notes app" dominates, rewrite hero before spending on assets | 2 days |
| R5 | There is real demand to write plugins | Research found no primary evidence; Obsidian meeting plugins get 10-900 downloads | **T4: Author interest.** Publish the plugin quickstart draft + 2 example plugins in the repo now; DM 20 plugin-minded developers (OpenWhispr, Obsidian, MCP communities); ask them to build a 50-line plugin in a week | 3+ finish a toy plugin, 1+ proposes their own idea. If 0, reposition plugins as "customization", stop investing in marketplace/registry work | 3 days |
| R6 | Users will trust a local recorder that is unsigned or newly built | Gatekeeper "Open Anyway" flow kills installs; Homebrew cask closed to unsigned; STIG-managed Macs block it | **T5: Install funnel test.** Hand the signed/notarized DMG (once built) to 10 users on clean macOS 15 and 26 via browser download; time to first recording | 9 of 10 get to a first recording in under 10 min unaided. This is a blocker, not a metric: start Apple Developer enrollment this week | Apple $99/yr; days of signing work |
| R7 | "Local by default, optional cloud" is believed by HN | Gemini path will be probed; any ambiguity is fatal | **T6: Red-team the README.** Ask 3 privacy-minded reviewers to find any outbound path not in the data-flow table; run a network-capture session (default settings and with lockdown on) and publish the result | Zero unexplained connections; lockdown shows zero outbound including plugins | 1-2 days |
| R8 | Hinglish accuracy is a differentiator users care about | Anecdotal pain; small PH audience | **T7: Benchmark first, claims later.** Run the benchmark tool on 1 hr of consented synthetic or volunteer Hinglish audio against Gemini, Chirp 3, Sarvam, local Whisper/Tara | Gemini or Sarvam beats local by at least 10 WER points absolute on our set; else drop the Hinglish headline entirely | 2 days + API costs |
| R9 | Ordinary notes quality and polish are sufficient that practice can be the hero | If notes feel worse than Granola, users never reach the practice feature | **T8: Notes parity check.** Show 5 users blind-labeled notes from Cora (templates, cloud note path) vs Granola for the same fictional meeting | At least 40% prefer or call it equal | 1 day |
| R10 | Wispr/Granola do not ship "practice from your meetings" before us | Cheap for them to ship once someone shows it | No cheap test; mitigate by speed and openness. Re-check the competitor landscape weekly until launch | n/a | 30 min/wk |

Test ordering this week: T1 and T5 start immediately (both gate everything), T2 and T7 in parallel, T3 after a 30-second demo cut exists, T4 once quickstart draft exists.

**Kill/pivot rules (decide now so you do not rationalize later):**
- T1 fails: pivot the hero to "post-meeting coaching and prep brief for the next meeting with this person" (lower-effort, less interactive), keep roleplay as a plugin.
- T2 local fails and users reject cloud: limit the hero demo to cloud-opt-in and be upfront; do not claim local roleplay.
- T4 fails: say "customizable" instead of "platform" in all copy.

---

## 9. Compliance and trust constraints on messaging

- Launch copy may say: local by default, no bot, open source, enterprise_lockdown blocks all outbound traffic including plugins (verify with T6 before saying it).
- Launch copy may not say: HIPAA compliant, HIPAA-ready, DoD/CMMC ready, SOC 2 certified (audit in progress), "your data never leaves your Mac" without the opt-in qualifier, or "private" about any cloud model path.
- The four lawsuit themes become four defaults, documented in the README: participant-notice tooling (consent message template), never train on user data, no public share links by default, documented retention/delete and voiceprint behavior (speakers.py audit).
- Plugins: permission manifest per plugin (transcript read, people read, write-back, network), policy hook so lockdown blocks plugin egress, and never let a plugin read audio or transcripts without an explicit per-plugin grant. Do not let any plugin or roleplay feature weaken the loopback token/Host/Origin model of the main API.
- Roleplay and persona data are derived from other people's speech; treat as sensitive, keep local, include delete cascade, and flag in the privacy doc that users are responsible for recording consent under their local law.
- Gemini: document paid tier or Vertex only; free tier may train on data with human review (likely, from Oct 2024 commentary; re-read current terms before publishing).

---

## 10. Success metrics

Measure only what can be measured without violating local-first: no default telemetry. Use GitHub, release downloads, opt-in anonymous usage ping (off by default, documented, disabled by lockdown), and direct outreach with a 10-person weekly user call.

### 10.1 Pre-launch (before Nov 17 Show HN, per the PH plan)

- Tests T1, T2, T5, T6 complete; at least 20-50 closed beta users on the notarized build; at least 5 usable testimonials from real people (not paid, not coached).
- 3 first-party plugins shipped; at least 2 outside developers have built a toy plugin.
- 30-60s demo video and README ready, with fictional data only.

### 10.2 First 30 days after launch

| Metric | Target | Notes |
|---|---|---|
| GitHub stars | 800-1,500 | Meetily/screenpipe took long; stars measure reach, not PMF |
| Notarized DMG downloads | 1,500+ | |
| Activation: first recording completed | 40% of downloads | Install-funnel health |
| Aha: at least 1 rehearsal run | 15% of activated users | The hero is being tried |
| Retention proxy: at least 2 rehearsals on different days within 14 days | 25% of rehearsers | Early R1 signal |
| PH | Top 10 with 200-450 upvotes (benchmarks: Granola launches 5-8th, Hyprnote #2, screenpipe #14/#9) | Do not optimize for rank. No vote solicitation |
| External plugin authors (published repo) | 3+ | R5 |
| User interviews done | 20+ | |
| Qualitative PMF signal (Sean Ellis question to active users) | 30%+ "very disappointed" if Cora went away (small n; interpret loosely) | |

### 10.3 90 days

| Metric | Target |
|---|---|
| Weekly active users (opt-in, or estimated via release/update checks) | 100-300 |
| Users with at least 2 rehearsals in a given week | 100+ (the headline success number) |
| 4-week retention of activated users | 25%+ |
| Stars | 2,500+ |
| External plugins | 10+, with at least 3 used by someone other than the author |
| Pro waitlist signups (if tested) | 100+, with at least 5% willing to pay $10 in a fake-door test |
| Design-partner conversations about teams | 3 |
| Kill/continue decision | If rehearsal repeat usage is under 10% and plugin authors under 3, redefine hero before month 4 |

Anti-metrics (watch, do not chase): rank, raw downloads without activation, plugin count from first-party only.

---

## 11. Dependencies on other workstreams

- **Plugin SDK:** Rehearse and the coach need typed access to people, transcript segments (with provenance), notes write-back, and a UI surface. Cora today has a hard-wired single coaching plugin, no manifest, no per-plugin scopes and an MCP server not governed by policy.py lockdown (from code_plugins.json). Positioning depends on fixing at least lockdown coverage for plugins before launch.
- **Notes templates:** table stakes (Granola, Fireflies, Meetily, Otter all have them). Ship, but never lead with them. Also fix the gap that the auto pipeline ignores notes_llm_provider, since "accurate and good notes" gates R9.
- **Transcription (Gemini):** keep as explicit opt-in with a data-flow label, and benchmark before claiming accuracy.
- **Launch/signing:** notarization is the single biggest funnel blocker; start now.
- **Phone capture / always-on server:** out of scope for launch messaging. Mention later as "send a voice note from your phone to your own Mac" once the loopback auth model is preserved in the remote design.

---

## 12. Decisions needed from the owner

1. Approve the hero: practice/coaching from real meetings (versus "extensible platform" or "Hinglish accuracy").
2. Approve the no-voice-cloning, no-other-participant-voiceprint rule for roleplay and coaching.
3. Will you accept shipping rehearsal with an explicit cloud-model opt-in if local quality fails T2, given the local-first story?
4. License: confirm what license the public repo carries before any "open source" claim in copy (the research assumed MIT-style; verify in the repo).
5. Willing to run 10 wizard-of-oz sessions this week (T1) and spend $99 plus signing effort immediately (T5)?
6. Do you want Hinglish as a launch proof post, or deferred until T7 shows a real gap?
7. Pro pricing: park until after day 90, or run a fake-door test earlier?

---

## 13. Appendix: honest evidence gaps

- No primary evidence that people want to rehearse from their own meetings; the whitespace is inferred from a competitor scan ("likely"), so T1 matters more than any other work.
- No evidence of demand for a meeting plugin SDK specifically.
- Litigation claims are allegations from secondary sources; dockets unchecked. Cite as "alleged" in any public material, or omit.
- Several statistics are unverified or sponsor-biased (Calendly 58%, the law-firm survey, Gallup 3x, Fellow 44%). Do not put them in launch assets.
- Market-size figures have inconsistent scope; do not use them.
- Competitor details (Screenpipe paid-pipe status, Yoodli live meeting integration, Granola Discover curation) are unverified; re-check before publishing a comparison table.
- Whether speakers.py creates voiceprints under BIPA is unassessed; needs code review and legal input before launch.
