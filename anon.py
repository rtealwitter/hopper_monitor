"""Stable per-salt pseudonym for a real username. Lab names are never hashed -
lab-level usage is the actionable public signal; individual identity is not."""
import hashlib

def pseudonym(value, salt):
    if not value:
        return None
    h = hashlib.sha256((salt + "user" + value).encode()).hexdigest()[:8]
    return f"user-{h}"
