from pipeline.windows import WINDOW_MAX_S, plan_windows, split_window


def stretches(*spans):
    return [(a, b) for a, b in spans]


def test_short_meeting_is_one_window():
    w = plan_windows(stretches((0, 10), (12, 30), (33, 60)))
    assert len(w) == 1 and (w[0].start, w[0].end) == (0, 60)


def test_long_pause_starts_a_new_window():
    w = plan_windows(stretches((0, 30), (60, 90)))   # 30 s of silence between
    assert [(x.start, x.end) for x in w] == [(0, 30), (60, 90)]


def test_cuts_at_the_longest_pause_near_the_target():
    # speech every 20 s with 2 s pauses, except a 6 s pause at t=196
    spans = [(i * 22.0, i * 22.0 + 20) for i in range(9)]      # last ends at 196
    spans += [(202.0 + i * 22.0, 222.0 + i * 22.0) for i in range(6)]
    w = plan_windows(spans)
    assert len(w) >= 2
    assert w[0].end == 196          # cut at the 6 s pause, not mid-run
    assert all(x.duration <= WINDOW_MAX_S for x in w)


def test_windows_cover_every_stretch_in_order_without_overlap():
    spans = [(i * 7.0, i * 7.0 + 5) for i in range(200)]       # ~23 min, 2 s pauses
    w = plan_windows(spans)
    covered = [s for x in w for s in x.stretches]
    assert covered == spans
    assert all(a.end <= b.start for a, b in zip(w, w[1:]))
    assert all(x.duration <= WINDOW_MAX_S for x in w)


def test_one_unbroken_stretch_longer_than_max_is_split():
    w = plan_windows(stretches((0, 800)))
    assert len(w) == 3 and all(x.duration <= WINDOW_MAX_S for x in w)
    assert w[0].start == 0 and w[-1].end == 800


def test_empty_input():
    assert plan_windows([]) == []


def test_split_window_cuts_at_longest_pause_and_refuses_short_ones():
    w = plan_windows(stretches((0, 50), (53, 100), (106, 150)))[0]
    a, b = split_window(w)
    assert (a.end, b.start) == (100, 106)
    short = plan_windows(stretches((0, 20), (24, 40)))[0]
    assert split_window(short) is None


def test_continuous_284_second_window_splits_without_a_pause():
    from pipeline.windows import Window
    original = Window(720, 1004, [(720, 1004)])
    halves = split_window(original)
    assert [(w.start, w.end) for w in halves] == [(720, 862), (862, 1004)]
    assert [s for w in halves for s in w.stretches] == [(720, 862), (862, 1004)]
    assert sum(b-a for w in halves for a,b in w.stretches) == 284


def test_tiny_edge_pause_does_not_prevent_balanced_splitting():
    from pipeline.windows import Window
    halves = split_window(Window(0, 284, [(0, 2), (3, 284)]))
    assert [(w.start, w.end) for w in halves] == [(0, 142), (142, 284)]
    assert halves[0].stretches == [(0, 2), (3, 142)]
    assert halves[1].stretches == [(142, 284)]
