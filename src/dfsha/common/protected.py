"""Versioned authenticated metadata envelopes. No implicit plaintext fallback."""
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dfsha.common.domain import Fault, need

MAGIC = b'DFSHAM01'


class MetadataCipher:
    def __init__(self, key):
        if len(key) != 32:
            raise ValueError('METADATA_KEY_INVALID')
        material = HKDF(algorithm=hashes.SHA256(), length=64, salt=None,
                        info=b'dfsha-metadata-v1').derive(key)
        self.aead = AESGCM(material[:32])
        self.index_key = material[32:]
        self.key_id = hashlib.sha256(key).digest()

    @classmethod
    def configured(cls, cfg):
        path = cfg.get('metadata_key_path')
        if not path:
            return None
        try:
            return cls(Path(path).read_bytes())
        except (OSError, ValueError):
            raise RuntimeError('METADATA_KEY_MISSING_OR_INVALID') from None

    def address(self, data):
        return hmac.digest(self.index_key, data, 'sha256').hex()

    def seal(self, data, context):
        nonce = os.urandom(12)
        header = MAGIC + self.key_id + nonce
        return header + self.aead.encrypt(nonce, data, header + context)

    def open(self, data, context):
        need(isinstance(data, bytes) and len(data) >= 68 and data[:8] == MAGIC,
             'DATA_LOSS')
        need(hmac.compare_digest(data[8:40], self.key_id), 'DATA_LOSS')
        try:
            return self.aead.decrypt(data[40:52], data[52:], data[:52] + context)
        except InvalidTag:
            raise Fault('DATA_LOSS') from None
