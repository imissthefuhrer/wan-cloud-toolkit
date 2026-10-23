"""HEAD-only metadata validation. Never fetch model bodies or print signed URLs."""
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def metadata(url):
    opener = urllib.request.build_opener(NoRedirect)
    sha = size = None
    original = urllib.parse.urlsplit(url)
    for _ in range(11):
        target = urllib.parse.urlsplit(url)
        if target.scheme != "https" and not (target.scheme == "http" and target.hostname == "127.0.0.1"):
            raise ValueError("Unsafe metadata URL scheme")
        try:
            response = opener.open(urllib.request.Request(url, method="HEAD"), timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            headers = response.headers
            # Only trust linked metadata on the original origin, never a CDN's ETag.
            if (target.scheme, target.netloc) == (original.scheme, original.netloc):
                linked_sha = headers.get("x-linked-etag", "").strip('"')
                linked_size = headers.get("x-linked-size", "")
                if linked_sha or linked_size:
                    if not re.fullmatch(r"[0-9a-fA-F]{64}", linked_sha) or not linked_size.isdigit() or int(linked_size) <= 0:
                        raise ValueError("Invalid SHA-256/size metadata")
                    candidate = (linked_sha.lower(), int(linked_size))
                    if sha is not None and candidate != (sha, size):
                        raise ValueError("Conflicting redirect metadata")
                    sha, size = candidate
            if response.code in (301, 302, 303, 307, 308):
                location = headers.get("Location")
                if not location:
                    raise ValueError("Redirect without Location")
                url = urllib.parse.urljoin(url, location)
                continue
            if response.code != 200:
                raise ValueError(f"Final HEAD status {response.code}, expected 200")
            if sha is None:
                raise ValueError("Missing authoritative SHA-256/size metadata")
            length = headers.get("Content-Length")
            if length is None or not length.isdigit() or int(length) != size:
                raise ValueError("Final Content-Length differs from authoritative size or is missing")
            return sha, size
    raise ValueError("Too many redirects")


if __name__ == "__main__":
    try:
        digest, length = metadata(sys.argv[1])
        print(digest, length)
    except Exception as error:
        # Network exceptions can include signed URLs; disclose only their class.
        print(f"Metadata verification failed: {error if isinstance(error, ValueError) else type(error).__name__}", file=sys.stderr)
        sys.exit(1)
