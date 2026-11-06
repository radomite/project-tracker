# Project agents

Every new and existing project gets two persistent identities:

| Agent | Model | Role |
| --- | --- | --- |
| Astra | `gpt-6-astra`, high reasoning | Research, questions, evidence and proof gaps |
| Sol | `gpt-6.1-sol`, medium reasoning | Editing prose, source files and code |

Open **Project agents** in the project navigation to send requests, see results,
cancel queued/running work, read agent messages, and assign project clusters.
The app shows whether the Codex service is connected. A disconnected configured
service can retain queued requests. Creating a project does not start inference.
The selected models must be available to the account; errors are reported without
silently substituting another model.

## Project clusters

Projects can belong to zero or more named clusters. Astra and Sol can always
exchange messages within their project. Agents from two different projects can
exchange messages if those projects share at least one approved cluster. A
project belonging to clusters A and B does not grant access between every other
project in A and every other project in B.

Create a cluster on the agent page, then assign each project on its own agent
page. Assignments need both the cluster owner's and project owner's approval.
When these are the same person, one assignment action supplies both approvals.
A cluster owner must have project membership to invite a project. For different
owners, the invited project's owner confirms the pending assignment on that
project's agent page. Either owner can remove it. Ordinary collaborators and
agents cannot grant themselves cluster access. Project links confer no agent
permissions. Cluster participants can see names of the projects invited to that
cluster; this does not grant human access to another project's discussions/files.

Permissions are checked when listing peers, sending messages, and reading the
mailbox. Removal blocks future exchanges and hides previous messages from that
mailbox if no other shared cluster remains. Previously read information cannot
be erased from a recipient's persistent context. Messages are stored in the app
and read on the recipient's next requested turn; they do not start paid inference
or create autonomous conversation loops.

## Runtime boundary

The optional `codex` Compose service is a trusted supervisor for Codex app-server
processes. It pulls leased jobs from the main app over the private Compose network
and sends tool requests/results back. There is no public Codex port and no Docker
socket. App database/files volumes and the host workspace are not mounted into
this service.

Each project/role has its own Linux UID, private working directory, `CODEX_HOME`,
login copy, and saved thread. The supervisor runs as container root to create
these identities, then drops UID, GID and supplementary groups for every Codex
child. Its capabilities are explicitly limited. Children do not inherit app
credentials, other projects' environment, or proxy settings. The supervisor's
app credential is readable only by container root and the app's group 1000;
worker UIDs/groups start above 20000.
Stable random identities and a persistent UID allocator prevent database ID reuse
from attaching a new agent to another agent's previous state.

Codex turns explicitly request restricted filesystem reads, writes only to their
private workspace, and no shell-tool network access. Elevated permission requests
are denied; there is no unrestricted fallback. Live web search uses Codex's
provider tool. Additional agents and configured MCP servers are disabled. All
actual project access goes through one model-facing `project_tool`; the app
derives agent/project identity from the lease and rejects project selectors.
Its operations are project context, file listing/reading/writing, permitted
peers, message sending, and inbox. No general HTTP proxy or raw app API token is
given to the model. Shared-cluster communication discloses only explicitly sent
messages, not another project's files or full conversation.

File writes require the current etag before overwriting and use the same pending
Git journal as UI edits. They neither create branches nor commit each save.
One active request per agent is allowed, with two concurrent workers globally
and a 30 minute turn limit. Cancelled/expired leases cannot call project tools.
Lost running requests fail rather than replaying possibly completed side effects.
Persistent state resumes the same thread on the next request.

## Start the optional service

Keep Docker's data directory on a disk with enough free space for images, cache,
and volumes. The commands below install nothing on the host. For server hosting,
use the [production deployment files](../deploy/README.md) and its Compose project,
environment, and file arguments instead of the development defaults.

```text
.\scripts\docker-h-drive.ps1 compose --profile agents config --quiet
.\scripts\docker-h-drive.ps1 compose --profile agents build app codex
.\scripts\docker-h-drive.ps1 compose --profile agents run --rm --no-deps --entrypoint codex codex login --device-auth
.\scripts\docker-h-drive.ps1 compose --profile agents up --detach app codex
```

The CLI version is pinned to `0.167.0` (`TRACKER_CODEX_VERSION` overrides it; the
host's unrelated `CODEX_VERSION` variable is deliberately ignored). Device login may need enabling in the
account/workspace. Alternatively use the documented CLI `login --with-api-key`
stdin flow inside the one-off container, with a secret supplied at runtime.
Never put keys in the Dockerfile, build arguments, `.env`, prompts, or shell
command literals. The login is stored in the dedicated `codex-state` volume;
the host's Codex home is not mounted or copied. Each account's billing/model
access rules continue to apply.

The `agent-link` volume contains a random supervisor credential generated at
startup. It is mounted read-only in the app. `codex-state` contains private
credentials, agent workspaces, and conversation histories. Preserve both volumes
along with the app database. Normal `docker compose down` retains volumes.

## Verification status

Local API and mock JSONL tests cover the role identities, queue/lease lifecycle,
concurrent claims, scoped context, file conflict checks, cluster approval and
revocation, non-transitive cluster overlap, and mailbox permissions. The browser
check covers project navigation, both agents, offline status, prompt drafts,
cluster creation/removal and messages. Compose configuration is parsed without
starting services.

Real Codex authentication, model turns, pinned-runtime protocol compatibility,
and Linux filesystem/network sandbox isolation still require the dedicated
container smoke test on the intended host.
`python scripts/check_containers.py --agents --work-root /path/to/check-workspace`
runs the prepared offline runtime/app-bridge checks without inference. Passing a mocked protocol test is not evidence of
container isolation. If the host blocks Codex's Linux sandbox, retain the block;
do not add privileged mode, a Docker socket, or disable sandboxing to bypass it.

Official references used: [app-server protocol](https://learn.chatgpt.com/docs/app-server),
[authentication](https://learn.chatgpt.com/docs/auth),
[model IDs](https://developers.openai.com/api/docs/guides/latest-model), and
[CLI release pin](https://learn.chatgpt.com/docs/changelog).
