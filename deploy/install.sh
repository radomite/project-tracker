#!/usr/bin/env bash
# Called by init.ps1 and CI. Downloads exactly one public GitHub commit.
set -Eeuo pipefail
umask 077

if [[ $# != 5 ]]; then
    echo 'Usage: install.sh OWNER/REPO FULL_COMMIT INSTALL_DIR|- DOMAIN PORT' >&2
    exit 2
fi
repository=$1 revision=$2 install_dir=$3 domain=$4 port=$5
[[ $repository =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || exit 2
[[ $revision =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ $domain =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && $domain == *.* && $domain != *..* ]] || exit 2
[[ $port =~ ^[0-9]{2,5}$ && $port -ge 1024 && $port -le 65535 ]] || exit 2
[[ $install_dir != - ]] || install_dir="$HOME/project-tracker"
[[ $install_dir =~ ^/[A-Za-z0-9_./-]+$ && $install_dir != / && $install_dir != *..* ]] || exit 2
for dependency in curl tar od flock docker; do command -v "$dependency" >/dev/null; done
docker_cli=(docker)
if ! docker info >/dev/null 2>&1; then
    command -v sudo >/dev/null
    sudo -v
    docker_cli=(sudo docker)
fi
"${docker_cli[@]}" compose version >/dev/null

mkdir -p "$install_dir"
install_dir=$(cd "$install_dir" && pwd -P)
exec 9>"$install_dir/deployment.lock"
flock -n 9 || { echo 'Another deployment is active.' >&2; exit 1; }
pending="$install_dir/failed-or-interrupted-deployment"
if [[ -e $pending ]]; then
    echo "Resolve the previous interrupted/failed deployment before retrying: $pending" >&2
    exit 1
fi
mkdir -p "$install_dir/releases" "$install_dir/secrets" "$install_dir/backups"
chmod 700 "$install_dir/secrets" "$install_dir/backups"
secret="$install_dir/secrets/setup-token"
if [[ ! -e $secret ]]; then
    # Readable by the container's UID 1000; the parent is private on the host.
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n' >"$secret"
    chmod 644 "$secret"
fi
[[ $(wc -c <"$secret") -ge 32 ]] || { echo 'Invalid setup key file.' >&2; exit 1; }

settings="$install_dir/production.env"
if [[ ! -e $settings ]]; then
    prefix="ghcr.io/${repository,,}"
    printf 'IMAGE_PREFIX=%s\nPUBLIC_ORIGIN=https://%s\nAPP_PORT=%s\nSETUP_TOKEN_FILE=%s\nCOMPOSE_PROFILES=\n' \
        "$prefix" "$domain" "$port" "$secret" >"$settings"
fi
# Do not source a .env file as shell code. Compose handles its values.
effective_origin=$(grep '^PUBLIC_ORIGIN=' "$settings" | cut -d= -f2-)
[[ $effective_origin == "https://$domain" ]] || {
    echo 'PUBLIC_ORIGIN differs from the requested domain; check production.env first.' >&2; exit 1;
}
[[ $(grep -c '^IMAGE_TAG=' "$settings" || true) == 0 ]] || {
    echo 'Keep IMAGE_TAG out of production.env; deploy a specific commit instead.' >&2; exit 1;
}

release="$install_dir/releases/$revision"
stage=$(mktemp -d "$install_dir/.staging.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
if [[ ! -d $release ]]; then
    curl --fail --location --retry 3 --proto '=https' \
        "https://codeload.github.com/$repository/tar.gz/$revision" -o "$stage/source.tar.gz"
    mkdir "$stage/source"
    tar -xzf "$stage/source.tar.gz" --strip-components=1 -C "$stage/source"
    test -f "$stage/source/deploy/compose.yaml"
    mv "$stage/source" "$release"
fi
cat "$settings" >"$release/deployment.env"
printf '\nIMAGE_TAG=%s\n' "$revision" >>"$release/deployment.env"
dc() { "${docker_cli[@]}" compose --project-name project-tracker --env-file "$release/deployment.env" --file "$release/deploy/compose.yaml" "$@"; }
dc config --quiet
current="$install_dir/current"
if [[ -e $current && ! -L $current ]]; then
    echo 'The current release path must be a deployment-managed symlink.' >&2; exit 1;
fi
if [[ ! -L $current && -n $(dc ps -a -q app) ]]; then
    echo 'Existing project-tracker containers have no matching current release; resolve the installation path first.' >&2
    exit 1
fi
services=(app latex)
if dc config --services | grep -qx codex; then services+=(codex); fi
# Pull everything before stopping the current version. Never build on the server.
dc pull "${services[@]}"
printf '%s\n' "$revision" >"$pending"
if [[ -L $current ]]; then
    previous=$(readlink -f "$current")
    old() { "${docker_cli[@]}" compose --project-name project-tracker --env-file "$previous/deployment.env" --file "$previous/deploy/compose.yaml" "$@"; }
    old_services=(app latex)
    app_id=$(old ps -a -q app)
    codex_id=$(old --profile agents ps -a -q codex)
    if [[ -n $codex_id ]]; then old_services+=(codex); fi
    if [[ -n $app_id ]]; then
        backup="$install_dir/backups/$(date -u +%Y%m%dT%H%M%SZ)-$revision"
        mkdir -p "$backup"
        old stop "${old_services[@]}"
        old_image=$("${docker_cli[@]}" inspect --format '{{.Image}}' "$app_id")
        if ! "${docker_cli[@]}" run --rm --pull never --network none --cap-drop ALL \
            --security-opt no-new-privileges:true --volumes-from "$app_id:ro" \
            --entrypoint tar "$old_image" -C /data -czf - . >"$backup/data.tar.gz"; then
            echo 'Backup failed; restarting the previous stack.' >&2
            old start "${old_services[@]}"
            rm -- "$pending"
            exit 1
        fi
        if [[ -n $codex_id ]]; then
            codex_image=$("${docker_cli[@]}" inspect --format '{{.Image}}' "$codex_id")
            if ! "${docker_cli[@]}" run --rm --pull never --network none --user 0 --cap-drop ALL --cap-add DAC_READ_SEARCH \
                --security-opt no-new-privileges:true --volumes-from "$codex_id:ro" \
                --entrypoint tar "$codex_image" -C /state -czf - . >"$backup/codex-state.tar.gz"; then
                echo 'Agent backup failed; restarting the previous stack.' >&2
                old start "${old_services[@]}"
                rm -- "$pending"
                exit 1
            fi
        fi
        cp "$previous/deployment.env" "$backup/previous.env"
        echo "Consistent stopped-stack backup: $backup"
    fi
fi
if ! dc up --detach --no-build --wait --wait-timeout 180 "${services[@]}"; then
    echo 'Deployment failed. Inspect compose logs. Previous data backups are retained.' >&2
    echo 'Do not roll back images across a database migration without restoring the matching data.' >&2
    exit 1
fi
ln -sfn "$release" "$install_dir/current.next"
mv -Tf "$install_dir/current.next" "$current"
rm -- "$pending"
# Use the actual effective Compose settings when preparing the Caddy fragment.
effective_port=$(dc port app 8765 | sed 's/.*://')
printf '%s {\n    encode zstd gzip\n    reverse_proxy 127.0.0.1:%s\n}\n' "$domain" "$effective_port" >"$install_dir/Caddyfile"
echo "Running commit: $revision"
echo "Caddy site fragment: $install_dir/Caddyfile"
echo "Initial setup key file: $secret (not printed in deployment logs)"
echo "Once Caddy imports that fragment and DNS points here, open https://$domain"
