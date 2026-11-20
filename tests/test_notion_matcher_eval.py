"""Notion matcher eval on the fictional fixture (T7 gate: link precision >= 0.8).
The measured local-model run is tools/eval_notion_matcher.py --model local_mlx."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("eval_notion_matcher",
                                              Path(__file__).resolve().parents[1] / "tools" / "eval_notion_matcher.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def test_lexical_matcher_meets_the_precision_gate_and_offers_misses_as_link_instead():
    result = ev.run()
    assert result["link_precision"] >= 0.8
    assert result["false_creates"] == result["rescued_by_link_instead"]


def test_model_links_outside_the_shortlist_are_ignored():
    class Liar:
        def complete(self, prompt, **kwargs):
            import re
            return [{"action_item_id": i, "decision": "link", "task_id": "T05", "confidence": 1.0}
                    for i in re.findall(r'<item id="([^"]+)">', prompt)]
    result = ev.run(Liar())
    # Only items with T05 on their shortlist (the security audit item, and "Renew the office lease" via "renew")
    # can be linked to it; the other 23 fall back to create.
    assert (result["links"], result["correct_links"]) == (2, 1)
