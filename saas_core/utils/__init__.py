# -*- coding: utf-8 -*-
"""
Utility functions for the SaaS platform.

This package contains validation and helper functions used across all SaaS modules.
"""

from .validators import (
    validate_subdomain,
    normalize_email,
    validate_odoo_version,
    validate_port_range,
    generate_database_name,
    generate_container_name,
)

from .db_utils import (
    DatabaseLock,
    TryLock,
    CronLock,
    savepoint,
    retry_on_error,
    retry_database_operation,
    with_cron_lock,
)

from .encryption import (
    encrypt_value,
    decrypt_value,
    is_encrypted,
    hash_for_search,
    get_key_info,
    EncryptionKeyManager,
    ENCRYPTED_PREFIX,
)
