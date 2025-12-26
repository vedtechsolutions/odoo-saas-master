# -*- coding: utf-8 -*-
"""
Support Session Model.

Tracks active support sessions with time limits and handles
session expiry notifications.
"""

import logging
from datetime import timedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Session duration in minutes
SUPPORT_SESSION_DURATION_MINUTES = 60


class SupportSession(models.Model):
    """Tracks support access sessions with time limits."""

    _name = 'saas.support.session'
    _description = 'Support Access Session'
    _order = 'start_time desc'

    # Session info
    user_id = fields.Many2one(
        'res.users',
        string='Logged In As',
        required=True,
        ondelete='cascade',
    )
    master_uid = fields.Integer(
        string='Master User ID',
        help='User ID of support staff on master server',
    )
    session_id = fields.Char(
        string='Session ID',
        index=True,
    )

    # Timing
    start_time = fields.Datetime(
        string='Session Start',
        default=fields.Datetime.now,
        required=True,
    )
    expiry_time = fields.Datetime(
        string='Session Expiry',
        required=True,
    )
    end_time = fields.Datetime(
        string='Session End',
    )

    # State
    state = fields.Selection([
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('ended', 'Ended by User'),
    ], string='Status', default='active', required=True)

    # Callback info
    master_callback_url = fields.Char(
        string='Master Callback URL',
        help='URL to notify master when session ends',
    )
    callback_sent = fields.Boolean(
        string='Callback Sent',
        default=False,
    )

    # Computed
    duration_minutes = fields.Integer(
        string='Duration (minutes)',
        compute='_compute_duration',
        store=True,
    )
    is_expired = fields.Boolean(
        string='Is Expired',
        compute='_compute_is_expired',
    )
    time_remaining_minutes = fields.Integer(
        string='Time Remaining (minutes)',
        compute='_compute_time_remaining',
    )

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for record in self:
            if record.start_time:
                end = record.end_time or fields.Datetime.now()
                delta = end - record.start_time
                record.duration_minutes = int(delta.total_seconds() / 60)
            else:
                record.duration_minutes = 0

    @api.depends('expiry_time')
    def _compute_is_expired(self):
        now = fields.Datetime.now()
        for record in self:
            record.is_expired = record.expiry_time and now > record.expiry_time

    @api.depends('expiry_time', 'state')
    def _compute_time_remaining(self):
        now = fields.Datetime.now()
        for record in self:
            if record.expiry_time and record.state == 'active':
                delta = record.expiry_time - now
                record.time_remaining_minutes = max(0, int(delta.total_seconds() / 60))
            else:
                record.time_remaining_minutes = 0

    @api.model
    def create_session(self, user_id, master_uid, session_id, master_callback_url=None):
        """Create a new support session with expiry time."""
        now = fields.Datetime.now()
        expiry = now + timedelta(minutes=SUPPORT_SESSION_DURATION_MINUTES)

        session = self.create({
            'user_id': user_id,
            'master_uid': master_uid,
            'session_id': session_id,
            'start_time': now,
            'expiry_time': expiry,
            'master_callback_url': master_callback_url,
            'state': 'active',
        })

        _logger.info(
            f"Support session created: user_id={user_id}, "
            f"master_uid={master_uid}, expires={expiry}"
        )
        return session

    def end_session(self, reason='ended'):
        """End the session and send callback to master."""
        self.ensure_one()
        if self.state != 'active':
            return False

        self.write({
            'state': 'expired' if reason == 'expired' else 'ended',
            'end_time': fields.Datetime.now(),
        })

        # Send callback to master
        self._send_end_callback()

        _logger.info(
            f"Support session ended: id={self.id}, reason={reason}, "
            f"duration={self.duration_minutes} minutes"
        )
        return True

    def _send_end_callback(self):
        """Notify master server that session has ended."""
        if not self.master_callback_url or self.callback_sent:
            return False

        try:
            import requests

            payload = {
                'session_id': self.session_id,
                'master_uid': self.master_uid,
                'user_id': self.user_id.id,
                'user_login': self.user_id.login,
                'start_time': self.start_time.isoformat() if self.start_time else None,
                'end_time': self.end_time.isoformat() if self.end_time else None,
                'duration_minutes': self.duration_minutes,
                'state': self.state,
            }

            response = requests.post(
                self.master_callback_url,
                json=payload,
                timeout=10,
            )

            if response.status_code == 200:
                self.callback_sent = True
                _logger.info(f"Session end callback sent successfully: {self.id}")
                return True
            else:
                _logger.warning(
                    f"Session end callback failed: status={response.status_code}"
                )
                return False

        except Exception as e:
            _logger.error(f"Failed to send session end callback: {e}")
            return False

    @api.model
    def check_session_valid(self, session_id):
        """Check if a support session is still valid."""
        session = self.search([
            ('session_id', '=', session_id),
            ('state', '=', 'active'),
        ], limit=1)

        if not session:
            return False, None, "No active session found"

        if session.is_expired:
            session.end_session(reason='expired')
            return False, session, "Session has expired"

        return True, session, None

    @api.model
    def cleanup_expired_sessions(self):
        """Cron job to clean up expired sessions."""
        expired = self.search([
            ('state', '=', 'active'),
            ('expiry_time', '<', fields.Datetime.now()),
        ])

        for session in expired:
            session.end_session(reason='expired')

        if expired:
            _logger.info(f"Cleaned up {len(expired)} expired support sessions")

        return True

    @api.model
    def get_active_session_for_user(self, user_id):
        """Get active support session for a user."""
        return self.search([
            ('user_id', '=', user_id),
            ('state', '=', 'active'),
            ('expiry_time', '>', fields.Datetime.now()),
        ], limit=1)
