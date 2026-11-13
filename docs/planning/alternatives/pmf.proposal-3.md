# Cora: positioning + PMF proposal 3 — "Hinglish-first accuracy, private by default, benchmark as proof"

Status: proposal, 2026-10-17. Inputs: research_pmf.json, research_competitors.json, research_producthunt.json, transcription-gemini.draft.md (G1/G2 gates), repo facts (tools/asr_bench.py, pipeline/romanize.py, cloud_asr.py, policy.enterprise_lockdown). No repo files modified. Evidence labels follow the research files: V = verified, L = likely, U = unverified/anecdotal.

---

## 0. The angle in one paragraph

Open-source "local meeting notes" is taken (Meetily 31.8k stars, Anarlog 9.5k; Humla got 9 PH upvotes, not featured). "Plugin platform" is a roadmap, not a launch-day product (plugin_registry.py is a single hard-wired loader; Screenpipe and Anarlog already have plugin stories). What Cora has that none of them do is a **Hinglish-tuned local pipeline** (Tara via mlx, Romanized-Hinglish output, vocabulary hints, existing benchmark tool) and an **owner who is the user**. So: lead with a narrow, falsifiable, demo-able claim ("it transcribes the way Indians actually talk, and the audio stays on your Mac unless you opt in"), prove it with a reproducible public benchmark, and let global builders arrive second via the benchmark write-up, the privacy architecture and the plugin story. The roleplay plugin is the "second act" demo, not the headline.

This angle only works if two things are true, both testable in week 1 (section 9): (1) mainstream tools measurably fail on code-switched meeting audio; (2) Cora's *local* path is competitive on it. If (2) fails and only cloud Gemini wins, the pitch changes to branch B in section 5. Do not hide this fork.

---

## 1. ICP

### Primary persona: "Aarav, the Indian builder-operator"
- Founder, CTO, engineering manager, PM or independent consultant at an India-based startup or services firm (or diaspora in US/UK/SG/UAE working with Indian teams). Mac user. 10-25 meetings a week; most are internal or client calls where Hindi and English alternate every sentence.
- Technical enough to install from a notarized DMG, paste an API key, and read a README. Already uses ChatGPT/Claude daily.
- Currently: Otter/Fireflies/Meet notes with Hindi mangled or dropped, or typing notes by hand, or pasting recordings into ChatGPT/Gemini manually.

### Jobs to be done
1. "After a call, give me notes and action items I do not have to correct, even when we switch languages mid-sentence." (accuracy)
2. "Let me record client and team calls without sending them to a vendor's servers or putting a bot in the call." (private by default, bot-free)
3. "Let me search my meetings and hand them to my own AI (MCP) without retyping names, terms and Hindi words." (own the data; vocabulary and people memory already in Cora)
4. Second-order: "Help me get better at the hard 1:1 / client conversation" (roleplay and coaching plugins, built from my own meetings).

### Triggers (when someone switches)
- A transcript that turns "matlab thoda sa delay hoga" into garbage in front of a client or boss.
- A client or enterprise customer asking "where does the recording go?" (security questionnaire, DPDP-style questions; unverified in detail, validate in interviews).
- A recent notetaker-privacy story (tl;dv 180k open meetings reached 633 HN points, Aug 2026; Otter/Fireflies/Granola suits, all allegations, V/L).
- New Mac, new job, or a tool's free tier or pricing change.

### Where they hang out (and what is allowed there)
- X/Twitter and LinkedIn "build in public" India tech circles; Peerlist; r/developersIndia, r/indianstartups, Indie Hackers; Indian founder WhatsApp/Slack groups (SaaSBoomi-type communities); YC/startup-school alumni groups.
- Global overlap: Hacker News, GitHub trending, r/LocalLLaMA (disclose affiliation, under ~10% self-promo, lead with the benchmark), r/macapps (tier rules; Cora currently misses Tier 1), Product Hunt.
- Exact community sizes and rules for the Indian channels were not researched. Treat as hypotheses; the interview step below produces the real list.

