# -*- coding: utf-8 -*-
"""
SaaS Support Access Request model.

Manages customer approval workflow for support access to tenant instances.
"""

import logging
import secrets
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from odoo.addons.saas_core.constants.fields import ModelNames

_logger = logging.getLogger(__name__)


class SaasSupportAccessRequest(models.Model):
    """Support access request requiring customer approval."""

    _name = 'saas.support.access.request'
    _description = 'Support Access Request'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # Relations
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        required=True,
        ondelete='cascade',
        index=True,
    )
    requested_by_id = fields.Many2one(
        'res.users',
        string='Requested By',
        required=True,
        default=lambda self: self.env.uid,
        ondelete='restrict',
    )

    # Request details
    reason = fields.Text(
        string='Reason for Access',
        help='Why support needs to access this instance',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('denied', 'Denied'),
            ('expired', 'Expired'),
            ('used', 'Used'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
    )

    # Approval token
    approval_token = fields.Char(
        string='Approval Token',
        readonly=True,
        copy=False,
        index=True,
    )
    token_expiry = fields.Datetime(
        string='Token Expiry',
        readonly=True,
    )

    # Timestamps
    requested_date = fields.Datetime(
        string='Requested',
        default=fields.Datetime.now,
        readonly=True,
    )
    approved_date = fields.Datetime(
        string='Approved',
        readonly=True,
    )
    accessed_date = fields.Datetime(
        string='Accessed',
        readonly=True,
    )

    # Related fields
    instance_subdomain = fields.Char(
        related='instance_id.subdomain',
        string='Subdomain',
        store=True,
    )
    customer_email = fields.Char(
        related='instance_id.admin_email',
        string='Customer Email',
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('instance_subdomain', 'requested_by_id', 'state')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.instance_subdomain} - {record.requested_by_id.name} ({record.state})"

    @api.model_create_multi
    def create(self, vals_list):
        """Generate approval token on create."""
        for vals in vals_list:
            if not vals.get('approval_token'):
                vals['approval_token'] = secrets.token_urlsafe(32)
            if not vals.get('token_expiry'):
                vals['token_expiry'] = fields.Datetime.now() + timedelta(hours=1)
        return super().create(vals_list)

    def action_approve(self):
        """Approve the support access request."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(_("This request is no longer pending."))

        if fields.Datetime.now() > self.token_expiry:
            self.state = 'expired'
            raise UserError(_("This request has expired."))

        self.write({
            'state': 'approved',
            'approved_date': fields.Datetime.now(),
        })

        # Notify support user that access was approved
        self._notify_support_approved()

        _logger.info(f"Support access approved for {self.instance_subdomain} by customer")
        return True

    def action_deny(self):
        """Deny the support access request."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(_("This request is no longer pending."))

        self.state = 'denied'
        _logger.info(f"Support access denied for {self.instance_subdomain} by customer")
        return True

    def action_access_instance(self):
        """
        Access the instance after approval.

        Creates login token and redirects to tenant.
        """
        self.ensure_one()

        if self.state != 'approved':
            raise UserError(_("This request has not been approved yet."))

        # Check if approval is still valid (within 1 hour of approval)
        if self.approved_date:
            time_since_approval = fields.Datetime.now() - self.approved_date
            if time_since_approval > timedelta(hours=1):
                self.state = 'expired'
                raise UserError(_("Approval has expired. Please request access again."))

        # Create the login token
        token = self.instance_id._create_support_access_token()

        if not token:
            raise UserError(_("Failed to create access token. Please try again."))

        # Mark as used
        self.write({
            'state': 'used',
            'accessed_date': fields.Datetime.now(),
        })

        # Log the access
        self.instance_id._log_support_access()

        # Redirect to tenant
        login_url = f"{self.instance_id.instance_url}/support/login?token={token}"
        return {
            'type': 'ir.actions.act_url',
            'url': login_url,
            'target': 'new',
        }

    def _notify_support_approved(self):
        """Notify the support user that their request was approved."""
        try:
            subject = f"Access Approved: {self.instance_id.name}"
            body_html = f"""
            <p>Your support access request for <strong>{self.instance_id.name}</strong> has been approved by the customer.</p>
            <p>You can now access the instance from the SaaS Platform.</p>
            <p><em>Note: This approval is valid for 1 hour.</em></p>
            """

            mail_values = {
                'subject': subject,
                'body_html': body_html,
                'email_to': self.requested_by_id.email,
                'email_from': self.env.company.email or 'noreply@vedtechsolutions.com',
                'auto_delete': True,
            }
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()
        except Exception as e:
            _logger.error(f"Failed to send approval notification: {e}")

    def get_approval_url(self):
        """Get the public URL for customer to approve this request."""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/support/approve/{self.approval_token}"

    @api.model
    def cleanup_expired_requests(self):
        """Cron job to mark expired requests."""
        expired = self.search([
            ('state', '=', 'pending'),
            ('token_expiry', '<', fields.Datetime.now()),
        ])
        expired.write({'state': 'expired'})
        _logger.info(f"Marked {len(expired)} support access requests as expired")
        return True
