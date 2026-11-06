# Hosting project.counthom.org

The production stack runs on the existing Linux Docker server. GitHub Actions
tests the source and publishes three versioned images to GitHub Container Registry
(GHCR). The server pulls those images; it does not install research toolchains or
build images. The default stack starts the app and isolated LaTeX worker. Codex is
an optional profile and requires its own login. Public source does not expose user
projects: accounts, files, Git histories, sessions, and agent state stay in volumes.

## 1. Publish the prepared repository

Run the public-tree check before the first commit. Local data and workstation
notes are ignored; do not use `git add --force` for them.

```powershell
python scripts/check_public_tree.py
gh auth login
git add .
git commit -m "Prepare research project tracker for deployment"
gh repo create project-tracker --public --source . --remote origin --push
```

Wait for **Test and publish** to finish on the main branch. It runs backend and
browser tests, builds the frontend, checks deployment syntax, and builds/publishes
`ghcr.io/OWNER/REPOSITORY/app:COMMIT`, `/latex:COMMIT`, and `/codex:COMMIT` for Linux
amd64. Image prefixes use lowercase owner/repository names. Every deployment uses
a full 40-character commit tag; no mutable `latest` tag is used for deployment.
Large optional CLI research tool images are not built by this workflow.

**Make all three GHCR packages public** in each package's settings after the first
publication. A public GitHub repository does not automatically make its packages
public. The bootstrap deliberately uses anonymous pulls; no GitHub credential is
copied to the server. See [GitHub's package visibility documentation](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

## 2. Run the PowerShell bootstrap

Prerequisites: Windows OpenSSH (`ssh` and `scp`), access to the existing Linux
server, and Docker Engine with Compose v2 on that server. The server also needs
`bash`, `curl`, `tar`, `flock`, and standard GNU utilities. No local Docker operation
is performed. The SSH user must either access Docker directly or be allowed to use
interactive `sudo docker`. Accept the server key only after verifying its fingerprint.

From this checkout:

```powershell
.\init.ps1 -Repository YOURNAME/project-tracker -Server deploy@curticapean.net
```

Or download the bootstrap from your public repository to an empty directory:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/YOURNAME/project-tracker/main/init.ps1 -OutFile init.ps1
.\init.ps1 -Repository YOURNAME/project-tracker -Server deploy@curticapean.net
```

`-Ref` accepts a branch, tag, or commit (default `main`) and resolves it to one
commit before downloading anything. Use a commit whose publish workflow succeeded.
The script downloads the corresponding installer and public source, then starts
the matching images. It does not upload your local database or files.

The default server installation is `$HOME/project-tracker`. Options:

```powershell
.\init.ps1 -Repository YOURNAME/project-tracker -Server deploy@curticapean.net -Ref FULL_COMMIT -InstallDirectory /home/deploy/project-tracker -AppPort 18765
```

The server directory contains:

- `production.env`: persistent non-secret settings. Existing settings are preserved.
- `secrets/setup-token`: random key for creating the first account; never logged by CI.
- `releases/COMMIT/`: source and effective deployment environment for that commit.
- `current`: symlink to the last successfully started release.
- `backups/`: consistent pre-update snapshots, private to the deployment user.
- `Caddyfile`: generated site block for the effective app port.

The initial setup key file is readable by the container's unprivileged UID, with a
private parent directory on the host. After successful startup, retrieve it over
SSH and enter it on the first-account screen:

```sh
cat "$HOME/project-tracker/secrets/setup-token"
```

Account setup is single-use. Subsequent users join through project invitations.

## 3. Connect the existing Caddy service

The provided fragment targets Caddy running as a **host service**, based on the
prior server setup. Verify the live configuration before applying it. The app
publishes only `127.0.0.1:18765`.
Do not expose that port through a firewall. Caddy handles HTTPS, Git HTTP requests,
and editor WebSockets. Secure cookies and the canonical HTTPS origin are enabled
in production; the plain HTTP loopback endpoint is only a backend/health endpoint.

Point the DNS A record for `project.counthom.org` at the same server as
`curticapean.net`. If you publish an AAAA record, it must point at that server too.
Ports 80 and 443 must already reach Caddy for certificate issuance.

Add the generated block to the existing `/etc/caddy/Caddyfile`, or copy it into a
directory that the existing Caddyfile already imports. **Keep every existing site
and route.** The default block is:

```caddyfile
project.counthom.org {
    encode zstd gzip
    reverse_proxy 127.0.0.1:18765
}
```

Back up the existing Caddyfile first, then validate and reload:

```sh
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-project-tracker
# Edit the existing file to add the block, preserving its other content.
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
curl --fail https://project.counthom.org/health
```

The bootstrap generates the fragment but does not rewrite the existing proxy
configuration. If the server's Caddy is actually a container, configure its
network/access to the backend first: `127.0.0.1` inside that container is not the
host loopback endpoint. Do not apply the host-service block unchanged in that case.
See [Caddy's reverse-proxy documentation](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## 4. Enable continuous deployment after the initial installation works

The default workflow tests/publishes only. Create a GitHub **production**
environment for deployment secrets and any desired approval rules. Use a dedicated
SSH key for CI. Its server account needs noninteractive Docker access; granting
Docker access gives that account control over the host, so protect the key.

Set these production environment secrets:

| Secret | Value |
| --- | --- |
| `DEPLOY_SSH_KEY` | Dedicated private SSH key, with matching public key in server `authorized_keys` |
| `DEPLOY_KNOWN_HOSTS` | Verified OpenSSH known-hosts entry for the server, including the hostname used below |

Set these production environment variables:

| Variable | Example |
| --- | --- |
| `DEPLOY_HOST` | `curticapean.net` |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_PATH` | `/home/deploy/project-tracker` (same directory used by bootstrap) |

Finally set the **repository** Actions variable `DEPLOY_ENABLED` to `true`.
Keeping it absent/false disables deployments. Now a successful main-branch
workflow deploys the exact commit it just tested/published. Pull requests cannot
deploy or publish. Strict SSH host-key checking stays enabled. Deployments are
serialized and are not cancelled halfway through an update.

## Updates, backups, and recovery

Run the same bootstrap again for a manual update. It downloads the new release
and pulls all required images **before** stopping the current stack. It then stops
writers, archives `/data` (including project files/Git histories), and archives
Codex state if its container exists. Credentials in those snapshots are sensitive.
The deployment stops if a backup fails. The new stack must become healthy before
the `current` link advances. This is a brief maintenance window, not a zero-downtime
deployment; the app intentionally uses a single process with SQLite.

A failed/interrupted update leaves a `failed-or-interrupted-deployment` marker.
Further updates refuse to proceed until you inspect and resolve that deployment.
After restoring consistent data/images (or confirming the new release is healthy
and fixing the release pointer), remove that marker deliberately. This prevents a
retry from pairing already-migrated data with an older release's backup metadata.

No workflow prunes Docker data, deletes volumes, or deletes old backups/releases.
Monitor disk use and retain/offload backups deliberately. For diagnostics:

```sh
cd "$HOME/project-tracker/current"
docker compose --project-name project-tracker --env-file deployment.env -f deploy/compose.yaml ps
docker compose --project-name project-tracker --env-file deployment.env -f deploy/compose.yaml logs --tail 100 app latex
```

An older image may not understand a migrated database. For recovery after a schema
change, stop app/Codex, preserve the failed deployment's data separately, restore
the **matching** `data.tar.gz` snapshot to the `project-tracker_app-data` and
`project-tracker_project-files` volumes, then start the commit recorded by that
backup's `previous.env`. Restore Codex's matching snapshot if used. Restoration
replaces data and is intentionally manual. Never run `down --volumes` on production.

To enable agents, set `COMPOSE_PROFILES=agents` in the server's `production.env`
and deploy again, then follow [Codex authentication](../docker/CODEX.md) using the
production Compose file/environment. Agent credentials belong in their volume;
never in GitHub, build arguments, source archives, or the browser. The agents'
Linux isolation/protocol checker still needs a successful real runtime run before
those boundaries can be claimed as validated.

Keep off-server backups of user data and agent state. Source hosting and GHCR
images are not backups of a running installation.
