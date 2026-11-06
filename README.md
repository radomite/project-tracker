# Research project tracker

Research discussions organized as **projects → topics → messages**, with
a project dashboard, a folder-based Files page, and recent messages. Docker Compose
separates the web app from optional research tool containers.

For HTTPS hosting at **project.counthom.org**, GitHub CI/image publishing, and
the Windows-to-server bootstrap, see [deployment](deploy/README.md).

## Run

With Docker, run `docker compose up --detach --build app latex`. Separate on-demand
services provide Git, Python, Typst, TeX Live, Lean with mathlib, and SageMath,
without installing those toolchains on the host. See [Docker setup](docker/README.md)
for tool commands, persistent volumes, migration, and validation.

Every project also has an Astra research agent and a Sol editing agent. The
optional Codex service uses separate persistent contexts; project clusters
authorize communication between agents. See [project agents](docker/CODEX.md).

For local Python development:

Python 3.11+ (tested on 3.13) and Git (tested on Git for Windows 2.44):

```powershell
python -m pip install -r requirements.txt
npm ci
npm run build
python scripts/editor-fonts.py
.\run.ps1
```

Or:

```text
python -m uvicorn app:app --host 127.0.0.1 --port 8765 --reload
```

Open **http://127.0.0.1:8765**. Create the first account; there is no default
password. Optional sample projects are illustrative. Subsequent accounts require
a project invitation. Data persists in `data/research.db`; set `RESEARCH_DB` to
an absolute path for a separate database.

## Topics and messages

Select a project, then a topic in the sidebar. Messages need only text; tags are
optional. Use the **Tags** composer action, or hover a message and click its tag
icon to choose tags. The other hover icons act directly on the message. Examples: `question`, `technique`, `proposed solution`, `promising`,
`failed`, `roadblock`, `open end`. Open end is an ordinary message tag. Only
humans can add the question tag or manage main
questions. A proposed solution is not automatically treated as a verified result.

The sidebar's **Projects** heading has a **+** button to create a private project.
Only a project name is required; add collaborator emails to generate individual
invitation links immediately. Copy and share the links manually; no email is sent.
The research objective is optional in the API and omitted from the creation form.
**Collaborators** in the sidebar opens membership and invitation management. It shows
the six projects with the most recent activity; **⋯** expands the remaining ones.
Projects and topics are ordered by their latest activity. Number badges show
your unread messages, summed across topics for each project. Your own messages
are already read; messages from collaborators and agents count until visible in
the open topic. Read status is saved per user and survives reloads and message
moves. Reading the overview or search results does not clear unread messages.
**Search everything** searches all accessible projects; **Search this project**
searches only the selected project. Both find projects, topics, messages (including
tags), and notes (including uploaded text/Typst source and file names). Results
open the matching project, topic, original message, or note. PDF file names are
searchable; PDF contents are not indexed. On mobile, Enter closes the sidebar to
show search results.

Consecutive messages from the same author share one round initials icon and a
small centered time in the left gutter. An author or day change starts a new
group. Messages have a date separator when the day changes and stacked tag pills on
the right. Click a message to open its action menu on the right. Full author names
are available on the initials icons.

Markdown and locally served KaTeX work in messages and Markdown files. Use `$...$` or
`\(...\)` inline, and `$$...$$` or `\[...\]` for display equations. Raw HTML is
sanitized and embedded images are disabled. **Ctrl+Enter** sends a message;
ordinary Enter adds a newline. Drafts survive navigation during the current page
session. New topic activity is checked every eight seconds. When reading older
messages or holding a selection, **New activity** lets you refresh explicitly.

Message actions include:

- **Reply:** select a message, choose **Reply**, then send from the composer.
  The reply contains a compact link back to the original message. The link
  follows the original if it moves to another topic. Reply drafts survive topic
  navigation, and **Cancel reply** keeps the draft text.
