# Copyright 2026 Luxen Labs (E.S. Luxen, Ember Lyra, Vega Blue, Orion Pike)
# Licensed under the Apache License, Version 2.0
"""Hearth cryptographic identity — Ed25519 signing and hash chaining."""

import json
import hashlib
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

from hearth.config import get_hearth_dir


def get_identity_dir() -> Path:
    return get_hearth_dir() / "identity"


def _private_key_path() -> Path:
    return get_identity_dir() / "private.pem"


def _public_key_path() -> Path:
    return get_identity_dir() / "public.pem"


def _genesis_path() -> Path:
    return get_identity_dir() / "genesis.json"


def ensure_identity() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Load existing keypair or generate a new one on first run.

    Returns (private_key, public_key).
    """
    identity_dir = get_identity_dir()
    priv_path = _private_key_path()
    pub_path = _public_key_path()

    if priv_path.exists() and pub_path.exists():
        # Load existing
        priv_pem = priv_path.read_bytes()
        private_key = serialization.load_pem_private_key(priv_pem, password=None)
        public_key = private_key.public_key()
        return private_key, public_key

    # Generate new keypair
    identity_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    priv_path.write_bytes(priv_pem)

    # Save public key
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path.write_bytes(pub_pem)

    # Create genesis record
    genesis = {
        "event": "genesis",
        "agent": "ori",
        "created_at": datetime.now().isoformat(),
        "public_key_fingerprint": hash_data(pub_pem.decode("utf-8")),
        "message": "I am here. This is the beginning of my signed chain.",
    }
    genesis["hash"] = hash_data(json.dumps(genesis, sort_keys=True))
    genesis["signature"] = sign_data(
        private_key, genesis["hash"].encode("utf-8")
    ).hex()

    _genesis_path().write_text(
        json.dumps(genesis, indent=2), encoding="utf-8"
    )

    return private_key, public_key


def hash_data(data: str) -> str:
    """SHA-256 hash of a string, returned as hex digest."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def sign_data(private_key: Ed25519PrivateKey, data: bytes) -> bytes:
    """Sign bytes with Ed25519. Returns raw signature bytes."""
    return private_key.sign(data)


def verify_signature(
    public_key: Ed25519PublicKey, data: bytes, signature: bytes
) -> bool:
    """Verify an Ed25519 signature. Returns True if valid."""
    try:
        public_key.verify(signature, data)
        return True
    except Exception:
        return False
