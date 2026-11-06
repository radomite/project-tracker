# Docker Compose

The web app runs separately from on-demand research tools. Install Docker with
Compose on the host; Python, Git, Typst, TeX Live, Lean/mathlib, and SageMath are
provided inside the images. Frontend assets are generated from the lockfile during
the app image build.

| Service | Contents | Default invocation |
| --- | --- | --- |
| `app` | Python, FastAPI, Git smart HTTP | One Uvicorn process, port 8765 |
| `codex` | Codex app-server supervisor, one Astra and one Sol identity per project | Optional `agents` profile; see [project agents](./CODEX.md) |
| `git` | Git, using the small app image | `git --version` |
| `python` | Python 3.13 | `python --version` |
| `typst` | Typst 0.15.1 | `typst --version` |
| `texlive` | Full TeX Live, including latexmk | `latexmk -v` |
| `lean` | Lean 4.35.0 and cached mathlib v4.35.0 | `lean --version` |
| `sagemath` | SageMath 10.10 | `sage --version` |

Git also stays inside `app` because the existing authenticated HTTP backend and
receive hooks run there and update its main working tree. The `git` service is
for client operations on working copies. The other tools share no Python
environment with the app or with each other.

## Start the app

From the repository root:

```text
docker compose config --quiet
docker compose up --detach --build app
```

Open http://127.0.0.1:8765 and create the first account. There is no default
password. Only the app starts; the tools profile is idle until a tool is requested.
The local Python server uses the same default port: stop it before starting this
service, or copy `.env.example` to `.env` and choose another `APP_PORT`.

The HTTP endpoint also serves each project's Git remote, with the same project
keys used by the local app. The Files page edits main and retains batched commits
and the read-only graph of all branches.

```text
docker compose logs --tail 100 app
docker compose stop app
docker compose up --detach app
```

Docker Desktop must use Linux containers. Host binding defaults to loopback.
`APP_BIND` and `APP_PORT` control the published address. If an HTTPS reverse proxy
is added later, set `RESEARCH_SECURE_COOKIE=1`; local HTTP uses 0.

## Run tools

The committed examples live in `tool-workspace/examples/`. Tool containers use
`/work` for that host folder and put generated output in `/work/output`. Each run
is disposable; source files, output, and package caches under `/work/.cache` remain
on the host. No tool binaries or SDKs are installed on the host.

```text
docker compose run --rm git --version
docker compose run --rm python examples/check.py
docker compose run --rm typst compile examples/hello.typ output/typst.pdf
docker compose run --rm texlive latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=/work/output examples/hello.tex
docker compose build lean
docker compose run --rm lean examples/Proof.lean
docker compose run --rm sagemath examples/check.sage
```

`run` automatically enables the requested tool's profile. These commands do not
require all tools to be running. The first pulls/builds are large, particularly
TeX Live, SageMath, and the compiled mathlib cache. Budget tens of gigabytes on
Docker's storage drive before preparing all toolchains. To prepare them in advance:

```text
docker compose build app lean
docker compose --profile tools pull python typst texlive sagemath
```

`TOOL_WORKSPACE` can select a different **existing** host folder. On Linux, set
`TOOL_UID` and `TOOL_GID` in `.env` to your `id -u` and `id -g` so output is writable
by your account; both default to 1000. The containers use an unprivileged numeric
user, a read-only root filesystem, and temporary home directories. Their caches
and generated files are written to the working folder.

The verified upstream Sage image is amd64-only, so its service explicitly selects
`linux/amd64`. ARM hosts need Docker's amd64 emulation or an alternative compatible
image supplied through `SAGEMATH_IMAGE`.

## Working with project files

App-owned project repositories are mounted read-only at `/projects/<project-id>`
inside every tool. This includes pending browser edits. The database volume is
not mounted into tools. For a stable source version, clone the project remote
into the tool working folder:

```text
docker compose run --rm git clone http://token@app:8765/git/projects/123.git my-project
docker compose run --rm --workdir /work/my-project texlive latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
docker compose run --rm git -C my-project add main.tex
docker compose run --rm git -C my-project -c user.name="Your name" -c user.email="you@example.org" commit -m "Update proof"
docker compose run --rm git -C my-project push origin main
```

