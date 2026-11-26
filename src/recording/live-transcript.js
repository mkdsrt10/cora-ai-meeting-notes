// Live transcript of one Recording session (GLOSSARY "Live transcript";
// docs/specs/live-transcript.md): turns the capture helper's live events into
// the JSONL record, captions and a paused/running status. The Recording
// session owns one per start while the `live` setting is on; nothing here can
// stop or change a Recording: every failure (a bad line, a full disk, a dead
// engine) only stops captions.
//
//   const live = createLiveTranscript({ key, mode, file, clock, onCaption, onStatus });
//     key: the Recording's first chunk id (the file and every event are keyed by it)
//     mode: 'on_device' | 'cloud_vertex'
//     file: { append(obj), close() } | null   one JSONL file per Recording session
//   live.chunk(chunkId, offsetMs)   a Chunk starts, offsetMs after the session's first one
//   live.event(ev)                  helper events: liveText, liveEngine, liveStatus
//   live.speaker(name)              a remote speaker hint (SPEAKER_ACTIVE from the meeting app)
//   live.status() -> { state, mode, engine, code, cloud }
//     state: 'starting' | 'running' | 'paused'
//     cloud: audio is streaming to the cloud engine now ("Live: Cloud" badge)
//   live.end() -> summary           counts for the live_transcript Usage event (no text, no names)
//
// JSONL line: { recording_id (the Chunk), track ('mic'|'sys'), speaker (hint or null), start, end
// (seconds since the Recording session started), text, final, engine, seg, lag_ms (the engine's
// caption delay for the line, for the eval) }. Finals as they come;
// a partial only when its segment never got a final (engine stopped mid-sentence). Lines continue
// across Chunks; times never go backwards per track.
//
// Echo: on speakers, the mic hears the other side a moment after the system track does (Nov 2026
// call: 64 of 183 mic lines repeated a remote speaker, ~230 ms behind). A mic final is held for
// ECHO_HOLD_MS, then dropped when most of its words appear, in order, in system lines that overlap
// it in time (your own reply to something said seconds earlier is kept). A dropped segment gets one
// caption { dropped: true, text: '' } so views remove its partial; counted as echoDropped.

const LAG_PAUSE_MS = 6000;       // captions this far behind speech count as paused
const LAG_RESUME_MS = 3000;
const ENGINE_START_MS = 30000;   // no engine line by then: paused
const SPEAKER_HINT_MS = 10000;   // a remote name this recent labels Them lines
const NON_NAMES = new Set(['you', 'participant', '']);
const ECHO_HOLD_MS = 3000;       // a mic final waits this long for the system track to catch up
const ECHO_SLACK_S = 1.5;        // an echo overlaps its system line in time, give or take this much
const ECHO_KEEP_S = 60;          // system lines kept for matching
const ECHO_MIN_WORDS = 3;        // shorter mic lines ("okay") are never called echo
const ECHO_SHARE = 0.6;          // share of the mic line's words found, in order, in the system text

