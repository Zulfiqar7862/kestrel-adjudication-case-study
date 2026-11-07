"""Check local Markdown links/images, fragments, inline diagram sources and media."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit


def anchors(text):
    clean = re.sub(r"```.*?```", "", text, flags=re.S)
    found = set(re.findall(r"<a\s+(?:id|name)=[\"\']([^\"\']+)", clean))
    counts = Counter()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", clean, re.M):
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower().strip()).replace(" ", "-")
        unique = slug + (f"-{counts[slug]}" if counts[slug] else "")
        counts[slug] += 1
        found.add(unique)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    files = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    failures, external = [], set()
    checked = 0
    for file in files:
        text = file.read_text()
        clean = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)", clean):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                external.add(target)
                continue
            destination = (file.parent / unquote(url.path)).resolve() if url.path else file
            checked += 1
            if not destination.exists():
                failures.append(f"{file.relative_to(root)}: missing {target}")
            elif (
                url.fragment
                and destination.suffix == ".md"
                and unquote(url.fragment) not in anchors(destination.read_text())
            ):
                failures.append(f"{file.relative_to(root)}: missing fragment {target}")
    for source in (root / "docs/diagrams").glob("*.mmd"):
        content = source.read_text().strip()
        if not any(content in p.read_text() for p in files if p.parent == root / "docs"):
            failures.append(f"{source.name}: source not kept inline in a current guide")
        image = root / "docs/images" / (source.stem + ".png")
        if not image.exists():
            failures.append(f"{source.name}: missing PNG")
    media = sorted(p for p in (root / "docs/images").iterdir() if p.suffix in {".png", ".gif"})
    for image in media:
        if not any(re.search(r"!\[[^\]]*\]\([^)]*" + re.escape(image.name) + r"\)", p.read_text()) for p in files):
            failures.append(f"{image.name}: not embedded in Markdown")
        if image.suffix == ".png" and image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            failures.append(f"{image.name}: invalid PNG signature")
        if image.suffix == ".gif" and image.read_bytes()[:6] not in (b"GIF87a", b"GIF89a"):
            failures.append(f"{image.name}: invalid GIF signature")
    result = {
        "markdown_files": len(files),
        "local_targets_checked": checked,
        "media_files_checked": len(media),
        "external_urls_not_http_validated": sorted(external),
        "failures": failures,
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(output)
    print(output, end="")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
