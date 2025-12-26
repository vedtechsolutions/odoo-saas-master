# -*- coding: utf-8 -*-
"""
Billing Transaction model.

Tracks payment attempts, successes, failures, and retry logic.
"""

import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.config import PaymentConfig

_logger = logging.getLogger(__name__)


class BillingTransactionType:
    """Transaction type constants."""
    SUBSCRIPTION = 'subscription'
    ADDON = 'addon'
    OVERAGE = 'overage'
    CREDIT_PURCHASE = 'credit_purchase'
    REFUND = 'refund'

    @classmethod
    def get_selection(cls):
        return [
            (cls.SUBSCRIPTION, 'Subscription Payment'),
            (cls.ADDON, 'Add-on Purchase'),
            (cls.OVERAGE, 'Overage Charge'),
            (cls.CREDIT_PURCHASE, 'Credit Purchase'),
            (cls.REFUND, 'Refund'),
        ]


class BillingTransactionState:
    """Transaction state constants."""
    PENDING = 'pending'
    PROCESSING = 'processing'
    SUCCESS = 'success'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'

    @classmethod
    def get_selection(cls):
        return [
            (cls.PENDING, 'Pending'),
            (cls.PROCESSING, 'Processing'),
            (cls.SUCCESS, 'Successful'),
            (cls.FAILED, 'Failed'),
            (cls.CANCELLED, 'Cancelled'),
            (cls.REFUNDED, 'Refunded'),
        ]


