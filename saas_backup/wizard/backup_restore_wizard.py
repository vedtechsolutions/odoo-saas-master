# -*- coding: utf-8 -*-
"""
Backup Restore Confirmation Wizard.

Provides a confirmation step before restoring a backup.
"""

from odoo import models, fields, api
from odoo.exceptions import UserError


class BackupRestoreWizard(models.TransientModel):
    """Wizard for confirming backup restore operation."""

    _name = 'saas.backup.restore.wizard'
    _description = 'Backup Restore Confirmation'

    backup_id = fields.Many2one(
        'saas.backup',
        string='Backup',
        required=True,
        readonly=True,
    )
    instance_id = fields.Many2one(
        'saas.instance',
        string='Instance',
        required=True,
        readonly=True,
    )

    # Display fields
    backup_reference = fields.Char(
        related='backup_id.reference',
        string='Backup Reference',
    )
    backup_date = fields.Datetime(
        related='backup_id.create_date',
        string='Backup Date',
    )
    backup_size = fields.Char(
        related='backup_id.size_display',
        string='Backup Size',
    )
    instance_subdomain = fields.Char(
        related='instance_id.subdomain',
        string='Instance Subdomain',
    )
    instance_state = fields.Selection(
        related='instance_id.state',
        string='Instance State',
    )

    # Confirmation
    confirm_restore = fields.Boolean(
        string='I understand this will replace the current database',
        default=False,
    )

    # Warning message
    warning_message = fields.Text(
        string='Warning',
        compute='_compute_warning_message',
    )

    @api.depends('instance_id', 'backup_id')
    def _compute_warning_message(self):
        for wizard in self:
            if wizard.instance_id and wizard.backup_id:
                wizard.warning_message = (
                    f"WARNING: This action will:\n\n"
                    f"1. Stop the instance '{wizard.instance_subdomain}'\n"
                    f"2. DELETE the current database completely\n"
                    f"3. Restore data from backup '{wizard.backup_reference}'\n"
                    f"4. Start the instance\n\n"
                    f"All data since the backup ({wizard.backup_date}) will be LOST.\n\n"
                    f"This operation cannot be undone!"
                )
            else:
                wizard.warning_message = ""

    def action_restore(self):
        """Execute the restore after confirmation."""
        self.ensure_one()

        if not self.confirm_restore:
            raise UserError(
                "You must check the confirmation box to proceed with the restore."
            )

        # Call the actual restore method on the backup
        return self.backup_id.action_restore_confirmed()

    def action_cancel(self):
        """Cancel the restore operation."""
        return {'type': 'ir.actions.act_window_close'}
