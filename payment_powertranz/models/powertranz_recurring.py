# -*- coding: utf-8 -*-

import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from lxml import etree
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date, format_amount, html2plaintext

_logger = logging.getLogger(__name__)

class PowertranzRecurring(models.Model):
    _name = 'powertranz.recurring'
    _description = 'PowerTranz Recurring Payment'
    _order = 'create_date desc'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, readonly=True)
    payment_token_id = fields.Many2one('payment.token', string='Payment Method', required=True, readonly=True)
    provider_id = fields.Many2one('payment.provider', string='Payment Provider', related='payment_token_id.provider_id', store=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    
    amount = fields.Monetary(string='Amount', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, readonly=True)
    
    frequency = fields.Selection([
        ('D', 'Daily'),
        ('W', 'Weekly'),
        ('M', 'Monthly'),
        ('Y', 'Yearly')
    ], string='Frequency', required=True, default='M')
    
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date')
    next_payment_date = fields.Datetime(string='Next Payment Date', compute='_compute_next_payment_date', store=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed')
    ], string='Status', default='draft', tracking=True)
    
    payment_count = fields.Integer(string='Payment Count', compute='_compute_payment_count')
    transaction_ids = fields.One2many('payment.transaction', 'powertranz_recurring_id', string='Transactions')
    
    powertranz_recurring_identifier = fields.Char(string='PowerTranz Recurring ID', readonly=True, 
                                                help='Identifier for PowerTranz-managed recurring payments')
    
    management_type = fields.Selection([
        ('merchant', 'Merchant Managed'),
        ('powertranz', 'PowerTranz Managed')
    ], string='Management Type', required=True, default='merchant',
       help='Merchant Managed: Odoo controls the payment schedule. PowerTranz Managed: PowerTranz controls the payment schedule.')
    
    description = fields.Text(string='Description')
    last_payment_date = fields.Date(string='Last Payment Date', readonly=True)
    last_payment_status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed')
    ], string='Last Payment Status', readonly=True)
    last_transaction_id = fields.Many2one('payment.transaction', string='Last Transaction', readonly=True)
    
    # For merchant-managed recurring payments
    retry_count = fields.Integer(string='Retry Count', default=0)
    max_retry_count = fields.Integer(string='Max Retry Count', default=3)
    retry_hours = fields.Integer(string='Hours Between Retries', default=6,
                              help='Number of hours to wait before retrying a failed payment')
    missed_payment_count = fields.Integer(string='Missed Payment Count', default=0,
                                   help='Number of missed payments to process on next successful attempt')
    last_retry_date = fields.Datetime(string='Last Retry Date', readonly=True)
    
    # Button for manual payment processing
    def action_pay_now(self):
        """Process a manual payment for this recurring subscription.
        This can be used for past due payments or to manually trigger a payment.
        """
        self.ensure_one()
        
        if self.state not in ['active', 'paused']:
            raise UserError(_("Only active or paused recurring payments can be processed manually."))
            
        if not self.payment_token_id or not self.payment_token_id.provider_id:
            raise UserError(_("No valid payment method available for this recurring payment."))
            
        # Process the payment
        result = self.process_payment()
        
        # Return appropriate action based on result
        if result.get('success'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Payment Successful'),
                    'message': _('The payment has been successfully processed.'),
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Payment Failed'),
                    'message': result.get('error_message', _('The payment could not be processed.')),
                    'sticky': True,
                    'type': 'danger',
                }
            }
    
    def process_payment(self):
        """Process a payment for this recurring subscription.
        
        Returns:
            dict: Result of the payment processing with keys:
                - success (bool): Whether the payment was successful
                - transaction (recordset): The created payment transaction
                - error_message (str): Error message if payment failed
        """
        self.ensure_one()
        
        # Check if we have a valid token
        token = self.payment_token_id
        if not token or not token.provider_id:
            return {
                'success': False,
                'error_message': _('No valid payment method available for this recurring payment.')
            }
            
        # Create a descriptive reference
        reference = f"{self.name}-{fields.Date.today().strftime('%Y%m%d')}"
        
        try:
            # Find existing transactions with the same reference to avoid duplicates
            existing_tx = self.env['payment.transaction'].sudo().search(
                [('reference', '=', reference)], limit=1)
            if existing_tx:
                _logger.info("Found existing transaction %s for recurring payment %s", 
                            existing_tx.reference, self.name)
                return {
                    'success': False,
                    'error_message': _('A transaction with this reference already exists.')
                }
            
            # Find the payment method for this provider
            provider = token.provider_id
            payment_method = self.env['payment.method'].sudo().search([
                ('provider_ids', 'in', [provider.id]),
                ('code', '=', 'card'),  # Assuming this is a card payment
            ], limit=1)
            
            if not payment_method:
                _logger.error("No card payment method found for provider %s", provider.name)
                # Try to find any payment method for this provider
                payment_method = self.env['payment.method'].sudo().search([
                    ('provider_ids', 'in', [provider.id]),
                ], limit=1)
                
            if not payment_method:
                return {
                    'success': False,
                    'error_message': _('No valid payment method found for this provider.')
                }
            
            # Create transaction values according to Odoo 18 standards
            tx_values = {
                'reference': reference,
                'provider_id': provider.id,
                'payment_method_id': payment_method.id,
                'amount': self.amount,
                'currency_id': self.currency_id.id,
                'partner_id': self.partner_id.id,
                'token_id': token.id,
                'operation': 'offline',  # This is a token payment
                'is_recurring': True,
            }
            
            # Create the transaction
            transaction = self.env['payment.transaction'].sudo().create(tx_values)
            
            # Set the recurring ID
            transaction.powertranz_recurring_id = self.id
            
            # Log the transaction creation
            _logger.info("Created recurring payment transaction %s for subscription %s", 
                        transaction.reference, self.name)
            
            # Process the payment using the token
            # This will call the provider-specific implementation of _send_payment_request
            transaction._send_payment_request()
            
            # Check the transaction state
            if transaction.state == 'done':
                # Update last payment date and status
                self.write({
                    'last_payment_date': fields.Date.today(),
                    'last_payment_status': 'success',
                    'last_transaction_id': transaction.id,
                    'missed_payment_count': 0,  # Reset missed payment count on success
                    'retry_count': 0,  # Reset retry count on success
                })
                
                # Recompute next payment date
                self._compute_next_payment_date()
                
                return {
                    'success': True,
                    'transaction': transaction,
                }
            else:
                # Update payment status for failed payment
                self.write({
                    'last_payment_status': 'failed',
                    'last_transaction_id': transaction.id,
                    'retry_count': self.retry_count + 1,
                    'last_retry_date': fields.Datetime.now(),
                })
                
                # Increment missed payment count
                if transaction.state == 'error':
                    self.missed_payment_count += 1
                
                return {
                    'success': False,
                    'transaction': transaction,
                    'error_message': transaction.state_message or _('Payment processing failed.')
                }
                
        except Exception as e:
            _logger.exception("Error processing recurring payment for %s: %s", self.name, str(e))
            return {
                'success': False,
                'error_message': str(e)
            }
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('powertranz.recurring') or _('New')
        return super().create(vals_list)
    
    @api.depends('start_date', 'frequency', 'last_payment_date', 'state')
    def _compute_next_payment_date(self):
        for record in self:
            if record.state not in ['active', 'paused']:
                record.next_payment_date = False
                continue
                
            # Get the base date for calculation
            if record.last_payment_date:
                base_date = record.last_payment_date
            else:
                base_date = record.start_date
                
            if not base_date:
                record.next_payment_date = False
                continue
            
            # Convert date to datetime if needed
            if isinstance(base_date, fields.Date):
                # Convert to datetime at 00:00:00
                base_datetime = datetime.combine(base_date, datetime.min.time())
            else:
                base_datetime = base_date
                
            # Calculate next payment date based on frequency
            if record.frequency == 'D':
                next_datetime = base_datetime + relativedelta(days=1)
            elif record.frequency == 'W':
                next_datetime = base_datetime + relativedelta(weeks=1)
            elif record.frequency == 'M':
                next_datetime = base_datetime + relativedelta(months=1)
            elif record.frequency == 'Y':
                next_datetime = base_datetime + relativedelta(years=1)
            else:
                next_datetime = base_datetime + relativedelta(months=1)  # Default to monthly
            
            record.next_payment_date = next_datetime
            
            # Check if we've passed the end date
            if record.end_date:
                end_datetime = datetime.combine(record.end_date, datetime.max.time())
                if record.next_payment_date > end_datetime:
                    record.next_payment_date = False
                    if record.state == 'active':
                        record.state = 'completed'
    
    def get_portal_url(self):
        """Get the portal URL for this recurring payment.
        
        Returns:
            str: URL to access this recurring payment from the portal
        """
        self.ensure_one()
        return f'/my/powertranz/recurring/{self.id}'
        
    def action_pause(self):
        """Pause an active recurring payment.
        
        This temporarily stops the recurring payment from being processed
        until it is resumed.
        """
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Only active recurring payments can be paused.'))
            
        self.write({'state': 'paused'})
        
        # Send email notification for paused payment
        try:
            template = self.env.ref('payment_powertranz.mail_template_recurring_payment_paused', False)
            if template:
                # Ensure template is properly rendered with context
                template.with_context(lang=self.partner_id.lang).send_mail(
                    self.id, 
                    force_send=True,
                    email_layout_xmlid='mail.mail_notification_layout',
                    email_values={
                        'email_to': self.partner_id.email,
                        'auto_delete': True,
                        'recipient_ids': [(4, self.partner_id.id)],
                        'email_from': self.company_id.email or self.env.user.email_formatted,
                    }
                )
                _logger.info('Successfully sent recurring payment pause email to %s', self.partner_id.email)
        except Exception as e:
            _logger.exception('Error sending recurring payment pause email: %s', e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_paused',
            subject="Recurring Payment Paused: {name}"
        )
        
        return True
        
    def action_resume(self):
        """Resume a paused recurring payment.
        
        This reactivates a paused recurring payment so it will continue
        to be processed according to its schedule.
        """
        self.ensure_one()
        if self.state != 'paused':
            raise UserError(_('Only paused recurring payments can be resumed.'))
            
        self.write({'state': 'active'})
        
        # Send email notification for resumed payment
        try:
            template = self.env.ref('payment_powertranz.mail_template_recurring_payment_resumed', False)
            if template:
                # Ensure template is properly rendered with context
                template.with_context(lang=self.partner_id.lang).send_mail(
                    self.id, 
                    force_send=True,
                    email_layout_xmlid='mail.mail_notification_layout',
                    email_values={
                        'email_to': self.partner_id.email,
                        'auto_delete': True,
                        'recipient_ids': [(4, self.partner_id.id)],
                        'email_from': self.company_id.email or self.env.user.email_formatted,
                    }
                )
                _logger.info('Successfully sent recurring payment resume email to %s', self.partner_id.email)
        except Exception as e:
            _logger.exception('Error sending recurring payment resume email: %s', e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_resumed',
            subject="Recurring Payment Resumed: {name}"
        )
        
        return True
        
    def action_cancel(self):
        """Cancel a recurring payment.
        
        This permanently stops the recurring payment from being processed.
        """
        self.ensure_one()
        if self.state not in ['draft', 'active', 'paused']:
            raise UserError(_('Only draft, active, or paused recurring payments can be cancelled.'))
            
        # If this is a PowerTranz-managed recurring payment, cancel it at the gateway
        if self.management_type == 'powertranz' and self.powertranz_recurring_identifier:
            try:
                self._cancel_at_powertranz()
            except Exception as e:
                _logger.exception('Error cancelling recurring payment at PowerTranz: %s', e)
            
        self.write({'state': 'cancelled'})
        
        # Send email notification for cancelled payment
        try:
            template = self.env.ref('payment_powertranz.mail_template_recurring_payment_cancelled', False)
            if template:
                # Ensure template is properly rendered with context
                template.with_context(lang=self.partner_id.lang).send_mail(
                    self.id, 
                    force_send=True,
                    email_layout_xmlid='mail.mail_notification_layout',
                    email_values={
                        'email_to': self.partner_id.email,
                        'auto_delete': True,
                        'recipient_ids': [(4, self.partner_id.id)],
                        'email_from': self.company_id.email or self.env.user.email_formatted,
                    }
                )
                _logger.info('Successfully sent recurring payment cancellation email to %s', self.partner_id.email)
        except Exception as e:
            _logger.exception('Error sending recurring payment cancellation email: %s', e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_cancelled',
            subject="Recurring Payment Cancelled: {name}"
        )
        
        return True
        
    def _cancel_at_powertranz(self):
        """Cancel the recurring payment at PowerTranz gateway.
        
        This method sends a request to the PowerTranz API to cancel a recurring payment.
        Only applicable for PowerTranz-managed recurring payments.
        
        Returns:
            bool: True if cancellation was successful, raises an exception otherwise
        """
        self.ensure_one()
        
        if not self.powertranz_recurring_identifier:
            raise UserError(_('No PowerTranz recurring identifier found for this payment.'))
            
        # Get the payment provider
        provider = self.provider_id
        if not provider:
            raise UserError(_('No payment provider found for this recurring payment.'))
            
        # Prepare the API endpoint and request data
        base_url = provider.powertranz_api_url
        if not base_url:
            raise UserError(_('PowerTranz API URL not configured for the payment provider.'))
            
        endpoint = '/api/Recurring/Cancel'
        
        # Get credentials
        merchant_id = provider.powertranz_merchant_id
        merchant_password = provider.powertranz_merchant_password
        
        if not merchant_id or not merchant_password:
            raise UserError(_('PowerTranz merchant credentials not properly configured.'))
            
        # Prepare request data
        request_data = {
            'MerchantId': merchant_id,
            'RecurringId': self.powertranz_recurring_identifier,
        }
        
        # Log the request
        _logger.info(
            'Sending cancellation request to PowerTranz for recurring payment %s (ID: %s)',
            self.name, self.powertranz_recurring_identifier
        )
        
        # Make the API request
        try:
            # Use the payment transaction model to make the request
            transaction_model = self.env['payment.transaction']
            response_data = transaction_model._make_powertranz_request(endpoint, request_data)
            
            # Process the response
            if response_data.get('Approved') is True:
                _logger.info(
                    'Successfully cancelled recurring payment %s at PowerTranz (ID: %s)',
                    self.name, self.powertranz_recurring_identifier
                )
                return True
            else:
                error_message = response_data.get('ResponseMessage', 'Unknown error')
                raise UserError(_('Failed to cancel recurring payment at PowerTranz: %s') % error_message)
                
        except Exception as e:
            _logger.exception(
                'Error cancelling recurring payment %s at PowerTranz: %s',
                self.name, str(e)
            )
            raise UserError(_('Error cancelling recurring payment at PowerTranz: %s') % str(e))
    
    def _compute_payment_count(self):
        for record in self:
            record.payment_count = len(record.transaction_ids)
    
    def action_view_payments(self):
        self.ensure_one()
        
        # Find the tree and form views for payment.transaction
        tree_view = self.env.ref('payment.payment_transaction_view_tree', False)
        form_view = self.env.ref('payment.payment_transaction_view_form', False)
        
        action = {
            'name': _('Payments'),
            'type': 'ir.actions.act_window',
            'res_model': 'payment.transaction',
            'domain': [('id', 'in', self.transaction_ids.ids)],
            'context': {'create': False}
        }
        
        # Set view_mode and views based on available views
        if tree_view and form_view:
            action['view_mode'] = 'list,form'
            action['views'] = [
                (tree_view.id, 'list'),
                (form_view.id, 'form')
            ]
        elif tree_view:
            action['view_mode'] = 'list'
            action['views'] = [(tree_view.id, 'list')]
        elif form_view:
            action['view_mode'] = 'form'
            action['views'] = [(form_view.id, 'form')]
        else:
            # Fallback to list view if specific views aren't found
            action['view_mode'] = 'list,form'
            
        return action
    
    def _post_formatted_message(self, template_xml_id, subject=None):
        """Post a formatted message to the chatter with rendered variables"""
        self.ensure_one()
        # Get basic frequency display text based on code
        frequency_display = {
            'D': 'Daily',
            'W': 'Weekly',
            'F': 'Fortnightly',
            'M': 'Monthly',
            'B': 'Bi-Monthly',
            'Q': 'Quarterly',
            'S': 'Semi-Annually',
            'Y': 'Yearly'
        }.get(self.frequency, self.frequency)
        
        # Format amount with 2 decimal places
        formatted_amount = f"{self.currency_id.symbol} {self.amount:.2f}"
        
        # Format next payment date
        next_date_str = self.next_payment_date.strftime('%Y-%m-%d') if self.next_payment_date else 'N/A'

        qweb_template_str = ""
        render_values = {
            'record': self,
            'formatted_amount': formatted_amount,
            'frequency_display': frequency_display,
            'next_date_str': next_date_str,
            'state_capitalized': self.state.capitalize()
        }
        
        # Build QWeb template string based on context
        if 'cancelled' in template_xml_id:
            qweb_template_str = """
                <div>
                    <p>Recurring payment <strong><t t-esc="record.name"/></strong> has been cancelled.</p>
                    <ul>
                        <li>Amount: <t t-esc="formatted_amount"/></li>
                        <li>Frequency: <t t-esc="frequency_display"/></li>
                        <li>Status: <t t-esc="state_capitalized"/></li>
                    </ul>
                </div>
            """
            if not subject:
                subject = f"Recurring Payment Cancelled: {self.name}"
        elif 'paused' in template_xml_id:
            qweb_template_str = """
                <div>
                    <p>Recurring payment <strong><t t-esc="record.name"/></strong> has been paused.</p>
                    <ul>
                        <li>Amount: <t t-esc="formatted_amount"/></li>
                        <li>Frequency: <t t-esc="frequency_display"/></li>
                        <li>Status: <t t-esc="state_capitalized"/></li>
                    </ul>
                </div>
            """
            if not subject:
                subject = f"Recurring Payment Paused: {self.name}"
        elif 'resumed' in template_xml_id:
            qweb_template_str = """
                <div>
                    <p>Recurring payment <strong><t t-esc="record.name"/></strong> has been resumed.</p>
                    <ul>
                        <li>Amount: <t t-esc="formatted_amount"/></li>
                        <li>Frequency: <t t-esc="frequency_display"/></li>
                        <li>Next Payment: <t t-esc="next_date_str"/></li>
                        <li>Status: <t t-esc="state_capitalized"/></li>
                    </ul>
                </div>
            """
            if not subject:
                subject = f"Recurring Payment Resumed: {self.name}"
        else:
            # Default to a basic message
            qweb_template_str = """
                <div>
                    <p>Recurring payment <strong><t t-esc="record.name"/></strong> status update: <strong><t t-esc="state_capitalized"/></strong></p>
                    <ul>
                        <li>Amount: <t t-esc="formatted_amount"/></li>
                        <li>Frequency: <t t-esc="frequency_display"/></li>
                        <li>Next Payment: <t t-esc="next_date_str"/></li>
                    </ul>
                </div>
            """
            if not subject:
                subject = f"Recurring Payment Update: {self.name}"
        
        # Parse the string template into an etree object
        parsed_template = etree.fromstring(qweb_template_str)
        body_html = self.env['ir.qweb']._render(parsed_template, render_values)
        
        # Format subject if needed
        if '{name}' in subject:
            subject = subject.format(name=self.name)
        
        # Use mail.mt_comment for rich HTML in chatter
        return self.with_context(mail_create_nosubscribe=True).message_post(
            body=body_html, # Output of _render is typically Markup safe
            subject=subject,
            message_type='comment',
            subtype_xmlid='mail.mt_comment'
        )
    
    def action_activate(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only draft recurring payments can be activated."))
        self.write({'state': 'active'})
        
        # Send email notification for recurring payment creation
        try:
            template = self.env.ref('payment_powertranz.mail_template_recurring_payment_created', False)
            if template:
                # Ensure template is properly rendered with context
                template.with_context(lang=self.partner_id.lang).send_mail(
                    self.id, 
                    force_send=True,
                    email_layout_xmlid='mail.mail_notification_layout',
                    email_values={
                        'email_to': self.partner_id.email,
                        'auto_delete': True,
                        'recipient_ids': [(4, self.partner_id.id)],
                        'email_from': self.company_id.email or self.env.user.email_formatted,
                    }
                )
                _logger.info('Successfully sent recurring payment creation email to %s', self.partner_id.email)
        except Exception as e:
            _logger.exception('Error sending recurring payment creation email: %s', e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_created',
            subject="Recurring Payment Setup: {name}"
        )
    
    def send_creation_email(self):
        """Send email notification about the creation of a recurring payment."""
        try:
            template = self.env.ref('payment_powertranz.mail_template_recurring_payment_created')
            if template:
                # Use with_context to ensure proper rendering
                template.with_context(lang=self.partner_id.lang).send_mail(
                    self.id, 
                    force_send=True,
                    email_layout_xmlid='mail.mail_notification_layout',
                    email_values={
                        'email_to': self.partner_id.email,
                        'auto_delete': True,
                        'recipient_ids': [(4, self.partner_id.id)],
                        'email_from': self.company_id.email or self.env.user.email_formatted,
                    }
                )
                _logger.info('Successfully sent recurring payment creation email to %s', self.partner_id.email)
            else:
                _logger.error('Could not find email template for recurring payment creation')
        except Exception as e:
            _logger.exception('Error sending recurring payment creation email: %s', e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_paused',
            subject="Recurring Payment Paused: {name}"
        )
    
    def action_resume(self):
        self.ensure_one()
        if self.state != 'paused':
            raise UserError(_("Only paused recurring payments can be resumed."))
        self.write({'state': 'active'})
        
        # Send email notification for resumed payment
        template = self.env.ref('payment_powertranz.mail_template_recurring_payment_resumed', False)
        if template and self.partner_id.email:
            try:
                # Get frequency display name
                frequency_mapping = {
                    'D': 'Daily',
                    'W': 'Weekly',
                    'M': 'Monthly',
                    'Y': 'Yearly',
                }
                frequency_display = frequency_mapping.get(self.frequency, self.frequency)
                
                # Create context for rendering
                ctx = {
                    'partner': self.partner_id,
                    'partner_name': self.partner_id.name,
                    'recurring': self,
                    'frequency_display': frequency_display,
                    'formatted_amount': f"{self.currency_id.symbol} {self.amount:.2f}",
                    'next_date': self.next_payment_date and self.next_payment_date.strftime('%m/%d/%Y') or 'N/A',
                    'company_name': self.company_id.name,
                }
                
                # Send email with proper context
                template.with_context(
                    lang=self.partner_id.lang or self.env.user.lang,
                    **ctx
                ).send_mail(
                    self.id, 
                    force_send=True,
                    email_values={
                        'email_to': self.partner_id.email,
                        'subject': f"Payment Resumed: {self.name}",
                        'auto_delete': True,
                    }
                )
                _logger.info("Successfully sent resume email notification for recurring payment %s", self.name)
            except Exception as e:
                _logger.error("Error sending resume email: %s", e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_resumed',
            subject="Recurring Payment Resumed: {name}"
        )
    
    def action_cancel(self):
        self.ensure_one()
        if self.state in ['cancelled', 'completed']:
            raise UserError(_("This recurring payment is already cancelled or completed."))
        self.write({'state': 'cancelled'})
        
        # If this is a PowerTranz-managed recurring payment, we need to cancel it at the gateway
        if self.management_type == 'powertranz' and self.powertranz_recurring_identifier:
            self._cancel_at_powertranz()
            
        # Send email notification for cancellation
        template = self.env.ref('payment_powertranz.mail_template_recurring_payment_cancelled', False)
        if template and self.partner_id.email:
            try:
                # Get frequency display name
                frequency_mapping = {
                    'D': 'Daily',
                    'W': 'Weekly',
                    'M': 'Monthly',
                    'Y': 'Yearly',
                }
                frequency_display = frequency_mapping.get(self.frequency, self.frequency)
                
                # Create context for rendering
                ctx = {
                    'partner': self.partner_id,
                    'partner_name': self.partner_id.name,
                    'recurring': self,
                    'frequency_display': frequency_display,
                    'formatted_amount': f"{self.currency_id.symbol} {self.amount:.2f}",
                    'company_name': self.company_id.name,
                }
                
                # Send email with proper context
                template.with_context(
                    lang=self.partner_id.lang or self.env.user.lang,
                    **ctx
                ).send_mail(
                    self.id, 
                    force_send=True,
                    email_values={
                        'email_to': self.partner_id.email,
                        'subject': f"Payment Cancelled: {self.name}",
                        'auto_delete': True,
                    }
                )
                _logger.info("Successfully sent cancellation email for recurring payment %s", self.name)
            except Exception as e:
                _logger.error("Error sending cancellation email: %s", e)
            
        # Post a properly formatted message to the chatter
        self._post_formatted_message(
            'payment_powertranz.mail_template_recurring_payment_cancelled',
            subject="Recurring Payment Cancelled: {name}"
        )
    
    def _cancel_at_powertranz(self):
        """Cancel the recurring payment at PowerTranz gateway"""
        try:
            # This would call the PowerTranz API to cancel the recurring payment
            provider = self.provider_id
            # Implementation would depend on PowerTranz API for cancelling recurring payments
            _logger.info(f"Cancelling PowerTranz-managed recurring payment {self.powertranz_recurring_identifier}")
            # TODO: Implement the actual API call to cancel the recurring payment
        except Exception as e:
            _logger.exception(f"Failed to cancel recurring payment at PowerTranz: {e}")
            raise UserError(_("Failed to cancel recurring payment at PowerTranz: %s") % str(e))
    
    def process_recurring_payment(self):
        """Process a recurring payment for merchant-managed subscriptions
        
        This method is used by both the cron job and the 'Pay Now' button to process
        recurring payments. It ensures consistent handling of retries and error cases.
        
        Returns:
            bool: True if payment was successful, False otherwise
        """
        self.ensure_one()
        _logger.info(f"===== PROCESSING RECURRING PAYMENT FOR {self.name} =====")
        
        # Validate state
        if self.state != 'active':
            _logger.info(f"Skipping recurring payment for {self.name} - not active (state: {self.state})")
            return False
        
        # Validate payment token
        token = self.payment_token_id
        if not token or not token.provider_ref:
            _logger.error(f"No valid payment token for {self.name}")
            return False
            
        # Calculate total amount including any missed payments
        total_amount = self.amount
        missed_payments = 0
        
        # If we have missed payments, include them in the transaction
        if self.missed_payment_count > 0:
            missed_payments = self.missed_payment_count
            total_amount += self.amount * missed_payments
            _logger.info(f"Including {missed_payments} missed payments for {self.name}. Total amount: {total_amount}")
            
        try:
            # Create a descriptive reference
            reference = f"{self.name}-{fields.Date.today().strftime('%Y%m%d')}"
            
            # Find existing transactions with the same reference to avoid duplicates
            existing_tx = self.env['payment.transaction'].sudo().search(
                [('reference', '=', reference)], limit=1)
            if existing_tx:
                _logger.info(f"Found existing transaction {existing_tx.reference} for recurring payment {self.name}")
                return False
                
            # Find the payment method for this provider
            provider = token.provider_id
            payment_method = self.env['payment.method'].sudo().search([
                ('provider_ids', 'in', [provider.id]),
                ('code', '=', 'card'),  # Assuming this is a card payment
            ], limit=1)
            
            if not payment_method:
                _logger.error(f"No card payment method found for provider {provider.name}")
                # Try to find any payment method for this provider
                payment_method = self.env['payment.method'].sudo().search([
                    ('provider_ids', 'in', [provider.id]),
                ], limit=1)
                
            if not payment_method:
                _logger.error(f"No valid payment method found for provider {provider.name}")
                return False
                
            # Create transaction values according to Odoo 18 standards
            tx_values = {
                'reference': reference,
                'provider_id': provider.id,
                'payment_method_id': payment_method.id,
                'amount': total_amount,
                'currency_id': self.currency_id.id,
                'partner_id': self.partner_id.id,
                'token_id': token.id,
                'operation': 'offline',  # This is a token payment
                'is_recurring': True,
                'powertranz_recurring_id': self.id,
            }
            
            # Create the transaction
            transaction = self.env['payment.transaction'].sudo().create(tx_values)
            
            # Log the transaction creation
            _logger.info(f"Created recurring payment transaction {transaction.reference} for subscription {self.name}")
            
            # Process the payment using the token
            # This will call the provider-specific implementation of _send_payment_request
            transaction._send_payment_request()
            
            # Check the transaction state
            if transaction.state == 'done':
                # Update last payment date and status
                self.write({
                    'last_payment_date': fields.Date.today(),
                    'last_payment_status': 'success',
                    'last_transaction_id': transaction.id,
                    'missed_payment_count': 0,  # Reset missed payment count on success
                    'retry_count': 0,  # Reset retry count on success
                })
                
                # Recompute next payment date
                self._compute_next_payment_date()
                
                # Send success email notification if the partner has an email
                if self.partner_id.email:
                    template = self.env.ref('payment_powertranz.mail_template_recurring_payment_success', False)
                    if template:
                        try:
                            # Get frequency display name
                            frequency_mapping = {
                                'D': 'Daily',
                                'W': 'Weekly',
                                'F': 'Fortnightly',
                                'M': 'Monthly',
                                'B': 'Bi-Monthly',
                                'Q': 'Quarterly',
                                'S': 'Semi-Annually',
                                'Y': 'Yearly',
                            }
                            frequency_display = frequency_mapping.get(self.frequency, self.frequency)
                            
                            # Create context for rendering
                            ctx = {
                                'partner': self.partner_id,
                                'partner_name': self.partner_id.name,
                                'recurring': self,
                                'frequency_display': frequency_display,
                                'formatted_amount': f"{self.currency_id.symbol} {self.amount:.2f}",
                                'next_date': self.next_payment_date and self.next_payment_date.strftime('%m/%d/%Y') or 'N/A',
                                'company_name': self.company_id.name,
                                'token_display': self.payment_token_id.display_name,
                                'payment_date': self.last_payment_date and self.last_payment_date.strftime('%m/%d/%Y') or 'Today',
                                'missed_payments': missed_payments,
                                'total_amount': total_amount,
                            }
                            
                            # Send email with proper context
                            template.with_context(
                                lang=self.partner_id.lang or self.env.user.lang,
                                **ctx
                            ).send_mail(
                                self.id, 
                                force_send=True,
                                email_layout_xmlid='mail.mail_notification_layout',
                                email_values={
                                    'email_to': self.partner_id.email,
                                    'auto_delete': True,
                                    'recipient_ids': [(4, self.partner_id.id)],
                                    'email_from': self.company_id.email or self.env.user.email_formatted,
                                }
                            )
                            _logger.info(f"Successfully sent success email for recurring payment {self.name}")
                        except Exception as e:
                            _logger.error(f"Error sending success email: {e}")
                
                # Post a properly formatted message to the chatter
                self._post_formatted_message(
                    'payment_powertranz.mail_template_recurring_payment_success',
                    subject="Recurring Payment Processed: {name}"
                )
                
                return True
            else:
                # Update payment status for failed payment
                self.write({
                    'last_payment_status': 'failed',
                    'last_transaction_id': transaction.id,
                    'retry_count': self.retry_count + 1,
                    'last_retry_date': fields.Datetime.now(),  # Use Datetime.now() for datetime field
                })
                
                # Increment missed payment count
                if transaction.state == 'error':
                    self.missed_payment_count += 1
                
                # Send email notification for failed payment
                template = self.env.ref('payment_powertranz.mail_template_recurring_payment_failed', False)
                if template and self.partner_id.email:
                    try:
                        # Get frequency display name
                        frequency_mapping = {
                            'D': 'Daily',
                            'W': 'Weekly',
                            'F': 'Fortnightly',
                            'M': 'Monthly',
                            'B': 'Bi-Monthly',
                            'Q': 'Quarterly',
                            'S': 'Semi-Annually',
                            'Y': 'Yearly',
                        }
                        frequency_display = frequency_mapping.get(self.frequency, self.frequency)
                        
                        # Create context for rendering
                        ctx = {
                            'partner': self.partner_id,
                            'partner_name': self.partner_id.name,
                            'recurring': self,
                            'frequency_display': frequency_display,
                            'formatted_amount': f"{self.currency_id.symbol} {self.amount:.2f}",
                            'next_date': self.next_payment_date and self.next_payment_date.strftime('%m/%d/%Y') or 'N/A',
                            'company_name': self.company_id.name,
                            'token_display': self.payment_token_id.display_name,
                        }
                        
                        # Send email with proper context
                        template.with_context(
                            lang=self.partner_id.lang or self.env.user.lang,
                            **ctx
                        ).send_mail(
                            self.id, 
                            force_send=True,
                            email_layout_xmlid='mail.mail_notification_layout',
                            email_values={
                                'email_to': self.partner_id.email,
                                'auto_delete': True,
                                'recipient_ids': [(4, self.partner_id.id)],
                                'email_from': self.company_id.email or self.env.user.email_formatted,
                            }
                        )
                        _logger.info("Successfully sent failure email for recurring payment %s", self.name)
                    except Exception as e:
                        _logger.error("Error sending failure email: %s", e)
                
                # Post a properly formatted message to the chatter
                self._post_formatted_message(
                    'payment_powertranz.mail_template_recurring_payment_failed',
                    subject="Recurring Payment Failed: {name}"
                )
                
                # If we've reached the maximum retry count, pause the subscription
                if self.retry_count >= self.max_retry_count:
                    self.action_pause()
                    
                return False
                
        except Exception as e:
            _logger.exception(f"ERROR processing recurring payment for {self.name}: {e}")
            # Get detailed exception information
            import traceback
            _logger.error(f"Detailed error traceback: {traceback.format_exc()}")
            
            # Attempt to write minimal failure status. This is best-effort.
            # If the transaction is already aborted by 'e', this write will also fail.
            try:
                self.write({
                    'last_payment_status': 'failed',
                    # Avoid incrementing retry_count here if the transaction might be broken,
                    # let the re-raised exception handle the state for the savepoint.
                    'last_retry_date': fields.Datetime.now(), # Use now() for datetime field
                })
            except Exception as inner_e:
                _logger.error(f"Failed to write minimal failure status for {self.name} after primary error: {inner_e}")

            _logger.info(f"===== END PROCESSING RECURRING PAYMENT FOR {self.name} (PROPAGATING ERROR) =====")
            raise # Re-raise the original exception 'e' to ensure the savepoint rolls back
            
    def force_process_payment(self):
        """Force process a recurring payment, bypassing all checks.
        This is a diagnostic method to help identify issues with payment processing.
        """
        self.ensure_one()
        _logger.info(f"============= FORCE PROCESSING PAYMENT FOR {self.name} ==============")
        
        if not self.payment_token_id:
            _logger.error(f"ERROR: No payment token found for recurring payment {self.name}")
            return False
            
        _logger.info(f"Token information: ID: {self.payment_token_id.id}, Name: {self.payment_token_id.display_name}, Provider ref: {self.payment_token_id.provider_ref}")
        
        if not self.payment_token_id.provider_ref:
            _logger.error(f"ERROR: Payment token has no provider reference for recurring payment {self.name}")
            return False
        
        # Calculate total amount including any missed payments
        total_amount = self.amount
        missed_payments = 0
        
        # If we have missed payments, include them in the transaction
        if self.missed_payment_count > 0:
            missed_payments = self.missed_payment_count
            total_amount += self.amount * missed_payments
            _logger.info(f"Including {missed_payments} missed payments in force transaction. Base amount: {self.amount}, Total: {total_amount}")
        
        # Create a new transaction for this recurring payment
        transaction_values = {
            'provider_id': self.provider_id.id,
            'amount': total_amount,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'token_id': self.payment_token_id.id,
            'operation': 'online_direct',
            'powertranz_recurring_id': self.id,
            'is_recurring': True,
            'reference': f"{self.name}-FORCE-{fields.Date.today().strftime('%Y%m%d')}",
        }
        
        _logger.info(f"Creating transaction with values: {transaction_values}")
        
        try:
            _logger.info(f"Creating transaction for recurring payment {self.name}")
            transaction = self.env['payment.transaction'].sudo().create(transaction_values)
            _logger.info(f"Transaction created with ID: {transaction.id}, Reference: {transaction.reference}")
            
            _logger.info(f"Sending payment request for transaction {transaction.reference}")
            result = transaction._send_payment_request()
            _logger.info(f"Payment request sent, transaction state: {transaction.state}")
            
            if transaction.state == 'done':
                self.write({
                    'last_payment_date': fields.Date.today(),
                    'last_payment_status': 'success',
                    'retry_count': 0,
                    'missed_payment_count': 0,  # Reset missed payment count on success
                    'last_transaction_id': transaction.id,
                })
                
                # Log the successful payment with missed payment info
                if missed_payments > 0:
                    _logger.info(f"Successfully processed forced payment with {missed_payments} missed payments included")
                else:
                    _logger.info(f"Successfully processed forced payment for {self.name}")
                
                # Send email notification for successful payment
                template = self.env.ref('payment_powertranz.mail_template_recurring_payment_success', False)
                if template and self.partner_id.email:
                    try:
                        # Get frequency display name
                        frequency_mapping = {
                            'D': 'Daily',
                            'W': 'Weekly',
                            'M': 'Monthly',
                            'Y': 'Yearly',
                        }
                        frequency_display = frequency_mapping.get(self.frequency, self.frequency)
                        
                        # Create context for rendering
                        ctx = {
                            'partner': self.partner_id,
                            'partner_name': self.partner_id.name,
                            'recurring': self,
                            'frequency_display': frequency_display,
                            'formatted_amount': f"{self.currency_id.symbol} {self.amount:.2f}",
                            'next_date': self.next_payment_date and self.next_payment_date.strftime('%m/%d/%Y') or 'N/A',
                            'company_name': self.company_id.name,
                            'token_display': self.payment_token_id.display_name,
                            'payment_date': self.last_payment_date and self.last_payment_date.strftime('%m/%d/%Y') or 'Today',
                            'missed_payments': missed_payments,
                            'total_amount': total_amount,
                        }
                        
                        # Send email with proper context
                        template.with_context(
                            lang=self.partner_id.lang or self.env.user.lang,
                            **ctx
                        ).send_mail(
                            self.id, 
                            force_send=True,
                            email_values={
                                'email_to': self.partner_id.email,
                                'subject': f"Payment Successful: {self.name}",
                                'auto_delete': True,
                            }
                        )
                        _logger.info("Successfully sent success email for forced payment %s", self.name)
                    except Exception as e:
                        _logger.error("Error sending success email for forced payment: %s", e)
                
                # Post a properly formatted message to the chatter
                self._post_formatted_message(
                    'payment_powertranz.mail_template_recurring_payment_success',
                    subject="Forced Recurring Payment Processed: {name}"
                )
                    
                return True
            else:
                _logger.error(f"Forced payment failed for {self.name}, transaction state: {transaction.state}")
                return False
                
        except Exception as e:
            import traceback
            _logger.exception(f"ERROR processing forced payment for {self.name}: {e}")
            _logger.error(f"Detailed error traceback: {traceback.format_exc()}")
            return False
    
    @api.model
    def _cron_process_recurring_payments(self):
        """Cron job to process all due merchant-managed recurring payments
        
        This method is responsible for finding and processing all recurring payments that are due,
        either by their scheduled date or because they need to be retried after a failure.
        It uses the same payment processing logic as the 'Pay Now' button to ensure consistency.
        
        Returns:
            bool: True if the cron job completed successfully
        """
        _logger.info("============= STARTING POWERTRANZ RECURRING PAYMENTS CRON JOB ==============")
        _logger.info("Processing merchant-managed recurring payments")
        
        # Find all active merchant-managed recurring payments that are due
        today = fields.Date.today()
        now = fields.Datetime.now()
        _logger.info(f"Current date: {today}, Current time: {now}")
        
        # First, log all active recurring payments regardless of due date
        all_active = self.search([('state', '=', 'active'), ('management_type', '=', 'merchant')])
        _logger.info(f"Total active merchant-managed recurring payments: {len(all_active)}")
        
        if not all_active:
            _logger.info("No active merchant-managed recurring payments found. Exiting cron job.")
            _logger.info("============= COMPLETED POWERTRANZ RECURRING PAYMENTS CRON JOB ==============")
            return True
            
        # Log information about all active recurring payments
        for rec_info in all_active:
            _logger.info(f"Active recurring payment: {rec_info.name}, Next payment date: {rec_info.next_payment_date}, "
                         f"Retry count: {rec_info.retry_count}, Last retry: {rec_info.last_retry_date}")
        
        # Find payments due by next_payment_date (convert next_payment_date to date for comparison)
        due_by_date = self.search([
            ('state', '=', 'active'),
            ('management_type', '=', 'merchant'),
            ('next_payment_date', '<=', fields.Datetime.now()),
        ])
        
        # Find payments due for retry based on hours elapsed
        due_for_retry_candidates = self.search([
            ('state', '=', 'active'),
            ('management_type', '=', 'merchant'),
            ('retry_count', '>', 0),
            ('retry_count', '<', self.env['ir.config_parameter'].sudo().get_param('payment_powertranz.max_retry_count', '3')),
            ('last_retry_date', '!=', False),
            ('last_payment_status', '=', 'failed'),
        ])
        
        # Filter retry payments based on hours elapsed since last retry
        retry_payments = self.env['powertranz.recurring']
        for payment in due_for_retry_candidates:
            if payment.last_retry_date:
                hours_since_retry = (now - payment.last_retry_date).total_seconds() / 3600
                _logger.info(f"Payment {payment.name} - Hours since last retry: {hours_since_retry:.1f}, "
                             f"Required hours: {payment.retry_hours}")
                if hours_since_retry >= payment.retry_hours:
                    retry_payments |= payment
                    _logger.info(f"Payment {payment.name} is due for retry after {hours_since_retry:.1f} hours")
        
        # Combine both sets of payments (due by date and due for retry)
        recurring_payments_to_process = due_by_date | retry_payments
        _logger.info(f"Found {len(due_by_date)} payments due by date and {len(retry_payments)} payments due for retry")
        _logger.info(f"Total recurring payments due for processing: {len(recurring_payments_to_process)}")
        
        if not recurring_payments_to_process:
            _logger.info("No recurring payments due for processing. Exiting cron job.")
            _logger.info("============= COMPLETED POWERTRANZ RECURRING PAYMENTS CRON JOB ==============")
            return True
        
        # Log details about payments to be processed
        if recurring_payments_to_process:
            _logger.info("Due recurring payments:")
            for rec_info in recurring_payments_to_process:
                _logger.info(f"Due payment: {rec_info.name}, Customer: {rec_info.partner_id.name}, "
                             f"Amount: {rec_info.amount} {rec_info.currency_id.name}, Next date: {rec_info.next_payment_date}, "
                             f"Retry count: {rec_info.retry_count}")
                
                # Check token validity
                if not rec_info.payment_token_id:
                    _logger.error(f"Missing payment token for {rec_info.name}")
                elif not rec_info.payment_token_id.provider_ref:
                    _logger.error(f"Token has no provider reference for {rec_info.name}")
                else:
                    # Only show first 6 chars of token reference for security
                    token_ref = rec_info.payment_token_id.provider_ref
                    masked_ref = token_ref[:6] + '...' if len(token_ref) > 6 else token_ref
                    _logger.info(f"Token for {rec_info.name}: {masked_ref}")
        
        # Process each payment within its own savepoint to isolate failures
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for recurring_id in recurring_payments_to_process.ids:
            with self.env.cr.savepoint():
                recurring = self.env['powertranz.recurring'].browse(recurring_id)
                _logger.info(f"Processing recurring payment {recurring.name} (ID: {recurring.id})")
                
                # Verify payment is still active (could have changed since our search)
                if recurring.state != 'active':
                    _logger.info(f"Skipping {recurring.name} - no longer active (state: {recurring.state})")
                    skipped_count += 1
                    continue
                    
                # Verify token is still valid
                if not recurring.payment_token_id or not recurring.payment_token_id.provider_ref:
                    _logger.error(f"Skipping {recurring.name} - invalid payment token")
                    skipped_count += 1
                    continue
                
                try:
                    # Process the payment using the same method as the 'Pay Now' button
                    result = recurring.process_recurring_payment()
                    if result:
                        _logger.info(f"Successfully processed recurring payment {recurring.name}")
                        success_count += 1
                    else:
                        _logger.warning(f"Failed to process recurring payment {recurring.name}")
                        failed_count += 1
                except Exception as e:
                    # The savepoint will automatically roll back on exception
                    _logger.exception(f"Error processing recurring payment {recurring.name}: {e}")
                    failed_count += 1
        
        # Log summary of processing results
        _logger.info(f"Recurring payments processed: {success_count} successful, {failed_count} failed, {skipped_count} skipped")
        _logger.info("============= COMPLETED POWERTRANZ RECURRING PAYMENTS CRON JOB ==============")
        return True
