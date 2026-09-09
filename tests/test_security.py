import os

import pytest
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def test_authenticated_encryption_and_tamper_rejection():
    cipher = AESGCM(AESGCM.generate_key(bit_length=256))
    nonce, aad = os.urandom(12), b"file-id:block-version:epoch"
    encrypted = cipher.encrypt(nonce, b"contenido de prueba\x00", aad)
    assert cipher.decrypt(nonce, encrypted, aad) == b"contenido de prueba\x00"
    altered = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    with pytest.raises(InvalidTag):
        cipher.decrypt(nonce, altered, aad)
    with pytest.raises(InvalidTag):
        cipher.decrypt(nonce, encrypted, b"otro-bloque")


def test_argon2id_password_verification():
    hasher = PasswordHasher(type=Type.ID, time_cost=2, memory_cost=19456, parallelism=1)
    encoded = hasher.hash("solo-prueba-no-credencial")
    assert encoded.startswith("$argon2id$")
    assert hasher.verify(encoded, "solo-prueba-no-credencial")
    assert not hasher.check_needs_rehash(encoded)
    with pytest.raises(VerifyMismatchError):
        hasher.verify(encoded, "incorrecta")
