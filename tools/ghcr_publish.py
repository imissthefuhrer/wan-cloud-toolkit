"""Fail-closed GHCR visibility/tag guards and digest reporting for manual CI."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request

IMAGE = 'ghcr.io/imissthefuhrer/wan-cloud-toolkit'
PACKAGE = '/users/imissthefuhrer/packages/container/wan-cloud-toolkit'


def api(path):
    token = os.environ.get('GH_TOKEN')
    if not token:
        raise RuntimeError('GH_TOKEN must contain the job GITHUB_TOKEN')
    request = urllib.request.Request('https://api.github.com' + path, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        # Never print headers, token, or response bodies.
        raise RuntimeError(f'GitHub package API HTTP {error.code}; check package Actions access and job permissions') from None


def guard(tag, before_push):
    if not re.fullmatch(r'git-[0-9a-f]{40}', tag):
        raise RuntimeError('Expected a full commit-based git-SHA tag')
    package = api(PACKAGE)
    if package is None:
        if before_push:
            print('Package not found; first GHCR publication defaults to private')
            return
        raise RuntimeError('Published package is not visible to the job; privacy could not be verified')
    if package.get('visibility') != 'private':
        raise RuntimeError('Refusing publication: GHCR package must be private; no visibility changes were made')
    if before_push:
        page = 1
        while True:
            versions = api(PACKAGE + f'/versions?per_page=100&page={page}')
            if not isinstance(versions, list):
                raise RuntimeError('Cannot list package tags; refusing to overwrite a commit tag')
            for version in versions:
                if tag in version.get('metadata', {}).get('container', {}).get('tags', []):
                    raise RuntimeError(f'Commit tag {tag} already exists; it will not be overwritten. Use its existing registry digest')
            if len(versions) < 100:
                break
            page += 1
    print('GHCR package visibility verified: private')


def disk_check(minimum_gib=12):
    free = shutil.disk_usage('/').free / 1024**3
    print(f'Runner root filesystem free: {free:.1f} GiB (required: {minimum_gib} GiB)')
    if free < minimum_gib:
        raise RuntimeError('Insufficient runner disk space. Select a larger CPU runner; no files were removed')


def registry_digest(entries):
    matches = {entry for entry in entries if re.fullmatch(re.escape(IMAGE) + r'@sha256:[0-9a-f]{64}', entry)}
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one pushed registry RepoDigest; never use the local image ID')
    return matches.pop()


def report(path):
    reference = registry_digest(json.loads(Path(path).read_text()))
    digest = reference.split('@', 1)[1]
    print(f'RunPod image: {reference}')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'digest={digest}\nimage={reference}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write(f'## Private RunPod image published\n\nTemplate image (copy exactly):\n\n`{reference}`\n\n'
                      f'Commit tag: `git-{os.environ["GITHUB_SHA"]}`\n\n'
                      'Platform: `linux/amd64`. Package visibility verified private.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'private', 'disk', 'report'))
    parser.add_argument('--tag')
    parser.add_argument('--repodigests')
    args = parser.parse_args()
    try:
        if args.mode == 'disk':
            disk_check()
        elif args.mode == 'report':
            report(args.repodigests)
        else:
            guard(args.tag, args.mode == 'preflight')
    except Exception as error:
        print(f'GHCR publish check failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
