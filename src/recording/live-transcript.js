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
// (seconds since the Recording session started), text, final, engine, seg }. Finals as they come;
// a partial only when its segment never got a final (engine stopped mid-sentence). Lines continue
// across Chunks; times never go backwards per track.

const LAG_PAUSE_MS = 6000;       // captions this far behind speech count as paused
const LAG_RESUME_MS = 3000;
const ENGINE_START_MS = 30000;   // no engine line by then: paused
const SPEAKER_HINT_MS = 10000;   // a remote name this recent labels Them lines
const NON_NAMES = new Set(['you', 'participant', '']);

const round3 = (x) => Math.round(x * 1000) / 1000;

function createLiveTranscript({ key, mode, file = null, clock, selfName = () => null, onCaption = () => {}, onStatus = () => {} }) {
  const tracks = { mic: newTrack(), sys: newTrack() };
  let chunkId = key;
  let offset = 0;                 // seconds, current Chunk's start in session time
  let engine = null;
  let fileOk = Boolean(file);
  let remote = null;              // { name, at }
  let ended = false;
  const counts = { finals: 0, partials: 0, lags: [], droppedS: 0, failures: {}, lagPauses: 0, words: 0, writeErrors: 0 };
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
    if (ev.final) {
      out.start = Math.max(out.start, t.lastFinalEnd);
      out.end = Math.max(out.end, out.start);
      t.lastFinalEnd = out.end;
      t.open = null;
      counts.finals += 1;
      counts.words += ev.text.split(/\s+/).filter(Boolean).length;
      write(out);
    } else {
      t.open = out;
      counts.partials += 1;
    }
    onCaption({ recordingId: key, chunkId, track: ev.track, who: ev.track === 'mic' ? 'You' : (speaker || 'Them'),
      speaker, seg: ev.seg, start: out.start, end: out.end, text: ev.text, final: ev.final });
    setStatus({ ...overall(), engine });
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

// GET /api/live/settings -> whether a start now streams audio to the cloud
// engine: the "Live: Cloud" badge on the Call prompt.
function liveCloudWillRun(settings) {
  return Boolean(settings && settings.mode === 'cloud_vertex' && !settings.refused);
}

module.exports = { createLiveTranscript, createLiveTranscriptFiles, liveCloudWillRun, LAG_PAUSE_MS, ENGINE_START_MS };
