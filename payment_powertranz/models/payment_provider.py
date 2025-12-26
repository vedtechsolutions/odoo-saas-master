# -*- coding: utf-8 -*-

import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from werkzeug import urls

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    def _valid_field_parameter(self, field, name):
        # Allow 'password' parameter for PowerTranz fields
        if name == 'password':
            return True
        return super()._valid_field_parameter(field, name)

    code = fields.Selection(
        selection_add=[('powertranz', 'PowerTranz')],
        ondelete={'powertranz': 'set default'}
    )

    powertranz_id = fields.Char(
        string="PowerTranz ID",
        help="The Merchant ID provided by PowerTranz.",
        required_if_provider='powertranz',
        groups='base.group_system' # Only show to system admins
    )
    powertranz_password = fields.Char(
        string="PowerTranz Password",
        help="The processing password provided by PowerTranz.",
        required_if_provider='powertranz',
        password=True, # Mask the field
        groups='base.group_system' # Only show to system admins
    )
    powertranz_gateway_key = fields.Char(
        string="Gateway Key",
        help="Optional Gateway Key provided by PowerTranz",
        groups='base.group_system' # Only show to system admins
    )

    powertranz_3ds_enabled = fields.Boolean(
        string="Enable 3D Secure",
        default=True,
        help="Enable 3D Secure authentication for card payments"
    )
    powertranz_recurring_type = fields.Selection([
        ('merchant', 'Merchant Managed'),
        ('powertranz', 'PowerTranz Managed')
        ], string="Recurring Type", default='merchant',
           help="Choose who manages recurring payments scheduling. "
                "'Merchant Managed' requires Odoo cron jobs. "
                "'PowerTranz Managed' relies on PowerTranz scheduling and webhooks."
    )
    powertranz_webhook_url = fields.Char(
        string="Webhook URL",
        compute='_compute_powertranz_webhook_url',
        store=True, # Store for easy copying/configuration in PowerTranz dashboard
        readonly=True,
        help="URL for PowerTranz to send webhook notifications (e.g., for PowerTranz Managed Recurring)."
    )
    powertranz_webhook_secret = fields.Char(
        string="Webhook Secret",
        help="Secret key used to authenticate webhook requests from PowerTranz. Used to verify the X-PowerTranz-Signature header.",
        copy=False,
        groups='base.group_system', # Only show to system admins
        password=True # Mask the field for security
    )
    
    powertranz_test_mode = fields.Boolean(
        string="Is Test Mode", # Field to determine test mode internally
        compute='_compute_powertranz_test_mode',
        help="Technical field indicating if the provider is in test mode based on its state."
    )
    
    powertranz_api_url = fields.Char(
        string="API URL",
        default='https://gateway.ptranz.com/Api',
        help="PowerTranz API endpoint URL used for transactions. Use https://staging.ptranz.com/Api for testing."
    )

    @api.depends('state')
    def _compute_powertranz_test_mode(self):
        """ Determine if the provider is in test mode based on state """
        for provider in self:
            provider.powertranz_test_mode = provider.state == 'test'


    @api.depends('state', 'code')
    def _compute_powertranz_webhook_url(self):
        """ Compute the webhook URL needed for PowerTranz configuration """
        for provider in self:
            if provider.code == 'powertranz' and provider.state != 'disabled':
                base_url = provider.get_base_url()
                provider.powertranz_webhook_url = urls.url_join(base_url, '/payment/powertranz/webhook')
            else:
                provider.powertranz_webhook_url = False


    @api.depends('code')
    def _compute_feature_support_fields(self):
        """ Tell Odoo which features PowerTranz supports """
        super()._compute_feature_support_fields()
        for provider in self:
            if provider.code == 'powertranz':
                provider.support_tokenization = True
                # Based on schema, seems full refunds only initially, can adjust later
                provider.support_refund = 'full_only'
                provider.support_manual_capture = 'full_only'
                # PowerTranz doesn't seem to support express checkout (Google/Apple Pay via Odoo standard flow)
                provider.support_express_checkout = False


    # Add compute methods for view configuration later if needed
    # Example:
    # @api.depends('code')
    # def _compute_view_configuration_fields(self):
    #     super()._compute_view_configuration_fields()
    #     # By default all fields are shown, hide specific ones if needed
    #     # for provider in self.filtered(lambda p: p.code == 'powertranz'):
    #     #     provider.show_allow_express_checkout = False # If PowerTranz doesn't support it

    # Override specific methods like _get_supported_currencies if needed

    def _powertranz_verify_credentials(self):
        """ Placeholder method to verify credentials with PowerTranz API """
        self.ensure_one()
        if self.code != 'powertranz':
            return
        # TODO: Implement API call to a PowerTranz endpoint (e.g., a status check)
        # using self.powertranz_id, self.powertranz_password etc.
        # Raise ValidationError if credentials are invalid
        # Example (requires 'requests' library):
        # try:
        #     # Make a test API call
        #     pass
        # except Exception as e:
        #     raise ValidationError(_("Credentials verification failed: %s", str(e)))
        _logger.warning("PowerTranz credential verification is not yet implemented.")
        pass # Remove pass when implemented

    # Minimal required methods for basic functionality are inherited

    def _get_redirect_form_view(self, is_validation=False):
        """ Return the PowerTranz redirect form template for FPI flow. """
        self.ensure_one()
        if self.code != 'powertranz':
            return super()._get_redirect_form_view(is_validation=is_validation)
            
        # PowerTranz uses FPI approach with redirect
        _logger.info("PowerTranz: Using FPI redirect flow.")
        
        # Create a view on the fly instead of referencing one by ID
        provider_id = self.id
        arch = """
            <form action="/payment/powertranz/redirect" method="post" class="o_payment_powertranz_redirect p-3">
                <input type="hidden" name="provider_id" value="%s"/>
                
                <div class="d-flex flex-column gap-2 align-items-center">
                    <!-- PowerTranz logo and title -->
                    <div class="d-flex align-items-center gap-2 mb-3">
                        <img src="/payment_powertranz/static/src/img/powertranz_logo.png" alt="PowerTranz" width="100" height="35" class="o_payment_provider_logo"/>
                        <h5 class="mb-0">Secure Payment</h5>
                    </div>
                    
                    <!-- Redirect message -->
                    <div class="alert alert-info text-center" role="alert">
                        <i class="fa fa-info-circle me-2"></i>
                        <span>You will be redirected to PowerTranz to complete your payment securely.</span>
                    </div>
                    
                    <!-- Processing indicator -->
                    <div class="text-center mt-2">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <p class="mt-2">Please wait, redirecting to payment page...</p>
                    </div>
                    
                    <!-- Secure payment message -->
                    <div class="d-flex align-items-center justify-content-center mt-3 text-muted">
                        <i class="fa fa-lock me-2"></i> 
                        <small>Your payment will be processed securely by PowerTranz.</small>
                    </div>
                    
                    <!-- Auto submit script -->
                    <script type="text/javascript">
                        document.addEventListener('DOMContentLoaded', function() {
                            // Submit the form immediately on page load
                            setTimeout(function() {
                                document.querySelector('.o_payment_powertranz_redirect').submit();
                            }, 500);
                        });
                    </script>
                </div>
            </form>
        """ % provider_id
        
        view = self.env['ir.ui.view'].create({
            'name': 'PowerTranz FPI Redirect Form',
            'type': 'qweb',
            'arch': arch
        })
        return view

    def _get_payment_provider_inline_form_vals(self, **kwargs):
        """ Return the values needed to render the PowerTranz redirect form. """
        self.ensure_one()
        if self.code == 'powertranz':
            # Only need basic values for the redirect form
            values = {
                'providerId': self.id,
                'mode': self.state,
            }
            return values
        _logger.warning("PowerTranz: Calling _get_payment_provider_inline_form_vals for non-PowerTranz provider.")
        return super()._get_payment_provider_inline_form_vals(**kwargs)

    def _powertranz_get_inline_form_values(self):
        """Return the values for the PowerTranz inline form.

        :return: A JSON string of values for the payment form.
        :rtype: str
        """
        self.ensure_one()
        inline_form_values = {
            'providerId': self.id,
            'state': self.state,
            'isTestMode': self.state == 'test',
            'recurringType': self.powertranz_recurring_type or '',
            '3dsEnabled': self.powertranz_3ds_enabled,
        }
        return json.dumps(inline_form_values) 