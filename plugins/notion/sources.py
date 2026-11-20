"""Notion tasks Context source: open Task titles from the local cache (no
network at notes time), capped at 20, those assigned to the call's People
first. Titles also go to the ASR vocabulary as terms. With a cloud notes
model the titles reach that model (stated in Settings > Connections, Q28)."""
from __future__ import annotations

import accounts
from notes_context import ContextBlock, ContextRequest

from . import tasks

CAP = 20


class NotionTasks:
    id = "notion.tasks"

    def gather(self, req: ContextRequest) -> list[ContextBlock]:
        if not tasks.configured():
            return []
        open_ = tasks.open_tasks()
        if not open_:
            return []
        theirs = {a["id"] for pid in req.person_ids if (a := accounts.confirmed(pid, "notion"))}
        ranked = sorted(open_, key=lambda t: (not (theirs & set(t["assignee_ids"])), ))[:CAP]
        lines = "\n".join(f"- {t['title']}" for t in ranked)
        return [
            ContextBlock(self.id, "Open Tasks in the user's Notion (titles only). When an Action item continues one, "
                         "use the Task's wording:\n" + lines, 0.6, frozenset({"action_items"})),
            ContextBlock(self.id, "\n".join(t["title"] for t in ranked), 0.4, frozenset({"asr"}), kind="terms"),
        ]
