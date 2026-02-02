import os


class Config:
    # File uploads
    UPLOAD_FOLDER = os.environ.get("TRUSTNET_UPLOAD_DIR", "uploads")
    MAX_FILE_MB = int(os.environ.get("TRUSTNET_MAX_FILE_MB", "16"))
    MAX_CONTENT_LENGTH = MAX_FILE_MB * 1024 * 1024  # enforced per request in route

    # Persistence
    DATA_DIR = os.environ.get("TRUSTNET_DATA_DIR", "data")
    DATA_FILE = os.path.join(DATA_DIR, "chain.json")
