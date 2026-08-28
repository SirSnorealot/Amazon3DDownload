# Amazon3DDownload

A small Python script that downloads Amazon 3D model packages for products that expose Amazon's mobile-app **View in 3D** feature.

The script accepts an Amazon product URL, `a.co` short link, or ASIN.

## Install

```bash
git clone https://github.com/SirSnorealot/Amazon3DDownload.git
cd Amazon3DDownload
pip install -r requirements.txt
```

## Usage

```bash
python amazon3d.py "https://a.co/d/041LnFSr"
```

Or with an ASIN:

```bash
python amazon3d.py B0CMZP2MNF
```

Choose a different output folder:

```bash
python amazon3d.py B0CMZP2MNF -o models
```

Downloaded files are saved to `downloads/` by default.

## How it works

Amazon exposes 3D metadata to its mobile-app product experience. For supported products, the response can contain a `3D_unencrypted` media entry with a `physicalId` and file extension.

The script:

1. Resolves the product ASIN.
2. Requests the Amazon product page using mobile-app context metadata.
3. Finds the 3D asset `physicalId`.
4. Downloads the model package from Amazon's media CDN.

For example:

```text
ASIN: B0CMZP2MNF
physicalId: 91tIB8dOoML
extension: zip
```

corresponds to a package like:

```text
https://m.media-amazon.com/images/I/91tIB8dOoML.zip
```

The ZIP may contain a glTF model, binary geometry, textures, and Amazon-specific scene metadata.

## Notes

Amazon can change this behavior at any time, so the script may stop working without warning.

Only download and use models where you have the right to do so. Product models may be copyrighted by Amazon, the seller, manufacturer, or another rights holder. This project is not affiliated with Amazon.

## AI disclosure

The initial version of this project and its documentation were written with assistance from **OpenAI ChatGPT**.

## License

MIT License. See `LICENSE`.
