#!/usr/bin/env python3
"""
Amazon3DDownload

Downloads Amazon "View in 3D" model packages and can convert them to OBJ
for use in other 3D software.

Initial version written with assistance from OpenAI ChatGPT.
"""

import argparse
import html
import json
import re
import sys
import tarfile
import urllib.parse
import zipfile
from pathlib import Path

import requests


APP_VERSION = "32.13.0.100"


def app_context():
    data = {
        "an": "Amazon.com",
        "av": APP_VERSION,
        "xv": "1.15.0",
        "os": "Android",
        "ov": "14",
        "cp": 788744,
        "uiv": 4,
        "ast": 3,
        "nal": "1",
        "di": {
            "pr": "Pixel 8 Pro",
            "md": "Pixel 8 Pro",
            "v": "husky",
            "mf": "Google",
            "dsn": "0123456789abcdef0123456789abcdef",
            "dti": "A1MPSLFC7L5AFK",
            "ca": "Android",
            "ct": "WIFI",
        },
        "dm": {
            "w": 1080,
            "h": 2400,
            "ld": 2.75,
            "dx": 420,
            "dy": 420,
            "pt": 0,
            "pb": 78,
        },
        "is": "unknown",
        "msd": ".amazon.com",
    }

    return "1.8%20" + urllib.parse.quote(
        json.dumps(data, separators=(",", ":")),
        safe="",
    )


def resolve_asin(value, session):
    value = value.strip()

    if re.fullmatch(r"[A-Z0-9]{10}", value, re.I):
        return value.upper()

    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("Give an Amazon URL, a.co URL, or 10-character ASIN.")

    r = session.get(value, allow_redirects=True, timeout=30)
    r.raise_for_status()

    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"[?&]asin=([A-Z0-9]{10})",
    ]

    for source in (r.url, r.text):
        for pattern in patterns:
            m = re.search(pattern, source, re.I)
            if m:
                return m.group(1).upper()

    raise ValueError("Could not find an ASIN in that link.")


def normalize(text):
    for _ in range(3):
        text = html.unescape(text)

    return (
        text.replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\u002F", "/")
        .replace("\\u002B", "+")
        .replace("\\u002b", "+")
        .replace("\\&quot;", '"')
    )


def find_asset(page, asin):
    page = normalize(page)

    # Preferred source: Amazon's 3D media metadata.
    m = re.search(
        r'"variant"\s*:\s*"3D_unencrypted".{0,1000}?'
        r'"physicalId"\s*:\s*"([^"]+)".{0,500}?'
        r'"extension"\s*:\s*"([^"]+)"',
        page,
        re.I | re.S,
    )
    if m:
        return m.group(1), m.group(2)

    # Fallback: /view-3d link.
    m = re.search(r'/view-3d\?[^"\'<>\s]+', page, re.I)
    if m:
        params = urllib.parse.parse_qs(
            urllib.parse.urlparse(
                "https://www.amazon.com" + html.unescape(m.group(0))
            ).query
        )
        physical_id = params.get("physicalId", [None])[0]
        extension = params.get("extension", ["zip"])[0]
        if physical_id:
            return physical_id, extension

    return None


def extract_package(package, destination):
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(package) as z:
        z.extractall(destination)

    # Amazon's package commonly stores the actual glTF files in metadata.tar.
    for tar_path in destination.rglob("*.tar"):
        tar_dir = tar_path.parent / tar_path.stem
        tar_dir.mkdir(exist_ok=True)
        with tarfile.open(tar_path) as t:
            t.extractall(tar_dir)

    models = list(destination.rglob("*.gltf"))
    if not models:
        raise ValueError("Downloaded package did not contain a .gltf model.")

    return models[0]


def convert_to_obj(gltf_path, obj_dir):
    try:
        import trimesh
    except ImportError:
        raise ValueError(
            "OBJ conversion needs trimesh. Run: pip install -r requirements.txt"
        )

    obj_dir.mkdir(parents=True, exist_ok=True)

    print("Loading glTF...")
    scene = trimesh.load(gltf_path, force="scene")

    obj_path = obj_dir / (gltf_path.stem + ".obj")

    print("Exporting OBJ...")
    scene.export(obj_path)

    if not obj_path.exists():
        raise ValueError("OBJ export failed.")

    return obj_path


def main():
    parser = argparse.ArgumentParser(
        description="Download Amazon View-in-3D furniture models."
    )
    parser.add_argument("product", help="Amazon URL, a.co URL, or ASIN")
    parser.add_argument(
        "--obj",
        action="store_true",
        help="Also convert the downloaded model to OBJ",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Output directory (default: downloads)",
    )
    args = parser.parse_args()

    try:
        session = requests.Session()
        asin = resolve_asin(args.product, session)

        print(f"ASIN: {asin}")

        headers = {
            "User-Agent": f"Amazon.com/{APP_VERSION} (Android/14/Pixel 8 Pro)",
            "Accept-Language": "en-US,en;q=0.9",
        }
        cookies = {"amzn-app-ctxt": app_context()}

        print("Looking for Amazon 3D model...")
        page = session.get(
            f"https://www.amazon.com/dp/{asin}",
            headers=headers,
            cookies=cookies,
            timeout=30,
        )
        page.raise_for_status()

        asset = find_asset(page.text, asin)
        if not asset:
            print("No 3D model found for this product.")
            return 1

        physical_id, extension = asset
        asset_url = (
            f"https://m.media-amazon.com/images/I/"
            f"{physical_id}.{extension}"
        )

        print(f"physicalId: {physical_id}")
        print(f"Downloading: {asset_url}")

        product_dir = Path(args.output) / asin
        product_dir.mkdir(parents=True, exist_ok=True)

        package = product_dir / f"{physical_id}.{extension}"

        with session.get(asset_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with package.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

        print(f"Saved: {package}")

        if args.obj:
            print("Extracting model...")
            gltf = extract_package(package, product_dir / "extracted")
            print(f"Found: {gltf}")

            obj = convert_to_obj(gltf, product_dir / "obj")
            print(f"OBJ ready: {obj}")

        return 0

    except (requests.RequestException, ValueError, OSError, zipfile.BadZipFile) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
