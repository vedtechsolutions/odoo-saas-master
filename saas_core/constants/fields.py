# -*- coding: utf-8 -*-
"""
Field and Model name constants for the SaaS platform.

Usage:
    from odoo.addons.saas_core.constants.fields import ModelNames, FieldNames

    class MyModel(models.Model):
        _name = ModelNames.INSTANCE
        plan_id = fields.Many2one(ModelNames.PLAN)
"""


class ModelNames:
    """Model _name constants."""

    # Core models
    PLAN = 'saas.plan'
    SERVER = 'saas.tenant.server'
    INSTANCE = 'saas.instance'

    # Subscription models
    SUBSCRIPTION = 'saas.subscription'
    INVOICE = 'saas.invoice'

    # Operational models
    BACKUP = 'saas.backup'
    QUEUE = 'saas.provisioning.queue'
    LOG = 'saas.activity.log'

    # Configuration models
    ADDON = 'saas.addon'
    FEATURE = 'saas.feature'


class FieldNames:
    """Common field name constants."""

    # Identifiers
    NAME = 'name'
    CODE = 'code'
    SUBDOMAIN = 'subdomain'
    FULL_DOMAIN = 'full_domain'

    # Relations
    PARTNER_ID = 'partner_id'
    PLAN_ID = 'plan_id'
    SERVER_ID = 'server_id'
    INSTANCE_ID = 'instance_id'
    SUBSCRIPTION_ID = 'subscription_id'

    # State fields
    STATE = 'state'
    IS_ACTIVE = 'is_active'
    IS_TRIAL = 'is_trial'

    # Resource limits
    CPU_LIMIT = 'cpu_limit'
    RAM_LIMIT_MB = 'ram_limit_mb'
    STORAGE_DB_LIMIT_GB = 'storage_db_limit_gb'
    STORAGE_FILE_LIMIT_GB = 'storage_file_limit_gb'
    USER_LIMIT = 'user_limit'
    INSTANCE_LIMIT = 'instance_limit'

    # Pricing
    MONTHLY_PRICE = 'monthly_price'
    YEARLY_PRICE = 'yearly_price'

    # Docker/Container
    CONTAINER_ID = 'container_id'
    DATABASE_NAME = 'database_name'
    PORT_HTTP = 'port_http'
    PORT_LONGPOLLING = 'port_longpolling'

    # Network
    IP_ADDRESS = 'ip_address'
    VPN_IP = 'vpn_ip'

    # Audit
    CREATED_BY_ID = 'created_by_id'
    UPDATED_BY_ID = 'updated_by_id'
    CREATED_DATE = 'created_date'
    UPDATED_DATE = 'updated_date'


class FieldLabels:
    """UI labels for fields."""

    # Common
    NAME = 'Name'
    CODE = 'Code'
    STATE = 'Status'
    ACTIVE = 'Active'

    # Plan related
    PLAN = 'Subscription Plan'
    MONTHLY_PRICE = 'Monthly Price'
    YEARLY_PRICE = 'Yearly Price'

    # Instance related
    SUBDOMAIN = 'Subdomain'
    FULL_DOMAIN = 'Full Domain'
    INSTANCE = 'Instance'

    # Server related
    SERVER = 'Tenant Server'
    IP_ADDRESS = 'IP Address'
    VPN_IP = 'VPN IP Address'

    # Resource limits
    CPU_LIMIT = 'CPU Limit (cores)'
    RAM_LIMIT = 'RAM Limit (MB)'
    STORAGE_DB = 'Database Storage (GB)'
    STORAGE_FILE = 'File Storage (GB)'
    USER_LIMIT = 'User Limit'
    INSTANCE_LIMIT = 'Instance Limit'