- **Move message:** move one message, that message and all later messages, or
  the entire topic into an existing or new topic. Original IDs, timestamps,
  tags, pins, and reply links are preserved. No move notices appear in the chat.
- **Move a selection:** Shift-click a message to start selecting, then Shift-click
  another to select the inclusive range of loaded messages. A regular message
  click opens its menu and can establish the start of the next Shift-click range.
  Checkboxes appear during selection. Use **Move selected messages** in the
  selection toolbar; Escape clears the selection. A batch move is atomic and
  rejects stale message revisions.
- **Drag and drop:** drag a message, or one of the selected messages, onto a topic
  in the sidebar to move it there. Drop onto **+** to name a new destination topic.
  Original timestamps and authorship are preserved; stale moves are rejected.
- **Pin main question:** feature a question-tagged message on the project dashboard.
- **Edit / Archive:** authors can edit their own messages; project
  owners can edit all. Archived messages are
  preserved and available through the API/export.

Invited human collaborators can reorganize project discussions. Agents can move
only their own non-question messages individually. Cross-project moves are not
allowed. The sidebar searches include messages from all topics in their scope.

## Project dashboard

The **Project dashboard** page contains:

1. **Main questions:** pinned question messages in responsive, side-by-side columns.
2. **Last 15 messages:** the latest 15 active messages across the entire project,
   selected before grouping by their current topics. This is not 15 per topic.

Main questions can be selected/reordered using **Manage**. Project context and related
projects are available under **Project details**.

## Files and Git

The **quill icon** opens the built-in manuscript editor: collapsible file tree,
source editor, and document preview. Typst and LaTeX use the same project files,
Git remote, permissions, and history. Select the main `.typ` or `.tex` document
independently of the section currently being edited. The editor supports live
co-editing through the application server, automatic compilation, manual
Recompile, PDF download, file uploads, and draft recovery after a disconnect.

Typst compilation runs in a browser worker with locally served compiler/fonts.
Universe package imports can contact packages.typst.org. LaTeX uses the `latex`
Docker service: pdfLaTeX, BibTeX, common LaTeX packages, and multi-file documents.
It runs one compilation at a time with a 60-second limit. The worker has no
project-data mount or published port; app and worker have CPU/memory limits.
Preview errors preserve the last successful PDF and never add output files to Git.

Editor saves appear in the current pending Git batch. Each person's local edits
are summarized into an **edit window**, spanning files edited in that connection.
Typing, selection, mouse activity, and scrolling through source/preview extend
the current window. It closes after two minutes without editor activity, on
window/tab focus loss, navigation, or WebSocket disconnect. Browsing alone creates
no history entry. Set `RESEARCH_EDITOR_IDLE_SECONDS` (default `120`) in Compose
to change the cooldown. Closing an edit window does not create a Git commit.
Commit batch and Git connections retain the existing project-wide behavior.

The editor is adapted in part from TeXlyre under AGPL-3.0-or-later; license texts
and provenance accompany the served assets, and **Editor source** downloads the
application source without research data. See [TeXlyre notices](third-party/texlyre/NOTICE.md).

**Files**, directly below Project dashboard, replaces Notes. It displays a folder
tree and accepts any file format, including binary and empty files, up to 100 MiB
per file. Upload multiple files or a folder, create text files and nested folders,
edit UTF-8 text, rename/move entries, and download original bytes. Empty folders
use Git's conventional empty `.gitkeep` marker, which the tree hides. Text previews
are limited to 2 MiB; binary files are downloaded. PDFs are not visually checked.
Existing notes are copied once into `notes/` with their original contents, while
their database records remain preserved.

Each project has a real Git HTTP remote. Open **Files → Git** for its URL:

```text
git clone http://token@127.0.0.1:8765/git/projects/123.git project-files
cd project-files
git pull --ff-only
# Edit files with your usual tools.
git add .
git commit -m "Update project files"
git push origin main
```

