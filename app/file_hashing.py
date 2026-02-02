import hashlib


def hash_file(filepath, chunk_size=4096):
    """Generate SHA-256 hash for any file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
