const { spawn } = require('child_process');
const readline = require('readline');

// Thin wrapper around the native `mic-watch` CLI (capture/MicWatcher.swift),
// which uses CoreAudio's kAudioDevicePropertyDeviceIsRunningSomewhere to
// report the instant any process starts/stops using the default input
// device — the same OS-level signal Notion's desktop app reportedly uses,
// rather than polling for specific meeting apps.
function startMicWatcher(binPath, { onMicOn, onMicOff }) {
  let proc;
  try {
    proc = spawn(binPath);
  } catch (err) {
    console.error('mic-watch failed to start:', err.message);
    return () => {};
  }

  proc.on('error', (err) => {
    console.error('mic-watch failed to start:', err.message);
  });

  const rl = readline.createInterface({ input: proc.stdout });
  rl.on('line', (line) => {
    const value = line.trim();
    console.log(`[debug ${new Date().toISOString()}] mic-watch line:`, value);
    if (value === 'MIC_ON') onMicOn();
    else if (value === 'MIC_OFF') onMicOff();
  });

  return () => {
    rl.close();
    proc.kill();
  };
}

module.exports = { startMicWatcher };
