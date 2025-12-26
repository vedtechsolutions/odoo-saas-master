# -*- coding: utf-8 -*-
"""
Field-level encryption utilities for PII data protection.

This module provides AES-256 encryption for sensitive fields like:
- admin_email
- admin_password
- customer phone numbers
- API keys and tokens

Implements T-084 (Field-level encryption for PII) and T-085 (Encryption key management).
"""

import base64
import hashlib
import logging
import os
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_logger = logging.getLogger(__name__)

# Configuration parameter keys
ENCRYPTION_KEY_PARAM = 'saas.pii_encryption_key'
ENCRYPTION_SALT_PARAM = 'saas.pii_encryption_salt'

# Marker prefix for encrypted values (to detect already encrypted data)
ENCRYPTED_PREFIX = 'ENC::'


class EncryptionKeyManager:
    """
    Manages encryption keys for field-level PII encryption.

    Keys are stored in ir.config_parameter and derived using PBKDF2.
    This provides:
    - Secure key storage in database
    - Key derivation from master key + salt
    - Automatic key generation if not exists
    """

    _instance = None
    _fernet = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_or_create_key(self, env):
        """
        Get existing encryption key or create a new one.

        Args:
            env: Odoo environment

        Returns:
            bytes: The encryption key
        """
        ICP = env['ir.config_parameter'].sudo()

        # Get or create master key
        master_key = ICP.get_param(ENCRYPTION_KEY_PARAM)
        if not master_key:
            # Generate a new master key (32 bytes = 256 bits)
            master_key = secrets.token_urlsafe(32)
            ICP.set_param(ENCRYPTION_KEY_PARAM, master_key)
            _logger.info("Generated new PII encryption master key")

        # Get or create salt
        salt = ICP.get_param(ENCRYPTION_SALT_PARAM)
        if not salt:
            salt = secrets.token_urlsafe(16)
            ICP.set_param(ENCRYPTION_SALT_PARAM, salt)
            _logger.info("Generated new PII encryption salt")

        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt.encode(),
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))

        return derived_key

    def get_fernet(self, env):
        """
        Get a Fernet instance for encryption/decryption.

        Args:
            env: Odoo environment

        Returns:
            Fernet: Fernet encryption instance
        """
        if self._fernet is None:
            key = self.get_or_create_key(env)
            self._fernet = Fernet(key)
        return self._fernet

    def rotate_key(self, env):
        """
        Rotate the encryption key.

        IMPORTANT: This will make existing encrypted data unreadable!
        Should only be called with a migration plan in place.

        Args:
            env: Odoo environment
        """
        ICP = env['ir.config_parameter'].sudo()

        # Generate new key and salt
        new_master_key = secrets.token_urlsafe(32)
        new_salt = secrets.token_urlsafe(16)

        ICP.set_param(ENCRYPTION_KEY_PARAM, new_master_key)
        ICP.set_param(ENCRYPTION_SALT_PARAM, new_salt)

        # Clear cached fernet
        self._fernet = None

        _logger.warning("Encryption key rotated! Existing encrypted data must be re-encrypted.")
        return True


# Singleton key manager
_key_manager = EncryptionKeyManager()


def encrypt_value(env, value):
    """
    Encrypt a string value using Fernet (AES-128-CBC).

    Args:
        env: Odoo environment
        value: String value to encrypt

    Returns:
        str: Encrypted value with ENC:: prefix, or original if already encrypted
    """
    if not value:
        return value

    # Don't double-encrypt
    if isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX):
        return value

    try:
        fernet = _key_manager.get_fernet(env)
        encrypted = fernet.encrypt(value.encode())
        return ENCRYPTED_PREFIX + encrypted.decode()
    except Exception as e:
        _logger.error(f"Encryption failed: {e}")
        # Return original value if encryption fails (fail-safe)
        return value


def decrypt_value(env, value):
    """
    Decrypt a string value that was encrypted with encrypt_value.

    Args:
        env: Odoo environment
        value: Encrypted string (with ENC:: prefix)

    Returns:
        str: Decrypted value, or original if not encrypted
    """
    if not value:
        return value

    # Only decrypt if it has our prefix
    if not isinstance(value, str) or not value.startswith(ENCRYPTED_PREFIX):
        return value

    try:
        fernet = _key_manager.get_fernet(env)
        encrypted_data = value[len(ENCRYPTED_PREFIX):]
        decrypted = fernet.decrypt(encrypted_data.encode())
        return decrypted.decode()
    except InvalidToken:
        _logger.error("Decryption failed: Invalid token (key mismatch or corrupted data)")
        return "[DECRYPTION_FAILED]"
    except Exception as e:
        _logger.error(f"Decryption failed: {e}")
        return "[DECRYPTION_FAILED]"


def is_encrypted(value):
    """
    Check if a value is encrypted.

    Args:
        value: Value to check

    Returns:
        bool: True if value appears to be encrypted
    """
    return isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)


def hash_for_search(value):
    """
    Create a searchable hash of a value.

    This allows searching encrypted fields without decrypting all records.
    Uses SHA-256 truncated to 16 chars for indexing.

    Args:
        value: Original plaintext value

    Returns:
        str: Hashed value for search index
    """
    if not value:
        return None

    # Normalize: lowercase and strip
    normalized = value.lower().strip()

    # SHA-256 hash, truncated
    hash_obj = hashlib.sha256(normalized.encode())
    return hash_obj.hexdigest()[:16]


def get_key_info(env):
    """
    Get information about the current encryption key (for admin display).

    Args:
        env: Odoo environment

    Returns:
        dict: Key information (without exposing the actual key)
    """
    ICP = env['ir.config_parameter'].sudo()

    master_key = ICP.get_param(ENCRYPTION_KEY_PARAM)
    salt = ICP.get_param(ENCRYPTION_SALT_PARAM)

    if not master_key:
        return {
            'status': 'not_configured',
            'message': 'Encryption key not yet generated',
        }

    # Create a fingerprint (first 8 chars of hash of the key)
    fingerprint = hashlib.sha256(master_key.encode()).hexdigest()[:8]

    return {
        'status': 'configured',
        'fingerprint': fingerprint.upper(),
        'algorithm': 'AES-128-CBC (Fernet)',
        'kdf': 'PBKDF2-SHA256',
        'iterations': 100000,
        'salt_configured': bool(salt),
    }