const round3 = (x) => Math.round(x * 1000) / 1000;
const words = (text) => String(text || '').toLowerCase().replace(/['’]/g, '').split(/[^\p{L}\p{N}]+/u).filter(Boolean);

// The mic hears the speakers muffled, so its copy is a rough re-hearing ("finished" for "finish",
// "a bit progress" for "a good progress"): words match when equal, one edit apart, or sharing 4 letters of stem.
function sameWord(a, b) {
  if (a === b) return true;
  if (a.length >= 4 && b.length >= 4 && a.slice(0, 4) === b.slice(0, 4)) return true;
  if (Math.min(a.length, b.length) < 3 || Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  while (i < a.length && a[i] === b[i]) i += 1;
  const tailA = a.slice(i + 1), tailB = b.slice(i + 1);
  return tailA === tailB || a.slice(i) === b.slice(i + 1) || a.slice(i + 1) === b.slice(i);
}

// Longest in-order match of `mine` inside some stretch of `theirs` (words may be skipped on either side).
function bestInOrder(mine, theirs) {
  let best = 0;
  const span = mine.length + 3;
  for (let at = 0; at < Math.max(1, theirs.length - mine.length + 1); at += 1) {
    const win = theirs.slice(at, at + span);
    const row = new Array(win.length + 1).fill(0);
    for (const m of mine) {
      let diag = 0;
      for (let j = 1; j <= win.length; j += 1) {
        const up = row[j];
        row[j] = sameWord(m, win[j - 1]) ? diag + 1 : Math.max(row[j], row[j - 1]);
        diag = up;
      }
    }
    best = Math.max(best, row[win.length]);
  }
  return best;
}

// Is a mic line (text, start, end in session seconds) mostly a re-hearing of system lines that overlap it?
function isEcho(text, start, end, sysLines) {
  const mine = words(text);
  if (mine.length < ECHO_MIN_WORDS) return false;
  const near = sysLines.filter((s) => s.end >= start - ECHO_SLACK_S && s.start <= end + ECHO_SLACK_S)
    .sort((a, b) => a.start - b.start);
  if (!near.length) return false;
  return bestInOrder(mine, near.flatMap((s) => words(s.text))) / mine.length >= ECHO_SHARE;
}

function createLiveTranscript({ key, mode, file = null, clock, selfName = () => null, onCaption = () => {}, onStatus = () => {} }) {
  const tracks = { mic: newTrack(), sys: newTrack() };
  let chunkId = key;
  let offset = 0;                 // seconds, current Chunk's start in session time
  let engine = null;
  let fileOk = Boolean(file);
  let remote = null;              // { name, at }
  let ended = false;
  const counts = { finals: 0, partials: 0, lags: [], droppedS: 0, failures: {}, lagPauses: 0, words: 0, writeErrors: 0, echoDropped: 0,
    echoDelayMs: null, echoReductionDb: null, echoFarS: 0 };
  let sysLines = [];              // recent system finals, session seconds: { start, end, text }
  const held = new Set();         // mic finals waiting out ECHO_HOLD_MS: { out, caption, timer }
  let status = { state: 'starting', mode, engine: null, code: null, cloud: mode === 'cloud_vertex' };
  let startTimer = clock.setTimeout(() => {
    if (!tracks.mic.engine && !tracks.sys.engine && status.state !== 'paused') pause('engine_start_timeout');
  }, ENGINE_START_MS);

  function newTrack() {
    return { engine: null, state: 'starting', open: null, lastStart: 0, lastFinalEnd: 0, lagging: false };
  }

  function setStatus(next) {
    const merged = { ...status, ...next };
    merged.cloud = mode === 'cloud_vertex' && merged.state !== 'paused';
    const changed = ['state', 'engine', 'code', 'cloud'].some((k) => status[k] !== merged[k]);
    status = merged;
    if (changed && !ended) onStatus({ ...status });
  }

  function overall() {
    const states = Object.values(tracks).map((t) => (t.lagging ? 'paused' : t.state));
    const code = Object.values(tracks).map((t) => t.code).find(Boolean) || null;
    if (states.includes('paused')) return { state: 'paused', code };
    if (states.includes('running')) return { state: 'running', code: null };
    return { state: 'starting', code: null };
  }

  function pause(code, track = null) {
    counts.failures[code] = (counts.failures[code] || 0) + 1;
    for (const [name, t] of Object.entries(tracks)) {
      if (!track || name === track) { t.state = 'paused'; t.code = code; }
    }
    setStatus({ ...overall(), engine });
  }

  function write(obj) {
    if (!fileOk) return;
    try {
      file.append(obj);
    } catch (err) {
      fileOk = false;   // one warning, then captions only
      counts.writeErrors += 1;
      console.warn('[Cora live] Live transcript not written:', err && err.message);
    }
  }

  function speakerFor(track) {
    if (track !== 'sys' || !remote) return null;
    return clock.now() - remote.at <= SPEAKER_HINT_MS ? remote.name : null;
  }

  function line(t, ev, final, speaker) {
    return {
      recording_id: chunkId,
      track: ev.track,
      speaker,
      start: round3(offset + ev.start),
      end: round3(offset + ev.end),
      text: ev.text,
      final,
      engine: t.engine || engine,
      seg: ev.seg,
      lag_ms: typeof ev.lagMs === 'number' ? ev.lagMs : null,
    };
  }

  function onText(ev) {
    const t = tracks[ev.track];
    // Times never go backwards on a track, even across a bad engine line.
    const start = Math.max(offset + ev.start, t.lastStart);
    const fixed = { ...ev, start: start - offset, end: Math.max(start, offset + ev.end) - offset };
    t.lastStart = start;
    if (t.state !== 'running') { t.state = 'running'; t.code = null; }
    if (typeof ev.lagMs === 'number') {
      if (ev.final) counts.lags.push(ev.lagMs);
      if (!t.lagging && ev.lagMs > LAG_PAUSE_MS) { t.lagging = true; t.code = 'lagging'; counts.lagPauses += 1; }
      else if (t.lagging && ev.lagMs < LAG_RESUME_MS) { t.lagging = false; t.code = null; }
    }
    const speaker = speakerFor(ev.track);
    const out = line(t, fixed, ev.final, speaker);
    const caption = { recordingId: key, chunkId, track: ev.track, who: ev.track === 'mic' ? 'You' : (speaker || 'Them'),
      speaker, seg: ev.seg, start: out.start, end: out.end, text: ev.text, final: ev.final };
    if (ev.final) {
      out.start = Math.max(out.start, t.lastFinalEnd);
      out.end = Math.max(out.end, out.start);
      t.lastFinalEnd = out.end;
      t.open = null;
      Object.assign(caption, { start: out.start, end: out.end });
      if (ev.track === 'sys') {
        sysLines = sysLines.filter((s) => s.end >= out.end - ECHO_KEEP_S);
        sysLines.push({ start: out.start, end: out.end, text: out.text });
      }
      if (ev.track === 'mic') hold(out, caption);
      else keep(out, caption);
    } else if (ev.track === 'mic' && isEcho(out.text, out.start, out.end, sysNow())) {
      t.open = null;
      drop(caption, false);
    } else {
      t.open = out;
      counts.partials += 1;
      onCaption(caption);
    }
    setStatus({ ...overall(), engine });
  }

  // System finals plus the system segment still being spoken (an echo can arrive before its source's final).
  function sysNow() {
    return tracks.sys.open ? [...sysLines, tracks.sys.open] : sysLines;
  }

  function keep(out, caption) {
    counts.finals += 1;
    counts.words += out.text.split(/\s+/).filter(Boolean).length;
    write(out);
    onCaption(caption);
  }

  function drop(caption, isLine = true) {
    if (isLine) counts.echoDropped += 1;   // dropped lines; a withdrawn partial is not one
    onCaption({ ...caption, text: '', final: true, dropped: true });
  }

  function settle(h) {
    held.delete(h);
    if (h.timer != null) clock.clearTimeout(h.timer);
    if (isEcho(h.out.text, h.out.start, h.out.end, sysNow())) drop(h.caption);
    else keep(h.out, h.caption);
  }

  // One helper (Chunk) stopped: fold its echo canceller counts in. Delay is the
  // last one found; reduction is weighted by each Chunk's far-end seconds.
  function addEcho(echo) {
    if (typeof echo.delayMs === 'number' && echo.delayMs >= 0) counts.echoDelayMs = echo.delayMs;
    const far = typeof echo.farS === 'number' ? echo.farS : 0;
    if (far > 0 && typeof echo.reductionDb === 'number') {
      const before = counts.echoFarS;
      counts.echoReductionDb = ((counts.echoReductionDb ?? 0) * before + echo.reductionDb * far) / (before + far);
    }
    counts.echoFarS += far;
  }

  function hold(out, caption) {
    const h = { out, caption, timer: null };
    held.add(h);
    h.timer = clock.setTimeout(() => { h.timer = null; if (!ended) settle(h); }, ECHO_HOLD_MS);
  }

  function flushOpen() {
    for (const t of Object.values(tracks)) {
      if (t.open) { write(t.open); t.open = null; }
    }
  }

  return {
    // Call once the previous Chunk's helper has exited: its open partials are
    // written as final:false, and the new helper's engines start afresh.
    chunk(id, offsetMs) {
      flushOpen();
      if (id !== chunkId) {
        for (const t of Object.values(tracks)) {
          if (t.state === 'running') t.state = 'starting';
          t.lagging = false;
        }
      }
      chunkId = id;
      offset = Math.max(0, offsetMs) / 1000;
    },
    event(ev) {
      if (ended || !ev) return;
      if (ev.type === 'liveText' && tracks[ev.track]) {
        onText(ev);
      } else if (ev.type === 'liveEngine' && tracks[ev.track]) {
        const t = tracks[ev.track];
        t.engine = ev.engine;
        engine = engine || ev.engine;
        if (ev.fallbackFrom) counts.failures[`fallback_${ev.fallbackFrom}`] = (counts.failures[`fallback_${ev.fallbackFrom}`] || 0) + 1;
        if (t.state !== 'paused') t.state = 'running';
        if (startTimer != null) { clock.clearTimeout(startTimer); startTimer = null; }
        setStatus({ ...overall(), engine });
      } else if (ev.type === 'liveStatus') {
        if (typeof ev.droppedS === 'number' && ev.state === 'stopped') counts.droppedS += ev.droppedS;
        if (ev.state === 'stopped' && ev.echo) addEcho(ev.echo);
        if (ev.state === 'paused') pause(ev.code || 'engine_error', ev.track && tracks[ev.track] ? ev.track : null);
        else if (ev.state === 'lagging') pause(ev.code || 'lagging', ev.track && tracks[ev.track] ? ev.track : null);
        else if (ev.state === 'running' && tracks[ev.track]) {
          if (typeof ev.droppedS === 'number') counts.droppedS = Math.max(counts.droppedS, ev.droppedS);
          tracks[ev.track].state = 'running';
          tracks[ev.track].code = null;
          setStatus({ ...overall(), engine });
        }
      }
    },
    speaker(name) {
      const n = String(name || '').trim();
      if (NON_NAMES.has(n.toLowerCase()) || n === selfName()) return;
      remote = { name: n, at: clock.now() };
    },
    status: () => ({ ...status }),
    end() {
      if (ended) return null;
      for (const h of [...held]) settle(h);
      flushOpen();
      ended = true;
      if (startTimer != null) { clock.clearTimeout(startTimer); startTimer = null; }
      try { if (file) file.close(); } catch {}
      return { mode, engine, ...counts };
    },
  };
}

// The real file adapter: <dir>/<key>_live.jsonl, appended line by line
// (python/live_transcript.py moves it into the Recording folder).
function createLiveTranscriptFiles(dir) {
  const fs = require('fs');
  const path = require('path');
  return {
    open(key) {
      fs.mkdirSync(dir, { recursive: true });
      const file = path.join(dir, `${key}_live.jsonl`);
      return {
        path: file,
        append: (obj) => fs.appendFileSync(file, JSON.stringify(obj) + '\n'),
        close: () => {},
      };
    },
  };
}

// Caption delay buckets for the live_transcript Usage event (ms upper edges).
const LAG_BUCKETS = [250, 500, 1000, 1500, 2000, 3000, 5000, 10000];
function lagBucket(ms) {
  if (typeof ms !== 'number') return null;
  return LAG_BUCKETS.find((edge) => ms <= edge) || 99999;
}
function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}

// summary (live.end()) -> the live_transcript Usage event payload: counts only.
function liveUsagePayload(recordingId, summary) {
  const failures = Object.entries(summary.failures || {})
    .map(([code, n]) => `${String(code).replace(/[^a-z0-9_]/gi, '').slice(0, 40)}:${n}`).join(',').slice(0, 200);
  return {
    recording_id: recordingId,
    mode: summary.mode,
    engine: summary.engine || 'none',
    finals: summary.finals,
    words: summary.words,
    lag_p50_ms: lagBucket(percentile(summary.lags, 50)),
    lag_p95_ms: lagBucket(percentile(summary.lags, 95)),
    lag_pauses: summary.lagPauses,
    dropped_s: Math.round((summary.droppedS || 0) * 10) / 10,
    failures,
    write_errors: summary.writeErrors,
    // Echo handling: mic lines dropped as echoes of the other side, and the
    // capture helper's canceller (delay found, dB removed, far-end seconds).
    echo_dropped: summary.echoDropped || 0,
    echo_delay_ms: typeof summary.echoDelayMs === 'number' ? summary.echoDelayMs : null,
    echo_reduction_db: typeof summary.echoReductionDb === 'number' ? Math.round(summary.echoReductionDb) : null,
    echo_far_s: Math.round(summary.echoFarS || 0),
  };
}

// GET /api/live/settings -> whether a start now streams audio to the cloud
// engine: the "Live: Cloud" badge on the Call prompt.
function liveCloudWillRun(settings) {
  return Boolean(settings && settings.mode === 'cloud_vertex' && !settings.refused);
}

module.exports = { createLiveTranscript, createLiveTranscriptFiles, liveCloudWillRun, liveUsagePayload, lagBucket, isEcho,
  LAG_PAUSE_MS, ENGINE_START_MS, ECHO_HOLD_MS };
