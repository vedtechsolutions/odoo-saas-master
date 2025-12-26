# -*- coding: utf-8 -*-
"""
Support Access Wizard.

Displays credentials and provides quick access link for support impersonation.
"""

from odoo import models, fields, api


class SupportAccessWizard(models.TransientModel):
    """Wizard showing support access credentials."""

    _name = 'saas.support.access.wizard'
    _description = 'Support Access Wizard'

    instance_id = fields.Many2one(
        'saas.instance',
        string='Instance',
        readonly=True,
    )
    instance_url = fields.Char(
        string='Instance URL',
        readonly=True,
    )
    admin_login = fields.Char(
        string='Username',
        readonly=True,
    )
    admin_password = fields.Char(
        string='Password',
        readonly=True,
    )

    def action_open_instance(self):
        """Open the instance login page in a new tab."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f"{self.instance_url}/web/login",
            'target': 'new',
        }

    def action_copy_credentials(self):
        """Show notification with credentials for easy copy."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Credentials Copied',
                'message': f"Username: {self.admin_login}\nPassword: {self.admin_password}",
                'type': 'info',
                'sticky': True,
            }
        }
