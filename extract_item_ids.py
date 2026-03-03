#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


URL_PATTERNS = [
    re.compile(r"https?://[^\"'\s>]+", re.IGNORECASE),
    re.compile(r"//[^\"'\s>]+", re.IGNORECASE),
    re.compile(r"/[^\"'\s>]+"),
]


def extract_urls(html: str) -> list[str]:
    urls: list[str] = []
    for pattern in URL_PATTERNS:
        urls.extend(pattern.findall(html))
    return urls


def extract_item_ids_from_url(url: str) -> list[int]:
    ids: list[int] = []

    patterns = [
        re.compile(r"(?:item|items)[^0-9]{0,8}(\d{1,6})", re.IGNORECASE),
        re.compile(r"/(\d{1,6})(?:\.[a-z0-9]+)?(?:\?|$)", re.IGNORECASE),
        re.compile(r"[?&](?:item_id|id|item)=(\d{1,6})", re.IGNORECASE),
    ]

    for pattern in patterns:
        for value in pattern.findall(url):
            try:
                ids.append(int(value))
            except ValueError:
                continue

    return ids


def extract_item_ids(html: str) -> list[int]:
    found: list[int] = []
    for url in extract_urls(html):
        found.extend(extract_item_ids_from_url(url))

    # IDs uniques triés
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrait les IDs d'items depuis un dump HTML (URLs d'images)."
    )
    parser.add_argument("input", help="Chemin du fichier HTML à analyser")
    parser.add_argument(
        "-o",
        "--output",
        help="Chemin du fichier de sortie (une ligne par ID)",
        default="",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Fichier introuvable: {input_path}")
        return 1

    html = input_path.read_text(encoding="utf-8", errors="ignore")
    item_ids = extract_item_ids(html)

    if not item_ids:
        print("Aucun ID trouvé.")
        return 2

    output = "\n".join(str(item_id) for item_id in item_ids)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output + "\n", encoding="utf-8")
        print(f"{len(item_ids)} IDs trouvés et écrits dans: {output_path}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
