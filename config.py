"""Config + path resolution. Import anywhere; it finds the project root."""
import os
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

WEIGHTS = CFG["weights"]
BUCKETS = list(WEIGHTS.keys())


def indicators():
    """Indicator specs as {key: spec}, with the key folded in as spec['key']."""
    return {k: {**v, "key": k} for k, v in CFG["indicators"].items()}