### Secondary personas (do not build for them yet)
- **Global builders / local-AI crowd**: arrive via HN/PH on the benchmark and the privacy architecture. They care about plugins and MCP. Same product, different story (section 6).
- **Regulated professionals** (lawyers, therapists, DoD contractors, HIPAA entities): strongest pain evidence (NYC Bar 2025-6, DFARS/CMMC, APA consent), but needs BAAs, attestations, local-only guarantees and a SOC 2 report first, and Meetily/Anarlog already target it. Position `enterprise_lockdown` as a trust signal, make **no HIPAA/CMMC/FedRAMP claim**, and defer selling.

### Explicit non-ICP for the next 90 days
Enterprise IT buyers; sales-call coaching (Gong territory); teams needing shared todos (needs sync backend); Windows/Linux users; people who want a meeting bot.

---

## 2. Value proposition and proof points

**Value proposition**: Meeting notes that understand code-switched Indian speech, from a recorder that keeps audio on your Mac by default and is open source, so every claim can be checked.

| Claim (ship only if proof exists) | Proof asset | Status today |
|---|---|---|
| "Handles Hinglish" | Public benchmark: Cora local (Tara) vs Cora+Gemini vs Chirp 3 vs Sarvam Saaras (codemix) vs Whisper large-v3 vs 3-4 mainstream notetakers, same clips, both strict and Hinglish-folded WER, with confidence intervals. tools/asr_bench.py already supports mlx-whisper, hf-whisper, indic-conformer, gemini, cmd:. | Tool exists; **no results yet**; vendor WER figures (27-70%) are not comparable (U) |
| "Private by default" | One-page data-flow table ("what leaves your machine, per setting"); lockdown socket-blocking test in CI (planned in transcription-gemini T-G9); no training, no public share links, no voiceprint upload | Gemini engine labelled honestly since e80bf9e; lockdown test planned, not yet shipped |
| "Bot-free" | Table-stakes (Granola won on this) — mention, don't headline | True |
| "Open source, inspectable" | Repo, MIT-style license as in repo, reproducible bench | 0 stars; notarization missing (blocker) |
| "Gets better for you" | Vocabulary + people memory + correctable transcript feeding hint priors (exists: vocabulary.py, curated vocab) | Exists; before/after demo needed |
| "Rehearse your next hard conversation from your last real one" | Roleplay plugin demo on fictional data | Not built; second-act demo only |

Rules for proof:
- No real meeting audio or transcripts in any public asset (org constraint and customer confidentiality). Benchmark audio must be (a) public-licensed Hindi/Indian-English/code-switched sets (candidate families to check licences on: FLEURS-hi, IndicVoices, Kathbath, Svarah; not verified here) plus (b) **consented, scripted-then-improvised fictional meetings recorded by 4-6 volunteers** (cost: a few days; also gives gold references). Publish audio and references under a clear licence, with signed consent.
- Report results even if Cora's local path loses. A lost benchmark published honestly is still the credibility asset on HN; a cherry-picked one is a launch-day thread killer.
- Say "on our test set of N minutes, M speakers" every time. No bare "95% accurate".

---

## 3. Why now

- Bot-free capture has won (Granola $1.5B, Mar 2026, V) and the backlash is concrete: three class actions (Otter, Fireflies BIPA, Granola; allegations, V/L), universities blocking bots (V), a 65% consent-gap survey (law-firm sponsored, bias possible), tl;dv exposure on HN.
- Large multilingual models and Indic-specific engines (Gemini, Chirp 3 hi-IN GA, Sarvam codemix at ₹30/hr; L) finally make code-switching tractable, but nobody has published a meeting-level comparison on real code-switched speech (research: no independent benchmark found).
- Local ASR on Apple Silicon is good enough to be the default, which makes "private AND accurate" a real option rather than a trade.
- MCP is everywhere (parity, not a selling point), so the durable layer is what Cora does with structured meeting data on your machine.
- Window is closing: Wispr ($280M) is entering meeting notes; Granola moves up to enterprise context.

---

## 4. Competitor framing (honest)

Principle: never claim "nobody else does X" in launch copy. Say what Cora is best at and link the evidence.

