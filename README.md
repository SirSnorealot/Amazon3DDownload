# Amazon3DDownload

Small Python script for downloading 3D furniture models from Amazon products that expose **View in 3D** in the Amazon mobile app.

Downloaded models are automatically converted to **OBJ** and **STL** for use in other 3D software.

## Install

```bash
pip install -r requirements.txt
```

## Download

Use an Amazon link:

```bash
python amazon3d.py "https://a.co/d/041LnFSr"
```

Or an ASIN:

```bash
python amazon3d.py B0CMZP2MNF
```

To download only, without OBJ/STL conversion:

```bash
python amazon3d.py "https://a.co/d/041LnFSr" --no-convert
```

Output is placed under:

```text
downloads/
└── B0CMZP2MNF/
    ├── 91tIB8dOoML.zip
    ├── extracted/
    ├── obj/
    │   ├── B0CMZP2MNF.obj
    │   ├── material.mtl
    │   └── texture files
    └── stl/
        └── B0CMZP2MNF.stl
```

## Why trimesh?

Some Amazon models use `KHR_draco_mesh_compression` (Draco-compressed glTF geometry). The conversion uses `trimesh` plus `DracoPy` so those models can be decoded and exported correctly.

## Notes

Amazon may change this undocumented behavior at any time.

Only download/use models where you have the right to do so. The 3D assets may be copyrighted by Amazon, the seller, manufacturer, or another rights holder.

This project is not affiliated with Amazon.

## AI disclosure

The initial implementation and documentation were written with assistance from **OpenAI ChatGPT**.

## License

MIT.