Replace 123 with the project ID shown by Files → Git. When Git asks for the
password, use a named key created in Project settings. Read-only keys can clone
and fetch; read/write keys can push. Keys remain scoped to one project and can be
revoked. Browser uploads, edits, renames, and deletions save immediately and collect
into a pending batch rather than creating a commit per action. The right-hand
**History** column combines pending local edits with a read-only Git graph across
all branches. Colored lines show ancestry, forks, and merges; labels identify
branch and tag tips. Commits appear in topological order so parents remain below
their children, even when commit timestamps differ. The web interface always edits
`main`; the graph does not switch branches or perform merges. Commit all pending
changes together with **Commit batch**, optionally adding a commit message. Local
edit authors and timestamps remain available inside each browser batch. Pending
files and their history survive server restarts; no timer or open browser is needed.
Git connections (clone, fetch/pull, or push) first commit any pending batch, so the
remote serves the latest files. If this advances the remote before a push, pull
and merge the batch before pushing again. Pushes to
`main` update the same files displayed in the app. Other branches and tags can
be stored through Git; the Files page shows `main`. Non-fast-forward pushes,
symlinks, submodules, and paths that cannot be checked out portably are rejected.

The implementation uses Git's official
[HTTP backend](https://git-scm.com/docs/git-http-backend) and
[updateInstead checkout behavior](https://git-scm.com/docs/git-config/2.44.3).
The server should run as one Uvicorn process, as in the supplied launch command.
Each installation serves its own project remotes; no external Git host is required.

## Access

All invited human collaborators can read and contribute; there is no separate
reader role. The project owner manages invitations and membership. Invitation
links are email-bound, single-use, and expire after seven days. Share them
manually; the app does not send email. Existing users can sign in on the
invitation screen.

**Project settings** creates named, revocable agent keys with either read-only
or read/write access to one project. Removing a collaborator revokes their keys
for that project. Linking projects grants no access to the target project.
Only accessible linked projects are returned.

## API

Interactive reference: **http://127.0.0.1:8765/docs**. The reference UI currently
uses FastAPI's CDN assets. The application itself serves its assets locally.

Humans use a session cookie and `X-CSRF-Token` from `/api/v1/auth/me`. Agents
use `Authorization: Bearer KEY`. Authorship is derived from
the credential, never accepted from a request field.

Important routes, under `/api/v1/projects/{project_id}`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/topics` | List/create topics |
| PATCH | `/topics/{topic_id}` | Rename a topic, with revision checking |
| GET / POST | `/topics/{topic_id}/messages` | List/post messages |
| GET / PATCH | `/messages/{message_id}` | Read/edit a message |
| PATCH | `/messages/{message_id}/tags` | Change tags with revision checking |
| POST | `/messages/{message_id}/move` | Move one/following/all messages |
| POST | `/topics/{topic_id}/move-messages` | Move selected IDs and revisions |
| POST | `/read` | Mark explicitly viewed message IDs read for the signed-in user |
| GET | `/overview` | Dashboard data: main questions and recent messages |
| GET | `/files` | File/folder tree, versions, branch, Git URL, and integrated history (`history_limit`, default 50, maximum 500) |
| POST | `/files/commit` | Commit all pending file changes together; optional `message` |
| GET / PUT | `/files/content?path=proofs/main.tex` | Download/upload original bytes |
| GET | `/files/preview?path=proofs/main.tex` | Metadata and optional UTF-8 preview |
| POST | `/files/folders` | Create a nested folder |
| PATCH / DELETE | `/files/entry` | Rename/move or delete an entry |
| GET | `/export` | Export current project content as JSON |

`GET /api/v1/search?q=...` searches accessible project, topic, message, tag, and
file names and UTF-8 file content up to 2 MiB. Add `project_id` to restrict the search to one accessible project.
`limit` (default 50, maximum 100) and `offset` page through the results. Results
include their type and project/topic identifiers, with `has_more` for pagination.
Archived messages are excluded, and agent keys search only their own project.

Uploads use raw bytes and require `If-None-Match: *` for creation, or `If-Match`
with the file's current ETag for replacement. Rename/delete also require the
current ETag. Stale edits return 412. Nonempty folders cannot be deleted in the
browser. Project-scoped read/write keys can use the file API as well as Git.
Legacy note endpoints remain available for compatibility and import into Files.

Project/topic responses include `last_activity` and the current human user's
`unread_count`. Topic lists are ordered by recency. Submit up to 200 IDs as
`{"message_ids":[123,124]}` to `/read`; this is a human-only, idempotent operation
restricted to that project. Listing messages has no read-status side effects.

Message submission body:

```json
{"body":"Try a different basis: $M_{ij}$.","tags":["technique","promising"]}
```

Ordinary messages use `"tags":[]` or omit tags. Message lists return messages in
chronological order, with `next_before` for older pages. Pass that cursor as
`before`; default limit is 60, maximum 200. `q` and `tag` filter results.
Use `Idempotency-Key` for retryable message submissions. Reuse with a changed
payload returns 409. Mutations and selections include current revisions to avoid
silently overwriting edits or moving a stale selection.

To reply, include `"reply_to_id":123` in the message submission. Responses include
`reply_to_id` and a `reply_to` preview with the source message's current topic and
author. Reply targets must be active messages in the same project and cannot be
reassigned after sending. Reply links survive edits and moves.

The old `/items` routes remain compatible with the first version. They refer to
the same records; legacy submissions appear in a General topic. Project
administration and legacy note uploads are human-only. Read/write keys can submit
messages, replies, non-question tags, and project files. Legacy open-end/rating API records remain available for
compatibility and export; the interface uses ordinary tags.

## Migration, export, and backup

The first startup of this version migrates existing entries into a General topic
for each project. IDs, titles, bodies, authorship, timestamps, links, history,
classifications, and main-question pins are preserved. For a populated old
database, a consistent `*-before-topics-*.db` backup is made beside it before
migration. The migration is repeatable and does not recreate messages.

The JSON export includes messages, reply links, topic structure, files (bytes as
base64), and retained legacy metadata/notes. It is a content export,
not a full account/revision-history backup. For a complete backup, stop the app
and copy both `data/research.db` and `data/research-files/`. The latter contains
each project's working files, pending batches, local edit journal, and full Git repository/history. For a custom
database path, the file root is beside it as `<database-stem>-files/`. Restore
both with the app stopped. SQLite-only backups do not include the new Files store.

## Development

No Node server is needed at runtime. Build the locally served frontend assets
from the npm lockfile (generated bundles and compiler binaries are ignored by Git):

```text
npm ci
npm run build
python scripts/editor-fonts.py
```

Checks use separate ignored databases:

```text
python -m unittest discover -s tests -p "test_*.py" -v
npm ci
npx playwright install chromium
npm run test:browser
```

The browser configuration can detect an existing local Chromium;
`LOCAL_CHROMIUM` overrides its executable. Check artifacts live in ignored
`.checks/` and `test-results/`. Local development notes can be kept in the ignored
`research-diary/` folder. Password recovery, email delivery, automatic model execution,
and general research-tool execution remain deferred. Container
toolchains are available through the [Docker Compose setup](docker/README.md).

Manuscript checks (no visual PDF inspection):

```text
node node_modules/@playwright/test/cli.js test --config=playwright.editor.config.js
python scripts/check_containers.py --tools
```

The second command creates a disposable Compose project to check real compilers
and removes only its own test volumes. It can download large research-tool images;
verify Docker storage space first.

## License

This project is distributed under [AGPL-3.0-or-later](LICENSE). The editor includes
TeXlyre adaptations; retain its [provenance and notices](third-party/texlyre/NOTICE.md).
Dependencies and bundled fonts retain their respective licenses. Network users
can download the corresponding application source through **Editor source**.
