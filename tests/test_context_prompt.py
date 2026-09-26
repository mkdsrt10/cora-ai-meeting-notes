from pipeline import context as c


def make_ctx():
    ctx = c.MeetingContext(title="Roadmap Sync", attendees=["Priya Shah", "Rahul Mehta"])
    for name in ctx.attendees:
        ctx.add(name, "attendees")
    ctx.add("Kubernetes", "curated")
    ctx.add("OKRs", "notes")
    ctx.add("Snowflake", "ocr")
    ctx.timed.append(c.Term("Databricks", c.WEIGHTS["nearby_ocr"], {"nearby_ocr"}, at=300.0))
    for i in range(200):
        ctx.add(f"Filler{i}", "learned")
    return ctx


def test_extract_terms_finds_names_acronyms_and_codes():
    terms = c.extract_terms("We met Priya Shah about the API and GPT-4 costs for Q3. The plan is fine. OpenAI too.")
    assert {"Priya Shah", "API", "GPT-4", "Q3", "OpenAI"} <= set(terms)
    assert "The" not in terms and "Plan" not in terms


def test_prompt_is_prose_with_attendees_and_respects_budget():
    ctx = make_ctx()
    prompt = ctx.prompt()
    assert prompt.startswith("Meeting: Roadmap Sync. Attendees: Priya Shah, Rahul Mehta.")
    assert c.count_tokens(prompt) <= c.PROMPT_TOKEN_BUDGET
    # higher-priority sources are packed before the long tail of learned words
    assert prompt.index("OKRs") < prompt.index("Filler0")
    assert "Snowflake" in prompt and "Kubernetes" in prompt


def test_nearby_screenshot_terms_only_near_their_time():
    ctx = make_ctx()
    assert "Databricks" in ctx.prompt(290, 310)
    assert "Databricks" not in ctx.prompt(900, 910)


def test_multi_source_terms_are_boosted():
    ctx = c.MeetingContext()
    ctx.add("Snowflake", "ocr")
    ctx.add("Snowflake", "learned")
    assert ctx.terms["snowflake"].score > c.WEIGHTS["ocr"]
    assert ctx.terms["snowflake"].sources == {"ocr", "learned"}


def test_prompts_are_recorded_for_debugging(tmp_path):
    ctx = make_ctx()
    ctx.record(0, 10, ctx.prompt(0, 10))
    ctx.save(tmp_path)
    saved = (tmp_path / "transcription_context.json").read_text()
    assert '"chunk_prompts"' in saved and "Priya Shah" in saved