| Competitor | What they really have | Where Cora does not win | Where Cora's angle holds |
|---|---|---|---|
| Granola | Bot-free, templates, Recipes (shareable prompts), MCP/API on Business, $1.5B, sued Jul 2026 (L) | Polish, distribution, integrations | Hinglish (unverified for Granola; test), open source, local engine; no per-user training opt-out dance |
| Otter / Fireflies | Fireflies "AI Skills" (200+ apps, scheduled multi-meeting runs, pushes to CRMs); Otter MCP, templates | Breadth, team features, integrations | Hindi: Otter reportedly unsupported (L, secondary sources); Fireflies and tl;dv Hindi quality **untested, do not claim** |
| Screenpipe (22k stars, YC S26) | Real plugin platform ("pipes", store), meeting capture | Plugin ecosystem, star count, commercial licence not OSI | Meeting-specific structure and accuracy; Cora is not an always-on screen recorder |
| Anarlog/Hyprnote (9.5k, YC S25, MIT) | Local meeting notes, early plugin SDK, aimed at law/finance/health | Brand, YC network, regulated positioning | Hinglish tuning, benchmark, Mac Studio/phone-capture roadmap |
| Meetily (31.8k, MIT, Pro $10) | Largest OSS local notes; extensibility paywalled | Stars, traction | Accuracy on Indian speech; extensibility free |
| Zoom / Meet / Teams native | Free, built-in; Zoom Hindi drops reported in one forum thread (U) | Zero-install | Works across all apps, local, code-switch proof |
| Sarvam / Chirp 3 / Gemini directly | Best Indic engines | Not a product for meetings | Cora is the meeting workflow around them, engine-agnostic; credit them in the benchmark |
| Yoodli, Gong AI Trainer, Peopling | Funded roleplay; Gong builds from real calls (enterprise sales only) | Funding, content | Individual, private, grounded in your own non-sales meetings (second act) |

Message discipline: "Cora is not the only extensible meeting tool" (it is not extensible yet at launch). "Cora is the one that was built and measured on how Indians actually speak" is the claim, and it is only allowed after the bench says so.

---

## 5. Positioning statement and copy

**Positioning statement**: For Indian and India-working founders, PMs and engineering managers who live on Macs and whose meetings switch between Hindi and English every sentence, Cora is the open-source meeting recorder that transcribes Hinglish accurately and keeps your audio on your Mac by default. Unlike Otter, Fireflies and Zoom notes (which miss or mangle code-switched speech and send audio to the vendor), Cora publishes its benchmark so you can check the claim yourself.

**One-sentence pitch**: Cora is an open-source Mac meeting recorder that gets Hinglish right, keeps audio on your machine by default, and proves it with a public benchmark you can rerun.

**Branch B pitch (if local loses but cloud wins, i.e. G1 passes only for Gemini)**: "Cora is an open-source Mac meeting recorder with the most accurate Hinglish transcription we could measure; audio stays local unless you choose a paid-tier Vertex/Gemini key, and one policy switch blocks every outbound call." Never use "nothing leaves your Mac" in this branch except next to the *local* engine label.

