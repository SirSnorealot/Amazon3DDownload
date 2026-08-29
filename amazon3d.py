#!/usr/bin/env python3
"""
Amazon3DDownload

Downloads Amazon "View in 3D" model packages and converts them to OBJ
and STL for use in other 3D software.

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


def decompress_draco(gltf_path):
    """Amazon models use KHR_draco_mesh_compression, which trimesh cannot
    read (it silently loads every vertex as 0,0,0). Decode the Draco blob
    and write an uncompressed copy of the glTF next to the original."""
    gltf = json.loads(gltf_path.read_text(encoding="utf-8"))

    extensions = set(gltf.get("extensionsRequired", [])) | set(
        gltf.get("extensionsUsed", [])
    )
    if "KHR_draco_mesh_compression" not in extensions:
        return gltf_path

    try:
        import DracoPy
        import numpy as np
    except ImportError:
        raise ValueError(
            "This model is Draco-compressed. Run: pip install -r requirements.txt"
        )

    print("Decompressing Draco geometry...")

    source_buffers = [
        (gltf_path.parent / buf["uri"]).read_bytes() for buf in gltf["buffers"]
    ]

    decoded_bin = bytearray()
    new_buffer_index = len(gltf["buffers"])
    buffer_views = gltf.setdefault("bufferViews", [])
    accessors = gltf["accessors"]

    def add_view(data):
        while len(decoded_bin) % 4:
            decoded_bin.append(0)
        buffer_views.append(
            {
                "buffer": new_buffer_index,
                "byteOffset": len(decoded_bin),
                "byteLength": len(data),
            }
        )
        decoded_bin.extend(data)
        return len(buffer_views) - 1

    def decoded_attribute(mesh, name):
        if name == "POSITION":
            return mesh.points
        if name == "NORMAL":
            return getattr(mesh, "normals", None)
        if name.startswith("TEXCOORD"):
            return getattr(mesh, "tex_coord", None)
        if name.startswith("COLOR"):
            return getattr(mesh, "colors", None)
        return None

    for mesh in gltf.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            draco = primitive.get("extensions", {}).pop(
                "KHR_draco_mesh_compression", None
            )
            if draco is None:
                continue

            view = buffer_views[draco["bufferView"]]
            offset = view.get("byteOffset", 0)
            blob = source_buffers[view["buffer"]][
                offset : offset + view["byteLength"]
            ]
            decoded = DracoPy.decode(blob)

            faces = np.asarray(decoded.faces, dtype=np.uint32)
            accessors[primitive["indices"]].update(
                {
                    "bufferView": add_view(faces.tobytes()),
                    "byteOffset": 0,
                    "componentType": 5125,
                    "count": int(faces.size),
                    "type": "SCALAR",
                }
            )

            for name, accessor_index in primitive["attributes"].items():
                array = decoded_attribute(decoded, name)
                if array is None or len(array) == 0:
                    continue
                array = np.asarray(array, dtype=np.float32)
                accessor = accessors[accessor_index]
                accessor.update(
                    {
                        "bufferView": add_view(array.tobytes()),
                        "byteOffset": 0,
                        "componentType": 5126,
                        "count": int(len(array)),
                    }
                )
                if name == "POSITION":
                    accessor["min"] = array.min(axis=0).tolist()
                    accessor["max"] = array.max(axis=0).tolist()

            if not primitive.get("extensions"):
                primitive.pop("extensions", None)

    bin_path = gltf_path.with_name(gltf_path.stem + "_decoded.bin")
    bin_path.write_bytes(decoded_bin)
    gltf["buffers"].append(
        {"uri": bin_path.name, "byteLength": len(decoded_bin)}
    )

    for key in ("extensionsUsed", "extensionsRequired"):
        if key in gltf:
            gltf[key] = [
                e for e in gltf[key] if e != "KHR_draco_mesh_compression"
            ]
            if not gltf[key]:
                del gltf[key]

    decoded_path = gltf_path.with_name(gltf_path.stem + "_decoded.gltf")
    decoded_path.write_text(json.dumps(gltf), encoding="utf-8")

    return decoded_path


def convert_model(gltf_path, product_dir):
    try:
        import trimesh
    except ImportError:
        raise ValueError(
            "Conversion needs trimesh. Run: pip install -r requirements.txt"
        )

    name = gltf_path.stem
    gltf_path = decompress_draco(gltf_path)

    print("Loading glTF...")
    scene = trimesh.load(gltf_path, force="scene")

    outputs = []
    for suffix in (".obj", ".stl"):
        out_dir = product_dir / suffix[1:]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (name + suffix)
        print(f"Exporting {suffix[1:].upper()}...")
        scene.export(out_path)
        if not out_path.exists():
            raise ValueError(f"{suffix[1:].upper()} export failed.")
        outputs.append(out_path)

    return outputs


def main():
    parser = argparse.ArgumentParser(
        description="Download Amazon View-in-3D furniture models."
    )
    parser.add_argument("product", help="Amazon URL, a.co URL, or ASIN")
    parser.add_argument(
        "--no-convert",
        action="store_true",
        help="Only download; skip OBJ/STL conversion",
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

        if not args.no_convert:
            print("Extracting model...")
            gltf = extract_package(package, product_dir / "extracted")
            print(f"Found: {gltf}")

            for path in convert_model(gltf, product_dir):
                print(f"Ready: {path}")

        return 0

    except (requests.RequestException, ValueError, OSError, zipfile.BadZipFile) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
