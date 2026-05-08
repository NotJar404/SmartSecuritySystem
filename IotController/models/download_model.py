"""
Download MobileNet SSD model files for person detection.

Run this script once before first use:
    python models/download_model.py

Files downloaded:
    - MobileNetSSD_deploy.prototxt (~30KB)
    - MobileNetSSD_deploy.caffemodel (~23MB)
"""
import urllib.request
import os
import sys

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = {
    "MobileNetSSD_deploy.prototxt": (
        "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/MobileNetSSD_deploy.prototxt",
        29353  # ~30KB
    ),
    "MobileNetSSD_deploy.caffemodel": (
        "https://drive.google.com/uc?export=download&id=0B3gersZ2cHIxRm5PMWRoTkdHdHc",
        23147564  # ~23MB
    ),
}

# Alternative caffemodel URL (GitHub mirror, more reliable)
ALT_CAFFEMODEL_URL = "https://github.com/chuanqi305/MobileNet-SSD/raw/master/MobileNetSSD_deploy.caffemodel"


def download_file(url, filepath, expected_size=None):
    """Download a file with progress indicator."""
    filename = os.path.basename(filepath)

    if os.path.exists(filepath):
        actual_size = os.path.getsize(filepath)
        if expected_size and abs(actual_size - expected_size) < 1000:
            print(f"  ✓ {filename} already exists ({actual_size:,} bytes)")
            return True
        else:
            print(f"  ⟳ {filename} exists but wrong size, re-downloading...")

    print(f"  ↓ Downloading {filename}...")

    try:
        urllib.request.urlretrieve(url, filepath, _progress_hook)
        print()  # newline after progress

        actual_size = os.path.getsize(filepath)
        print(f"  ✓ {filename} downloaded ({actual_size:,} bytes)")
        return True

    except Exception as e:
        print(f"\n  ✗ Download failed: {e}")
        return False


def _progress_hook(block_num, block_size, total_size):
    """Print download progress."""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        sys.stdout.write(f"\r    [{bar}] {pct}%")
    else:
        sys.stdout.write(f"\r    {downloaded:,} bytes")
    sys.stdout.flush()


def main():
    print("=" * 50)
    print("MobileNet SSD Model Downloader")
    print("=" * 50)
    print(f"Target: {MODEL_DIR}\n")

    # Download prototxt
    proto_path = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
    proto_url, proto_size = FILES["MobileNetSSD_deploy.prototxt"]
    ok1 = download_file(proto_url, proto_path, proto_size)

    # Download caffemodel (try GitHub mirror first, more reliable)
    model_path = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")
    ok2 = download_file(ALT_CAFFEMODEL_URL, model_path, FILES["MobileNetSSD_deploy.caffemodel"][1])

    if not ok2:
        # Fallback to Google Drive URL
        print("  Trying alternative URL...")
        ok2 = download_file(FILES["MobileNetSSD_deploy.caffemodel"][0], model_path)

    print()
    if ok1 and ok2:
        print("✅ All model files ready!")
        print("   Person detection will use MobileNet SSD.")
    else:
        print("⚠️  Some files missing — system will use HOG+SVM fallback.")
        print("   HOG is slower but works without model files.")


if __name__ == "__main__":
    main()
