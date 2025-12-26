# -*- coding: utf-8 -*-
"""
Subscription billing extensions.

Note: Main billing logic is in proration.py (SaasSubscriptionBilling).
This file contains additional MRR/ARR analytics.
"""

import logging
from datetime import date

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SubscriptionAnalytics(models.Model):
    """Analytics extensions for subscriptions."""

    _inherit = 'saas.subscription'

    # MRR/ARR calculations
    mrr = fields.Monetary(
        string='MRR',
        compute='_compute_mrr_arr',
        help='Monthly Recurring Revenue',
    )
    arr = fields.Monetary(
        string='ARR',
        compute='_compute_mrr_arr',
        help='Annual Recurring Revenue',
    )

    @api.depends('recurring_price', 'billing_cycle', 'state')
    def _compute_mrr_arr(self):
        """Calculate MRR and ARR."""
        for sub in self:
            if sub.state not in ['active', 'past_due']:
                sub.mrr = 0
                sub.arr = 0
                continue

            if sub.billing_cycle == 'yearly':
                sub.arr = sub.recurring_price
                sub.mrr = sub.recurring_price / 12
            else:
                sub.mrr = sub.recurring_price
                sub.arr = sub.recurring_price * 12


class MRRReport(models.Model):
    """MRR/ARR reporting model."""

    _name = 'saas.mrr.report'
    _description = 'MRR Report'
    _auto = False
    _order = 'date desc'

    date = fields.Date(
        string='Date',
        readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        readonly=True,
    )
    subscription_id = fields.Many2one(
        'saas.subscription',
        string='Subscription',
        readonly=True,
    )
    plan_id = fields.Many2one(
        'saas.plan',
        string='Plan',
        readonly=True,
    )
    billing_cycle = fields.Selection(
        selection=[
            ('monthly', 'Monthly'),
            ('yearly', 'Yearly'),
        ],
        string='Billing Cycle',
        readonly=True,
    )
    mrr = fields.Float(
        string='MRR',
        readonly=True,
    )
    arr = fields.Float(
        string='ARR',
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('trial', 'Trial'),
            ('active', 'Active'),
            ('past_due', 'Past Due'),
            ('suspended', 'Suspended'),
            ('cancelled', 'Cancelled'),
            ('expired', 'Expired'),
        ],
        string='State',
        readonly=True,
    )

    def init(self):
        """Create the SQL view for MRR reporting."""
        self.env.cr.execute("""
            DROP VIEW IF EXISTS saas_mrr_report;
            CREATE OR REPLACE VIEW saas_mrr_report AS (
                SELECT
                    s.id as id,
                    CURRENT_DATE as date,
                    s.partner_id,
                    s.id as subscription_id,
                    s.plan_id,
                    s.billing_cycle,
                    s.state,
                    CASE
                        WHEN s.state IN ('active', 'past_due') THEN
                            CASE
                                WHEN s.billing_cycle = 'yearly' THEN s.recurring_price / 12
                                ELSE s.recurring_price
                            END
                        ELSE 0
                    END as mrr,
                    CASE
                        WHEN s.state IN ('active', 'past_due') THEN
                            CASE
                                WHEN s.billing_cycle = 'yearly' THEN s.recurring_price
                                ELSE s.recurring_price * 12
                            END
                        ELSE 0
                    END as arr
                FROM saas_subscription s
            )
        """)
