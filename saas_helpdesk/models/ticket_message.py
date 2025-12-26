# -*- coding: utf-8 -*-
"""
Ticket Message model for support ticket communications.
"""

from odoo import models, fields, api


class TicketMessage(models.Model):
    """Message/reply on a support ticket."""

    _name = 'saas.ticket.message'
    _description = 'Ticket Message'
    _order = 'create_date desc'

    ticket_id = fields.Many2one(
        'saas.ticket',
        string='Ticket',
        required=True,
        ondelete='cascade',
        index=True,
    )
    ticket_reference = fields.Char(
        related='ticket_id.reference',
        string='Ticket Ref',
        readonly=True,
        store=True,
    )

    # Message content
    body = fields.Html(
        string='Message',
        required=True,
    )
    is_internal = fields.Boolean(
        string='Internal Note',
        default=False,
        help='Internal notes are not visible to customers',
    )

    # Author information
    author_id = fields.Many2one(
        'res.partner',
        string='Author',
        default=lambda self: self.env.user.partner_id,
        required=True,
    )
    author_name = fields.Char(
        related='author_id.name',
        string='Author Name',
        readonly=True,
    )
    is_customer_message = fields.Boolean(
        string='From Customer',
        compute='_compute_is_customer_message',
        store=True,
    )

    # Attachments
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'ticket_message_attachment_rel',
        'message_id',
        'attachment_id',
        string='Attachments',
    )
    attachment_count = fields.Integer(
        string='Attachment Count',
        compute='_compute_attachment_count',
    )

    # Timestamps
    create_date = fields.Datetime(
        string='Sent On',
        readonly=True,
    )

    @api.depends('author_id', 'ticket_id.partner_id')
    def _compute_is_customer_message(self):
        """Check if message is from the customer."""
        for message in self:
            if message.ticket_id and message.author_id:
                message.is_customer_message = (
                    message.author_id == message.ticket_id.partner_id
                )
            else:
                message.is_customer_message = False

    def _compute_attachment_count(self):
        """Count attachments."""
        for message in self:
            message.attachment_count = len(message.attachment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to update ticket and track first response."""
        messages = super().create(vals_list)

        for message in messages:
            ticket = message.ticket_id

            # Update first response date if this is first staff response
            if not message.is_customer_message and not ticket.first_response_date:
                ticket.first_response_date = message.create_date

            # If customer responds to pending ticket, move to open
            if message.is_customer_message and ticket.state == 'pending':
                ticket.write({'state': 'open'})

            # Post to chatter
            body = f"<p><strong>{'Internal Note' if message.is_internal else 'Reply'}</strong> from {message.author_id.name}:</p>{message.body}"
            subtype = 'mail.mt_note' if message.is_internal else 'mail.mt_comment'
            ticket.message_post(body=body, subtype_xmlid=subtype)

        return messages

    def action_view_attachments(self):
        """View attachments."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attachments',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.attachment_ids.ids)],
        }
