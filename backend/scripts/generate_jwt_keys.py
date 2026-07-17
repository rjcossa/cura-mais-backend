#!/usr/bin/env python
"""Generates the RSA keypair used to sign/verify access tokens (RS256) and
a Fernet key for encrypting MFA secrets at rest, writing them to
`backend/keys/`. Run once per environment — re-running overwrites existing
keys, which invalidates every previously issued access token (refresh
tokens/sessions are unaffected since they're independent opaque values).

Usage:
    python scripts/generate_jwt_keys.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"


def main() -> None:
    KEYS_DIR.mkdir(exist_ok=True)
    private_path = KEYS_DIR / "jwt_private.pem"
    public_path = KEYS_DIR / "jwt_public.pem"

    if private_path.exists() or public_path.exists():
        answer = input(
            f"Key files already exist in {KEYS_DIR}. Overwrite? This invalidates all "
            "existing access tokens. [y/N] "
        )
        if answer.strip().lower() != "y":
            print("Aborted.")
            sys.exit(1)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    private_path.chmod(0o600)

    print(f"Wrote {private_path}")
    print(f"Wrote {public_path}")

    fernet_key = Fernet.generate_key().decode()
    print("\nAdd this to your .env as MFA_ENCRYPTION_KEY:")
    print(f"MFA_ENCRYPTION_KEY={fernet_key}")

    import secrets

    print("\nAlso set a real TOKEN_HASH_PEPPER in your .env (do not use the default):")
    print(f"TOKEN_HASH_PEPPER={secrets.token_urlsafe(32)}")


if __name__ == "__main__":
    main()
