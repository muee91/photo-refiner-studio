#!/usr/bin/env python3
import json


def main() -> None:
    missing = []
    versions = {}
    try:
        import PIL
        from PIL import ImageCms

        versions["Pillow"] = PIL.__version__
        try:
            ImageCms.createProfile("sRGB")
            versions["Pillow-ImageCms"] = "available"
        except Exception:
            missing.append("Pillow with LittleCMS/ImageCms support")
    except ImportError:
        missing.append("Pillow")
    try:
        import numpy

        versions["NumPy"] = numpy.__version__
    except ImportError:
        missing.append("NumPy")
    try:
        import cv2

        versions["OpenCV"] = cv2.__version__
        if not hasattr(cv2, "SIFT_create"):
            missing.append("OpenCV with SIFT support")
    except ImportError:
        missing.append("OpenCV")
    try:
        import yaml

        versions["PyYAML"] = yaml.__version__
    except ImportError:
        missing.append("PyYAML")

    result = {"ok": not missing, "versions": versions, "missing": missing}
    print(json.dumps(result, indent=2))
    if missing:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
