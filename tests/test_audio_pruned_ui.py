"""Notes view of a Recording whose audio was pruned (audio_pruning.py): a line
saying why the audio is gone stands where the player would be, and
Retranscribe, which needs the audio, is disabled with the reason."""
import shutil
import subprocess
from pathlib import Path

import pytest
from test_failed_stage_ui import HARNESS as FAILED_STAGE_HARNESS

# The failed-stage harness plus notepad.js (selectedRecording).
HARNESS = FAILED_STAGE_HARNESS.replace("'detail.js',", "'notepad.js','detail.js',")
assert HARNESS != FAILED_STAGE_HARNESS


def _run(tmp_path, body):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'audio-pruned-ui.cjs'
    script.write_text(HARNESS + "(async()=>{\n" + body + "\n})().catch(error=>{console.error(error);process.exitCode=1;});\n")
    result = subprocess.run(['node', str(script), str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


def _record(pruned):
    return ("{id:'rec-9',title:'Standup',recorded_at:'2026-09-01T10:00:00Z',duration_seconds:600,"
            "analysis_stage:'ready',audio_url:null,notes:'',versions:[],audio_pruned:" + pruned + "}")


@needs_node
@pytest.mark.parametrize("pruned, text", [
    ("{at:'2026-11-11T09:00:00+00:00',reason:'retention',limit:30}", "Audio removed after 30 days"),
    ("{at:'2026-11-11T09:00:00+00:00',reason:'cap',limit:500}", "Audio removed to stay under the 500 MB cap"),
])
def test_a_pruned_recording_says_why_its_audio_is_gone_and_cannot_be_retranscribed(tmp_path, pruned, text):
    _run(tmp_path, f'''
 run(`selectedDetail={_record(pruned)}; selectedRecordingId='rec-9'; renderAudioState(selectedRecording())`);
 const notice=node('#notepadAudioNotice');
 assert.notEqual(notice.style.display,'none');
 assert.match(notice.textContent,/^{text}\\. The transcript and notes are kept\\.$/);
 const reprocess=node('#notepadReprocessBtn');
 assert.equal(reprocess.disabled,true);
 assert.match(reprocess.title,/audio was removed/);

 // A later reset of the processing status does not re-enable it.
 run('resetProcessingStatus()');
 assert.equal(reprocess.disabled,true);
''')


@needs_node
def test_a_recording_with_its_audio_shows_no_notice_and_can_be_retranscribed(tmp_path):
    _run(tmp_path, f'''
 run(`selectedDetail={_record('null')}; selectedRecordingId='rec-9'; renderAudioState(selectedRecording())`);
 assert.equal(node('#notepadAudioNotice').style.display,'none');
 assert.equal(node('#notepadAudioNotice').textContent,'');
 assert.equal(node('#notepadReprocessBtn').disabled,false);
''')
