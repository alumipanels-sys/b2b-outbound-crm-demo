"""Decrypt an encrypted ColdDev backup (.db.enc) back to a plain SQLite database.

Usage:
    python tools/decrypt_backup.py <backup.db.enc> [output.db]

Password comes from BACKUP_PASSWORD in .env, or you will be prompted.
After decryption the output runs PRAGMA integrity_check automatically.
"""

import getpass
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# Console-safe output on GBK Windows terminals
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1]).resolve()
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)
    dst = Path(sys.argv[2]).resolve() if len(sys.argv) >= 3 else src.with_suffix(".decrypted.db")

    password = ""
    try:
        from config import BACKUP_PASSWORD
        password = (BACKUP_PASSWORD or "").strip()
    except Exception:
        pass
    if not password:
        password = getpass.getpass("Enter the backup encryption password: ")
    if not password:
        print("No password provided.")
        sys.exit(1)

    from services.backup_service import decrypt_backup_file, verify_backup
    try:
        decrypt_backup_file(src, dst, password)
    except Exception as e:
        print(f"Decryption failed (wrong password or corrupted file): {e}")
        sys.exit(1)

    check = verify_backup(dst)
    if check["integrity"] == "ok":
        print(f"✅ Decrypted successfully and integrity check passed: {dst} ({dst.stat().st_size / 1024:.0f} KB)")
    else:
        print(f"⚠️ Decryption completed but the integrity check failed: {check['integrity']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