class BillingTransaction(models.Model):
    """Payment transaction tracking for SaaS billing."""

    _name = 'saas.billing.transaction'
    _description = 'Billing Transaction'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Unique reference constraint
    _reference_unique = models.Constraint(
        'UNIQUE(reference)',
        'Transaction reference must be unique!'
    )

    # Basic fields
    name = fields.Char(
        string='Description',
        required=True,
        tracking=True,
    )
    reference = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='New',
        index=True,
    )

    # State
    state = fields.Selection(
        selection=BillingTransactionState.get_selection(),
        string='Status',
        default=BillingTransactionState.PENDING,
        required=True,
        tracking=True,
        index=True,
    )

    # Type
    transaction_type = fields.Selection(
        selection=BillingTransactionType.get_selection(),
        string='Type',
        required=True,
        default=BillingTransactionType.SUBSCRIPTION,
        tracking=True,
    )

    # Relations
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='restrict',
        index=True,
    )
    subscription_id = fields.Many2one(
        ModelNames.SUBSCRIPTION,
        string='Subscription',
        ondelete='set null',
        index=True,
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        ondelete='set null',
    )

    # Amount
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        tracking=True,
    )
    amount_refunded = fields.Monetary(
        string='Amount Refunded',
        default=0.0,
    )

    # Payment gateway info
    gateway = fields.Selection(
        selection=[
            ('powertranz', 'PowerTranz'),
            ('manual', 'Manual'),
            ('credit', 'Credit Balance'),
            ('bank_transfer', 'Bank Transfer'),
        ],
        string='Payment Gateway',
        default='powertranz',
    )
    gateway_reference = fields.Char(
        string='Gateway Reference',
        help='Transaction ID from payment gateway',
    )
    gateway_response = fields.Text(
        string='Gateway Response',
        help='Raw response from payment gateway',
    )

    # Retry handling
    retry_count = fields.Integer(
        string='Retry Count',
        default=0,
    )
    max_retries = fields.Integer(
        string='Max Retries',
        default=PaymentConfig.MAX_PAYMENT_RETRIES,
    )
    next_retry_date = fields.Datetime(
        string='Next Retry',
    )
    last_retry_date = fields.Datetime(
        string='Last Retry',
    )

    # Error tracking
    error_code = fields.Char(
        string='Error Code',
    )
    error_message = fields.Text(
        string='Error Message',
    )

    # Timestamps
    processed_at = fields.Datetime(
        string='Processed At',
    )
    completed_at = fields.Datetime(
        string='Completed At',
    )

    # Billing period
    period_start = fields.Date(
        string='Period Start',
    )
    period_end = fields.Date(
        string='Period End',
    )

    # Computed fields (stored for search/filter)
    is_retryable = fields.Boolean(
        string='Can Retry',
        compute='_compute_is_retryable',
        store=True,
    )

    @api.depends('state', 'retry_count', 'max_retries')
    def _compute_is_retryable(self):
        """Check if transaction can be retried."""
        for txn in self:
            txn.is_retryable = (
                txn.state == BillingTransactionState.FAILED and
                txn.retry_count < txn.max_retries
            )

    @api.constrains('amount', 'transaction_type')
    def _check_amount(self):
        """Validate transaction amount based on type."""
        for txn in self:
            if txn.amount == 0:
                raise ValidationError(_("Transaction amount cannot be zero."))
            # Refunds should be negative, other types should be positive
            if txn.transaction_type == BillingTransactionType.REFUND:
                if txn.amount > 0:
                    raise ValidationError(_("Refund amount should be negative."))
            else:
                if txn.amount < 0:
                    raise ValidationError(_("Payment amount must be positive."))

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate reference and name."""
        for vals in vals_list:
            # Auto-generate reference
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'saas.billing.transaction'
                ) or 'New'

            # Auto-generate name if not provided
            if not vals.get('name'):
                tx_type = vals.get('transaction_type', BillingTransactionType.SUBSCRIPTION)
                type_labels = dict(BillingTransactionType.get_selection())
                vals['name'] = type_labels.get(tx_type, 'Payment')
        return super().create(vals_list)

    def action_process(self):
        """Start processing the transaction."""
        self.ensure_one()
        if self.state != BillingTransactionState.PENDING:
            raise UserError(_("Can only process pending transactions."))

        self.write({
            'state': BillingTransactionState.PROCESSING,
            'processed_at': fields.Datetime.now(),
        })

        # Attempt payment
        try:
            self._execute_payment()
        except Exception as e:
            self._handle_payment_failure(str(e))

        return True

    def _execute_payment(self):
        """Execute the actual payment - override in gateway-specific modules."""
        # Check for credit balance first
        if self.gateway == 'credit':
            return self._pay_with_credit()

        # For PowerTranz or other gateways, this would be extended
        # by payment_powertranz module

        # For now, simulate manual payment
        if self.gateway == 'manual':
            # Mark as successful - admin will verify manually
            self._handle_payment_success('MANUAL')
        else:
            # Placeholder for gateway integration
            raise UserError(_("Payment gateway not configured. Use manual payment."))

    def _pay_with_credit(self):
        """Pay using customer credit balance."""
        Credit = self.env['saas.customer.credit']
        available = Credit.get_available_balance(self.partner_id.id)

        if available < self.amount:
            raise UserError(_("Insufficient credit balance. Available: %s") % available)

        # Deduct credit
        Credit.use_credit(
            partner_id=self.partner_id.id,
            amount=self.amount,
            description=f"Payment for {self.name}",
            transaction_id=self.id,
        )

        self._handle_payment_success('CREDIT_BALANCE')
        return True

    def _handle_payment_success(self, gateway_ref):
        """Handle successful payment."""
        self.write({
            'state': BillingTransactionState.SUCCESS,
            'gateway_reference': gateway_ref,
            'completed_at': fields.Datetime.now(),
            'error_code': False,
            'error_message': False,
        })

        # Update subscription if linked
        if self.subscription_id:
            self.subscription_id.action_mark_paid()

        # Mark invoice as paid if linked
        if self.invoice_id and self.invoice_id.state == 'posted':
            # Create payment and reconcile
            pass  # Would implement actual payment posting

        self.message_post(body=f"Payment successful. Reference: {gateway_ref}")
        return True

    def _handle_payment_failure(self, error_msg, error_code=None):
        """Handle failed payment."""
        self.write({
            'state': BillingTransactionState.FAILED,
            'error_message': error_msg,
            'error_code': error_code,
            'last_retry_date': fields.Datetime.now(),
        })

        # Schedule retry if applicable
        if self.is_retryable:
            self._schedule_retry()
        else:
            # Max retries exceeded - suspend subscription
            self._handle_max_retries_exceeded()

        self.message_post(body=f"Payment failed: {error_msg}")
        return True

    def _schedule_retry(self):
        """Schedule next retry attempt."""
        # Retry intervals: day 0, day 1, day 3
        retry_intervals = [0, 1, 3]
        next_interval = retry_intervals[min(self.retry_count, len(retry_intervals) - 1)]

        next_retry = fields.Datetime.now() + timedelta(days=next_interval)
        self.write({
            'next_retry_date': next_retry,
            'retry_count': self.retry_count + 1,
        })

        _logger.info(
            f"Transaction {self.reference} scheduled for retry on {next_retry}"
        )

    def _handle_max_retries_exceeded(self):
        """Handle when max retries are exceeded."""
        if self.subscription_id:
            # Mark subscription as past due / suspend
            if self.subscription_id.state == 'active':
                self.subscription_id.action_suspend()

            self.message_post(
                body="Max payment retries exceeded. Subscription suspended."
            )

        # Create activity for manual follow-up
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary='Payment Failed - Manual Review Required',
            note=f'Transaction {self.reference} failed after {self.retry_count} retries.',
        )

    def action_retry(self):
        """Manually retry a failed transaction."""
        self.ensure_one()
        if not self.is_retryable:
            raise UserError(_("This transaction cannot be retried."))

        self.write({
            'state': BillingTransactionState.PENDING,
            'error_code': False,
            'error_message': False,
        })

        return self.action_process()

    def action_cancel(self):
        """Cancel the transaction."""
        self.ensure_one()
        if self.state == BillingTransactionState.SUCCESS:
            raise UserError(_("Cannot cancel successful transactions. Use refund instead."))

        self.write({'state': BillingTransactionState.CANCELLED})
        self.message_post(body="Transaction cancelled")
        return True

    def action_refund(self):
        """Refund a successful transaction."""
        self.ensure_one()
        if self.state != BillingTransactionState.SUCCESS:
            raise UserError(_("Can only refund successful transactions."))

        # Create refund transaction
        refund = self.create({
            'name': f"Refund: {self.name}",
            'transaction_type': BillingTransactionType.REFUND,
            'partner_id': self.partner_id.id,
            'subscription_id': self.subscription_id.id if self.subscription_id else False,
            'amount': -self.amount,
            'gateway': self.gateway,
            'state': BillingTransactionState.SUCCESS,
            'completed_at': fields.Datetime.now(),
        })

        # Update original transaction
        self.write({
            'state': BillingTransactionState.REFUNDED,
            'amount_refunded': self.amount,
        })

        # Add credit to customer
        Credit = self.env['saas.customer.credit']
        Credit.add_credit(
            partner_id=self.partner_id.id,
            amount=self.amount,
            credit_type='refund',
            description=f"Refund for {self.name}",
            transaction_id=refund.id,
        )

        self.message_post(body=f"Transaction refunded. Refund ref: {refund.reference}")
        return True

    @api.model
    def cron_process_pending(self):
        """Cron job to process pending transactions."""
        pending = self.search([
            ('state', '=', BillingTransactionState.PENDING),
        ], limit=50)

        for txn in pending:
            try:
                txn.action_process()
            except Exception as e:
                _logger.error(f"Error processing transaction {txn.reference}: {e}")

        return True

    @api.model
    def cron_retry_failed(self):
        """Cron job to retry failed transactions."""
        now = fields.Datetime.now()

        to_retry = self.search([
            ('state', '=', BillingTransactionState.FAILED),
            ('retry_count', '<', PaymentConfig.MAX_PAYMENT_RETRIES),
            ('next_retry_date', '<=', now),
        ], limit=50)

        for txn in to_retry:
            try:
                txn.action_retry()
            except Exception as e:
                _logger.error(f"Error retrying transaction {txn.reference}: {e}")

        return True
