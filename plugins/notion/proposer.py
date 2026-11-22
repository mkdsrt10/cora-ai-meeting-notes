"""Notion Proposals (ADR 0002, spec §Notion plugin):

- task.link: add a comment "From ‹meeting›, ‹date›: ‹action item›" to an
  existing Task, and set its Meeting relation when mapped and the Recording
  has a Notion meeting page Link. Never edits a Task's title or body (Q61).
- task.create: a new Task in the mapped database, following the Usage
  instructions (grouped sub-steps become a checklist). Assignee only from the
  owner's confirmed Account, else empty (Q55). A low-confidence match offers
  the 3 nearest Tasks as "link instead". A Task with the same title created in
  the last day is flagged (Q31).
- task.update: "Mark done in Notion" when a Linked To-do is ticked done in
  Cora (T8; see on_action_item).

One key per Action item ("notion:task:<id>"), so reprocessing never proposes
again what the user confirmed or dismissed, and Linked items get nothing new.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import accounts
import outbox
from outbox import Applied, Field, Proposal

from . import matcher, tasks

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _meeting(ctx) -> tuple[str, str]:
    rec = ctx.recording or {}
    title = rec.get("title") or "Meeting"
    when = str(rec.get("recorded_at") or "")[:10]
    return title, when


def comment_text(meeting: str, date: str, item_text: str) -> str:
    return f"From {meeting}, {date}: {item_text}" if date else f"From {meeting}: {item_text}"


def _linked(ctx, item_id: str) -> bool:
    return any(lk["action_item_id"] == item_id and lk["service"] == "notion" for lk in ctx.links)


def _recently_created(title: str) -> dict | None:
    want = " ".join(matcher.tokens(title))
    cutoff = dt.datetime.now().astimezone() - dt.timedelta(days=1)
    for t in tasks.all_tasks():
        try:
            created = dt.datetime.fromisoformat(str(t.get("created_time") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= cutoff and " ".join(matcher.tokens(t["title"])) == want:
            return t
    return None


class NotionProposer:
    automatic = True

    # ---- propose ---------------------------------------------------------------
    def propose(self, ctx) -> list[Proposal]:
        if not tasks.configured():
            return []
        items = [i for i in ctx.action_items if not i["done"] and not _linked(ctx, i["id"])]
        if not items:
            return []
        s = tasks.settings()
        owner_ids = {i["id"]: (accounts.for_owner(i.get("owner"), "notion") or {}).get("id") for i in items}
        try:
            model_cm = ctx.text_model()
        except Exception:
            model_cm = None
        if model_cm is not None:
            with model_cm as model:
                decisions = matcher.decide(items, tasks.open_tasks(), model=model,
                                           instructions=s.get("usage_instructions") or "", owner_accounts=owner_ids)
        else:
            decisions = matcher.decide(items, tasks.open_tasks(), instructions=s.get("usage_instructions") or "",
                                       owner_accounts=owner_ids)
        by_id = {i["id"]: i for i in items}
        meeting, date = _meeting(ctx)
        proposals: list[Proposal] = []
        groups: dict[str, list[matcher.Decision]] = {}
        for d in decisions:
            if d.decision == "skip":
                continue
            if d.decision == "create" and d.group:
                groups.setdefault(d.group, []).append(d)
                continue
            item = by_id[d.action_item_id]
            if d.decision == "link":
                proposals.append(self._link(item, tasks.task(d.task_id) or {}, meeting, date, d.confidence,
                                            ctx.recording_id))
            else:
                proposals.append(self._create([item], d.nearest, meeting, date, s, owner_ids, ctx.recording_id))
        for members in groups.values():
            group_items = [by_id[d.action_item_id] for d in members]
            proposals.append(self._create(group_items, members[0].nearest if len(members) == 1 else [],
                                          meeting, date, s, owner_ids, ctx.recording_id))
        return proposals

    def _link(self, item, task, meeting, date, confidence, recording_id) -> Proposal:
        text = comment_text(meeting, date, item["text"])
        return Proposal(
            key=f"notion:task:{item['id']}", kind="task.link", title=f"Link to '{task.get('title', '')}'",
            fields=(Field("comment", "Comment added to the Task", text, True, "textarea"),),
            payload={"task_id": task.get("id"), "task_title": task.get("title"), "comment": text,
                     "confidence": round(confidence, 2), "recording_id": recording_id},
            action_item_ids=(item["id"],),
            target={"id": task.get("id"), "title": task.get("title"), "url": task.get("url")},
            sends=f"One comment on the Task '{task.get('title', '')}' in Notion: the comment text above. "
                  "Its title and body are not changed.")

    def _create(self, items, nearest, meeting, date, s, owner_ids, recording_id) -> Proposal:
        mapping = s["mapping"]
        first = items[0]
        title = first["text"]
        checklist = [i["text"] for i in items[1:]]
        owner_account = owner_ids.get(first["id"])
        assignee_user = accounts.user("notion", owner_account) if owner_account else None
        due = first.get("due") or ""
        fields = [Field("title", "Title", title)]
        if mapping.get("assignee"):
            options = [{"value": "", "label": "Unassigned"}]
            if assignee_user:
                options.append({"value": assignee_user["id"], "label": assignee_user["name"]})
            me = accounts.self_user("notion")
            if me and me["id"] != (assignee_user or {}).get("id"):
                options.append({"value": me["id"], "label": f"{me['name']} (you)"})
            fields.append(Field("assignee", "Assignee", assignee_user["id"] if assignee_user else "", True, "select",
                                tuple(options)))
        if mapping.get("due"):
            fields.append(Field("due", "Due (YYYY-MM-DD)", due if DATE.match(due) else "", True))
        if mapping.get("area"):
            fields.append(Field("area", "Area", "", True))
        if checklist:
            fields.append(Field("checklist", "Checklist (one per line)", "\n".join(checklist), True, "textarea"))
        if nearest:
            fields.append(Field("link_instead", "Or link instead to", "", True, "select",
                                tuple([{"value": "", "label": "Create a new Task"}] +
                                      [{"value": t["id"], "label": t["title"]} for t in nearest])))
        twin = _recently_created(title)
        if twin:
            fields.append(Field("warning", "Heads-up", f"A Task with this title was created in the last day: "
                                f"'{twin['title']}'", False, "readonly"))
        db_name = s.get("database_title") or "your Tasks database"
        return Proposal(
            key=f"notion:task:{first['id']}", kind="task.create", title=f"Create Task '{title}'",
            fields=tuple(fields),
            payload={"database_id": s["database_id"], "data_source_id": s.get("data_source_id") or "", "mapping": mapping, "meeting": meeting, "date": date,
                     "recording_id": recording_id,
                     "item_text": first["text"], "nearest": [{"id": t["id"], "title": t["title"], "url": t.get("url")}
                                                             for t in nearest]},
            action_item_ids=tuple(i["id"] for i in items),
            sends=f"A new Task in {db_name}: the title, assignee, due date, Area and checklist above, and the line "
                  f"'From {meeting}{', ' + date if date else ''}.' Or, if you pick a Task to link instead, "
                  "one comment on that Task.")

    # ---- apply -----------------------------------------------------------------
    def apply(self, proposal: Proposal, edits: dict[str, Any], conn) -> Applied:
        p = proposal.payload
        if proposal.kind == "task.link":
            return self._apply_link(p["task_id"], edits.get("comment") or p["comment"], conn, proposal)
        if proposal.kind == "task.create":
            instead = str(edits.get("link_instead") or "")
            if instead:
                if instead not in {t["id"] for t in p.get("nearest") or []}:
                    raise ValueError("link target was not offered")
                return self._apply_link(instead, comment_text(p["meeting"], p["date"], p["item_text"]), conn, proposal)
            return self._apply_create(p, edits, conn)
        if proposal.kind == "task.update":
            return self._apply_done(p, conn)
        raise ValueError(f"unsupported kind {proposal.kind}")

    def _apply_link(self, task_id: str, comment: str, conn, proposal: Proposal) -> Applied:
        conn.request("POST", "/comments", json={"parent": {"page_id": task_id},
                                                "rich_text": [{"type": "text", "text": {"content": comment[:2000]}}]})
        meeting_page = _meeting_page(proposal.payload.get("recording_id"))
        mapping = tasks.settings()["mapping"]
        if meeting_page and mapping.get("meeting"):
            page = conn.request("GET", f"/pages/{task_id}")
            existing = [r.get("id") for r in ((page.get("properties") or {}).get(mapping["meeting"]) or {})
                        .get("relation") or []]
            if meeting_page not in existing:
                conn.request("PATCH", f"/pages/{task_id}", json={"properties": {mapping["meeting"]: {
                    "relation": [{"id": i} for i in existing + [meeting_page]]}}})
        task = tasks.task(task_id) or {}
        return Applied("notion", task_id, task.get("url") or "", "task")

    def _apply_create(self, p: dict, edits: dict, conn) -> Applied:
        mapping = p["mapping"]
        title = str(edits.get("title") or p["item_text"]).strip()[:2000]
        props: dict[str, Any] = {mapping["title"]: {"title": [{"type": "text", "text": {"content": title}}]}}
        assignee = str(edits.get("assignee") or "")
        if mapping.get("assignee") and assignee:
            if accounts.user("notion", assignee) is None:
                raise ValueError("assignee is not a Notion user")
            props[mapping["assignee"]] = {"people": [{"id": assignee}]}
        due = str(edits.get("due") or "")
        if mapping.get("due") and DATE.match(due):
            props[mapping["due"]] = {"date": {"start": due}}
        area = str(edits.get("area") or "").strip()
        if mapping.get("area") and area:
            props[mapping["area"]] = {"select": {"name": area[:100]}}
        children = [{"object": "block", "type": "to_do", "to_do": {
            "rich_text": [{"type": "text", "text": {"content": line.strip()[:2000]}}], "checked": False}}
            for line in str(edits.get("checklist") or "").splitlines() if line.strip()]
        children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {
            "content": f"From {p['meeting']}{', ' + p['date'] if p['date'] else ''}. (via Cora)"}}]}})
        # A Proposal made before data sources carries only database_id: Notion still
        # accepts that parent for a database with one data source.
        parent = ({"type": "data_source_id", "data_source_id": p["data_source_id"]} if p.get("data_source_id")
                  else {"database_id": p["database_id"]})
        page = conn.request("POST", "/pages", json={"parent": parent, "properties": props,
                                                    "children": children})
        tasks.upsert({"id": page.get("id"), "title": title, "url": page.get("url"), "assignee_ids":
                      [assignee] if assignee else [], "created_time": page.get("created_time")})
        return Applied("notion", str(page.get("id")), str(page.get("url") or ""), "task")

    def _apply_done(self, p: dict, conn) -> Applied:
        mapping = tasks.settings()["mapping"]
        prop, done_value = mapping.get("status"), mapping.get("done_value")
        if not prop:
            raise ValueError("status mapping missing")
        page = conn.request("GET", f"/pages/{p['task_id']}")
        kind = ((page.get("properties") or {}).get(prop) or {}).get("type") or "status"
        if kind != "checkbox" and not done_value:
            raise ValueError("done value missing")
        value = {"checkbox": True} if kind == "checkbox" else {kind: {"name": done_value}}
        conn.request("PATCH", f"/pages/{p['task_id']}", json={"properties": {prop: value}})
        tasks.set_done(p["task_id"], True)
        return Applied("notion", p["task_id"], p.get("url") or "", "task.done")

    # ---- done in Cora -> "Mark done in Notion" (T8) ------------------------------
    def on_action_item(self, event: str, item: dict, ctx) -> list[Proposal]:
        """Ticking a Linked To-do done raises one task.update per Linked Task
        that is still open in Notion; unticking withdraws it if not yet confirmed."""
        if event != "done" or not tasks.configured():
            return []
        mapping = tasks.settings()["mapping"]
        if not mapping.get("status"):
            return []
        linked = {lk["external_id"] for lk in outbox.links(action_item_id=item["id"], service="notion")
                  if lk["kind"] == "task"}
        result = []
        for task_id in sorted(linked):
            key = f"notion:done:{item['id']}:{task_id}"
            if not item["done"]:
                outbox.withdraw(key)
                continue
            task = tasks.task(task_id) or {"id": task_id, "title": "", "done": False}
            if task["done"]:
                continue   # already done in Notion (e.g. the status pull ticked this To-do)
            title = task.get("title") or "the Linked Task"
            result.append(Proposal(
                key=key, kind="task.update", title=f"Mark done in Notion: '{title}'",
                payload={"task_id": task_id, "url": task.get("url"), "recording_id": item["recording_id"]},
                action_item_ids=(item["id"],), target={"id": task_id, "title": title, "url": task.get("url")},
                sends=f"Sets the status of '{title}' to '{mapping.get('done_value') or 'done'}' in Notion. "
                      "Nothing else changes."))
        return result


def _meeting_page(recording_id: str | None) -> str | None:
    """The Recording's Notion meeting page, when a Link of kind meeting_page exists
    (none is written yet: Call Log stays with the old sync script, Q60)."""
    if not recording_id:
        return None
    for lk in outbox.links(recording_id=recording_id, service="notion"):
        if lk["kind"] == "meeting_page":
            return lk["external_id"]
    return None
