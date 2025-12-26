# -*- coding: utf-8 -*-
"""
SaaS Provisioning Queue model.

Manages async provisioning tasks with retry logic, locking, and error tracking.
Consolidates T-076 to T-081 / PQ-001 to PQ-006.
"""

import logging
import traceback
from datetime import datetime, timedelta

from odoo import models, fields, api, SUPERUSER_ID, _
from odoo.exceptions import UserError

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.states import QueueState, InstanceState

_logger = logging.getLogger(__name__)


class QueueAction:
    """Queue action type constants."""
    PROVISION = 'provision'
    START = 'start'
    STOP = 'stop'
    RESTART = 'restart'
    TERMINATE = 'terminate'
    BACKUP = 'backup'
    RESTORE = 'restore'

    @classmethod
    def get_selection(cls):
        return [
            (cls.PROVISION, 'Provision Instance'),
            (cls.START, 'Start Instance'),
            (cls.STOP, 'Stop Instance'),
            (cls.RESTART, 'Restart Instance'),
            (cls.TERMINATE, 'Terminate Instance'),
            (cls.BACKUP, 'Create Backup'),
            (cls.RESTORE, 'Restore Backup'),
        ]


class SaasProvisioningQueue(models.Model):
    """Queue for async provisioning and instance management tasks."""

    _name = ModelNames.QUEUE
    _description = 'Provisioning Queue'
    _order = 'priority desc, create_date asc'
    _inherit = ['mail.thread']

    # Note: Duplicate prevention is handled in create_task() method
    # Partial unique constraints are not fully portable across databases

    # Odoo 19 index syntax for efficient queue processing
    _pending_retry_idx = models.Index('(state, next_retry_date) WHERE state = \'pending\'')

    # Basic identification
    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='New',
    )

    # Task definition
    action = fields.Selection(
        selection=QueueAction.get_selection(),
        string='Action',
        required=True,
        index=True,
    )
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        required=True,
        ondelete='cascade',
        index=True,
    )
    priority = fields.Selection(
        selection=[
            ('0', 'Low'),
            ('1', 'Normal'),
            ('2', 'High'),
            ('3', 'Urgent'),
        ],
        string='Priority',
        default='1',
        index=True,
    )

    # State management
    state = fields.Selection(
        selection=QueueState.get_selection(),
        string='Status',
        default=QueueState.PENDING,
        required=True,
        tracking=True,
        index=True,
    )

    # Retry logic
    attempt_count = fields.Integer(
        string='Attempts',
        default=0,
        help='Number of processing attempts made',
    )
    max_attempts = fields.Integer(
        string='Max Attempts',
        default=3,
        help='Maximum retry attempts before marking as failed',
    )
    next_retry_date = fields.Datetime(
        string='Next Retry',
        help='When to retry after a failure',
    )

    # Processing lock
    processing_lock_date = fields.Datetime(
        string='Lock Acquired',
        help='Timestamp when processing lock was acquired',
    )
    processing_worker = fields.Char(
        string='Processing Worker',
        help='ID of the worker processing this task',
    )

    # Execution tracking
    started_date = fields.Datetime(
        string='Started',
        readonly=True,
    )
    completed_date = fields.Datetime(
        string='Completed',
        readonly=True,
    )
    duration_seconds = fields.Float(
        string='Duration (s)',
        compute='_compute_duration',
        store=True,
    )

    # Error tracking
    error_message = fields.Text(
        string='Error Message',
    )
    error_traceback = fields.Text(
        string='Error Traceback',
    )
    error_count = fields.Integer(
        string='Error Count',
        default=0,
    )

    # Additional data
    payload = fields.Text(
        string='Payload',
        help='JSON payload with additional parameters',
    )
    result = fields.Text(
        string='Result',
        help='JSON result from task execution',
    )

    # Relations for display
    partner_id = fields.Many2one(
        related='instance_id.partner_id',
        string='Customer',
        store=True,
        readonly=True,
    )
    server_id = fields.Many2one(
        related='instance_id.server_id',
        string='Server',
        store=True,
        readonly=True,
    )

    @api.depends('started_date', 'completed_date')
    def _compute_duration(self):
        """Calculate task duration in seconds."""
        for queue in self:
            if queue.started_date and queue.completed_date:
                delta = queue.completed_date - queue.started_date
                queue.duration_seconds = delta.total_seconds()
            else:
                queue.duration_seconds = 0

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate reference."""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'saas.provisioning.queue'
                ) or 'New'
        return super().create(vals_list)

    def action_cancel(self):
        """Cancel pending queue entry."""
        for queue in self:
            if queue.state not in [QueueState.PENDING]:
                raise UserError(_("Only pending tasks can be cancelled."))
            queue.write({
                'state': QueueState.CANCELLED,
                'completed_date': fields.Datetime.now(),
            })

    def action_retry(self):
        """Manually retry a failed task."""
        for queue in self:
            if queue.state != QueueState.FAILED:
                raise UserError(_("Only failed tasks can be retried."))
            queue.write({
                'state': QueueState.PENDING,
                'attempt_count': 0,
                'error_message': False,
                'error_traceback': False,
                'next_retry_date': False,
                'processing_lock_date': False,
                'processing_worker': False,
            })

    def _acquire_lock(self, worker_id):
        """
        Attempt to acquire processing lock on this queue entry.
        Returns True if lock acquired, False otherwise.
        Uses database-level locking to prevent race conditions.
        """
        self.ensure_one()
        lock_timeout = fields.Datetime.now() - timedelta(minutes=30)

        # Use SQL to atomically lock the record
        self.env.cr.execute("""
            UPDATE saas_provisioning_queue
            SET processing_lock_date = %s,
                processing_worker = %s
            WHERE id = %s
              AND state = %s
              AND (processing_lock_date IS NULL OR processing_lock_date < %s)
            RETURNING id
        """, (
            fields.Datetime.now(),
            worker_id,
            self.id,
            QueueState.PENDING,
            lock_timeout,
        ))

        result = self.env.cr.fetchone()
        return result is not None

    def _release_lock(self):
        """Release the processing lock."""
        self.ensure_one()
        self.write({
            'processing_lock_date': False,
            'processing_worker': False,
        })

    def _execute_task(self):
        """Execute the queue task with error handling."""
        self.ensure_one()

        # Update state and attempt count
        self.write({
            'state': QueueState.PROCESSING,
            'attempt_count': self.attempt_count + 1,
            'started_date': fields.Datetime.now(),
            'error_message': False,
            'error_traceback': False,
        })
        self.env.cr.commit()

        try:
            instance = self.instance_id

            # Execute action based on type
            if self.action == QueueAction.PROVISION:
                instance._do_provision()
                # Send welcome email on successful provisioning
                self._send_welcome_email()

            elif self.action == QueueAction.START:
                instance.action_start()

            elif self.action == QueueAction.STOP:
                instance.action_stop()

            elif self.action == QueueAction.RESTART:
                instance.action_restart()

            elif self.action == QueueAction.TERMINATE:
                instance.action_terminate()

            elif self.action == QueueAction.BACKUP:
                # Find and execute backup
                if self.payload:
                    import json
                    payload = json.loads(self.payload)
                    backup_id = payload.get('backup_id')
                    if backup_id:
                        backup = self.env['saas.backup'].browse(backup_id)
                        backup._execute_backup()

            elif self.action == QueueAction.RESTORE:
                if self.payload:
                    import json
                    payload = json.loads(self.payload)
                    backup_id = payload.get('backup_id')
                    if backup_id:
                        backup = self.env['saas.backup'].browse(backup_id)
                        backup._execute_restore()

            # Mark as completed
            self.write({
                'state': QueueState.COMPLETED,
                'completed_date': fields.Datetime.now(),
            })
            self._release_lock()

            _logger.info(f"Queue task {self.name} completed successfully")

        except Exception as e:
            error_msg = str(e)
            error_tb = traceback.format_exc()

            _logger.error(f"Queue task {self.name} failed: {error_msg}")

            # Check if we should retry
            if self.attempt_count < self.max_attempts:
                # Calculate exponential backoff delay
                delay_minutes = 2 ** self.attempt_count  # 2, 4, 8 minutes
                next_retry = fields.Datetime.now() + timedelta(minutes=delay_minutes)

                self.write({
                    'state': QueueState.PENDING,  # Back to pending for retry
                    'error_message': error_msg,
                    'error_traceback': error_tb,
                    'error_count': self.error_count + 1,
                    'next_retry_date': next_retry,
                })
                self._release_lock()

                _logger.info(
                    f"Queue task {self.name} will retry in {delay_minutes} minutes "
                    f"(attempt {self.attempt_count}/{self.max_attempts})"
                )
            else:
                # Max attempts reached, mark as failed
                self.write({
                    'state': QueueState.FAILED,
                    'error_message': error_msg,
                    'error_traceback': error_tb,
                    'error_count': self.error_count + 1,
                    'completed_date': fields.Datetime.now(),
                })
                self._release_lock()

                _logger.error(
                    f"Queue task {self.name} failed permanently after "
                    f"{self.max_attempts} attempts"
                )

    def _send_welcome_email(self):
        """Send welcome email after successful provisioning."""
        self.ensure_one()
        try:
            instance = self.instance_id
            template = self.env.ref(
                'saas_subscription.mail_template_saas_instance_ready',
                raise_if_not_found=False
            )
            if template and instance.admin_email:
                template.send_mail(instance.id, force_send=True)
                _logger.info(f"Welcome email sent to {instance.admin_email}")
        except Exception as e:
            _logger.warning(f"Failed to send welcome email: {e}")
            # Don't fail the task just because email failed

    @api.model
    def cron_process_queue(self):
        """
        Cron job to process pending queue entries.
        Runs every 5 minutes, processes up to 10 tasks per run.
        PQ-005: Queue processing cron.
        """
        import uuid
        worker_id = str(uuid.uuid4())[:8]

        _logger.info(f"Queue processor {worker_id} starting...")

        # Find pending tasks ready for processing
        now = fields.Datetime.now()
        pending_tasks = self.search([
            ('state', '=', QueueState.PENDING),
            '|',
            ('next_retry_date', '=', False),
            ('next_retry_date', '<=', now),
        ], limit=10, order='priority desc, create_date asc')

        processed_count = 0
        for task in pending_tasks:
            # Try to acquire lock
            if task._acquire_lock(worker_id):
                try:
                    # Execute task - it manages its own transactions/commits
                    task._execute_task()
                    processed_count += 1
                except Exception as e:
                    _logger.error(f"Unexpected error processing task {task.name}: {e}")
                    try:
                        self.env.cr.rollback()
                    except Exception:
                        pass  # Ignore rollback errors

        _logger.info(f"Queue processor {worker_id} completed. Processed {processed_count} tasks.")
        return True

    @api.model
    def cron_cleanup_old_entries(self):
        """
        Cleanup old completed/cancelled queue entries.
        Keep completed entries for 30 days, failed for 90 days.
        """
        now = fields.Datetime.now()

        # Delete completed entries older than 30 days
        completed_cutoff = now - timedelta(days=30)
        old_completed = self.search([
            ('state', 'in', [QueueState.COMPLETED, QueueState.CANCELLED]),
            ('completed_date', '<', completed_cutoff),
        ])
        if old_completed:
            _logger.info(f"Deleting {len(old_completed)} old completed queue entries")
            old_completed.unlink()

        # Delete failed entries older than 90 days
        failed_cutoff = now - timedelta(days=90)
        old_failed = self.search([
            ('state', '=', QueueState.FAILED),
            ('completed_date', '<', failed_cutoff),
        ])
        if old_failed:
            _logger.info(f"Deleting {len(old_failed)} old failed queue entries")
            old_failed.unlink()

        return True

    @api.model
    def create_task(self, instance, action, priority='1', payload=None):
        """
        Helper method to create a queue task.
        Prevents duplicate pending tasks for same instance/action.
        """
        # Check for existing pending/processing task
        existing = self.search([
            ('instance_id', '=', instance.id),
            ('action', '=', action),
            ('state', 'in', [QueueState.PENDING, QueueState.PROCESSING]),
        ], limit=1)

        if existing:
            _logger.warning(
                f"Task {action} already queued for instance {instance.subdomain}"
            )
            return existing

        # Create new task
        vals = {
            'instance_id': instance.id,
            'action': action,
            'priority': priority,
        }
        if payload:
            import json
            vals['payload'] = json.dumps(payload)

        task = self.create(vals)
        _logger.info(f"Created queue task {task.name} for {action} on {instance.subdomain}")
        return task
