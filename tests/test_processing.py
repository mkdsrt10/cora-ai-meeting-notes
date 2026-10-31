"""Processing modes must compose safely and cover the whole source."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import db
import processing
from pipeline import cloud_asr, processing_notes


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    original = db.get_setting
    monkeypatch.setattr(db, 'get_setting', lambda key, default=None: default if key == 'processing_preferences' else original(key, default))


def test_mode_defaults_and_overrides_do_not_mutate_preferences(monkeypatch):
    monkeypatch.setattr(processing, 'preferences', lambda: processing.validate({'mode': 'cloud'}))
    assert processing.resolve()['transcription'] == 'gemini'
    selected = processing.resolve({'mode': 'local_thorough', 'template': 'technical_review'})
    assert selected['provider'] == 'local_mlx'
    assert selected['transcription'] == 'local'
    assert processing.preferences()['mode'] == 'cloud'
    mixed = processing.resolve({'mode': 'local_thorough', 'transcription': 'gemini', 'provider': 'openai'})
    assert mixed['provider'] == 'openai' and mixed['transcription'] == 'gemini'


@pytest.mark.parametrize('value', [{'mode':'wrong'}, {'provider':'wrong'}, {'template':'../../file'}, {'transcription':'wrong'}, []])
def test_reject_bad_options(value):
    with pytest.raises(ValueError):
        processing.validate(value)


def test_lockdown_overrides_automatic_cloud_but_rejects_manual_cloud(monkeypatch):
    monkeypatch.setattr(processing, 'preferences', lambda: processing.validate({'mode':'cloud'}))
    monkeypatch.setenv('VOICECOACH_ENTERPRISE_LOCKDOWN', '1')
    assert processing.resolve()['provider'] == 'local_mlx'
    assert cloud_asr.engine() == 'local'
    with pytest.raises(Exception, match='lockdown'):
        processing.resolve({'mode':'cloud'})


def test_scope_is_thread_local_locked_and_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(processing.paths, 'DATA_DIR', tmp_path)
    with processing.scope(processing.validate({'mode':'cloud'})):
        assert cloud_asr.engine() == 'gemini'
        with ThreadPoolExecutor() as pool:
            assert pool.submit(processing.CURRENT.get).result() is None
        with pytest.raises(ValueError, match='Another processing'):
            with processing.scope(processing.validate({})):
                pass
    assert processing.CURRENT.get() is None


def test_template_ai_and_explicit_selection():
    calls = []
    def generate(prompt, **kwargs):
        calls.append(prompt)
        return 'standup'
    assert processing.choose_template('auto', generate, 'updates', 'daily') == ('standup','ai')
    assert processing.choose_template('one_on_one', generate, 'updates', '') == ('one_on_one','manual')
    assert len(calls) == 1
    assert processing.choose_template('auto', lambda *a, **k: 'unknown', '', '') == ('general','ai_fallback')


def response():
    return dict(title='Release planning', overview='Ship on Friday.', **{k:'- None noted.' for k in processing_notes.FIELDS if k != 'overview'})


def test_cloud_template_and_hierarchy_cover_late_transcript(monkeypatch):
    import credentials
    prompts = []
    monkeypatch.setattr(credentials, 'get_public_status', lambda: {'gemini_model':'configured-model'})
    def generate(**kwargs):
        prompts.append(kwargs)
        return 'technical_review' if kwargs['trace_name'] == 'template.select' else json.dumps(response())
    monkeypatch.setattr(credentials, 'call_configured_llm', generate)
    text = ('early discussion\n' * 6000) + 'FINAL DECISION: cancel release'
    result = processing_notes.generate_notes(text, [], [], options=processing.validate({'mode':'cloud'}))
    assert result['processing']['template'] == 'technical_review'
    assert result['processing']['model'] == 'configured-model'
    assert any('FINAL DECISION: cancel release' in p['prompt'] for p in prompts if p['trace_name'].startswith('notes.chunk'))
    assert any(p['trace_name'].startswith('notes.merge') for p in prompts)
    assert 'Technical review' in processing_notes.render(result)


def test_malformed_output_is_retried_once(monkeypatch):
    import credentials
    calls = []
    monkeypatch.setattr(credentials, 'get_public_status', lambda: {})
    monkeypatch.setattr(credentials, 'call_configured_llm', lambda **k: calls.append(k) or '{}')
    with pytest.raises(ValueError, match='incomplete notes'):
        processing_notes.generate_notes('Hello', [], [], options=processing.validate({'mode':'cloud','template':'general'}))
    assert len(calls) == 2


def test_local_thorough_uses_full_context_and_releases(monkeypatch):
    class LLM:
        def __init__(self, model):
            self._model = SimpleNamespace(args=SimpleNamespace(max_position_embeddings=8192))
            self._tokenizer = SimpleNamespace(encode=lambda text:list(text), apply_chat_template=lambda messages, **k: messages[0]['content'])
            self.released = False
        def generate(self, prompt, **kwargs):
            assert 'specific fact' in prompt
            return json.dumps(response())
        def release(self):
            self.released = True
    llm = LLM('test')
    monkeypatch.setattr(processing_notes, 'LazyLLM', lambda model: llm)
    result = processing_notes.generate_notes('specific fact', [], [], options=processing.validate({'mode':'local_thorough','template':'technical_review'}))
    assert result['processing']['mode'] == 'local_thorough'
    assert llm.released


def test_light_keeps_extractor_with_template_guidance(monkeypatch):
    import pipeline.notes
    captured = {}
    def light(*args, **kwargs):
        captured.update(kwargs)
        return response()
    monkeypatch.setattr(pipeline.notes, 'generate_enhanced_notes', light)
    result = processing_notes.generate_notes('hello', [], [], user_notes='My notes', options=processing.validate({'template':'standup'}))
    assert 'blockers' in captured['template_instruction']
    assert captured['user_notes'] == 'My notes'
    assert result['processing']['template_selection'] == 'manual'


def test_split_keeps_every_character_and_handles_single_long_turn():
    text = 'अंतिम निर्णय\n' * 1000
    chunks = processing_notes.split_text(text, lambda text: len(text) <= 100)
    assert ''.join(chunks) == text
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_regeneration_uses_segments_not_previous_ai_summary(tmp_path, monkeypatch):
    from api.routes import recordings
    import local_meeting_pipeline
    folder = tmp_path / 'meeting'
    folder.mkdir()
    (folder / 'transcript_diarized.md').write_text('OLD AI HALLUCINATION')
    old = dict(segments=[dict(start='00:00',end='00:03',speaker_name='A',text='Real words')], model='local-mlx:test')
    monkeypatch.setattr(recordings, 'safe_folder', lambda _: folder)
    monkeypatch.setattr(db, 'get_recording_data', lambda _, key: old if key == 'diarization' else {})
    monkeypatch.setattr(db, 'get_notes', lambda _: '')
    monkeypatch.setattr(db, 'update_recording_data', lambda *a: None)
    monkeypatch.setattr(local_meeting_pipeline, '_archive_previous_outputs', lambda _: None)
    def generate(text, *args, **kwargs):
        assert 'Real words' in text and 'HALLUCINATION' not in text
        return dict(response(), keywords=[], processing=dict(processing.validate({}), template='standup'))
    monkeypatch.setattr(processing_notes, 'generate_notes', generate)
    req = SimpleNamespace(send_json=lambda payload: payload)
    token = processing.CURRENT.set(processing.validate({}))
    try:
        result = recordings._re_summarize(req, '', {'id':'meeting'})
    finally:
        processing.CURRENT.reset(token)
    assert result['call_summary']['processing']['template'] == 'standup'
    assert (folder / 'transcript_diarized.md').read_text() == 'OLD AI HALLUCINATION'
    assert 'locally' in json.loads((folder / 'diarization.json').read_text())['privacy_note']


def test_coerce_bullet_arrays_and_escaped_newlines():
    result = response()
    result['key_entities_md'] = ['Alice','DevOps']
    result['action_items_md'] = '- First\\n- Second'
    parsed = processing_notes.parse(json.dumps(result))
    assert parsed['keywords'] == ['Alice','DevOps']
    assert parsed['action_items_md'] == '- First\n- Second'


def test_meeting_context_excludes_internal_paths():
    context = json.loads(processing.meeting_context({'recording_name':'Daily','source_file':'/private/audio','pipeline_key':'internal'}, [{'speaker_name':'Alice'}]))
    assert context == {'recording_name':'Daily','participants':['Alice']}


def test_gemini_adapter_honors_configured_model_and_output_budget(monkeypatch):
    import credentials
    captured = {}
    monkeypatch.setattr(credentials, 'get_public_status', lambda: {})
    monkeypatch.setattr(credentials, '_read_secure_file', lambda: {'gemini_model':'configured-model'})
    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text='general')
    monkeypatch.setattr(credentials, 'get_client', lambda **_: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    text, _, model = credentials._call_configured_llm('meeting data', 'static instructions', 'gemini', None, 256)
    assert text == 'general' and model == 'configured-model'
    assert captured['contents'] == 'meeting data'
    assert captured['config'] == {'system_instruction':'static instructions','max_output_tokens':256}
