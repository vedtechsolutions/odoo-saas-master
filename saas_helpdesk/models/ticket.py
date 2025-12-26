# -*- coding: utf-8 -*-
"""
Support Ticket model for SaaS helpdesk.
"""

import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from odoo.addons.saas_core.constants.fields import ModelNames

_logger = logging.getLogger(__name__)


class TicketPriority:
    """Ticket priority constants."""
    LOW = '0'
    MEDIUM = '1'
    HIGH = '2'
    URGENT = '3'

    @classmethod
    def get_selection(cls):
        return [
            (cls.LOW, 'Low'),
            (cls.MEDIUM, 'Medium'),
            (cls.HIGH, 'High'),
            (cls.URGENT, 'Urgent'),
        ]


class TicketState:
    """Ticket state constants."""
    NEW = 'new'
    OPEN = 'open'
    IN_PROGRESS = 'in_progress'
    PENDING = 'pending'
    RESOLVED = 'resolved'
    CLOSED = 'closed'
    CANCELLED = 'cancelled'

    @classmethod
    def get_selection(cls):
        return [
            (cls.NEW, 'New'),
            (cls.OPEN, 'Open'),
            (cls.IN_PROGRESS, 'In Progress'),
            (cls.PENDING, 'Pending Customer'),
            (cls.RESOLVED, 'Resolved'),
            (cls.CLOSED, 'Closed'),
            (cls.CANCELLED, 'Cancelled'),
        ]

    @classmethod
    def get_open_states(cls):
        """States considered 'open' for SLA purposes."""
        return [cls.NEW, cls.OPEN, cls.IN_PROGRESS, cls.PENDING]


