# -*- coding: utf-8 -*-
"""
Instance extension for backup functionality.

Adds backup-related fields and methods to instances.
"""

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from odoo.addons.saas_core.constants.config import BackupConfig

_logger = logging.getLogger(__name__)


class SaasInstanceBackup(models.Model):
    """Extend SaaS Instance with backup capabilities."""

    _inherit = 'saas.instance'

    # Backup relations
    backup_ids = fields.One2many(
        'saas.backup',
        'instance_id',
        string='Backups',
    )
    schedule_ids = fields.One2many(
        'saas.backup.schedule',
        'instance_id',
        string='Backup Schedules',
    )

    # Backup statistics
    backup_count = fields.Integer(
        string='Backup Count',
        compute='_compute_backup_stats',
    )
    last_backup_date = fields.Datetime(
        string='Last Backup',
        compute='_compute_backup_stats',
    )
    last_backup_state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        string='Last Backup Status',
        compute='_compute_backup_stats',
    )
    total_backup_size = fields.Float(
        string='Total Backup Size (MB)',
        compute='_compute_backup_stats',
    )
    backup_size_display = fields.Char(
        string='Backup Size',
        compute='_compute_backup_stats',
    )

    # Retention info
    backup_retention_days = fields.Integer(
        string='Backup Retention (days)',
        compute='_compute_backup_retention',
    )

    def _compute_backup_stats(self):
        """Compute backup statistics for instance."""
        for instance in self:
            backups = instance.backup_ids.filtered(
                lambda b: b.state in ['completed', 'pending', 'in_progress', 'failed']
            )
            instance.backup_count = len(backups)

            # Get last backup
            last_backup = backups.sorted('create_date', reverse=True)[:1]
            if last_backup:
                instance.last_backup_date = last_backup.create_date
                instance.last_backup_state = last_backup.state
            else:
                instance.last_backup_date = False
                instance.last_backup_state = False

            # Calculate total size of completed backups
            completed = backups.filtered(lambda b: b.state == 'completed')
            total_size = sum(b.total_size for b in completed)
            instance.total_backup_size = total_size

            if total_size >= 1024:
                instance.backup_size_display = f"{total_size / 1024:.2f} GB"
            else:
                instance.backup_size_display = f"{total_size:.2f} MB"

    def _compute_backup_retention(self):
        """Get backup retention based on plan."""
        for instance in self:
            if not instance.plan_id:
                instance.backup_retention_days = BackupConfig.RETENTION_TRIAL
                continue

            plan_code = instance.plan_id.code if hasattr(instance.plan_id, 'code') else ''

            retention_map = {
                'trial': BackupConfig.RETENTION_TRIAL,
                'starter': BackupConfig.RETENTION_BASIC,
                'professional': BackupConfig.RETENTION_PROFESSIONAL,
                'enterprise': BackupConfig.RETENTION_ENTERPRISE,
            }

            instance.backup_retention_days = retention_map.get(
                plan_code, BackupConfig.RETENTION_BASIC
            )

    def action_create_backup(self):
        """Create a manual backup for this instance."""
        self.ensure_one()

        if self.state != 'running':
            raise UserError(_("Can only backup running instances."))

        Backup = self.env['saas.backup']
        backup = Backup.create({
            'instance_id': self.id,
            'backup_type': 'full',
            'trigger': 'manual',
        })

        # Start backup immediately
        backup.action_start_backup()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Backup',
            'res_model': 'saas.backup',
            'view_mode': 'form',
            'res_id': backup.id,
        }

    def action_view_backups(self):
        """View all backups for this instance."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Backups - {self.subdomain}',
            'res_model': 'saas.backup',
            'view_mode': 'list,form',
            'domain': [('instance_id', '=', self.id)],
            'context': {'default_instance_id': self.id},
        }

    def action_restore_backup(self):
        """Open wizard to select backup for restore."""
        self.ensure_one()

        # Get available backups
        backups = self.backup_ids.filtered(lambda b: b.state == 'completed')
        if not backups:
            raise UserError(_("No completed backups available for restore."))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Backup to Restore',
            'res_model': 'saas.backup',
            'view_mode': 'list,form',
            'domain': [('instance_id', '=', self.id), ('state', '=', 'completed')],
            'target': 'new',
        }

    def action_configure_backup_schedule(self):
        """Configure backup schedule for this instance."""
        self.ensure_one()

        # Check if schedule exists
        existing = self.schedule_ids.filtered(lambda s: s.is_active)
        if existing:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Backup Schedule',
                'res_model': 'saas.backup.schedule',
                'view_mode': 'form',
                'res_id': existing[0].id,
            }

        # Create new schedule
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Backup Schedule',
            'res_model': 'saas.backup.schedule',
            'view_mode': 'form',
            'context': {
                'default_instance_id': self.id,
                'default_name': f'{self.subdomain} - Daily Backup',
            },
        }
