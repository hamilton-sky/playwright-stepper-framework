#!/usr/bin/env bash
#
# purge-model-history.sh — remove the vendored ML model from git history.
#
# WHAT THIS IS FOR
#   stepper/models/all-MiniLM-L6-v2/model.safetensors (87MB) was committed to
#   this repository. It has since been removed from the working tree, so new
#   commits no longer carry it — but every commit made before that removal
#   still does. `git clone` walks the whole history, so a fresh clone still
#   pays ~85MB for a file `python stepper/download_models.py` fetches on demand.
#
#   Removing it from history is the only way to get that back, and it rewrites
#   every commit hash from the model's first appearance onward.
#
# WHY THIS IS A SCRIPT AND NOT SOMETHING ALREADY DONE FOR YOU
#   This rewrites shared history and needs a force-push to the default branch.
#   That breaks every existing clone: anyone with work in flight has to re-clone
#   or rebase onto the new history, and open pull requests will need rebasing.
#   That is a call for whoever owns the repository to make, with whoever else is
#   working in it, not something to land inside an unrelated change.
#
# BEFORE YOU RUN IT
#   1. Tell every collaborator. They should push or stash anything unpushed.
#   2. Merge or note every open pull request — each one needs rebasing after.
#   3. Check whether branch protection on the default branch allows force-push;
#      you will need to lift it for the push and put it back afterwards.
#
# USAGE
#   ./scripts/purge-model-history.sh /tmp/stepper-purge
#
#   Runs against a FRESH CLONE at the path you give (git-filter-repo requires
#   one). Your working copy is never touched. Nothing is pushed — the script
#   stops before that and prints the command, so you can inspect the result.
#
set -euo pipefail

WORKDIR="${1:-}"
REMOTE_DEFAULT="$(git config --get remote.origin.url 2>/dev/null || true)"
TARGET_PATH="stepper/models"

if [[ -z "$WORKDIR" ]]; then
    echo "usage: $0 <empty-directory-for-the-fresh-clone>" >&2
    echo "example: $0 /tmp/stepper-purge" >&2
    exit 2
fi

if [[ -z "$REMOTE_DEFAULT" ]]; then
    echo "error: no origin remote found; run this from inside the repo." >&2
    exit 2
fi

if ! command -v git-filter-repo >/dev/null 2>&1 && ! python -c "import git_filter_repo" 2>/dev/null; then
    cat >&2 <<'MSG'
error: git-filter-repo is not installed.

    pip install git-filter-repo

git-filter-branch can do this too, but it is orders of magnitude slower and
mangles tags and refs in ways filter-repo does not. Use filter-repo.
MSG
    exit 2
fi

if [[ -e "$WORKDIR" ]]; then
    echo "error: $WORKDIR already exists — give me a path that does not." >&2
    exit 2
fi

echo "==> Cloning $REMOTE_DEFAULT into $WORKDIR (fresh clone, as filter-repo requires)"
git clone --no-local "$REMOTE_DEFAULT" "$WORKDIR"
cd "$WORKDIR"

BEFORE="$(du -sh .git | cut -f1)"
echo "==> .git before: $BEFORE"

echo "==> Stripping $TARGET_PATH from every commit"
git filter-repo --path "$TARGET_PATH" --invert-paths --force

AFTER="$(du -sh .git | cut -f1)"
echo "==> .git after:  $AFTER"

echo
echo "==> Verifying the blob is gone"
if git rev-list --objects --all | grep -q "model.safetensors"; then
    echo "    FAILED — model.safetensors is still reachable. Do not push." >&2
    exit 1
fi
echo "    clean: no model.safetensors object remains"

echo
echo "==> Verifying the tree still builds"
python -m pytest stepper/tests/unit/ -q -o addopts="" 2>&1 | tail -3

cat <<MSG

────────────────────────────────────────────────────────────────────────────
Rewrite complete in $WORKDIR — .git went $BEFORE -> $AFTER.
NOTHING HAS BEEN PUSHED.

Inspect it, then when you and your collaborators are ready:

    cd $WORKDIR
    git remote add origin $REMOTE_DEFAULT     # filter-repo drops the remote on purpose
    git push --force --all origin
    git push --force --tags origin

Afterwards, everyone else runs:

    git fetch origin
    git reset --hard origin/<their-branch>    # or re-clone

Open pull requests will need rebasing onto the rewritten history.
────────────────────────────────────────────────────────────────────────────
MSG
