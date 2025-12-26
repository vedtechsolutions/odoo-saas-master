# -*- coding: utf-8 -*-
"""
Validation utility functions for the SaaS platform.

Usage:
    from odoo.addons.saas_core.utils.validators import validate_subdomain
    validate_subdomain('mycompany')  # Raises ValidationError if invalid
"""

import re
from odoo.exceptions import ValidationError

from odoo.addons.saas_core.constants.reserved import (
    RESERVED_SUBDOMAINS,
    BLOCKED_SUBDOMAIN_PATTERNS,
)
from odoo.addons.saas_core.constants.messages import ValidationErrors
from odoo.addons.saas_core.constants.config import OdooVersions


def validate_subdomain(subdomain):
    """
    Validate a subdomain string.

    Args:
        subdomain: The subdomain to validate

    Raises:
        ValidationError: If subdomain is invalid

    Returns:
        str: The validated subdomain (lowercase)
    """
    if not subdomain:
        raise ValidationError(ValidationErrors.SUBDOMAIN_REQUIRED)

    # Normalize to lowercase
    subdomain = subdomain.lower().strip()

    # Check length
    if len(subdomain) < 3:
        raise ValidationError(ValidationErrors.SUBDOMAIN_TOO_SHORT)

    if len(subdomain) > 30:
        raise ValidationError(ValidationErrors.SUBDOMAIN_TOO_LONG)

    # Check format: only lowercase letters, numbers, and hyphens
    if not re.match(r'^[a-z0-9-]+$', subdomain):
        raise ValidationError(ValidationErrors.SUBDOMAIN_INVALID)

    # Must start with letter or number
    if not re.match(r'^[a-z0-9]', subdomain):
        raise ValidationError(ValidationErrors.SUBDOMAIN_INVALID_START)

    # Must end with letter or number
    if not re.match(r'.*[a-z0-9]$', subdomain):
        raise ValidationError(ValidationErrors.SUBDOMAIN_INVALID_END)

    # Check against reserved subdomains
    if subdomain in RESERVED_SUBDOMAINS:
        raise ValidationError(ValidationErrors.SUBDOMAIN_RESERVED)

    # Check against blocked patterns
    for pattern in BLOCKED_SUBDOMAIN_PATTERNS:
        if re.match(pattern, subdomain):
            raise ValidationError(ValidationErrors.SUBDOMAIN_RESERVED)

    return subdomain


def normalize_email(email):
    """
    Normalize an email address.

    Args:
        email: The email address to normalize

    Raises:
        ValidationError: If email is invalid

    Returns:
        str: The normalized email (lowercase, stripped)
    """
    if not email:
        raise ValidationError(ValidationErrors.EMAIL_REQUIRED)

    email = email.lower().strip()

    # Basic email format validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise ValidationError(ValidationErrors.EMAIL_INVALID)

    return email


def validate_odoo_version(version):
    """
    Validate an Odoo version string.

    Args:
        version: The version to validate

    Raises:
        ValidationError: If version is not supported

    Returns:
        str: The validated version
    """
    supported = OdooVersions.get_supported()
    if version not in supported:
        raise ValidationError(
            f"Odoo version '{version}' is not supported. "
            f"Supported versions: {', '.join(supported)}"
        )
    return version


def validate_port_range(port, min_port, max_port):
    """
    Validate a port number is within range.

    Args:
        port: The port number to validate
        min_port: Minimum allowed port
        max_port: Maximum allowed port

    Raises:
        ValidationError: If port is out of range

    Returns:
        int: The validated port
    """
    if not isinstance(port, int):
        raise ValidationError(f"Port must be an integer, got {type(port).__name__}")

    if port < min_port or port > max_port:
        raise ValidationError(
            f"Port {port} is out of range. Must be between {min_port} and {max_port}."
        )

    return port


def generate_database_name(subdomain):
    """
    Generate a database name from subdomain.

    Args:
        subdomain: The tenant subdomain

    Returns:
        str: Database name in format 'saas_subdomain'
    """
    # Replace hyphens with underscores for PostgreSQL compatibility
    safe_name = subdomain.replace('-', '_')
    return f"saas_{safe_name}"


def generate_container_name(subdomain):
    """
    Generate a Docker container name from subdomain.

    Args:
        subdomain: The tenant subdomain

    Returns:
        str: Container name in format 'odoo-subdomain'
    """
    return f"odoo-{subdomain}"
