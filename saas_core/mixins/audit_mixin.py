# -*- coding: utf-8 -*-
"""
Audit mixin for tracking record creation and modification.

Usage:
    class MyModel(models.Model):
        _name = 'my.model'
        _inherit = ['saas.audit.mixin']
"""

from odoo import models, fields, api


class SaasAuditMixin(models.AbstractModel):
    """
    Mixin that adds audit tracking fields to models.

    Adds:
        - created_by_id: User who created the record
        - updated_by_id: User who last modified the record
        - created_date: Date/time of creation
        - updated_date: Date/time of last modification
    """
    _name = 'saas.audit.mixin'
    _description = 'Audit Mixin'

    created_by_id = fields.Many2one(
        'res.users',
        string='Created By',
        readonly=True,
        default=lambda self: self.env.user,
        copy=False,
    )
    updated_by_id = fields.Many2one(
        'res.users',
        string='Last Updated By',
        readonly=True,
        copy=False,
    )
    created_date = fields.Datetime(
        string='Created On',
        readonly=True,
        default=fields.Datetime.now,
        copy=False,
    )
    updated_date = fields.Datetime(
        string='Last Updated On',
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Set created_by and created_date on record creation."""
        for vals in vals_list:
            vals['created_by_id'] = self.env.user.id
            vals['created_date'] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        """Set updated_by and updated_date on record modification."""
        vals['updated_by_id'] = self.env.user.id
        vals['updated_date'] = fields.Datetime.now()
        return super().write(vals)
