#!/usr/bin/env python3
"""
Amazon3DDownload

Download Amazon 3D model packages for products that expose a mobile-app
"View in 3D" experience.

Initial version written with assistance from OpenAI ChatGPT.
"""

import argparse
import html
import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests


APP_VERSION = "32.13.0.100"


def make_app_context():
    obj = {
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
        json.dumps(obj, separators=(",", ":")),
        safe=""
    )


def resolve_asin(value, session):
    value = value.strip()

    # Direct ASIN
    if re.fullmatch(r"[A-Z0-9]{10}", value, re.I):
        return value.upper()

    # Amazon URL / a.co short URL
    if not re.match(r"^https?://", value, re.I):
        raise ValueError("Input must be an Amazon URL or a 10-character ASIN.")

    r = session.get(value, allow_redirects=True, timeout=30)
    r.raise_for_status()

    candidates = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})",
        r"[?&]asin=([A-Z0-9]{10})",
    ]

    for pattern in candidates:
        m = re.search(pattern, r.url, re.I)
        if m:
            return m.group(1).upper()

    for pattern in candidates:
        m = re.search(pattern, r.text, re.I)
        if m:
            return m.group(1).upper()

    raise ValueError("Could not determine ASIN from the supplied URL.")


def normalize_amazon_html(text):
    for _ in range(3):
        text = html.unescape(text)

    return (
        text
        .replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\u002F", "/")
        .replace("\\u002b", "+")
        .replace("\\u002B", "+")
        .replace("\\&quot;", '"')
    )


def find_3d_asset(text, asin):
    text = normalize_amazon_html(text)

    # Best signal: Amazon mediaDetails entry for a 3D package.
    pattern = re.compile(
        r'"variant"\s*:\s*"3D_unencrypted".{0,800}?'
        r'"physicalId"\s*:\s*"([^"]+)".{0,400}?'
        r'"extension"\s*:\s*"([^"]+)"',
        re.I | re.S,
    )

    m = pattern.search(text)
    if m:
        return {
            "asin": asin,
            "physical_id": m.group(1),
            "extension": m.group(2),
        }

    # Fallback: parse the /view-3d link.
    m = re.search(r'/view-3d\?[^"\'<>\s]+', text, re.I)
    if m:
        url = html.unescape(m.group(0))
        params = urllib.parse.parse_qs(
            urllib.parse.urlparse("https://www.amazon.com" + url).query
        )

        physical_id = params.get("physicalId", [None])[0]
        extension = params.get("extension", ["zip"])[0]

        if physical_id:
            return {
                "asin": asin,
                "physical_id": physical_id,
                "extension": extension,
            }

    return None


def download_model(value, output_dir):
    session = requests.Session()

    asin = resolve_asin(value, session)
    print(f"ASIN: {asin}")

    headers = {
        "User-Agent": f"Amazon.com/{APP_VERSION} (Android/14/Pixel 8 Pro)",
        "Accept-Language": "en-US,en;q=0.9",
    }

    cookies = {
        "amzn-app-ctxt": make_app_context(),
    }

    product_url = f"https://www.amazon.com/dp/{asin}"

    print("Checking Amazon for 3D asset...")
    r = session.get(
        product_url,
        headers=headers,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()

    asset = find_3d_asset(r.text, asin)

    if not asset:
        print("No downloadable 3D asset found for this product.")
        return 1

    physical_id = asset["physical_id"]
    extension = asset["extension"]

    asset_url = (
        f"https://m.media-amazon.com/images/I/"
        f"{physical_id}.{extension}"
    )

    print(f"physicalId: {physical_id}")
    print(f"Asset: {asset_url}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{asin}_{physical_id}.{extension}"

    print(f"Downloading to: {output_file}")

    with session.get(asset_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with output_file.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    print("Done.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Download Amazon 3D model packages from an Amazon URL or ASIN."
    )
    parser.add_argument(
        "product",
        help="Amazon product URL, a.co short URL, or ASIN"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Output directory (default: downloads)"
    )

    args = parser.parse_args()

    try:
        return download_model(args.product, Path(args.output))
    except requests.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
