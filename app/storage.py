import json
import os


def save_chain(path, chain):
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                chain, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_chain(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
