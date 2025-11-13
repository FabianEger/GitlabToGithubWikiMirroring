#!/usr/bin/env python3
import os
import sys
import tempfile
import subprocess
import re
from typing import Tuple

def run(cmd, cwd=None, check=True):
    print(f"▶️ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=check)
# --- Regex patterns and helpers for link conversion ---

LINK_INLINE_RE = re.compile(
    r'''
    \[([^\]]+)\]                 # [label]
    \(                           # (
    \s*                          # optional space
    (?:\.\./|\.\/)+              # one or more ../ or ./
    \s*                          # optional space
    ([^\)\#\s][^\)\#]*?)         # page path (no ) or # or space)
    (\#[^\)\s]+)?                # optional anchor
    \s*                          # optional space
    \)                           # )
    ''',
    re.VERBOSE | re.UNICODE
)

REF_LINK_RE = re.compile(
    r'''
    ^\s*                         # line start
    \[([^\]]+)\]:                # [label]:
    \s*                          # optional space
    (?:\.\./|\.\/)+              # one or more ../ or ./
    \s*                          # optional space
    ([^\s#][^\s#]*)              # path
    (\#[^\s]+)?                  # optional anchor
    (?:\s+["\'].+["\'])?         # optional "title"
    \s*$                         # end of line
    ''',
    re.VERBOSE | re.MULTILINE | re.UNICODE
)

def _replace_inline_match(m: re.Match) -> str:
    label = m.group(1)
    path = m.group(2).strip()
    anchor = m.group(3) or ""
    return f"[{label}]({path}{anchor})"

def _replace_ref_match(m: re.Match) -> str:
    label = m.group(1)
    path = m.group(2).strip()
    anchor = m.group(3) or ""
    return f"[{label}]: {path}{anchor}"

def convert_gitlab_wiki_links_in_dir(wiki_dir: str, verbose: bool = True) -> Tuple[int, int]:
    """
    Walk wiki_dir and convert GitLab-style relative links like (../Page) or (./Page)
    to GitHub-style links like (Page).
    Returns (files_changed, total_replacements)
    """
    files_changed = 0
    total_replacements = 0

    for root, _, files in os.walk(wiki_dir):
        for filename in files:
            if not filename.lower().endswith((".md", ".markdown")):
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                with open(filepath, "r", encoding="latin1") as fh:
                    content = fh.read()

            new_content = content
            new_content, n1 = LINK_INLINE_RE.subn(_replace_inline_match, new_content)
            new_content, n2 = REF_LINK_RE.subn(_replace_ref_match, new_content)
            n = n1 + n2

            if n > 0:
                with open(filepath, "w", encoding="utf-8") as fh:
                    fh.write(new_content)
                    print(new_content)
                files_changed += 1
                total_replacements += n
                if verbose:
                    print(f"{n} link(s) fixed in: {filepath}")

    print(f"\n Link conversion completed — {files_changed} file(s) updated, {total_replacements} total replacements.")
    return files_changed, total_replacements



def copy_github_wiki(src_repo, dst_repo, token=None):
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_prefix = f"https://{token}:x-oauth-basic@" if token else "https://"
        gitlab_url = src_repo
        github_url = dst_repo

        print(f"Cloning wiki from GitLab: {gitlab_url}")
        try:
            run(["git", "clone", gitlab_url, tmpdir])
        except subprocess.CalledProcessError:
            print("Source wiki not found — exiting.")
            return

        # Set up new remote
        print(f"Setting new remote to GitHub wiki: {github_url}")
        run(["git", "remote", "set-url", "origin", github_url], cwd=tmpdir)
        

        # Rewrite internal links
        convert_gitlab_wiki_links_in_dir(tmpdir,verbose=True)
        
        # git add and commit if there are changes
        # Check git status
        status = subprocess.run(["git", "status", "--porcelain"], cwd=tmpdir, capture_output=True, text=True)
        changed = status.stdout.strip()
        if changed:
            print("Changes detected, staging and committing...")
            run(["git", "add", "-A"], cwd=tmpdir)
            # commit with a clear message
            try:
                run(["git", "commit", "-m", "chore: rewrite GitLab-style relative wiki links for GitHub"], cwd=tmpdir)
            except subprocess.CalledProcessError:
                # possible no changes to commit (race) — continue
                print("Nothing to commit after staging (maybe identical content).")
        else:
            print("No changes detected after link rewrite (nothing to commit).")


        # Ensure correct branch name (GitHub wikis use 'main')
        try:
            run(["git", "checkout", "master"], cwd=tmpdir)
        except subprocess.CalledProcessError:
            run(["git", "branch", "-M", "master"], cwd=tmpdir)

        print("🚀 Pushing wiki to GitHub...")
        try:
            run(["git", "push", "origin", "master", "--force"], cwd=tmpdir)
        except subprocess.CalledProcessError:
            print("GitHub wiki not initialized — creating it.")
            home_path = os.path.join(tmpdir, "Home.md")
            if not os.path.exists(home_path):
                with open(home_path, "w") as f:
                    f.write(f"# {github_url} Wiki\n\n(Initialized from GitLab)")
                run(["git", "add", "Home.md"], cwd=tmpdir)
                run(["git", "commit", "-m", "Initialize wiki"], cwd=tmpdir)
            run(["git", "push", "-u", "origin", "master", "--force"], cwd=tmpdir)

        print("Wiki copied successfully from GitLab → GitHub!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python copy_wiki.py <source_repo> <destination_repo> [github_token]")
        print("Example: python copy_wiki.py user1/source-repo user2/dest-repo ghp_XXXXXXX")
        sys.exit(1)

    src_repo = sys.argv[1]
    dst_repo = sys.argv[2]
    token = sys.argv[3] if len(sys.argv) > 3 else None

    copy_github_wiki(src_repo, dst_repo, token)
