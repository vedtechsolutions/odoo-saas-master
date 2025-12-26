# -*- coding: utf-8 -*-
"""
SaaS Subscription Plan model.

Defines pricing tiers with resource limits for customer instances.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError

from odoo.addons.saas_core.constants.fields import ModelNames, FieldNames, FieldLabels
from odoo.addons.saas_core.constants.config import PlanConfig


class SaasPlan(models.Model):
    """Subscription plan defining pricing and resource limits."""

    _name = ModelNames.PLAN
    _description = 'SaaS Subscription Plan'
    _order = 'sequence, id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Odoo 19 constraint syntax
    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Plan code must be unique!'
    )

    # Basic fields
    name = fields.Char(
        string=FieldLabels.NAME,
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string=FieldLabels.CODE,
        required=True,
        index=True,
        help='Unique plan identifier (e.g., trial, solo, starter)',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Display order in lists',
    )
    description = fields.Text(
        string='Description',
        help='Plan description for marketing purposes',
    )
    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, this plan is not available for new subscriptions',
    )
    is_trial = fields.Boolean(
        string='Trial Plan',
        default=False,
        help='Mark this as a trial/free plan',
    )

    # Pricing
    monthly_price = fields.Float(
        string=FieldLabels.MONTHLY_PRICE,
        digits=(10, 2),
        default=0.0,
        tracking=True,
    )
    yearly_price = fields.Float(
        string=FieldLabels.YEARLY_PRICE,
        digits=(10, 2),
        default=0.0,
        tracking=True,
        help='Annual price (typically discounted)',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )

    # Resource limits
    cpu_limit = fields.Float(
        string=FieldLabels.CPU_LIMIT,
        default=PlanConfig.DEFAULT_CPU_LIMIT,
        help='CPU cores allocated to instance (e.g., 0.5, 1.0, 2.0)',
    )
    ram_limit_mb = fields.Integer(
        string=FieldLabels.RAM_LIMIT,
        default=PlanConfig.DEFAULT_RAM_LIMIT_MB,
        help='RAM limit in megabytes',
    )
    storage_db_limit_gb = fields.Float(
        string=FieldLabels.STORAGE_DB,
        default=PlanConfig.DEFAULT_STORAGE_DB_GB,
        help='Database storage limit in gigabytes',
    )
    storage_file_limit_gb = fields.Float(
        string=FieldLabels.STORAGE_FILE,
        default=PlanConfig.DEFAULT_STORAGE_FILE_GB,
        help='File storage limit in gigabytes',
    )
    user_limit = fields.Integer(
        string=FieldLabels.USER_LIMIT,
        default=PlanConfig.DEFAULT_USER_LIMIT,
        help='Maximum number of users allowed',
    )
    instance_limit = fields.Integer(
        string=FieldLabels.INSTANCE_LIMIT,
        default=PlanConfig.DEFAULT_INSTANCE_LIMIT,
        help='Maximum number of instances per subscription',
    )

    # Features
    backup_retention_days = fields.Integer(
        string='Backup Retention (days)',
        default=7,
        help='Number of days to retain backups',
    )
    support_level = fields.Selection(
        selection=[
            ('community', 'Community'),
            ('email', 'Email Support'),
            ('priority', 'Priority Support'),
            ('dedicated', 'Dedicated Support'),
        ],
        string='Support Level',
        default='community',
    )

    # Computed fields
    instance_count = fields.Integer(
        string='Instances',
        compute='_compute_instance_count',
        # Not stored - recalculates on each access to ensure accuracy
        # Storing would require triggers from saas.instance model
    )
    subscription_count = fields.Integer(
        string='Subscriptions',
        compute='_compute_subscription_count',
    )

    def _compute_instance_count(self):
        """Count instances using this plan."""
        Instance = self.env[ModelNames.INSTANCE]
        for plan in self:
            plan.instance_count = Instance.search_count([
                ('plan_id', '=', plan.id)
            ])

    def _compute_subscription_count(self):
        """Count active subscriptions for this plan."""
        # Will be implemented when subscription model exists
        for plan in self:
            plan.subscription_count = 0

    def action_view_instances(self):
        """Open instances using this plan."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Instances - {self.name}',
            'res_model': ModelNames.INSTANCE,
            'view_mode': 'tree,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    @api.model
    def get_trial_plan(self):
        """Get the trial plan record."""
        return self.search([('code', '=', PlanConfig.PLAN_TRIAL)], limit=1)

    @api.model
    def get_available_plans(self):
        """Get all active non-trial plans."""
        return self.search([
            ('is_active', '=', True),
            ('is_trial', '=', False),
        ])

    @api.constrains(FieldNames.RAM_LIMIT_MB)
    def _check_ram_limit(self):
        """
        Validate RAM limit meets minimum requirements for Odoo 19.

        Odoo 19 requires at least 1GB RAM to run reliably.
        512MB causes 96%+ memory pressure and instability.
        256MB causes immediate crashes and blank screens.
        """
        for plan in self:
            if plan.ram_limit_mb < PlanConfig.MIN_RAM_LIMIT_MB:
                raise ValidationError(
                    f"RAM limit must be at least {PlanConfig.MIN_RAM_LIMIT_MB}MB (1GB). "
                    f"Odoo 19 requires minimum 1GB RAM to run reliably. "
                    f"Lower values cause memory pressure, worker crashes, and connection issues."
                )
            if plan.ram_limit_mb > PlanConfig.MAX_RAM_LIMIT_MB:
                raise ValidationError(
                    f"RAM limit cannot exceed {PlanConfig.MAX_RAM_LIMIT_MB}MB."
                )

    @api.constrains(FieldNames.CPU_LIMIT)
    def _check_cpu_limit(self):
        """Validate CPU limit is within acceptable range."""
        for plan in self:
            if plan.cpu_limit < PlanConfig.MIN_CPU_LIMIT:
                raise ValidationError(
                    f"CPU limit must be at least {PlanConfig.MIN_CPU_LIMIT} cores."
                )
            if plan.cpu_limit > PlanConfig.MAX_CPU_LIMIT:
                raise ValidationError(
                    f"CPU limit cannot exceed {PlanConfig.MAX_CPU_LIMIT} cores."
                )
