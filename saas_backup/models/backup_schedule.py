# -*- coding: utf-8 -*-
"""
Backup Schedule model.

Manages scheduled backup configurations for instances.
"""

import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.config import BackupConfig

_logger = logging.getLogger(__name__)


class BackupFrequency:
    """Backup frequency constants."""
    HOURLY = 'hourly'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'

    @classmethod
    def get_selection(cls):
        return [
            (cls.HOURLY, 'Hourly'),
            (cls.DAILY, 'Daily'),
            (cls.WEEKLY, 'Weekly'),
            (cls.MONTHLY, 'Monthly'),
        ]


class BackupSchedule(models.Model):
    """Scheduled backup configuration."""

    _name = 'saas.backup.schedule'
    _description = 'Backup Schedule'
    _order = 'name'
    _inherit = ['mail.thread']

    # Basic fields
    name = fields.Char(
        string='Name',
        required=True,
    )
    is_active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
    )

    # Target
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        ondelete='cascade',
        index=True,
        help='Leave empty for global schedule',
    )
    apply_to_all = fields.Boolean(
        string='Apply to All Instances',
        default=False,
        help='If checked, backup all active instances',
    )

    # Schedule configuration
    frequency = fields.Selection(
        selection=BackupFrequency.get_selection(),
        string='Frequency',
        default=BackupFrequency.DAILY,
        required=True,
    )
    hour = fields.Integer(
        string='Hour (UTC)',
        default=BackupConfig.BACKUP_HOUR,
        help='Hour of the day (0-23) in UTC',
    )
    minute = fields.Integer(
        string='Minute',
        default=BackupConfig.BACKUP_MINUTE,
    )
    day_of_week = fields.Selection(
        selection=[
            ('0', 'Monday'),
            ('1', 'Tuesday'),
            ('2', 'Wednesday'),
            ('3', 'Thursday'),
            ('4', 'Friday'),
            ('5', 'Saturday'),
            ('6', 'Sunday'),
        ],
        string='Day of Week',
        default='0',
        help='For weekly backups',
    )
    day_of_month = fields.Integer(
        string='Day of Month',
        default=1,
        help='For monthly backups (1-28)',
    )

    # Backup settings
    backup_type = fields.Selection(
        selection=[
            ('full', 'Full (Database + Filestore)'),
            ('database', 'Database Only'),
            ('filestore', 'Filestore Only'),
        ],
        string='Backup Type',
        default='full',
        required=True,
    )
    retention_override = fields.Integer(
        string='Retention Override (days)',
        help='Override default plan retention. Leave 0 to use plan defaults.',
    )

    # Tracking
    next_run = fields.Datetime(
        string='Next Run',
        compute='_compute_next_run',
        store=True,
    )
    last_run = fields.Datetime(
        string='Last Run',
        readonly=True,
    )
    last_status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('partial', 'Partial'),
            ('failed', 'Failed'),
        ],
        string='Last Status',
        readonly=True,
    )

    # Statistics
    backup_count = fields.Integer(
        string='Total Backups',
        compute='_compute_backup_stats',
    )
    success_count = fields.Integer(
        string='Successful Backups',
        compute='_compute_backup_stats',
    )
    failed_count = fields.Integer(
        string='Failed Backups',
        compute='_compute_backup_stats',
    )

    # Related backups
    backup_ids = fields.One2many(
        'saas.backup',
        'schedule_id',
        string='Backups',
    )

    @api.constrains('hour')
    def _check_hour(self):
        """Validate hour is in valid range."""
        for schedule in self:
            if not 0 <= schedule.hour <= 23:
                raise ValidationError(_("Hour must be between 0 and 23."))

    @api.constrains('minute')
    def _check_minute(self):
        """Validate minute is in valid range."""
        for schedule in self:
            if not 0 <= schedule.minute <= 59:
                raise ValidationError(_("Minute must be between 0 and 59."))

    @api.constrains('day_of_month')
    def _check_day_of_month(self):
        """Validate day of month is in valid range."""
        for schedule in self:
            if not 1 <= schedule.day_of_month <= 28:
                raise ValidationError(_("Day of month must be between 1 and 28."))

    @api.depends('frequency', 'hour', 'minute', 'day_of_week', 'day_of_month', 'last_run', 'is_active')
    def _compute_next_run(self):
        """Calculate next scheduled run time."""
        now = fields.Datetime.now()

        for schedule in self:
            if not schedule.is_active:
                schedule.next_run = False
                continue

            # Start from last run or now
            base = schedule.last_run or now

            if schedule.frequency == BackupFrequency.HOURLY:
                next_run = base.replace(minute=schedule.minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(hours=1)

            elif schedule.frequency == BackupFrequency.DAILY:
                next_run = base.replace(
                    hour=schedule.hour,
                    minute=schedule.minute,
                    second=0,
                    microsecond=0
                )
                if next_run <= now:
                    next_run += timedelta(days=1)

            elif schedule.frequency == BackupFrequency.WEEKLY:
                # Find next occurrence of day_of_week
                target_day = int(schedule.day_of_week)
                current_day = now.weekday()
                days_ahead = target_day - current_day
                if days_ahead <= 0:
                    days_ahead += 7

                next_run = now.replace(
                    hour=schedule.hour,
                    minute=schedule.minute,
                    second=0,
                    microsecond=0
                ) + timedelta(days=days_ahead)

            elif schedule.frequency == BackupFrequency.MONTHLY:
                # Next occurrence of day_of_month
                next_run = now.replace(
                    day=schedule.day_of_month,
                    hour=schedule.hour,
                    minute=schedule.minute,
                    second=0,
                    microsecond=0
                )
                if next_run <= now:
                    # Move to next month
                    if now.month == 12:
                        next_run = next_run.replace(year=now.year + 1, month=1)
                    else:
                        next_run = next_run.replace(month=now.month + 1)

            else:
                next_run = False

            schedule.next_run = next_run

    def _compute_backup_stats(self):
        """Compute backup statistics."""
        for schedule in self:
            backups = schedule.backup_ids
            schedule.backup_count = len(backups)
            schedule.success_count = len(backups.filtered(lambda b: b.state == 'completed'))
            schedule.failed_count = len(backups.filtered(lambda b: b.state == 'failed'))

    def action_run_backup(self):
        """Manually trigger scheduled backup."""
        self.ensure_one()

        Backup = self.env['saas.backup']
        Instance = self.env[ModelNames.INSTANCE]

        # Get target instances
        if self.apply_to_all:
            instances = Instance.search([('state', '=', 'running')])
        elif self.instance_id:
            instances = self.instance_id
        else:
            raise UserError(_("No instances configured for this schedule."))

        created_backups = Backup
        failed = 0

        for instance in instances:
            try:
                backup = Backup.create({
                    'instance_id': instance.id,
                    'backup_type': self.backup_type,
                    'trigger': 'scheduled',
                    'schedule_id': self.id,
                })
                backup.action_start_backup()
                created_backups |= backup
            except Exception as e:
                failed += 1
                _logger.error(f"Failed to backup instance {instance.subdomain}: {e}")

        # Update schedule
        total = len(instances)
        if failed == 0:
            status = 'success'
        elif failed < total:
            status = 'partial'
        else:
            status = 'failed'

        self.write({
            'last_run': fields.Datetime.now(),
            'last_status': status,
        })

        self.message_post(
            body=f"Scheduled backup completed: {total - failed}/{total} successful"
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Created Backups',
            'res_model': 'saas.backup',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_backups.ids)],
        }

    def action_view_backups(self):
        """View backups for this schedule."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Backups - {self.name}',
            'res_model': 'saas.backup',
            'view_mode': 'list,form',
            'domain': [('schedule_id', '=', self.id)],
            'context': {'default_schedule_id': self.id},
        }
