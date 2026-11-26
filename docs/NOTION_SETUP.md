# Connect Cora to Notion

Cora turns the action items from your meetings into Notion Tasks, or links them to Tasks you already have. It only **suggests**. Nothing is written to Notion until you click **Confirm**, and every write acts as you.

About 5 minutes. You need Cora 0.4.6 or later, in the new look (Settings › Appearance).

## 1. Make a Notion token

1. Open [notion.so/profile/integrations](https://www.notion.so/profile/integrations) and click **New integration**.
2. Name it `Cora`, pick your workspace, type **Internal**, and save.
3. Under **Capabilities**, tick:
   - **Read content**, **Update content**, **Insert content**: to read your Tasks and create new ones.
   - **Read comments**, **Insert comments**: linking an action item to an existing Task adds a comment.
   - **Read user information without email addresses**, if offered: Cora can then list everyone in the workspace for **Assignee**. Without it (a personal access token has no such option), Cora offers you plus everyone already assigned on your Tasks.
4. Copy the **Internal integration secret** (starts with `ntn_` or `secret_`).

A personal access token works too: paste it the same way in step 3.

## 2. Give it your Tasks database

In Notion, open your Tasks database (the full page, not a linked view), click **⋯** › **Connections** › **Connect to**, and pick `Cora`.

Cora sees only the pages you connect it to.

## 3. Connect in Cora

1. **Settings › Connections** › Notion: paste the token and click **Connect**. The token goes into the macOS Keychain; it is never written to a file or sent anywhere but Notion.
2. **Settings › Notion**:
   - **Tasks database link**: in Notion, open the database, **⋯** › **Copy link**, and paste it here.
   - Map the properties Cora should fill: **Title**, **Status** (and which status means done), **Assignee**, **Due date**, and optionally **Area** and a **Meeting** relation.
   - **Usage instructions**: plain words on how your team uses the database, for example "One Task per deliverable; small follow-ups go in the parent Task's checklist". Cora follows them when it decides between creating and linking.
   - Click **Save**, then **Refresh Tasks**.

## 4. Use it

After a meeting is processed:

- Each action item gets a **Notion** chip, and the sidebar shows **Suggested** with everything waiting across meetings.
- Click a suggestion to open it. You can edit the title, **Assignee**, due date and checklist, or under **Or link instead to**, pick an existing Task (best matches are marked ★). Then **Confirm**.
- **Assignee**: you for your own items. For someone else, Cora preselects their Notion account once it is linked on their Person page, or when their full name matches exactly one Notion person. Otherwise pick from the list.
- **Name in Notion differs from the meeting** ("Sam K." vs "Samir Kapoor", or two people called Alex)? Open **People › that person › Accounts**, pick their Notion account under **Pick their account…** and click **Link**. Their items get them as Assignee from then on.
- **Dismissed one by mistake?** Its action item now shows an **Add to Notion** chip, and **Suggested › Dismissed** lists the last 30 days with **Bring back**.
- **Suggest again (Notion)** in a meeting's **⋯** menu makes fresh suggestions, for example after you change the Usage instructions.
- Ticking a linked to-do done in Cora offers **Mark done in Notion**.

## What Cora sends to Notion, and when

- **Only on your Confirm:** the Task you reviewed (title, assignee, due date, checklist, and the line "From ‹meeting›, ‹date›. (via Cora)"), or one comment on the Task you linked to.
- **In the background:** reads your Tasks and the workspace's user names, so it can match and assign. Nothing from your meetings is sent.
- **The suggestion itself** is made on this Mac with your notes model. If that model is a cloud one (Settings › Where models run), your open Task titles go to it with the action items.
- **Disconnect** any time in Settings › Connections; that removes the token from the Keychain. If your organization turns on enterprise lockdown, connections are blocked.

## If something looks wrong

| You see | Do this |
|---|---|
| "Connect it in Settings › Connections first" | The token is missing or was revoked. Paste it again. |
| No Tasks, or "0 Tasks cached" | The database isn't connected to the integration (step 2), or the link points to a linked view. Open the source database and copy its link. |
| Assignee only offers "Unassigned" and you | Cora learns teammates from the people assigned on your Tasks. Click **Refresh Tasks** in Settings › Notion, then **Suggest again (Notion)** on the meeting. Someone never assigned on any Task can't be offered unless the token can read user information. |
| Old suggestions still show the old choices | Open the meeting's **⋯** › **Suggest again (Notion)**. |

Questions or ideas: **Settings › Help & feedback** › Request a feature. Issues are public, so don't paste meeting content or customer names.
