# -*- coding: utf-8 -*-
"""
Ticket Category model for organizing support tickets.
"""

from odoo import models, fields, api


class TicketCategory(models.Model):
    """Support ticket category with SLA settings."""

    _name = 'saas.ticket.category'
    _description = 'Ticket Category'
    _order = 'sequence, name'

    # Odoo 19 constraint syntax
    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Category code must be unique!'
    )

    name = fields.Char(
        string='Name',
        required=True,
        translate=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
        help='Unique category identifier',
    )
    description = fields.Text(
        string='Description',
        translate=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    color = fields.Integer(
        string='Color',
        default=0,
    )

    # Default assignment
    default_user_id = fields.Many2one(
        'res.users',
        string='Default Assignee',
        help='Default user to assign tickets in this category',
    )
    team_ids = fields.Many2many(
        'res.users',
        'ticket_category_user_rel',
        'category_id',
        'user_id',
        string='Support Team',
        help='Users who can handle tickets in this category',
    )

    # SLA settings (in hours)
    sla_response_time = fields.Float(
        string='Response Time SLA (hours)',
        default=24.0,
        help='Target time to first response',
    )
    sla_resolution_time = fields.Float(
        string='Resolution Time SLA (hours)',
        default=72.0,
        help='Target time to resolve ticket',
    )

    # Ticket relationship for stored computed counts
    ticket_ids = fields.One2many(
        'saas.ticket',
        'category_id',
        string='Tickets',
    )

    # Statistics (stored for search/filter performance)
    ticket_count = fields.Integer(
        string='Ticket Count',
        compute='_compute_ticket_count',
        store=True,
    )
    open_ticket_count = fields.Integer(
        string='Open Tickets',
        compute='_compute_ticket_count',
        store=True,
    )

    @api.depends('ticket_ids', 'ticket_ids.state')
    def _compute_ticket_count(self):
        """Count tickets in this category."""
        for category in self:
            tickets = category.ticket_ids
            category.ticket_count = len(tickets)
            category.open_ticket_count = len(tickets.filtered(
                lambda t: t.state not in ['resolved', 'closed', 'cancelled']
            ))

    def action_view_tickets(self):
        """View tickets in this category."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Tickets - {self.name}',
            'res_model': 'saas.ticket',
            'view_mode': 'list,kanban,form',
            'domain': [('category_id', '=', self.id)],
            'context': {'default_category_id': self.id},
        }
