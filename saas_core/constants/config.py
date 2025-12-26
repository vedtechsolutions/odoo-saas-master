# -*- coding: utf-8 -*-
"""
Configuration constants for the SaaS platform.

Usage:
    from odoo.addons.saas_core.constants.config import DomainConfig, ServerConfig
"""


class DomainConfig:
    """Domain and DNS configuration."""

    BASE_DOMAIN = 'vedtechsolutions.com'
    TENANT_SUBDOMAIN_SUFFIX = 'tenants.vedtechsolutions.com'
    WILDCARD_DOMAIN = '*.tenants.vedtechsolutions.com'

    # Subdomain validation
    SUBDOMAIN_MIN_LENGTH = 3
    SUBDOMAIN_MAX_LENGTH = 30
    SUBDOMAIN_PATTERN = r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$'

    # Cloudflare settings
    CLOUDFLARE_ZONE_ID = '41430abd983f84e4cf32ef692f1dc587'


class ServerConfig:
    """Server and network configuration."""

    # Master Server (SaaS Platform)
    MASTER_IP = '66.94.97.44'
    MASTER_HOSTNAME = 'vedtechsolutions.com'

    # Tenant Server (Customer Instances)
    TENANT_IP = '85.239.231.125'
    TENANT_VPN_IP = '10.0.0.2'
    TENANT_HOSTNAME = 'tenant1.vedtechsolutions.com'

    # Docker configuration
    DOCKER_API_PORT = 2375
    DOCKER_NETWORK = 'tenant_network'
    DOCKER_IMAGE = 'vedtech/odoo:19.0'

    # Port ranges for tenant instances
    TENANT_PORT_MIN = 8100
    TENANT_PORT_MAX = 8299
    LONGPOLLING_PORT_OFFSET = 1000

    # VPN configuration
    VPN_INTERFACE = 'wg0'
    VPN_PORT = 51820
    VPN_SUBNET = '10.0.0.0/24'


class PlanConfig:
    """Plan configuration and limits."""

    # Plan codes
    PLAN_TRIAL = 'trial'
    PLAN_SOLO = 'solo'
    PLAN_STARTER = 'starter'
    PLAN_PROFESSIONAL = 'professional'
    PLAN_ENTERPRISE = 'enterprise'

    # Trial settings
    TRIAL_DURATION_DAYS = 14
    TRIAL_GRACE_PERIOD_DAYS = 3

    # Resource defaults
    DEFAULT_CPU_LIMIT = 1.0  # 1 core - smooth experience with Website module
    DEFAULT_RAM_LIMIT_MB = 1024  # 1GB - minimum safe for Odoo 19
    DEFAULT_STORAGE_DB_GB = 2
    DEFAULT_STORAGE_FILE_GB = 5
    DEFAULT_USER_LIMIT = 3
    DEFAULT_INSTANCE_LIMIT = 1

    # Memory limits
    # IMPORTANT: Odoo 19 requires minimum 1GB RAM per container to run reliably.
    # Official Odoo formula: Heavy worker ~1GB, Light worker ~150MB
    # 512MB causes high memory pressure (96%+ usage) and connection drops.
    # 256MB is NOT viable - causes crashes and blank screens.
    MIN_RAM_LIMIT_MB = 1024  # 1GB - Minimum for Odoo 19 containers
    MAX_RAM_LIMIT_MB = 16384  # 16GB

    # Other resource limits
    MIN_CPU_LIMIT = 0.25
    MAX_CPU_LIMIT = 8.0
    MAX_STORAGE_DB_GB = 500
    MAX_STORAGE_FILE_GB = 1000
    MAX_USER_LIMIT = 1000
    MAX_INSTANCE_LIMIT = 100

    # Plan-specific resource limits (aligned with Odoo 19 requirements)
    # Updated December 2025 - minimum 1GB RAM per instance
    PLAN_LIMITS = {
        'trial': {
            'cpu_cores': 1.0,
            'ram_mb': 1024,        # 1GB - minimum for Odoo 19
            'storage_db_gb': 2,
            'storage_file_gb': 5,
            'users': 3,
            'instances': 1,
            'backup_retention_days': 3,
        },
        'solo': {
            'cpu_cores': 1.0,
            'ram_mb': 1024,        # 1GB
            'storage_db_gb': 2,
            'storage_file_gb': 5,
            'users': 1,
            'instances': 1,
            'backup_retention_days': 3,
        },
        'starter': {
            'cpu_cores': 1.0,
            'ram_mb': 2048,        # 2GB
            'storage_db_gb': 5,
            'storage_file_gb': 10,
            'users': 3,
            'instances': 1,
            'backup_retention_days': 7,
        },
        'professional': {
            'cpu_cores': 2.0,
            'ram_mb': 4096,        # 4GB
            'storage_db_gb': 25,
            'storage_file_gb': 50,
            'users': 15,
            'instances': 3,
            'backup_retention_days': 30,
        },
        'enterprise': {
            'cpu_cores': 4.0,
            'ram_mb': 8192,        # 8GB
            'storage_db_gb': 100,
            'storage_file_gb': 250,
            'users': 100,
            'instances': 10,
            'backup_retention_days': 90,
        },
    }

    @classmethod
    def get_plan_limit(cls, plan_code, limit_name, default=None):
        """Get a specific limit for a plan.

        Args:
            plan_code: Plan code (trial, solo, starter, professional, enterprise)
            limit_name: Limit name (cpu_cores, ram_mb, storage_db_gb, etc.)
            default: Default value if not found

        Returns:
            The limit value or default
        """
        plan_limits = cls.PLAN_LIMITS.get(plan_code, {})
        return plan_limits.get(limit_name, default)


class PaymentConfig:
    """Payment and billing configuration."""

    # Currency
    DEFAULT_CURRENCY = 'USD'

    # Payment provider
    PAYMENT_PROVIDER = 'powertranz'

    # Invoice settings
    INVOICE_DUE_DAYS = 15
    PAYMENT_RETRY_DAYS = 3
    MAX_PAYMENT_RETRIES = 3

    # Grace periods
    GRACE_PERIOD_DAYS = 7
    SUSPENSION_WARNING_DAYS = 3


class BackupConfig:
    """Backup configuration."""

    # Backup retention by plan tier
    RETENTION_TRIAL = 3
    RETENTION_BASIC = 7
    RETENTION_PROFESSIONAL = 30
    RETENTION_ENTERPRISE = 90

    # Backup schedule
    BACKUP_HOUR = 2  # 2 AM
    BACKUP_MINUTE = 0

    # Storage
    BACKUP_PATH = '/opt/tenants/backups'
    MAX_BACKUP_SIZE_GB = 50


class OdooVersions:
    """Supported Odoo versions."""

    V17 = '17'
    V18 = '18'
    V19 = '19'

    DEFAULT = V19

    @classmethod
    def get_selection(cls):
        """Return selection list for Odoo field."""
        return [
            (cls.V17, 'Odoo 17'),
            (cls.V18, 'Odoo 18'),
            (cls.V19, 'Odoo 19'),
        ]

    @classmethod
    def get_supported(cls):
        """Return list of supported versions."""
        return [cls.V17, cls.V18, cls.V19]
