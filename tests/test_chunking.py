import local_meeting_pipeline as lmp


def test_chunks_end_at_pauses_and_respect_caps():
    chunks = lmp.plan_chunks([(0, 3), (3.5, 6), (7, 40), (41, 42), (60, 61)])
    assert chunks == [(0, 6), (7, 32.0), (32.0, 42), (60, 61)]
    assert all(end - start <= lmp.CHUNK_MAX_S for start, end in chunks)


def test_empty_and_tiny_stretches():
    assert lmp.plan_chunks([]) == []
    assert lmp.plan_chunks([(1.0, 1.01)]) == []
