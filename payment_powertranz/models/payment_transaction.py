# -*- coding: utf-8 -*-

import logging
import json
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

from odoo.addons.payment_powertranz.tools.card_data_manager import card_data_manager
from odoo.addons.payment_powertranz.tools.security import mask_sensitive_data

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # Keep both transaction identifiers to ensure compatibility
    powertranz_transaction_id = fields.Char(
        string="PowerTranz Transaction ID",
        help="The transaction identifier from PowerTranz",
        readonly=True,
    )
    
    # Make UUID also serve as transaction_id (database compatibility)
    powertranz_transaction_uuid = fields.Char(
        string="PowerTranz Transaction UUID",
        help="The UUID sent to PowerTranz as the transaction identifier",
        readonly=True,
    )
    
    # Link to recurring payment record
    powertranz_recurring_id = fields.Many2one(
        'powertranz.recurring',
        string="Recurring Payment",
        help="The recurring payment record associated with this transaction",
        readonly=True
    )
    
    # Non-sensitive recurring payment data (JSON)
    powertranz_recurring = fields.Text(
        string="Recurring Payment Data",
        help="JSON data for recurring payment setup"
    )
    
    # Add missing field for recurring identifier
    powertranz_recurring_identifier = fields.Char(
        string="Recurring Identifier",
        help="Identifier for PowerTranz managed recurring payments, if applicable.",
        readonly=True
    )
    
    # Flag to indicate if this is a recurring payment
    is_recurring = fields.Boolean(
        string="Is Recurring Payment",
        default=False,
        help="Indicates if this transaction is part of a recurring payment."
    )
    
    # 3DS Status Tracking (maintain this as it's not sensitive)
    powertranz_spi_token = fields.Char(
        string="PowerTranz SPI Token",
        help="The SPI token returned by PowerTranz to identify the transaction",
        readonly=True
    )
    
    # 3DS Status Tracking
    powertranz_3ds_status = fields.Selection([
        ('pending', 'Pending'), # Initial state or before 3DS check
        ('fingerprint', 'Device Fingerprinting Required'), # Requires device data collection
        ('challenge', 'Challenge Required'), # Requires user interaction via iframe
        ('authenticated', 'Authenticated'), # 3DS authentication successful
        ('failed', 'Authentication Failed') # 3DS authentication failed
    ], string="3DS Status", readonly=True, copy=False,
        help="Tracks the status of the 3D Secure authentication process.")

    powertranz_3ds_redirect_data = fields.Text(
        string="3DS Redirect Data",
        help="HTML/JavaScript code provided by PowerTranz for 3DS device fingerprinting or challenge.",
        readonly=True
    )

    # 3DS Authentication Results
    powertranz_authentication_status = fields.Char(
        string="3DS Authentication Status",
        help="The 3DS authentication status (Y=Authenticated, N=Failed, A=Attempted, U=Unavailable)",
        readonly=True
    )
    powertranz_eci_value = fields.Char(
        string="ECI Value",
        help="The Electronic Commerce Indicator value from 3DS authentication",
        readonly=True
    )
    powertranz_cavv = fields.Char(
        string="CAVV",
        help="The Cardholder Authentication Verification Value from 3DS",
        readonly=True
    )
    powertranz_xid = fields.Char(
        string="XID",
        help="The transaction identifier from 3DS",
        readonly=True
    )
    
    # Transaction results - maintain non-sensitive fields 
    powertranz_authorization_code = fields.Char(
        string="Authorization Code",
        help="The authorization code returned by PowerTranz",
        readonly=True
    )
    
    powertranz_rrn = fields.Char(
        string="RRN",
        help="The Retrieval Reference Number returned by PowerTranz",
        readonly=True
    )
    
    powertranz_iso_response_code = fields.Char(
        string="Response Code",
        help="The ISO response code returned by PowerTranz",
        readonly=True
    )
    
    powertranz_card_brand = fields.Char(
        string="Card Brand",
        help="The card brand used for the transaction",
        readonly=True
    )

    powertranz_card_last_four = fields.Char(
        string="Card Last Four",
        help="Last 4 digits of the card number for display purposes",
        readonly=True,
        size=4
    )

    powertranz_response_message = fields.Char(
        string="Response Message",
        help="The response message returned by PowerTranz",
        readonly=True
    )
    
    # Handle the transaction_id/transaction_uuid sync automatically
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Ensure transaction_id and transaction_uuid are in sync
        for record in records:
            if record.powertranz_transaction_uuid and not record.powertranz_transaction_id:
                record.powertranz_transaction_id = record.powertranz_transaction_uuid
            elif record.powertranz_transaction_id and not record.powertranz_transaction_uuid:
                record.powertranz_transaction_uuid = record.powertranz_transaction_id
        return records
    
    def write(self, vals):
        res = super().write(vals)
        # Ensure transaction_id and transaction_uuid are in sync after write
        if vals.get('powertranz_transaction_uuid') and not vals.get('powertranz_transaction_id'):
            for record in self:
                if record.powertranz_transaction_uuid != record.powertranz_transaction_id:
                    super(PaymentTransaction, record).write({
                        'powertranz_transaction_id': record.powertranz_transaction_uuid
                    })
        elif vals.get('powertranz_transaction_id') and not vals.get('powertranz_transaction_uuid'):
            for record in self:
                if record.powertranz_transaction_id != record.powertranz_transaction_uuid:
                    super(PaymentTransaction, record).write({
                        'powertranz_transaction_uuid': record.powertranz_transaction_id
                    })
        return res
    
    # Add a method to get card data from memory
    def _get_card_data(self):
        """Get card data from memory store instead of database fields
        
        Returns:
            dict: Card data dictionary or None if not found
        """
        self.ensure_one()
        card_data = card_data_manager.retrieve(self.reference)
        
        if card_data:
            _logger.info("PowerTranz: Found card data in memory for %s", self.reference)
            return card_data
            
        # No card data found in memory
        _logger.info("PowerTranz: No card data found in memory for %s", self.reference)
        return None

    def _get_specific_rendering_values(self, processing_values):
        """ Override of payment to return PowerTranz-specific rendering values.

        Note: This method will be implemented fully in a later prompt.
        For now, we just return an empty dict as placeholder.
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'powertranz':
            return res

        # We'll implement this fully in a later prompt
        return {}

    # ========== Odoo 19 Payment API Methods ==========

    @api.model
    def _search_by_reference(self, provider_code, payment_data):
        """Override of payment to find the transaction based on PowerTranz data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict payment_data: The payment data sent by the provider
        :return: The transaction if found
        :rtype: payment.transaction
        """
        if provider_code != 'powertranz':
            return super()._search_by_reference(provider_code, payment_data)

        reference = self._extract_reference(provider_code, payment_data)
        if reference:
            tx = self.search([('reference', '=', reference), ('provider_code', '=', 'powertranz')])
        else:
            # Try to find by PowerTranz transaction identifier
            transaction_id = payment_data.get('TransactionIdentifier')
            if transaction_id:
                tx = self.search([
                    ('powertranz_transaction_id', '=', transaction_id),
                    ('provider_code', '=', 'powertranz')
                ])
            else:
                # Try by SPI token
                spi_token = payment_data.get('SpiToken')
                if spi_token:
                    tx = self.search([
                        ('powertranz_spi_token', '=', spi_token),
                        ('provider_code', '=', 'powertranz')
                    ])
                else:
                    _logger.warning("PowerTranz: Received data with missing reference/identifier")
                    tx = self

        if not tx:
            _logger.warning("PowerTranz: No transaction found matching reference %s", reference)

        return tx

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        """Extract the transaction reference from the PowerTranz payment data.

        :param str provider_code: The code of the provider handling the transaction
        :param dict payment_data: The payment data sent by the provider
        :return: The transaction reference
        :rtype: str
        """
        if provider_code != 'powertranz':
            return super()._extract_reference(provider_code, payment_data)

        # PowerTranz sends the reference in different fields depending on the flow
        reference = payment_data.get('reference')
        if not reference:
            reference = payment_data.get('OrderIdentifier')
        if not reference:
            reference = payment_data.get('ExternalIdentifier')

        return reference

    def _extract_amount_data(self, payment_data):
        """Extract the amount, currency and rounding precision from PowerTranz payment data.

        :param dict payment_data: The payment data sent by the provider
        :return: The amount data dict or None to skip validation
        :rtype: dict|None
        """
        if self.provider_code != 'powertranz':
            return super()._extract_amount_data(payment_data)

        # PowerTranz sends amount as TotalAmount in major units (e.g., 29.00 for $29.00)
        total_amount = payment_data.get('TotalAmount')
        if total_amount is None:
            # Skip amount validation if not provided
            return None

        # PowerTranz returns amount in major units (dollars), not minor units (cents)
        try:
            amount = float(total_amount)
        except (ValueError, TypeError):
            amount = 0.0

        # PowerTranz uses ISO currency codes
        currency_code = payment_data.get('CurrencyCode', '')
        # Convert numeric ISO code to alpha code if needed
        if currency_code and currency_code.isdigit():
            currency_code = self._get_currency_alpha_code(currency_code)

        return {
            'amount': amount,
            'currency_code': currency_code or self.currency_id.name,
            'precision_digits': 2,  # PowerTranz uses 2 decimal precision
        }

    def _get_currency_alpha_code(self, numeric_code):
        """Convert ISO numeric currency code to alpha code.

        :param str numeric_code: The numeric ISO currency code
        :return: The alpha currency code
        :rtype: str
        """
        # Common currency mappings
        currency_map = {
            '840': 'USD',
            '978': 'EUR',
            '826': 'GBP',
            '124': 'CAD',
            '388': 'JMD',
            '780': 'TTD',
            '052': 'BBD',
            '951': 'XCD',
        }
        return currency_map.get(numeric_code, self.currency_id.name if self.currency_id else 'USD')

    def _extract_token_values(self, payment_data):
        """Extract the create values of a token from the PowerTranz payment data.

        :param dict payment_data: The payment data sent by the provider
        :return: The token values dict
        :rtype: dict
        """
        if self.provider_code != 'powertranz':
            return super()._extract_token_values(payment_data)

        # Get token value from PowerTranz response
        token_value = payment_data.get('PanToken')
        if not token_value:
            # Use transaction identifier as fallback
            token_value = payment_data.get('TransactionIdentifier')

        if not token_value:
            _logger.warning("PowerTranz: No PanToken or TransactionIdentifier for tokenization")
            return {}

        # Get card details for display
        card_brand = payment_data.get('CardBrand', 'Card')
        # Get last 4 digits if available
        masked_pan = payment_data.get('MaskedPan', '')
        last_four = masked_pan[-4:] if len(masked_pan) >= 4 else ''

        # If MaskedPan not in response, try to get from stored card data or database field
        if not last_four or last_four == '****':
            # First try in-memory card data
            card_data = card_data_manager.retrieve(self.reference)
            if card_data and card_data.get('card_number'):
                card_number = card_data.get('card_number', '')
                if len(card_number) >= 4:
                    last_four = card_number[-4:]
                    _logger.info("PowerTranz: Got last 4 digits from in-memory card data: %s", last_four)
            # Fallback to database field (persists across worker processes)
            elif self.powertranz_card_last_four:
                last_four = self.powertranz_card_last_four
                _logger.info("PowerTranz: Got last 4 digits from database field: %s", last_four)

        # Build payment_details in format "Brand •••• 1234"
        if last_four and last_four != '****':
            payment_details = f"{card_brand} •••• {last_four}"
        else:
            payment_details = f"{card_brand} •••• ****"

        return {
            'provider_ref': token_value,
            'payment_details': payment_details,
        }

    def _apply_updates(self, payment_data):
        """Override of payment to update the transaction based on PowerTranz payment data.

        This method replaces _process_notification_data in Odoo 19.

        :param dict payment_data: The payment data sent by the provider
        :return: None
        """
        if self.provider_code != 'powertranz':
            return super()._apply_updates(payment_data)

        masked_data = mask_sensitive_data(payment_data)
        _logger.info("PowerTranz: Processing payment data: %s", masked_data)

        # Extract key fields from the payment data
        iso_response_code = payment_data.get('IsoResponseCode')
        approved = payment_data.get('Approved', False)
        transaction_id = payment_data.get('TransactionIdentifier')

        # Update transaction with PowerTranz data
        vals = {
            'provider_reference': transaction_id,
            'powertranz_iso_response_code': iso_response_code,
            'powertranz_response_message': payment_data.get('ResponseMessage'),
            'powertranz_authorization_code': payment_data.get('AuthorizationCode'),
            'powertranz_rrn': payment_data.get('RRN'),
            'powertranz_card_brand': payment_data.get('CardBrand'),
        }

        # Update the payment method if card brand is provided
        card_brand = payment_data.get('CardBrand', '').lower()
        if card_brand:
            # Map PowerTranz card brands to Odoo payment method codes
            brand_mapping = {
                'visa': 'visa',
                'mastercard': 'mastercard',
                'amex': 'amex',
                'american express': 'amex',
                'discover': 'discover',
                'diners': 'diners',
                'jcb': 'jcb',
            }
            pm_code = brand_mapping.get(card_brand, 'card')
            payment_method = self.env['payment.method']._get_from_code(pm_code)
            if payment_method:
                self.payment_method_id = payment_method

        # Handle 3DS data if present
        risk_mgmt = payment_data.get('RiskManagement', {})
        three_ds = risk_mgmt.get('ThreeDSecure', {})
        if three_ds:
            vals.update({
                'powertranz_authentication_status': three_ds.get('AuthenticationStatus'),
                'powertranz_eci_value': three_ds.get('Eci'),
                'powertranz_cavv': three_ds.get('Cavv'),
                'powertranz_xid': three_ds.get('Xid'),
            })

        # Store recurring identifier if present
        if payment_data.get('RecurringIdentifier'):
            vals['powertranz_recurring_identifier'] = payment_data.get('RecurringIdentifier')

        self.write(vals)

        # Update transaction state based on PowerTranz response
        if approved and iso_response_code == '00':
            # Transaction successful
            _logger.info("PowerTranz: Payment successful for %s", self.reference)
            self._set_done()
            # Note: recurring setup is now handled in _tokenize() override to ensure token exists

        elif iso_response_code == '3D0' and three_ds.get('AuthenticationStatus') == 'Y':
            # 3DS authentication successful but payment pending
            _logger.info("PowerTranz: 3DS authentication successful for %s, pending completion", self.reference)
            self._set_pending()

        elif iso_response_code in ('00', '85') and not approved:
            # Authorized but not captured (manual capture mode)
            _logger.info("PowerTranz: Payment authorized for %s", self.reference)
            self._set_authorized()

        else:
            # Transaction failed
            error_msg = payment_data.get('ResponseMessage', _('Payment failed'))
            _logger.warning("PowerTranz: Payment failed for %s: %s", self.reference, error_msg)
            self._set_error(error_msg)
            # Only clean up card data on failure - successful transactions need it for tokenization
            card_data_manager.remove(self.reference)
            _logger.info("PowerTranz: Cleaned up card data for failed transaction %s", self.reference)

    def _handle_recurring_setup(self, payment_data):
        """Handle recurring payment setup after successful payment.

        :param dict payment_data: The payment data from PowerTranz
        :return: None
        """
        _logger.info("PowerTranz: _handle_recurring_setup called for %s, tokenize=%s, powertranz_recurring=%s",
                    self.reference, self.tokenize, self.powertranz_recurring)

        # Check tokenize OR powertranz_recurring (if recurring was requested, we should proceed)
        if not self.tokenize and not self.powertranz_recurring:
            _logger.info("PowerTranz: Skipping recurring setup - no tokenize and no recurring data for %s", self.reference)
            return

        # Check if this is a subscription/recurring payment
        is_subscription = (
            self.env.context.get('is_subscription_payment', False) or
            (hasattr(self, 'powertranz_recurring_id') and self.powertranz_recurring_id) or
            payment_data.get('is_subscription_payment') or
            (hasattr(self, 'is_recurring') and self.is_recurring) or
            (hasattr(self, 'powertranz_recurring') and self.powertranz_recurring)
        )

        _logger.info("PowerTranz: is_subscription=%s for %s", is_subscription, self.reference)

        if not is_subscription:
            _logger.info("PowerTranz: Skipping recurring setup - not a subscription for %s", self.reference)
            return

        if not self.token_id:
            _logger.warning("PowerTranz: No token available for recurring setup on %s", self.reference)
            return

        _logger.info("PowerTranz: Setting up recurring payment for %s", self.reference)

        # Get recurring payment data from transaction
        recurring_data = {}
        if hasattr(self, 'powertranz_recurring') and self.powertranz_recurring:
            try:
                recurring_data = json.loads(self.powertranz_recurring)
            except (json.JSONDecodeError, TypeError) as e:
                _logger.warning("PowerTranz: Failed to parse recurring data: %s", e)

        # Set default values
        recurring_data.setdefault('frequency', 'M')
        recurring_data.setdefault('management_type', 'merchant')
        recurring_data.setdefault('start_date', fields.Date.today())
        recurring_data.setdefault('description', f'Recurring payment for {self.reference}')

        # Create the recurring payment record
        recurring = self._create_recurring_payment(self.token_id, recurring_data)
        if recurring:
            _logger.info("PowerTranz: Created recurring payment %s", recurring.name)
            self.write({'powertranz_recurring_id': recurring.id})
    
    # Note: In Odoo 19, _create_payment is handled by the base payment module
    # The accounting integration (account.payment creation) is done automatically
    # through post-processing in the payment framework

    def _tokenize(self, payment_data):
        """Override to handle recurring payment setup after token creation.

        The recurring setup must happen AFTER the token is created, so we call
        the parent method first and then handle recurring setup.

        :param dict payment_data: The payment data sent by the provider.
        :return: None
        """
        # Call parent to create the token
        super()._tokenize(payment_data)

        # Now that token is created, handle recurring setup
        if self.token_id:
            _logger.info("PowerTranz: Token created for %s, now setting up recurring payment", self.reference)
            self._handle_recurring_setup(payment_data)

    def _powertranz_create_token(self, notification_data):
        """Create a payment token from the notification data.

        Note: In Odoo 19, tokenization is primarily handled through _extract_token_values
        and the base _tokenize method. This method is kept for backward compatibility
        and specific PowerTranz token creation needs.

        :param dict notification_data: The notification data from PowerTranz
        :return: The created token or None
        :rtype: payment.token or None
        """
        self.ensure_one()

        # Check if we should tokenize this transaction
        if not self.tokenize:
            _logger.info("PowerTranz: Tokenization not requested for %s", self.reference)
            return None

        # Get token values using the standard Odoo 19 method
        token_values = self._extract_token_values(notification_data)
        if not token_values:
            _logger.warning("PowerTranz: Could not extract token values for %s", self.reference)
            return None

        # Get additional card details from notification data or memory
        masked_pan = notification_data.get('MaskedPan', '')
        card_brand = notification_data.get('CardBrand', '')

        # If we don't have masked PAN from notification, try card data from memory or database
        if not masked_pan or masked_pan == '******':
            card_data = self._get_card_data()
            if card_data and card_data.get('card_number'):
                card_number = card_data.get('card_number')
                if len(card_number) >= 10:
                    masked_pan = f"{card_number[:6]}{'*' * (len(card_number) - 10)}{card_number[-4:]}"
                else:
                    masked_pan = f"{'*' * (len(card_number) - 4)}{card_number[-4:]}"
            # Fallback to database field (persists across worker processes)
            elif self.powertranz_card_last_four:
                masked_pan = f"{'*' * 12}{self.powertranz_card_last_four}"
                _logger.info("PowerTranz: Got masked PAN from database field for %s", self.reference)

        # Determine card brand if not provided
        if not card_brand:
            card_data = self._get_card_data()
            if card_data and card_data.get('card_number'):
                card_number = card_data.get('card_number')
                if card_number.startswith('4'):
                    card_brand = 'Visa'
                elif card_number.startswith(('51', '52', '53', '54', '55')):
                    card_brand = 'Mastercard'
                elif card_number.startswith(('34', '37')):
                    card_brand = 'American Express'
                elif card_number.startswith('6'):
                    card_brand = 'Discover'
                else:
                    card_brand = 'Card'
            else:
                card_brand = 'Card'

        # Build token creation values following Odoo 19 standards
        token_vals = {
            'provider_id': self.provider_id.id,
            'payment_method_id': self.payment_method_id.id,
            'partner_id': self.partner_id.id,
            'provider_ref': token_values.get('provider_ref'),
            'payment_details': token_values.get('payment_details'),
        }

        # Add PowerTranz-specific token fields
        token_vals.update({
            'powertranz_masked_pan': masked_pan,
            'powertranz_card_brand': card_brand,
        })

        # Add expiry if available from card data
        card_data = self._get_card_data()
        if card_data and card_data.get('expiry_month') and card_data.get('expiry_year'):
            month = str(card_data.get('expiry_month', '')).zfill(2)
            year = str(card_data.get('expiry_year', ''))
            if len(year) == 4:
                year = year[2:]
            token_vals['powertranz_expiry'] = f"{month}{year}"

        try:
            token = self.env['payment.token'].sudo().create(token_vals)
            _logger.info("PowerTranz: Created token %s for transaction %s", token.id, self.reference)
            # Clean up card data after successful token creation
            card_data_manager.remove(self.reference)
            _logger.info("PowerTranz: Cleaned up card data after token creation for %s", self.reference)
            return token
        except Exception as e:
            _logger.error("PowerTranz: Failed to create token for %s: %s", self.reference, e)
            # Clean up card data even on failure
            card_data_manager.remove(self.reference)
            return None

    def _send_payment_request(self):
        """Override to implement FPI approach with PowerTranz.

        :return: None
        """
        _logger.info(f"===== SENDING PAYMENT REQUEST FOR TRANSACTION {self.reference} =====")
        _logger.info(f"Transaction details: Amount: {self.amount} {self.currency_id.name}, Provider: {self.provider_id.name}")
        
        super()._send_payment_request()
        if self.provider_code != 'powertranz':
            _logger.info(f"Skipping PowerTranz processing for transaction {self.reference} with provider {self.provider_code}")
            return

        # Check if 3DS is enabled for this transaction
        three_d_secure_enabled = self.provider_id.powertranz_3ds_enabled
        _logger.info("PowerTranz: 3DS is %s for transaction %s", 
                    "enabled" if three_d_secure_enabled else "disabled", 
                    self.reference)
        
        # Get card data from memory instead of transaction fields
        has_card_data = False
        card_data = self._get_card_data()
        if card_data:
            has_card_data = True
        
        # If we have card data, we're using a new card, not a token
        # This overrides the token_id check because sometimes both can be present
        is_using_token = False if has_card_data else self.token_id is not None
        
        # Check if this is a recurring payment transaction
        is_recurring = self.is_recurring or self.powertranz_recurring_id or self.env.context.get('recurring_payment', False)
        
        _logger.info("PowerTranz: Transaction details for %s: has_card_data=%s, token_id=%s, is_using_token=%s, is_recurring=%s", 
                    self.reference, has_card_data, self.token_id is not None, is_using_token, is_recurring)

        # Choose endpoint based on transaction type and features
        if is_using_token:
            # For saved cards (tokens), use /Sale endpoint
            _logger.info("PowerTranz: Using FPI direct flow with /Sale for saved card payment")
            endpoint = '/Sale'
            # Force 3DS off for saved card payments and recurring payments
            three_d_secure_enabled = False
            
            # If this is a recurring payment, log additional info
            if is_recurring:
                _logger.info("PowerTranz: Processing recurring payment for transaction %s", self.reference)
        elif three_d_secure_enabled:
            _logger.info("PowerTranz: Using FPI redirect flow with 3DS for new card")
            endpoint = '/Sale'
        else:
            _logger.info("PowerTranz: Using FPI direct flow without 3DS for new card")
            endpoint = '/Sale'
        
        # Prepare API request
        api_request = self._prepare_powertranz_fpi_request(endpoint, is_recurring=is_recurring)
        
        try:
            # Make API request to PowerTranz
            response_data = self._make_powertranz_request(endpoint, api_request)
            
            # Process response based on 3DS setting
            if three_d_secure_enabled:
                # Get 3DS redirect URL from response
                redirect_url = self._process_powertranz_fpi_response(response_data)
                if redirect_url:
                    return {
                        'type': 'ir.actions.act_url',
                        'url': redirect_url,
                        'target': 'self',
                    }
            else:
                # Process direct payment response
                self._process_direct_payment_response(response_data)
                
            # Clean up card data from memory after transaction is processed
            # BUT only if NOT tokenizing - tokenization needs card data for last 4 digits
            # Also keep card data if recurring is set (which implies tokenization)
            should_keep_card_data = self.tokenize or self.powertranz_recurring
            if has_card_data and not should_keep_card_data:
                card_data_manager.remove(self.reference)
                _logger.info("PowerTranz: Removed card data from memory for %s (not tokenizing)", self.reference)
            elif has_card_data:
                _logger.info("PowerTranz: Keeping card data for %s (tokenize=%s, recurring=%s)",
                            self.reference, self.tokenize, bool(self.powertranz_recurring))
                
        except ValidationError as e:
            _logger.exception("Validation error sending PowerTranz payment request for %s: %s", self.reference, e)
            self._set_error(str(e))
        except Exception as e:
            _logger.exception("Unexpected error sending PowerTranz payment request for %s: %s", self.reference, e)
            self._set_error(_("PowerTranz communication error: %s") % str(e))

    def _prepare_powertranz_fpi_request(self, endpoint, is_validation=False, is_recurring=False):
        """Prepare the request data for PowerTranz FPI API.
        
        Args:
            endpoint (str): API endpoint to call
            is_validation (bool): Whether this is a validation-only request
            is_recurring (bool): Whether this is a recurring payment transaction
            
        Returns:
            dict: Request data for PowerTranz API
        """
        self.ensure_one()
        
        # Generate a unique transaction identifier if not already set
        import uuid
        tx_uuid = self.powertranz_transaction_uuid or str(uuid.uuid4())
        if not self.powertranz_transaction_uuid:
            self.write({'powertranz_transaction_uuid': tx_uuid})
        
        # Basic payment data
        amount = self.amount
        if is_validation:
            # For validation requests, use a small amount
            amount = 1.00
            
        # Get ISO numeric currency code
        # PowerTranz requires numeric currency codes
        currency_code = self._get_iso_currency_code(self.currency_id.name)
        
        # Prepare basic request data
        # Generate a unique order identifier to avoid duplicate order ID errors
        # Use the reference as the base but add a timestamp to ensure uniqueness
        import datetime
        unique_order_id = f"{self.reference}_{int(datetime.datetime.now().timestamp())}"
        
        request_data = {
            'totalAmount': amount,
            'currencyCode': currency_code,
            'transactionIdentifier': tx_uuid,
            'externalIdentifier': self.reference,  # Keep original reference for transaction lookup
            'orderIdentifier': unique_order_id,    # Use unique ID to avoid duplicates
        }
        
        # Log the unique order ID being used
        _logger.info("PowerTranz: Using unique order ID %s for transaction %s", 
                    unique_order_id, self.reference)
        
        # Add recurring flag for recurring payments
        if is_recurring:
            request_data['Recurring'] = True
            _logger.info("PowerTranz: Added Recurring flag to request for transaction %s", self.reference)
        
        # Add card data from memory if available
        card_data = self._get_card_data()
        if card_data and not self.token_id:
            _logger.info("PowerTranz: Using card data from memory for transaction %s", self.reference)
            
            # Format card expiry data
            month = card_data.get('expiry_month', '').zfill(2)
            year = card_data.get('expiry_year', '')
            if len(year) == 4:
                year = year[2:]  # Get last 2 digits
            expiry = year + month  # PowerTranz expects YYMM format
            
            # Add card data to the source field
            request_data['source'] = {
                'cardPan': card_data.get('card_number', ''),
                'cardExpiration': expiry,
                'cardholderName': card_data.get('card_holder', ''),
                'cardCvv': card_data.get('cvc', '')
            }
        elif self.token_id:
            _logger.info("PowerTranz: Using token for transaction %s", self.reference)
            token = self.token_id
            
            # For saved cards, set Recurring flag to true and disable 3DS
            # Note: This may be overridden by the is_recurring parameter
            if 'Recurring' not in request_data:
                request_data['Recurring'] = True
            
            # Set the token ID as a top-level field in the request
            request_data['tokenId'] = token.provider_ref
            
            # Based on version 20 implementation that worked successfully
            # PowerTranz requires both tokenId and card details
            
            # Always use a test card in test mode
            if self.provider_id.state == 'test':
                _logger.info("PowerTranz: Using test card for saved card payment in test mode")
                # In test mode, use a known working test card
                request_data['source'] = {
                    'cardPan': '5100270000000023',  # Use a known working test card
                    'cardExpiration': '2512',      # Always use the known working format YYMM
                    'cardholderName': 'Test User', # Always use the known working name
                    'cardCvv': '123'               # Always use the known working CVV
                }
            else:
                # Get card details from the token if available
                card_brand = token.powertranz_card_brand if hasattr(token, 'powertranz_card_brand') else ''
                masked_pan = token.powertranz_masked_pan if hasattr(token, 'powertranz_masked_pan') and token.powertranz_masked_pan else ''
                expiry = token.powertranz_expiry if hasattr(token, 'powertranz_expiry') and token.powertranz_expiry else ''

                # If we don't have the card details stored, try to extract from payment_details
                if not masked_pan:
                    # payment_details typically contains "VISA •••• 1234" format
                    payment_details = token.payment_details or ''
                    if payment_details:
                        # Try to extract last 4 digits from payment_details
                        import re
                        match = re.search(r'(\d{4})$', payment_details.replace(' ', ''))
                        last4 = match.group(1) if match else '0000'
                    else:
                        last4 = '0000'
                    masked_pan = '************' + last4
                
                if not expiry:
                    # Use a future date for expiry (next year, same month)
                    import datetime
                    now = datetime.datetime.now()
                    next_year = now.year + 1
                    month = str(now.month).zfill(2)
                    year = str(next_year)[-2:]
                    expiry = year + month  # YYMM format
                
                # Use partner name for cardholder
                cardholder_name = self.partner_id.name or 'Card Holder'
                
                # Format the request data with card details
                # For recurring payments, we only need tokenId, not card details
                if self.is_recurring or self.powertranz_recurring_id:
                    _logger.info("PowerTranz: Using token only for recurring payment %s", self.reference)
                else:
                    # For regular saved card payments, include minimal card details
                    _logger.info("PowerTranz: Including minimal card details with token for %s", self.reference)
                    request_data['source'] = {
                        'cardholderName': cardholder_name
                    }
            
            # Log the token being used (masked for security)
            token_value = token.provider_ref
            if token_value and len(token_value) > 10:
                masked_token = token_value[:2] + '*' * (len(token_value) - 4) + token_value[-2:]
                _logger.info("PowerTranz: Using token %s for transaction %s", masked_token, self.reference)
                
            # Log the card details being used (masked for security)
            if 'source' in request_data and 'cardPan' in request_data['source']:
                card_number = request_data['source']['cardPan']
                masked_card = '*' * 12 + card_number[-4:] if len(card_number) >= 4 else card_number
                _logger.info("PowerTranz: Using card %s for transaction %s", masked_card, self.reference)
        
        # If 3DS is required, set the appropriate flags
        # BUT skip 3DS for saved card (token-based) payments - card was already authenticated
        provider = self.provider_id
        is_token_payment = self.token_id and self.token_id.id
        if provider.powertranz_3ds_enabled and endpoint == '/Sale' and not is_token_payment:
            request_data['threeDSecure'] = True
            
            # Add 3DS browser info
            browser_info = self._get_browser_info()
            if browser_info:
                if 'extendedData' not in request_data:
                    request_data['extendedData'] = {}
                
                if 'browserInfo' not in request_data['extendedData']:
                    request_data['extendedData']['browserInfo'] = browser_info
            
            # Add merchant response URL for 3DS
            from werkzeug import urls
            base_url = self.provider_id.get_base_url()
            
            # Don't force HTTPS as it was working with HTTP in the old version
            # if base_url.startswith('http://'):
            #     base_url = 'https://' + base_url[7:]
                
            merchant_response_url = urls.url_join(base_url, '/payment/powertranz/merchant_response')
            if 'extendedData' not in request_data:
                request_data['extendedData'] = {}
            
            if 'threeDSecure' not in request_data['extendedData']:
                request_data['extendedData']['threeDSecure'] = {}
            
            request_data['extendedData']['threeDSecure']['merchantResponseUrl'] = merchant_response_url
            request_data['extendedData']['threeDSecure']['challengeWindowSize'] = 0  # Full screen
            
        # Add billing address if available
        billing_address = self._get_billing_address()
        if billing_address:
            request_data['billingAddress'] = billing_address
            
        return request_data
        
    def _get_browser_info(self):
        """Get browser information for 3DS authentication.
        
        This information is typically collected by the frontend
        and passed to the backend, but we'll provide default values
        here for testing purposes.
        
        Returns:
            dict: Browser information for 3DS
        """
        # These are placeholder values - in a real implementation,
        # this data would come from the frontend
        return {
            'acceptHeader': 'application/json',
            'colorDepth': '24',
            'javaEnabled': False,
            'javascriptEnabled': True,
            'language': 'en-US',
            'screenHeight': '600',
            'screenWidth': '800',
            'timeZone': '180',
            'userAgent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
        }
        
    def _get_iso_currency_code(self, currency_name):
        """Convert currency name to ISO numeric code.
        
        Args:
            currency_name (str): ISO alpha currency code (e.g. 'USD')
            
        Returns:
            str: ISO numeric currency code (e.g. '840')
        """
        # Common currency codes mapping
        currency_codes = {
            'USD': '840',
            'EUR': '978',
            'GBP': '826',
            'JMD': '388',
            'CAD': '124'
        }
        
        return currency_codes.get(currency_name, '840')  # Default to USD if not found
    
    def _get_iso_country_code(self, country_code):
        """Convert country code to ISO numeric code.
        
        Args:
            country_code (str): ISO alpha-2 country code (e.g. 'US')
            
        Returns:
            str: ISO numeric country code (e.g. '840')
        """
        # Common country codes mapping
        country_codes = {
            'US': '840',
            'GB': '826',
            'CA': '124',
            'JM': '388'
        }
        
        return country_codes.get(country_code, '840')  # Default to US if not found
    
    def _get_billing_address(self):
        """Get billing address information.
        
        Returns:
            dict: Billing address data for PowerTranz API
        """
        self.ensure_one()
        
        # Get partner first/last name
        from odoo.addons.payment import utils as payment_utils
        partner_first_name, partner_last_name = payment_utils.split_partner_name(self.partner_name)
        
        # Basic address data
        address = {
            'firstName': partner_first_name,
            'lastName': partner_last_name,
            'line1': self.partner_address or '',
            'city': self.partner_city or '',
            'state': self.partner_state_id.code if self.partner_state_id else '',
            'postalCode': self.partner_zip or '',
            'countryCode': self._get_iso_country_code(self.partner_country_id.code or 'US'),
            'emailAddress': self.partner_email or '',
            'phoneNumber': self.partner_phone or '+1 555-555-5555'
        }
        
        # Add line2 if available
        if hasattr(self, 'partner_street2') and self.partner_street2:
            address['line2'] = self.partner_street2
        
        return address
    
    def _process_direct_payment_response(self, response_data):
        """Process the response from a direct payment request.
        
        :param dict response_data: The API response data
        :return: None
        """
        self.ensure_one()
        
        _logger.info(f"Processing direct payment response for transaction {self.reference}")
        
        # Log the full response for debugging
        import json
        from odoo.addons.payment_powertranz.tools.security import mask_sensitive_data
        masked_response = mask_sensitive_data(response_data)
        _logger.info(f"Full PowerTranz response for {self.reference}: {json.dumps(masked_response, indent=2)}")
        
        # Check if the response has an approved status
        # PowerTranz API returns 'Approved' with capital A
        approved = response_data.get('Approved', False)
        _logger.info(f"Transaction {self.reference} approved status: {approved}")
        
        # Get response code and message
        # PowerTranz API returns 'IsoResponseCode' and 'ResponseMessage' with capital letters
        response_code = response_data.get('IsoResponseCode', '')
        response_message = response_data.get('ResponseMessage', '')
        _logger.info(f"Transaction {self.reference} response code: {response_code}, message: {response_message}")
        
        # Check if the response has the necessary fields
        if not response_data or 'TransactionIdentifier' not in response_data:
            _logger.error("PowerTranz: Invalid response data for transaction %s", self.reference)
            self._set_error("Invalid response from payment gateway")
            return
        
        # Store response data in transaction fields
        vals = {
            'provider_reference': response_data.get('TransactionIdentifier'),
            'powertranz_authorization_code': response_data.get('AuthorizationCode'),
            'powertranz_rrn': response_data.get('RRN'),
            'powertranz_iso_response_code': response_data.get('IsoResponseCode'),
            'powertranz_card_brand': response_data.get('CardBrand'),
            'powertranz_response_message': response_data.get('ResponseMessage'),
        }
        
        # Handle token creation if needed
        if self.tokenize and not self.token_id and approved:
            _logger.info(f"Creating token for transaction {self.reference}")
            self._powertranz_create_token_from_response(response_data)
            
        # Set transaction status based on response
        if approved:
            _logger.info(f"Setting transaction {self.reference} to 'done' state")
            self._set_done()
            # No need to call _post_process_after_done() as it's handled by _set_done()
        else:
            _logger.error(f"Transaction {self.reference} failed with error: {response_message} ({response_code})")
            self._set_error(f"PowerTranz payment error: {response_message} ({response_code})")
            
        _logger.info(f"Completed processing direct payment response for transaction {self.reference}, final state: {self.state}")
        
        # Write values to transaction
        self.write(vals) 

    def _process_powertranz_fpi_response(self, response_data):
        """Process a PowerTranz FPI response for 3DS flow.
        
        This method handles the response from the initial Auth request,
        which should contain a SPI token for 3DS authentication.
        
        Args:
            response_data (dict): Response data from PowerTranz API
            
        Returns:
            str: Redirect URL for 3DS authentication if applicable, otherwise None
        """
        self.ensure_one()
        
        # Check if the response has the necessary fields
        if not response_data or 'SpiToken' not in response_data:
            _logger.error("PowerTranz: Invalid 3DS response data for transaction %s", self.reference)
            self._set_error("Invalid 3DS response from payment gateway")
            return None
        
        # Store SPI token for 3DS authentication
        spi_token = response_data.get('SpiToken')
        self.write({
            'powertranz_spi_token': spi_token,
            'powertranz_3ds_status': 'authenticated'  # Mark as authenticated for now
        })
        
        # Save 3DS authentication data if available
        if 'RiskManagement' in response_data and 'ThreeDSecure' in response_data['RiskManagement']:
            threeds_data = response_data['RiskManagement']['ThreeDSecure']
            self.write({
                'powertranz_authentication_status': threeds_data.get('AuthenticationStatus'),
                'powertranz_cavv': threeds_data.get('Cavv'),
                'powertranz_eci_value': threeds_data.get('Eci'),
                'powertranz_xid': threeds_data.get('Xid')
            })
        
        _logger.info("PowerTranz: 3DS authentication initiated for %s with SPI token %s", 
                     self.reference, spi_token)
        
        # Create redirect URL for 3DS completion
        from werkzeug import urls
        base_url = self.provider_id.get_base_url()
        redirect_url = urls.url_join(base_url, f'/payment/powertranz/complete?spi_token={spi_token}')
        
        _logger.info("PowerTranz: 3DS redirect URL for %s: %s", self.reference, redirect_url)
        return redirect_url

    def _create_recurring_payment(self, token, recurring_data):
        """Create a recurring payment record from transaction data.
        
        :param payment.token token: The payment token to use for recurring payments
        :param dict recurring_data: Dictionary containing recurring payment details
        :return: The created recurring payment record
        :rtype: recordset of 'powertranz.recurring'
        """
        if not token or not recurring_data:
            _logger.warning('Cannot create recurring payment: Missing token or recurring data')
            return False
            
        self.ensure_one()
        _logger.info('Creating recurring payment for transaction %s with token %s', self.reference, token.id)
        
        # Extract recurring payment details
        frequency = recurring_data.get('frequency', 'M')
        start_date = recurring_data.get('start_date')
        end_date = recurring_data.get('end_date')
        management_type = recurring_data.get('management_type', 'merchant')
        description = recurring_data.get('description', f'Recurring payment for {self.reference}')
        
        # Convert string dates to date objects if needed
        if start_date and isinstance(start_date, str):
            try:
                start_date = fields.Date.from_string(start_date)
            except ValueError:
                _logger.warning('Invalid start date format: %s, using today', start_date)
                start_date = fields.Date.today()
        elif not start_date:
            start_date = fields.Date.today()
            
        if end_date and isinstance(end_date, str):
            try:
                end_date = fields.Date.from_string(end_date)
            except ValueError:
                _logger.warning('Invalid end date format: %s, using None', end_date)
                end_date = None
                
        # Create the recurring payment record
        vals = {
            'partner_id': self.partner_id.id,
            'payment_token_id': token.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'frequency': frequency,
            'start_date': start_date,
            'end_date': end_date,
            'management_type': management_type,
            'description': description,
            'state': 'active'  # Activate immediately
        }
        
        # Add PowerTranz-specific fields if available
        if hasattr(self, 'powertranz_recurring_identifier') and self.powertranz_recurring_identifier:
            vals['powertranz_recurring_identifier'] = self.powertranz_recurring_identifier
            
        # Create the recurring payment record
        recurring = self.env['powertranz.recurring'].sudo().create(vals)
        
        if recurring:
            # Link the transaction to the recurring payment
            self.write({
                'powertranz_recurring_id': recurring.id,
                'is_recurring': True
            })
            _logger.info('Successfully created recurring payment %s for transaction %s', recurring.name, self.reference)
            
            # Send notification email for the newly created recurring payment
            try:
                _logger.info("Sending email notification to %s for recurring payment %s", 
                             recurring.partner_id.email, recurring.name)
                
                template = self.env.ref('payment_powertranz.mail_template_recurring_payment_created', False)
                if template and recurring.partner_id.email:
                    # Ensure template is properly rendered with context
                    template.with_context(lang=recurring.partner_id.lang).send_mail(
                        recurring.id, 
                        force_send=True,
                        email_layout_xmlid='mail.mail_notification_layout',
                        email_values={
                            'email_to': recurring.partner_id.email,
                            'auto_delete': True,
                            'recipient_ids': [(4, recurring.partner_id.id)],
                            'email_from': recurring.company_id.email or self.env.user.email_formatted,
                        }
                    )
                    _logger.info('Successfully sent recurring payment creation email to %s', recurring.partner_id.email)
                else:
                    _logger.warning("Cannot send email: Partner %s has no email or template not found", recurring.partner_id.name)
            except Exception as e:
                _logger.exception('Error sending recurring payment email: %s', e)
        else:
            _logger.error('Failed to create recurring payment for transaction %s', self.reference)
            
        return recurring

    def _delayed_create_recurring_payment(self):
        """Create a recurring payment record from transaction data.
        
        This method is called after a transaction is completed to create a recurring payment
        record if the transaction was marked for recurring payments.
        """
        self.ensure_one()
        
        # Check if this transaction is for a recurring payment and has not already created one
        if not self.powertranz_recurring or self.powertranz_recurring_id:
            _logger.info('Transaction %s is not eligible for recurring payment creation', self.reference)
            return False
            
        # Check if the transaction is in a completed state
        if self.state != 'done':
            _logger.info('Transaction %s is not completed, cannot create recurring payment', self.reference)
            return False
            
        # Check if we have a token
        if not self.token_id:
            _logger.warning('Transaction %s has no token, cannot create recurring payment', self.reference)
            return False
            
        # Parse the recurring data
        try:
            recurring_data = json.loads(self.powertranz_recurring)
        except (json.JSONDecodeError, TypeError) as e:
            _logger.error('Error parsing recurring data for transaction %s: %s', self.reference, e)
            recurring_data = {
                'frequency': 'M',  # Monthly by default
                'management_type': 'merchant',
                'description': f'Recurring payment for {self.reference}'
            }
            
        # Create the recurring payment
        recurring = self._create_recurring_payment(self.token_id, recurring_data)
        
        # If recurring payment was created successfully, try to send email notification
        if recurring:
            try:
                _logger.info('Successfully created recurring payment record %s for transaction %s', 
                            recurring.name, self.reference)
                
                # Send email notification with proper error handling
                recurring.send_creation_email()
                _logger.info('Successfully sent recurring payment creation email for %s', recurring.name)
            except Exception as email_error:
                _logger.exception('Error sending recurring payment email: %s', email_error)
                # Continue with the process even if email sending fails
        
        return recurring
        
    @api.model
    def _cron_create_delayed_recurring_payments(self):
        """Cron job to create delayed recurring payments.
        
        This method scans for transactions that:
        - Are completed
        - Have a payment token
        - Have recurring data
        - Don't already have a recurring payment
        """
        _logger.info('Running cron job to create delayed recurring payments')
        
        # Find transactions that are completed and have recurring data
        transactions = self.search([
            ('state', '=', 'done'),
            ('powertranz_recurring', '!=', False),
            ('powertranz_recurring_id', '=', False),
            ('token_id', '!=', False)
        ])
        
        # Also look for transactions that are still in progress but have 3DS tokens
        # These might be waiting for 3DS completion
        transactions_3ds = self.search([
            ('state', 'in', ['draft', 'pending']),
            ('powertranz_recurring', '!=', False),
            ('powertranz_recurring_id', '=', False),
            ('powertranz_spi_token', '!=', False)
        ])
        
        # Log information about found transactions
        if not transactions and not transactions_3ds:
            _logger.info('No transactions found for delayed recurring payment creation')
            return
            
        _logger.info('Found %d completed transactions and %d 3DS transactions for delayed recurring payment creation', 
                    len(transactions), len(transactions_3ds))
        
        # Process completed transactions
        for tx in transactions:
            try:
                _logger.info('Processing completed transaction %s for recurring payment creation', tx.reference)
                tx._delayed_create_recurring_payment()
            except Exception as e:
                _logger.exception('Error creating delayed recurring payment for transaction %s: %s', tx.reference, e)
                
        # For 3DS transactions, check if they have a token yet
        for tx in transactions_3ds:
            try:
                # If the transaction has a token, try to create the recurring payment
                if tx.token_id:
                    _logger.info('Processing 3DS transaction %s with token for recurring payment creation', tx.reference)
                    tx._delayed_create_recurring_payment()
                else:
                    _logger.info('3DS transaction %s does not have a token yet, skipping', tx.reference)
            except Exception as e:
                _logger.exception('Error processing 3DS transaction %s for recurring payment: %s', tx.reference, e)
                
        _logger.info('PowerTranz: Completed creating delayed recurring payments') 

    def _make_powertranz_request(self, endpoint, data, method='POST'):
        """Make an API request to PowerTranz.
        
        :param str endpoint: The endpoint to call (e.g., '/Auth', '/Sale')
        :param dict data: The data to send to PowerTranz
        :param str method: HTTP method to use (default: POST)
        :return: The API response data
        :rtype: dict
        :raise: ValidationError if the API request fails
        """
        self.ensure_one()
        import requests
        import json
        
        # Get API URL from provider
        api_url = self.provider_id.powertranz_api_url
        
        # Add endpoint to URL
        if not api_url.endswith('/'):
            api_url += '/'
        url = api_url.rstrip('/') + endpoint
        
        # Prepare headers with authentication - use PowerTranz-PowerTranzPassword as in the old version
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'PowerTranz-PowerTranzId': self.provider_id.powertranz_id,
            'PowerTranz-PowerTranzPassword': self.provider_id.powertranz_password,
        }
        
        # Add gateway key if provided
        if self.provider_id.powertranz_gateway_key:
            headers['PowerTranz-GatewayKey'] = self.provider_id.powertranz_gateway_key
        
        # Convert data to JSON
        data_json = json.dumps(data)
        
        # Log the request (mask sensitive data)
        from odoo.addons.payment_powertranz.tools.security import mask_sensitive_data
        masked_data = mask_sensitive_data(data)
        masked_headers = {k: v if 'password' not in k.lower() else '***' for k, v in headers.items()}
        _logger.info("PowerTranz API Request to %s: Headers=%s, Data=%s", url, masked_headers, masked_data)
        
        # Send the request
        try:
            response = requests.request(method, url, headers=headers, data=data_json, timeout=30)
            
            # Log the response text for debugging, even if status code is not 200
            if response.status_code != 200:
                _logger.error("PowerTranz API error: HTTP %s: %s", response.status_code, response.text)
                
            response.raise_for_status()
            response_data = response.json()
            
            # Log the response (mask sensitive data)
            masked_response = mask_sensitive_data(response_data)
            _logger.info("PowerTranz API Response from %s: %s", url, masked_response)
            
            return response_data
        except requests.exceptions.RequestException as e:
            # Try to parse response text for more detailed error info
            error_details = ""
            if hasattr(e, 'response') and e.response and e.response.text:
                try:
                    error_json = json.loads(e.response.text)
                    error_details = f"\nAPI Error Details: {json.dumps(error_json, indent=2)}"
                except:
                    error_details = f"\nAPI Error Response: {e.response.text}"
                    
            _logger.exception("Error making PowerTranz API request: %s%s", e, error_details)
            raise ValidationError(_("API communication error: %s%s") % (str(e), error_details))
        except json.JSONDecodeError as e:
            _logger.exception("Error decoding PowerTranz API response: %s", e)
            raise ValidationError(_("Invalid API response format: %s") % str(e)) 