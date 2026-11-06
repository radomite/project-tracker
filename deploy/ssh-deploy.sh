#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
: "${DEPLOY_HOST:?Set DEPLOY_HOST}"
: "${DEPLOY_USER:?Set DEPLOY_USER}"
: "${DEPLOY_PATH:?Set DEPLOY_PATH}"
: "${DEPLOY_SSH_KEY:?Set DEPLOY_SSH_KEY}"
: "${DEPLOY_KNOWN_HOSTS:?Set DEPLOY_KNOWN_HOSTS}"
: "${GITHUB_REPOSITORY:?}"
: "${GITHUB_SHA:?}"
[[ $DEPLOY_HOST =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || exit 2
[[ $DEPLOY_USER =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || exit 2
[[ $GITHUB_SHA =~ ^[a-f0-9]{40}$ ]] || exit 2
ssh_dir=$(mktemp -d)
trap 'rm -rf -- "$ssh_dir"' EXIT
printf '%s\n' "$DEPLOY_SSH_KEY" >"$ssh_dir/key"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" >"$ssh_dir/known_hosts"
options=(-i "$ssh_dir/key" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$ssh_dir/known_hosts")
target="$DEPLOY_USER@$DEPLOY_HOST"
remote_file="project-tracker-install-$GITHUB_SHA.sh"
scp "${options[@]}" deploy/install.sh "$target:$remote_file"
printf -v command 'bash %q %q %q %q %q %q' "$remote_file" "$GITHUB_REPOSITORY" "$GITHUB_SHA" "$DEPLOY_PATH" "${DEPLOY_DOMAIN:-project.counthom.org}" 18765
ssh "${options[@]}" "$target" "$command"
