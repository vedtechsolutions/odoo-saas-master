# -*- coding: utf-8 -*-
"""
State constants for SaaS models.

Usage:
    from odoo.addons.saas_core.constants.states import InstanceState

    state = fields.Selection(
        selection=InstanceState.get_selection(),
        default=InstanceState.DRAFT,
    )
"""


class InstanceState:
    """Instance state constants."""

    DRAFT = 'draft'
    PENDING = 'pending'
    PROVISIONING = 'provisioning'
    RUNNING = 'running'
    STOPPED = 'stopped'
    SUSPENDED = 'suspended'
    ERROR = 'error'
    TERMINATED = 'terminated'

    @classmethod
    def get_selection(cls):
        """Return selection list for Odoo field."""
        return [
            (cls.DRAFT, 'Draft'),
            (cls.PENDING, 'Pending'),
            (cls.PROVISIONING, 'Provisioning'),
            (cls.RUNNING, 'Running'),
            (cls.STOPPED, 'Stopped'),
            (cls.SUSPENDED, 'Suspended'),
            (cls.ERROR, 'Error'),
            (cls.TERMINATED, 'Terminated'),
        ]

    @classmethod
    def get_active_states(cls):
        """Return states that are considered active/billable."""
        return [cls.RUNNING, cls.STOPPED, cls.SUSPENDED]

    @classmethod
    def get_operational_states(cls):
        """Return states where container exists."""
        return [cls.RUNNING, cls.STOPPED, cls.SUSPENDED, cls.ERROR]


class ServerState:
    """Tenant server state constants."""

    OFFLINE = 'offline'
    ONLINE = 'online'
    MAINTENANCE = 'maintenance'
    FULL = 'full'
    ERROR = 'error'

    @classmethod
    def get_selection(cls):
        """Return selection list for Odoo field."""
        return [
            (cls.OFFLINE, 'Offline'),
            (cls.ONLINE, 'Online'),
            (cls.MAINTENANCE, 'Maintenance'),
            (cls.FULL, 'Full'),
            (cls.ERROR, 'Error'),
        ]

    @classmethod
    def get_available_states(cls):
        """Return states where server can accept new instances."""
        return [cls.ONLINE]


class SubscriptionState:
    """Subscription state constants."""

    DRAFT = 'draft'
    TRIAL = 'trial'
    ACTIVE = 'active'
    PAST_DUE = 'past_due'
    SUSPENDED = 'suspended'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'

    @classmethod
    def get_selection(cls):
        """Return selection list for Odoo field."""
        return [
            (cls.DRAFT, 'Draft'),
            (cls.TRIAL, 'Trial'),
            (cls.ACTIVE, 'Active'),
            (cls.PAST_DUE, 'Past Due'),
            (cls.SUSPENDED, 'Suspended'),
            (cls.CANCELLED, 'Cancelled'),
            (cls.EXPIRED, 'Expired'),
        ]

    @classmethod
    def get_billable_states(cls):
        """Return states that should generate invoices."""
        return [cls.ACTIVE, cls.PAST_DUE]


class BackupState:
    """Backup state constants."""

    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    EXPIRED = 'expired'

    @classmethod
    def get_selection(cls):
        """Return selection list for Odoo field."""
        return [
            (cls.PENDING, 'Pending'),
            (cls.IN_PROGRESS, 'In Progress'),
            (cls.COMPLETED, 'Completed'),
            (cls.FAILED, 'Failed'),
            (cls.EXPIRED, 'Expired'),
        ]


class QueueState:
    """Provisioning queue state constants."""

    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'

    @classmethod
    def get_selection(cls):
        """Return selection list for Odoo field."""
        return [
            (cls.PENDING, 'Pending'),
            (cls.PROCESSING, 'Processing'),
            (cls.COMPLETED, 'Completed'),
            (cls.FAILED, 'Failed'),
            (cls.CANCELLED, 'Cancelled'),
        ]