class SaasTicket(models.Model):
    """Support ticket for SaaS customers."""

    _name = 'saas.ticket'
    _description = 'Support Ticket'
    _order = 'priority desc, create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Odoo 19 constraint syntax
    _reference_unique = models.Constraint(
        'UNIQUE(reference)',
        'Ticket reference must be unique!'
    )

    # Basic fields
    name = fields.Char(
        string='Subject',
        required=True,
        tracking=True,
    )
    reference = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='New',
    )
    description = fields.Html(
        string='Description',
        help='Detailed description of the issue',
    )

    # State and priority
    state = fields.Selection(
        selection=TicketState.get_selection(),
        string='Status',
        default=TicketState.NEW,
        required=True,
        tracking=True,
        index=True,
    )
    priority = fields.Selection(
        selection=TicketPriority.get_selection(),
        string='Priority',
        default=TicketPriority.MEDIUM,
        required=True,
        tracking=True,
        index=True,
    )
    kanban_state = fields.Selection(
        selection=[
            ('normal', 'Grey'),
            ('done', 'Green'),
            ('blocked', 'Red'),
        ],
        string='Kanban State',
        default='normal',
    )
    color = fields.Integer(
        string='Color',
        compute='_compute_color',
        store=True,
    )

    # Category
    category_id = fields.Many2one(
        'saas.ticket.category',
        string='Category',
        tracking=True,
        ondelete='restrict',
    )

    # Customer information
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        tracking=True,
        ondelete='restrict',
        index=True,
    )
    partner_email = fields.Char(
        related='partner_id.email',
        string='Customer Email',
        readonly=True,
    )
    partner_phone = fields.Char(
        related='partner_id.phone',
        string='Customer Phone',
        readonly=True,
    )

    # Related SaaS records
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Related Instance',
        tracking=True,
        ondelete='set null',
        help='SaaS instance this ticket relates to',
    )
    subscription_id = fields.Many2one(
        ModelNames.SUBSCRIPTION,
        string='Related Subscription',
        tracking=True,
        ondelete='set null',
        help='Subscription this ticket relates to',
    )

    # Assignment
    user_id = fields.Many2one(
        'res.users',
        string='Assigned To',
        tracking=True,
        index=True,
    )
    team_id = fields.Many2one(
        'res.users',
        string='Team Lead',
        help='Team lead responsible for this ticket',
    )

    # Dates and SLA tracking
    create_date = fields.Datetime(
        string='Created On',
        readonly=True,
    )
    first_response_date = fields.Datetime(
        string='First Response',
        readonly=True,
        help='When the first response was sent',
    )
    resolved_date = fields.Datetime(
        string='Resolved On',
        readonly=True,
    )
    closed_date = fields.Datetime(
        string='Closed On',
        readonly=True,
    )
    deadline = fields.Datetime(
        string='Deadline',
        tracking=True,
        help='Expected resolution deadline',
    )

    # SLA computed fields
    sla_response_hours = fields.Float(
        string='Response Time (hours)',
        compute='_compute_sla_times',
        store=True,
    )
    sla_resolution_hours = fields.Float(
        string='Resolution Time (hours)',
        compute='_compute_sla_times',
        store=True,
    )
    sla_response_status = fields.Selection(
        selection=[
            ('on_track', 'On Track'),
            ('warning', 'Warning'),
            ('breached', 'Breached'),
            ('met', 'Met'),
        ],
        string='Response SLA',
        compute='_compute_sla_status',
        store=True,
    )
    sla_resolution_status = fields.Selection(
        selection=[
            ('on_track', 'On Track'),
            ('warning', 'Warning'),
            ('breached', 'Breached'),
            ('met', 'Met'),
        ],
        string='Resolution SLA',
        compute='_compute_sla_status',
        store=True,
    )

    # Ticket Messages (renamed to avoid conflict with mail.thread's message_ids)
    ticket_message_ids = fields.One2many(
        'saas.ticket.message',
        'ticket_id',
        string='Ticket Messages',
    )
    ticket_message_count = fields.Integer(
        string='Message Count',
        compute='_compute_ticket_message_count',
        store=True,
    )

    # Tags for additional categorization
    tag_ids = fields.Many2many(
        'saas.ticket.tag',
        string='Tags',
    )

    @api.depends('priority')
    def _compute_color(self):
        """Set color based on priority."""
        color_map = {
            TicketPriority.LOW: 0,      # Grey
            TicketPriority.MEDIUM: 4,   # Blue
            TicketPriority.HIGH: 2,     # Orange
            TicketPriority.URGENT: 1,   # Red
        }
        for ticket in self:
            ticket.color = color_map.get(ticket.priority, 0)

    @api.depends('first_response_date', 'resolved_date', 'create_date')
    def _compute_sla_times(self):
        """Calculate SLA times in hours."""
        for ticket in self:
            if ticket.first_response_date and ticket.create_date:
                delta = ticket.first_response_date - ticket.create_date
                ticket.sla_response_hours = delta.total_seconds() / 3600
            else:
                ticket.sla_response_hours = 0

            if ticket.resolved_date and ticket.create_date:
                delta = ticket.resolved_date - ticket.create_date
                ticket.sla_resolution_hours = delta.total_seconds() / 3600
            else:
                ticket.sla_resolution_hours = 0

    @api.depends('sla_response_hours', 'sla_resolution_hours', 'category_id',
                 'first_response_date', 'resolved_date', 'state', 'create_date')
    def _compute_sla_status(self):
        """Calculate SLA status."""
        now = fields.Datetime.now()
        for ticket in self:
            response_target = ticket.category_id.sla_response_time or 24.0
            resolution_target = ticket.category_id.sla_resolution_time or 72.0

            # Response SLA
            if ticket.first_response_date:
                if ticket.sla_response_hours <= response_target:
                    ticket.sla_response_status = 'met'
                else:
                    ticket.sla_response_status = 'breached'
            elif ticket.create_date:
                elapsed = (now - ticket.create_date).total_seconds() / 3600
                if elapsed > response_target:
                    ticket.sla_response_status = 'breached'
                elif elapsed > response_target * 0.8:
                    ticket.sla_response_status = 'warning'
                else:
                    ticket.sla_response_status = 'on_track'
            else:
                ticket.sla_response_status = 'on_track'

            # Resolution SLA
            if ticket.state in ['resolved', 'closed']:
                if ticket.sla_resolution_hours <= resolution_target:
                    ticket.sla_resolution_status = 'met'
                else:
                    ticket.sla_resolution_status = 'breached'
            elif ticket.create_date:
                elapsed = (now - ticket.create_date).total_seconds() / 3600
                if elapsed > resolution_target:
                    ticket.sla_resolution_status = 'breached'
                elif elapsed > resolution_target * 0.8:
                    ticket.sla_resolution_status = 'warning'
                else:
                    ticket.sla_resolution_status = 'on_track'
            else:
                ticket.sla_resolution_status = 'on_track'

    @api.depends('ticket_message_ids')
    def _compute_ticket_message_count(self):
        """Count messages on this ticket."""
        for ticket in self:
            ticket.ticket_message_count = len(ticket.ticket_message_ids)

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate reference and set defaults."""
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'saas.ticket'
                ) or 'New'

            # Set default assignee from category
            if vals.get('category_id') and not vals.get('user_id'):
                category = self.env['saas.ticket.category'].browse(vals['category_id'])
                if category.default_user_id:
                    vals['user_id'] = category.default_user_id.id

        tickets = super().create(vals_list)

        # Send auto-response email for each created ticket (T-134)
        for ticket in tickets:
            ticket._send_ticket_created_notification()

        return tickets

    def _send_ticket_created_notification(self):
        """Send auto-response email when ticket is created."""
        self.ensure_one()
        try:
            template = self.env.ref(
                'saas_helpdesk.mail_template_ticket_created',
                raise_if_not_found=False
            )
            if not template:
                template = self.env['mail.template'].search(
                    [('name', '=', 'SaaS Helpdesk: Ticket Created')], limit=1
                )
            if template and self.partner_id:
                template.send_mail(self.id, force_send=True)
                _logger.info(f"Ticket created notification sent for {self.reference}")
        except Exception as e:
            _logger.error(f"Failed to send ticket created notification: {e}")

    def _send_ticket_resolved_notification(self):
        """Send notification when ticket is resolved."""
        self.ensure_one()
        try:
            template = self.env.ref(
                'saas_helpdesk.mail_template_ticket_resolved',
                raise_if_not_found=False
            )
            if not template:
                template = self.env['mail.template'].search(
                    [('name', '=', 'SaaS Helpdesk: Ticket Resolved')], limit=1
                )
            if template and self.partner_id:
                template.send_mail(self.id, force_send=True)
                _logger.info(f"Ticket resolved notification sent for {self.reference}")
        except Exception as e:
            _logger.error(f"Failed to send ticket resolved notification: {e}")

    @api.onchange('category_id')
    def _onchange_category_id(self):
        """Set default assignee when category changes."""
        if self.category_id and self.category_id.default_user_id:
            self.user_id = self.category_id.default_user_id

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Load customer's instances for selection."""
        if self.partner_id:
            return {
                'domain': {
                    'instance_id': [('partner_id', '=', self.partner_id.id)],
                    'subscription_id': [('partner_id', '=', self.partner_id.id)],
                }
            }

    def action_open(self):
        """Mark ticket as open/acknowledged."""
        self.ensure_one()
        if self.state != TicketState.NEW:
            raise UserError(_("Can only open new tickets."))
        self.write({'state': TicketState.OPEN})
        self.message_post(body="Ticket opened and acknowledged.")

    def action_start_progress(self):
        """Start working on ticket."""
        self.ensure_one()
        if self.state not in [TicketState.NEW, TicketState.OPEN, TicketState.PENDING]:
            raise UserError(_("Cannot start progress on this ticket."))
        self.write({
            'state': TicketState.IN_PROGRESS,
            'user_id': self.user_id.id or self.env.user.id,
        })
        self.message_post(body="Started working on ticket.")

    def action_pending(self):
        """Mark as pending customer response."""
        self.ensure_one()
        if self.state not in [TicketState.OPEN, TicketState.IN_PROGRESS]:
            raise UserError(_("Cannot set pending on this ticket."))
        self.write({'state': TicketState.PENDING})
        self.message_post(body="Waiting for customer response.")

    def action_resolve(self):
        """Mark ticket as resolved."""
        self.ensure_one()
        if self.state in [TicketState.CLOSED, TicketState.CANCELLED]:
            raise UserError(_("Cannot resolve a closed or cancelled ticket."))
        self.write({
            'state': TicketState.RESOLVED,
            'resolved_date': fields.Datetime.now(),
        })
        self.message_post(body="Ticket marked as resolved.")
        self._send_ticket_resolved_notification()

    def action_close(self):
        """Close the ticket."""
        self.ensure_one()
        if self.state == TicketState.CANCELLED:
            raise UserError(_("Cannot close a cancelled ticket."))
        self.write({
            'state': TicketState.CLOSED,
            'closed_date': fields.Datetime.now(),
        })
        if not self.resolved_date:
            self.resolved_date = fields.Datetime.now()
        self.message_post(body="Ticket closed.")

    def action_reopen(self):
        """Reopen a resolved or closed ticket."""
        self.ensure_one()
        if self.state not in [TicketState.RESOLVED, TicketState.CLOSED]:
            raise UserError(_("Can only reopen resolved or closed tickets."))
        self.write({
            'state': TicketState.OPEN,
            'resolved_date': False,
            'closed_date': False,
        })
        self.message_post(body="Ticket reopened.")

    def action_cancel(self):
        """Cancel the ticket."""
        self.ensure_one()
        if self.state == TicketState.CLOSED:
            raise UserError(_("Cannot cancel a closed ticket."))
        self.write({'state': TicketState.CANCELLED})
        self.message_post(body="Ticket cancelled.")

    def action_assign_to_me(self):
        """Assign ticket to current user."""
        self.write({'user_id': self.env.user.id})

    def action_view_messages(self):
        """View all messages for this ticket."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Messages - {self.reference}',
            'res_model': 'saas.ticket.message',
            'view_mode': 'list,form',
            'domain': [('ticket_id', '=', self.id)],
            'context': {'default_ticket_id': self.id},
        }

    def action_send_reply(self):
        """Open wizard to send a reply."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Reply',
            'res_model': 'saas.ticket.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_id': self.id,
                'default_author_id': self.env.user.partner_id.id,
                'default_is_internal': False,
            },
        }


class TicketTag(models.Model):
    """Tags for ticket categorization."""

    _name = 'saas.ticket.tag'
    _description = 'Ticket Tag'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
    )
    color = fields.Integer(
        string='Color',
        default=0,
    )