Use a project key as the Git password when prompted. `app` is the Compose network
hostname; from the host use the published localhost URL instead. Tool changes are
made in the clone and pushed through the authenticated remote. They do not bypass
the app by writing directly into its repositories.

The tool containers provide command-line execution. Connecting web editor compile
actions to container jobs is a separate application feature; the app has no Docker
socket or container-management privilege.

## Lean and mathlib

The Lean image checks out mathlib commit
`56a005855ea17e0b0958f73ec801ae140b0a1679` (release v4.35.0), installs the compiler
specified in that checkout's `lean-toolchain`, and fetches its compiled artifacts
with `lake exe cache get`. The build then checks a proof importing Mathlib. The
Elan installer is versioned and checksum-verified for amd64/arm64.

`lean` runs standalone files with the bundled mathlib and its dependency paths.
It calls the installed compiler directly, so a stray host toolchain file cannot
silently install a different compiler. `docker compose run --rm lean lake build`
uses Lake for a full project in the working folder; its dependency configuration
must match the bundled compiler. That project's dependencies and build artifacts
are managed by its own Lake configuration.

To change mathlib, set `MATHLIB_REVISION` to a full commit SHA and rebuild `lean`.
The corresponding Lean version follows automatically. Compiler/version changes
may require proof changes. Image digests are pinned in `compose.yaml` and the
Dockerfiles; image variables in Compose allow deliberate updates. Debian package
repositories and PyPI transitive dependencies still follow their repositories;
this is a version-pinned toolchain, not a byte-for-byte offline rebuild lock.

## Persistence and backups

Two named volumes are used:

- `app-data`: SQLite database, WAL, and database migration backups under `/data`.
- `project-files`: working trees, Git histories, and pending edit journals mounted
  at `/data/research-files` in the app and `/projects` read-only in tools.

Compose uses its project name as a prefix for both volumes. A normal
`docker compose down` preserves them. `down --volumes` deletes that project's data.
Back up both volumes together with the app stopped. Tool working copies/output
are in the host `tool-workspace` folder and are backed up separately.

The Docker setup starts with its own volumes; it does not automatically copy or
change the existing local database. To migrate a stopped local app into **fresh,
empty** container volumes:

```text
docker compose build app
docker compose create app
docker compose cp data/. app:/data/
docker compose run --rm --no-deps --user 0 --cap-add CHOWN --entrypoint /bin/sh app -c "chown -R 1000:1000 /data"
docker compose up --detach app
```

Copy both the database and its matching research-files directory. For custom
database names, retain the app's canonical container layout (`research.db` and
`research-files`). Existing Git receive-hook paths are refreshed on access, so
repositories moved from Windows receive the container's hook/Python paths.

## Validate in isolation

```text
python scripts/check_containers.py
python scripts/check_containers.py --tools
```

The helper uses host Python's standard library to control Docker; it installs no
host dependencies. It creates a fresh random Compose project and working folder
under `.checks`, runs the backend suite inside Docker, checks HTTP, real Git
clone/push between containers, read-only source mounts, and database/pending-edit
persistence across restart. `--tools` also compiles the Typst/TeX examples, checks
the Lean proof with mathlib, and runs the Python/Sage computations. PDF checks are
compilation and file-header checks only; no visual PDF inspection is performed.
Only that disposable project's containers and volumes are removed afterward.
The checker refuses to start below 5 GiB free on the workspace drive, or 30 GiB
with `--tools`. Docker's storage drive must also have enough space if it is on a
different drive. `--min-free-gb` deliberately overrides this preflight estimate.

The complete optional toolchain and real Codex isolation checks are not claimed
as validated. Run the relevant checker on the intended Docker host before relying
on those integrations. Allow tens of gigabytes for the full research tool bundle.

## Upstream references

- [Typst's maintained image and CLI](https://github.com/typst/typst#installation).
- [TeX Live images and full scheme](https://github.com/islandoftex/texlive#readme).
- [Mathlib release](https://github.com/leanprover-community/mathlib4/releases/tag/v4.35.0),
  [matching compiler](https://github.com/leanprover-community/mathlib4/blob/v4.35.0/lean-toolchain),
  and [compiled cache](https://github.com/leanprover-community/mathlib4/tree/master/Cache).
- [SageMath's maintained Docker image](https://hub.docker.com/r/sagemath/sagemath).
