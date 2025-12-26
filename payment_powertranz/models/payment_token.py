# -*- coding: utf-8 -*-

import logging
import requests # Add dependency in manifest
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    # === PowerTranz Recurring Fields ===
    powertranz_recurring_enabled = fields.Boolean(
        string="Recurring Enabled (PowerTranz)",
        help="Whether PowerTranz managed recurring payments are configured for this token."
    )
    powertranz_recurring_frequency = fields.Selection([
        # Frequencies supported by PowerTranz (adjust based on actual API support)
        ('D', 'Daily'),
        ('W', 'Weekly'),
        ('F', 'Fortnightly'), # Bi-Weekly
        ('M', 'Monthly'),
        ('B', 'Bi-Monthly'),
        ('Q', 'Quarterly'),
        ('S', 'Semi-Annually'),
        ('Y', 'Yearly')
    ], string="Recurring Frequency", help="Frequency set for PowerTranz managed recurring payments.")

    powertranz_recurring_start_date = fields.Date(
        string="Recurring Start Date",
        help="Start date for PowerTranz managed recurring payments."
    )

    powertranz_recurring_end_date = fields.Date(
        string="Recurring End Date",
        help="Optional end date for PowerTranz managed recurring payments."
    )

    # This identifier is crucial for managing PowerTranz-side recurring
    powertranz_recurring_identifier = fields.Char(
        string="Recurring Identifier",
        help="The unique identifier assigned by PowerTranz for this recurring setup.",
        readonly=True,
        index=True # Index for potential lookups
    )

    powertranz_recurring_active = fields.Boolean(
        string="Recurring Active (PowerTranz)",
        help="Whether the PowerTranz managed recurring subscription is currently active.",
        readonly=True # Status typically updated via webhooks
    )

    powertranz_recurring_next_date = fields.Date(
        string="Next Recurring Date (PowerTranz)",
        help="Date of the next scheduled payment for PowerTranz managed recurring.",
        readonly=True # Status typically updated via webhooks
    )

    # === PowerTranz Specific Fields ===
    powertranz_card_brand = fields.Char(
        string="Card Brand",
        help="The brand of the card (Visa, Mastercard, etc.)",
        readonly=True
    )
    
    powertranz_masked_pan = fields.Char(
        string="Masked PAN",
        help="The masked card number",
        readonly=True
    )
    
    powertranz_expiry = fields.Char(
        string="Card Expiry",
        help="The card expiration date in MMYY format",
        readonly=True
    )

    def _get_card_brand_emoji(self):
        """Return an emoji representation of the card brand.
        
        :return: Emoji for the card brand
        :rtype: str
        """
        self.ensure_one()
        if not self.powertranz_card_brand:
            return "💳"
            
        if self.powertranz_card_brand.lower() == 'visa':
            return "💳 Visa"
        elif self.powertranz_card_brand.lower() == 'mastercard':
            return "💳 Mastercard"
        
        # Default for other card brands
        return f"💳 {self.powertranz_card_brand}"

    # === Overridden Methods ===
    def _prepare_payment_transaction_values(self, **kwargs):
        """Override to include PowerTranz recurring identifier in transaction values if applicable.

        :param dict kwargs: Optional keyword arguments passed to the parent method.
        :return: The transaction values including PowerTranz specifics.
        :rtype: dict
        """
        values = super()._prepare_payment_transaction_values(**kwargs)

        # Only add if it's a PowerTranz token and has a recurring ID
        if self.provider_code == 'powertranz' and self.powertranz_recurring_identifier:
            values.update({
                'powertranz_recurring_identifier': self.powertranz_recurring_identifier,
                # Add other necessary flags if PowerTranz requires them for recurring payments via token
            })

        return values

    @api.depends('powertranz_card_brand', 'powertranz_masked_pan')
    def _compute_display_name(self):
        """Override to customize display name for PowerTranz tokens."""
        super()._compute_display_name()
        for token in self:
            if token.provider_code == 'powertranz' and token.powertranz_masked_pan:
                last_digits = token.powertranz_masked_pan[-4:] if len(token.powertranz_masked_pan) >= 4 else '****'
                brand_emoji = token._get_card_brand_emoji()
                token.display_name = f"{brand_emoji} **** {last_digits}"

    # === PowerTranz Specific Methods ===
    def powertranz_cancel_recurring(self):
        """Initiate cancellation of a PowerTranz managed recurring subscription.
           Makes an API call to PowerTranz.
        """
        self.ensure_one()

        if not self.powertranz_recurring_identifier:
            raise ValidationError(_("This token does not have a PowerTranz recurring identifier to cancel."))

        if self.provider_code != 'powertranz':
            raise ValidationError(_("This action is only available for PowerTranz tokens."))

        provider = self.provider_id
        if not provider or not provider.powertranz_id or not provider.powertranz_password:
             raise ValidationError(_("PowerTranz provider is not configured correctly."))

        # Construct the API endpoint URL
        # Use the computed API URL which respects test/prod mode
        # Ensure the endpoint path is correct based on PowerTranz docs
        url = f"{provider.powertranz_api_url}/admin/recurring/cancel"

        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'PowerTranz-PowerTranzId': provider.powertranz_id,
            'PowerTranz-PowerTranzPassword': provider.powertranz_password,
        }
        if provider.powertranz_gateway_key:
            headers['PowerTranz-GatewayKey'] = provider.powertranz_gateway_key

        payload = {
            'RecurringIdentifier': self.powertranz_recurring_identifier
        }

        _logger.info("Attempting to cancel PowerTranz recurring subscription %s", self.powertranz_recurring_identifier)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            result = response.json()
            _logger.info("PowerTranz recurring cancellation response: %s", result)

            # Check PowerTranz response code for successful cancellation (e.g., 'R5')
            # Adjust based on actual PowerTranz API documentation for the cancel endpoint
            if result.get('IsoResponseCode') == 'R5':
                self.write({
                    'powertranz_recurring_active': False,
                    'powertranz_recurring_enabled': False, # Also disable it
                    # Clear dates if needed
                    # 'powertranz_recurring_next_date': False,
                })
                _logger.info("Successfully cancelled PowerTranz recurring %s", self.powertranz_recurring_identifier)
                # Return something indicating success, perhaps for frontend feedback
                # Could post a message to the chatter
                self.message_post(body=_("PowerTranz recurring subscription cancelled successfully."))
                return True
            else:
                # Cancellation failed on PowerTranz side
                error_message = result.get('ResponseMessage', _('Unknown error from PowerTranz.'))
                _logger.error("Failed to cancel PowerTranz recurring %s: %s", self.powertranz_recurring_identifier, error_message)
                raise ValidationError(_("Failed to cancel recurring subscription: %s") % error_message)

        except requests.exceptions.Timeout:
            _logger.error("Timeout cancelling PowerTranz recurring %s", self.powertranz_recurring_identifier)
            raise ValidationError(_("The request to cancel the recurring subscription timed out."))
        except requests.exceptions.RequestException as e:
            _logger.exception("Error cancelling PowerTranz recurring subscription %s", self.powertranz_recurring_identifier)
            raise ValidationError(_("An error occurred while contacting PowerTranz: %s", str(e)))
        except Exception as e:
             _logger.exception("Unexpected error cancelling PowerTranz recurring subscription %s", self.powertranz_recurring_identifier)
             raise ValidationError(_("An unexpected error occurred: %s", str(e))) 