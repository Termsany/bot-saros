"""Encryption for the daily backups on Telegram (security plan item 11, owner 2026-11-08).

The server holds only a PUBLIC key: it can lock a backup but never open one, so neither someone in the server nor
someone in the Telegram chat can read the backups. The PRIVATE key, protected by a passphrase, stays with the owner
(off the server). Each backup gets its own random AES-256-GCM key, locked with RSA-OAEP (SHA-256).

  python scripts/backup_crypto.py keygen <folder>          # on your own computer: backup-private.pem + backup-public.pem
  python scripts/backup_crypto.py decrypt <file.enc> [out]  # on your own computer: asks the passphrase, writes the .tar.gz
  python scripts/backup_crypto.py verify <file.enc>         # the monthly restore test: opens and checks it, writes nothing

File format: b"RAQMBK1\\n" + 2-byte length + the RSA-locked key + 12-byte nonce + AES-GCM(archive).
"""
import getpass, os, sys
from pathlib import Path

MAGIC = b"RAQMBK1\n"
PUBLIC_KEY = Path(os.getenv("RAQM_BACKUP_PUBKEY", "/etc/raqm-backup/public.pem"))


def _oaep():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    return padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def encrypt(data: bytes, public_pem: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pub = serialization.load_pem_public_key(public_pem)
    if getattr(pub, "key_size", 0) < 3072:
        raise ValueError("the backup public key must be RSA 3072+ bits")
    key, nonce = AESGCM.generate_key(256), os.urandom(12)
    locked = pub.encrypt(key, _oaep())
    return MAGIC + len(locked).to_bytes(2, "big") + locked + nonce + AESGCM(key).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, private_pem: bytes, passphrase: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC):
        raise ValueError("not a RAQM encrypted backup")
    n = int.from_bytes(blob[len(MAGIC):len(MAGIC) + 2], "big"); i = len(MAGIC) + 2
    locked, nonce, body = blob[i:i + n], blob[i + n:i + n + 12], blob[i + n + 12:]
    key = serialization.load_pem_private_key(private_pem, password=passphrase).decrypt(locked, _oaep())
    return AESGCM(key).decrypt(nonce, body, MAGIC)


def public_key():
    """The server's public key, or None when it isn't installed yet (then the backup says it went unencrypted)."""
    try:
        return PUBLIC_KEY.read_bytes() if PUBLIC_KEY.is_file() else None
    except OSError:
        return None


def keygen(folder: Path, passphrase: bytes):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    folder.mkdir(parents=True, exist_ok=True)
    priv = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    (folder / "backup-private.pem").write_bytes(priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(passphrase)))
    (folder / "backup-public.pem").write_bytes(priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


def main(argv):
    if argv[:1] == ["keygen"] and len(argv) == 2:
        p1 = getpass.getpass("passphrase للمفتاح الخاص (12 حرف على الأقل): ").encode()
        if len(p1) < 12 or getpass.getpass("تاني: ").encode() != p1:
            return "الـ passphrase قصيرة أو مش متطابقة"
        keygen(Path(argv[1]), p1)
        print(f"✅ {argv[1]}/backup-private.pem (خليه عندك بس، ومعاه نسخة على فلاشة) و backup-public.pem (ده اللي يتحط على السيرفر)")
        return None
    if argv[:1] == ["decrypt"] and len(argv) in (2, 3):
        src = Path(argv[1]); out = Path(argv[2]) if len(argv) == 3 else src.with_suffix("")
        key = Path(os.getenv("RAQM_BACKUP_PRIVATE", "backup-private.pem")).read_bytes()
        out.write_bytes(decrypt(src.read_bytes(), key, getpass.getpass("passphrase: ").encode()))
        print(f"✅ {out}")
        return None
    if argv[:1] == ["verify"] and len(argv) == 2:
        key = Path(os.getenv("RAQM_BACKUP_PRIVATE", "backup-private.pem")).read_bytes()
        res = verify_backup(Path(argv[1]), key, getpass.getpass("passphrase: ").encode())
        for ok, line in res: print(f"{'✅' if ok else '❌'} {line}")
        bad = sum(1 for ok, _ in res if not ok)
        print("✅ النسخة بتتفك وسليمة" if not bad else f"🚨 {bad} مشكلة")
        return 1 if bad else None
    return __doc__


def verify_backup(src: Path, private_pem: bytes, passphrase: bytes):
    """[(ok, line)] for an encrypted backup (owner, 2026-11-08, the monthly restore test): opened in memory with the
    private key, unpacked into a temporary folder that is deleted afterwards, and checked like a restore
    (restore_check.py). A users' backup is a tar of each user's own .tar.gz: each one must open."""
    import io, tarfile, tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import restore_check
    try:
        plain = decrypt(src.read_bytes(), private_pem, passphrase)
    except Exception as e:
        return [(False, f"مقدرناش نفك التشفير ({type(e).__name__}): الـ passphrase أو المفتاح غلط، أو الملف اتغيّر")]
    out = [(True, f"التشفير اتفك: {len(plain) / 1048576:.1f} MB")]
    if src.name.startswith("raqm-users-backup"):
        try:
            with tarfile.open(fileobj=io.BytesIO(plain), mode="r:") as tar:
                parts = [m for m in tar.getmembers() if m.isfile()]
                for m in parts:
                    with tarfile.open(fileobj=tar.extractfile(m), mode="r:gz") as inner:
                        inner.getmembers()
            return out + [(True, f"{len(parts)} مستخدم، كل نسخة بتتفتح")]
        except Exception as e:
            return out + [(False, f"نسخة مستخدم مش بتتفتح: {type(e).__name__}: {e}")]
    with tempfile.TemporaryDirectory() as td:
        arc = Path(td) / "a.tar.gz"; arc.write_bytes(plain)
        try:
            return out + restore_check.verify(restore_check.unpack(arc, Path(td) / "out"))
        except Exception as e:
            return out + [(False, f"الأرشيف مش بيتفك: {type(e).__name__}: {e}")]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
