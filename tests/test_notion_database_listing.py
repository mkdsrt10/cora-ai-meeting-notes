"""The Tasks database is picked by pasting its Notion link: Cora never lists
every database the integration can see (some workspaces share hundreds, many
with the same name)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest  # noqa: E402

import connections  # noqa: E402
from plugins.notion import routes  # noqa: E402

DB = "1f2e3d4c5b6a79881f2e3d4c5b6a7988"
VIEW = "aaaabbbbccccddddeeeeffff00001111"


def test_there_is_no_listing_of_every_database():
    assert not hasattr(routes, "databases") and not hasattr(routes, "get_databases")


def test_a_pasted_link_picks_that_exact_database(fake_conn):
    fake = fake_conn("notion")
    fake.on("GET", f"/databases/{DB}", {"id": DB, "title": [{"plain_text": "Tasks"}]})
    found = routes.database_from_link(fake, f"https://www.notion.so/acme/Tasks-{DB}?v={VIEW}&pvs=4")
    assert found == {"id": DB, "title": "Tasks"}
    assert [r["path"] for r in fake.requests] == [f"/databases/{DB}"]


def test_a_dashed_id_works_too(fake_conn):
    fake = fake_conn("notion")
    fake.on("GET", f"/databases/{DB}", {"id": DB, "title": []})
    dashed = f"{DB[:8]}-{DB[8:12]}-{DB[12:16]}-{DB[16:20]}-{DB[20:]}"
    assert routes.database_from_link(fake, dashed) == {"id": DB, "title": "Untitled"}


def test_a_link_cora_cannot_see_says_to_share_it(fake_conn):
    fake = fake_conn("notion")

    def missing(r):
        raise connections.ConnectionFailed("permanent", 404, "object_not_found")
    fake.on("GET", f"/databases/{DB}", missing)
    with pytest.raises(ValueError, match="Connections"):
        routes.database_from_link(fake, DB)
    with pytest.raises(ValueError, match="Copy link"):
        routes.database_from_link(fake, "https://www.notion.so/not-a-database")