**Tagline options (≤60 chars; count in brackets; PH forbids hype words)**
1. Meeting notes that actually understand Hinglish [47]
2. Hinglish meeting notes, private by default [42]  (recommended; claim only valid with local engine passing G1, else use #3)
3. Open-source meeting notes that get Hinglish right [49]
4. Accurate Hinglish notes. Local-first. Open source. [50]
5. Local meeting notes that don't mangle your Hindi [48]
6. Rehearse your next hard 1:1 from your last real one [51]  (second act / plugin tagline, not the main one)
Avoid: "Your meetings, in Hinglish. Nothing leaves your Mac." (false when Gemini is enabled).

Tagline test: show 8-10 builders the options for 5 seconds each, ask "what does it do, who is it for?" (PH CEO advice: test with friends).

---

## 6. Two audiences, one launch, sequenced

| | Wave 1: India builders (lead) | Wave 2: global builders (follow, same 48h window) |
|---|---|---|
| Hook | "Your Hinglish meetings, transcribed properly, on your Mac" | "We benchmarked 8 ASR engines on code-switched meetings; here is the data and the code" |
| Channel | X/LinkedIn India, Peerlist, r/developersIndia, founder groups | Show HN (link GitHub repo), r/LocalLLaMA (benchmark post), PH |
| Asset | 60s demo: Hinglish meeting to clean notes | Benchmark write-up + data-flow diagram + plugin teaser |
| Metric | installs, retained recorders | stars, HN points, plugin-author signups |

PH note: the PH audience is US-centric and the "Novel/Useful" criteria reward a clear differentiator. The benchmark + Hinglish demo is novel; "local open-source notetaker" is not. Treat HN/GitHub as the growth engine, PH as badge and credibility (Screenpipe: 218-pt HN, #1 GitHub trending, but PH #14 and #9).

Research-suggested dates (Show HN Tue 2026-11-17, PH Thu 2026-11-19 00:01 PT) are feasible only if notarization lands by ~Nov 6; otherwise slide to Dec 1/3 per the PH research. Do not launch unsigned.

---

## 7. Pricing and business model

Principle: free OSS core forever; charge later for convenience, not for privacy or for the benchmark.

- **Launch (Nov 2026): everything free**, BYO API keys (Gemini paid-tier/Vertex, Sarvam, Chirp). No billing code before launch. Costs to user at published rates: Chirp 3 about $0.016/min (L), Sarvam about ₹30/hr (L).
- **Candidate paid layers, ordered by fit (decide after the Wave-1 data)**:
  1. *Managed accuracy*: "Cora Credits", pass-through ASR on a paid, no-training Vertex/Sarvam account, opt-in, per-minute, so users without a cloud account get top accuracy. Needs a proxy service, DPAs and policy work, so it is **not** a launch item and creates a SOC 2 scope question (Cora becomes a processor). Decide only if interviews show key-setup friction is the blocker.
  2. *Cora Pro for individuals*, $8-12/mo ($99/yr) anchored to Meetily Pro $10 / Granola Business $14: signed auto-updates, curated plugin pack, always-on server/phone-capture setup helper, priority support. India price tier (e.g. ₹299-499) since ChatGPT Go was free for a year in India (L); expect ARPU well under US.
  3. *Teams later*: shared plugin registry, team todo ledger, SSO, audit log (needs sync backend, SOC 2 report; defer).
  4. Plugin store revenue share: not before there are plugins.
- **Never paywall**: lockdown, local engine, export, MCP, the benchmark, plugin SDK.
- **Cheapest willingness-to-pay test (pre-launch)**: a "Pro early supporter" page with price shown ($8/mo, ₹399/mo variant) and a refundable-deposit or at least email + "what would you pay for" field, gated behind actually using the app. No money collected before there is something to deliver, and no payment form that collects card data under placeholder terms. Target signal is stated in section 9.

---

## 8. Compliance and messaging guardrails (SOC 2 / HIPAA / DoD context)

- Marketing claims must match controls. Allowed: "local by default", "enterprise_lockdown blocks outbound traffic including plugins" **only after** the socket-blocking test exists and passes in CI. Not allowed: HIPAA-compliant, CMMC-ready, FedRAMP, "secure" without scope.
- Cloud ASR (Gemini/Chirp/Sarvam) must be explicit opt-in, labelled with what leaves the device, paid-tier/Vertex only by default (free-tier Gemini may train with human review, L), and blocked by lockdown. Sarvam and any non-Google engine add a new processor: list it in the data-flow table or exclude it from the launch.
- Mirror what the lawsuits target: consent-notice template for participants, no training on user data, no public share links by default, and a code review of speakers.py to document whether voice embeddings exist and are retained (BIPA risk is **unassessed**; get legal input before any US marketing push).
- India-specific: privacy law and consent norms (DPDP Act) apply to recordings of people; do a short legal read before promoting "record your calls" to Indian users. Not legal advice; flagged as open.
- Benchmark participants: written consent covering publication of audio.
- Never ship real meeting data in screenshots, GIFs or the bench; seed_demo_data.py (fictional) is the source for all visuals.

---

## 9. Riskiest assumptions and cheapest tests (run in weeks 1-3, before launch)

Ordered by how fatal each is to the angle. Each has a pre-registered pass bar so the result cannot be rationalized.

| # | Assumption | Why risky | Cheapest test | Cost | Pass bar | If it fails |
|---|---|---|---|---|---|---|
| A1 | Mainstream tools are visibly bad on Hinglish meetings | Evidence is Otter-no-Hindi + one Zoom thread (L/U). Fireflies, tl;dv, Meet, Granola, Krisp Hindi quality unknown | Record 3 x 5-min fictional Hinglish meetings; run through Otter, Fireflies, tl;dv, Gemini app, Meet/Zoom native, Granola free tiers; score with asr_bench folded WER | 1-2 days, free tiers | Best mainstream tool is ≥ 1.5x Cora's best on folded WER, or visibly drops words | Drop "others fail"; reframe to "private + extensible + works in Hinglish"; angle weakens, consider global-builder-first |
| A2 | Cora's **local** path is competitive on Hinglish | The privacy half depends on it; Tara is the owner's own model; weights/licence/download story unverified | Run bench: Tara vs Whisper large-v3 vs Gemini vs Chirp 3 vs Sarvam on public + volunteer audio; use the G1/G2 gate from transcription-gemini | 2-3 days after T-G5 | Local within 25% relative folded WER of the best cloud arm, or beats Whisper large-v3 by ≥ 30% | Branch B pitch; local becomes "fallback", optional cloud is the Hinglish story; do not use "private by default" as headline |
| A3 | Target users exist and care enough to switch | Pain is anecdotal; Indian size and willingness to pay unknown | 15 problem interviews (5 founders/PMs, 5 consultants/EMs, 5 diaspora managing India teams), recruited via X/LinkedIn/Peerlist/founder groups; ask for their last bad transcript story, current tool, spend | 1 week, 0 cost | ≥ 8/15 have a recent Hindi-mix transcript failure; ≥ 5 will install a beta this month; ≥ 3 name a price ≥ ₹300/$5 | Segment is not a beachhead; fall back to builder-operator wedge with roleplay |
| A4 | Users will install and trust an unsigned/new OSS app | Gatekeeper friction kills first-run (Sequoia; PH research) | Notarize a DMG (T-4 weeks item); give it to 20 beta users via browser download; measure install-to-first-recording | 2-4 days + $99 | ≥ 70% of beta users reach a first transcript within 15 minutes unaided | Do not launch; fix onboarding/signing first |
| A5 | Accuracy gains matter on notes quality, not just WER | WER can overstate usefulness | Blind A/B of notes from two engines for 10 beta users on the same meeting; ask "which would you send?" | 2 days | ≥ 65% prefer the leading engine's notes | Focus on notes/templates quality rather than ASR |
| A6 | Benchmark will earn attention on HN/LocalLLaMA | Show HN posts for peers got 4-18 points | Post a draft benchmark teaser in r/LocalLLaMA or a small dev group (follow rules, disclose); watch responses and reproduction attempts | 1 day | ≥ 3 people ask for the code or rerun it; no methodology demolition | Tighten methodology, add independent datasets before Show HN |
| A7 | Privacy default won't be undermined by the Gemini story | HN/LocalLLaMA readers will probe it | Red-team the data-flow table with 3 security-minded reviewers; run the lockdown socket test | 1 day | No unlabelled egress found; lockdown test green | Remove cloud default from marketing; ship cloud as "advanced" only |
| A8 | Anyone would pay (Pro, credits) | India price sensitivity (L) | Supporter page with price shown, only for activated beta users | 1 day to build page | ≥ 10% of active beta users click "reserve" and ≥ 3 leave a price reason | Stay free; revisit managed credits only if setup friction was the blocker |
| A9 | Plugin story raises PH "Novel" without overpromising | Plugin platform not yet built; Hyprnote's 18-point extensibility post | Show the roleplay demo clip (fictional data) to 10 beta users; ask "would you use this weekly?" | 1 day | ≥ 4/10 say weekly | Keep plugins as roadmap, not hero |
| A10 | Legal/privacy exposure from recording and voice data is acceptable | BIPA question open; India consent norms | Code review of speakers.py embeddings + 1 hour legal review | 1-2 days | Documented answer; consent-notice template written | Hold US marketing push until resolved |

Kill/pivot rule: if A1 and A2 both fail, do **not** launch with this angle. Fall back to the builder-operator + roleplay wedge (research_pmf beachhead 1) and postpone to Dec.

---

## 10. Success metrics

Launch target in line with comparables (Granola's launches reached top 5-10 at ~200-450 upvotes; Screenpipe and Humla show OSS can underperform on PH while winning on stars): measure installs, retention and stars, not rank.

### 30 days after launch (by ~Dec 19, 2026)
| Metric | Floor | Target | Stretch |
|---|---|---|---|
| GitHub stars | 300 | 1,000 | 2,500 |
| Notarized DMG downloads (GitHub Releases) | 500 | 1,500 | 4,000 |
| Activated users (first transcript in 24h) | 40% of installs | 55% | 70% |
| Weekly active recorders (self-reported opt-in telemetry-free: via update checks or survey; no telemetry by default) | 80 | 250 | 600 |
| Week-4 retention of activated users (≥ 1 recording in week 4) | 20% | 30% | 40% |
| Indian-user share of active (survey) | 30% | 45% | 60% |
| Benchmark reproductions / forks of bench data | 3 | 10 | 25 |
| PH points / HN points | n/a | ~250 / 100 | top 5 / 300 |
| Plugin or template contributions from outsiders | 0 | 3 | 10 |
| "Very disappointed if Cora went away" (Sean Ellis survey, n ≥ 30 active) | 25% | 35% | 40% |
| Quality: median folded WER on bench vs best mainstream | published | ≥ 1.5x better | ≥ 2x |
| Privacy incidents / unlabelled egress reports | 0 | 0 | 0 |

### 90 days (by ~Feb 17, 2027)
| Metric | Floor | Target | Stretch |
|---|---|---|---|
| GitHub stars | 800 | 2,500 | 6,000 |
| Monthly active recorders | 300 | 1,000 | 3,000 |
| Week-8 retention of activated users | 20% | 30% | 40% |
| Sean Ellis "very disappointed" | 30% | 40% | 50% |
| Paying or committed supporters (Pro early access) | 0 | 50 | 200 |
| Outside plugin authors with a published plugin | 2 | 10 | 30 |
| Named case studies (India builders, with consent) | 2 | 5 | 10 |
| Open security reports handled within SLA | 100% | 100% | 100% |
| Decision made on managed credits / Pro price | yes | yes | yes |

PMF signal definition: 90 days from launch, ≥ 40% "very disappointed", ≥ 30% week-8 retention among activated users, and at least 25 users who recorded ≥ 3 Hinglish meetings in a week unprompted. If retention is below 20% while installs are high, the problem is the product, not distribution.

---

## 11. 4-5 week plan (solo founder + AI agents, today 2026-10-17)

| Week | Focus | Gate |
|---|---|---|
| 1 (Oct 19-25) | Apple Developer enrollment + notarize pipeline; record 4-6 volunteer fictional meetings + consent forms; run A1 (competitor check); start 15 interviews (A3); bench v2 per transcription-gemini | A1 result, first Tara baseline |
| 2 (Oct 26-Nov 1) | A2 full bench sweep; A10 speakers.py review + legal read; beta of 20 users on notarized DMG (A4); lockdown socket test | A2 pass/fail: choose branch A or B |
| 3 (Nov 2-8) | Rewrite README/data-flow table/privacy doc; benchmark write-up draft; demo video from seed_demo_data.py; A5/A7/A9 tests; schedule PH (≥ 10 days ahead) | Kill/pivot decision |
| 4 (Nov 9-15) | Cut release, FAQ, first comments, Show HN and PH drafts, India channel posts, support channel | Go/no-go |
| 5 (Nov 16-22) | Launch window (Nov 17 HN, Nov 19 PH if gates met); reply to all comments | Metrics log |
Slip rule: if notarization or A2 slips, move launch to Dec 1/3 (avoid Nov 23-27).

---

## 12. Owner decisions needed

1. Lead with Hinglish/India angle only if A1+A2 pass; otherwise approve fallback wedge (roleplay + privacy).
2. Approve publishing a benchmark that may show Cora losing on some axes.
3. Approve volunteer recording program (consent, licence for published audio) and who the volunteers are.
4. Decide whether Sarvam (non-Google processor) is in the launch benchmark/UI or bench-only.
5. Approve India pricing exploration and the "no payment collected pre-launch" rule.
6. Commission legal review on voice embeddings/BIPA and India consent norms before US marketing.
7. Confirm Tara weights licence and the distribution path (download vs bundle) before claiming "local Hinglish model" publicly.
8. Choose launch date: Nov 17/19 vs Dec 1/3, contingent on notarization.

## 13. Open unknowns (carried from research, not resolved here)
Hinglish market size and WTP; real Hinglish WER of Gemini/Chirp/Sarvam on meeting audio; Fireflies/tl;dv/Granola Hindi quality; lawsuit outcomes; Screenpipe store activity; Reddit rule text; whether Tara/Hinglish tuning generalizes beyond the owner's speaking style (single-speaker overfit risk: bench must include volunteers with different accents and languages mix ratios).
