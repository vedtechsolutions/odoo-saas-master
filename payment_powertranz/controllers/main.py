from odoo import http
from odoo.http import request
import logging
import json
import pprint

from odoo.addons.payment_powertranz.tools.card_data_manager import card_data_manager
from odoo.addons.payment_powertranz.tools.security import mask_sensitive_data

_logger = logging.getLogger(__name__)


class PowerTranzController(http.Controller):
    
    @http.route('/payment/powertranz/create_transaction', type='jsonrpc', auth='public')
    def powertranz_create_transaction(self, **data):
        """Create a transaction and return its processing values.

        :param dict data: The transaction creation data
        :return: The processing values of the transaction
        :rtype: dict
        """
        try:
            # Retrieve the tx and process it
            tx_sudo = self._get_tx_from_json_data(**data)
            # Mask sensitive data before logging
            masked_data = mask_sensitive_data(data)
            _logger.info("PowerTranz: Processing transaction %s with data: %s", tx_sudo.reference, masked_data)
            
            # Extract card data from the request
            card_data = {}
            if data.get('powertranz_card_number'):
                card_data = {
                    'card_number': data.get('powertranz_card_number'),
                    'card_holder': data.get('powertranz_card_holder'),
                    'expiry_month': data.get('powertranz_card_expiry_month'),
                    'expiry_year': data.get('powertranz_card_expiry_year'),
                    'cvc': data.get('powertranz_card_cvc'),
                    'brand': data.get('powertranz_card_brand'),
                    'save_card': data.get('powertranz_save_card', False),
                }
                
                # Extract and store the last 4 digits in the database for display purposes
                card_number = card_data['card_number']
                last_four = card_number[-4:] if len(card_number) >= 4 else ''

                # Log the card data being received (with masking for security)
                masked_pan = 'XXXXXXXXXXXX' + last_four if last_four else 'XXXX'
                _logger.info("PowerTranz: Received card data for tx %s: PAN=%s, Expiry=%s/%s",
                            tx_sudo.reference, masked_pan,
                            card_data.get('expiry_month'),
                            card_data.get('expiry_year'))

                # Store last 4 digits in the database (persists across worker processes)
                if last_four:
                    tx_sudo.write({'powertranz_card_last_four': last_four})
                    _logger.info("PowerTranz: Stored last 4 digits '%s' in database for tx %s",
                                last_four, tx_sudo.reference)

                # Store card data in memory instead of database
                card_data_manager.store(tx_sudo.reference, card_data)
                _logger.info("PowerTranz: Card data stored in memory for transaction %s", tx_sudo.reference)
            
            # Only store non-sensitive data in the transaction
            write_vals = {}
            
            # Log recurring and save card flags for debugging
            _logger.info("PowerTranz: Transaction %s - save_card=%s, recurring=%s",
                        tx_sudo.reference,
                        data.get('powertranz_save_card'),
                        data.get('powertranz_recurring'))

            # Add recurring payment data if provided
            if data.get('powertranz_recurring'):
                # Convert to JSON string since we're using a Text field
                recurring_data = data.get('powertranz_recurring')
                write_vals['powertranz_recurring'] = json.dumps(recurring_data)
                _logger.info("PowerTranz: Adding recurring payment data to transaction %s: %s",
                            tx_sudo.reference, recurring_data)
            
            # Store is_subscription_payment flag
            if data.get('is_subscription_payment'):
                tx_sudo = tx_sudo.with_context(is_subscription_payment=True)
            
            # Store tokenization flag but not actual card data
            if card_data.get('save_card'):
                write_vals['tokenize'] = True
                _logger.info("PowerTranz: Setting tokenize=True for transaction %s", tx_sudo.reference)

            # Write values to the transaction if needed
            if write_vals:
                _logger.info("PowerTranz: Writing to transaction %s: %s", tx_sudo.reference, write_vals)
                tx_sudo.write(write_vals)
                # Force commit to ensure data is persisted
                self.env.cr.commit() if hasattr(self.env.cr, 'commit') else None
                _logger.info("PowerTranz: Transaction %s tokenize field after write: %s",
                            tx_sudo.reference, tx_sudo.tokenize)
            
            # Get processing values
            processing_values = tx_sudo._get_processing_values()
            _logger.info("PowerTranz: Got processing values for %s: %s", tx_sudo.reference, processing_values)
            
            # Add recurring payment configuration to processing values
            processing_values['allow_tokenization'] = tx_sudo.provider_id.allow_tokenization
            processing_values['powertranz_recurring_type'] = tx_sudo.provider_id.powertranz_recurring_type or 'powertranz'
            processing_values['is_subscription_payment'] = True  # Always show recurring options when tokenization is enabled
            
            # Check if 3DS is enabled
            three_d_secure_enabled = tx_sudo.provider_id.powertranz_3ds_enabled
            _logger.info("PowerTranz: 3DS is %s for transaction %s", 
                        "enabled" if three_d_secure_enabled else "disabled", tx_sudo.reference)
            
            # Send payment request
            _logger.info("PowerTranz: Sending payment request for %s", tx_sudo.reference)
            result = tx_sudo._send_payment_request()
            _logger.info("PowerTranz: Payment request result for %s: %s", tx_sudo.reference, result)
            
            # Handle different result types based on 3DS setting
            if three_d_secure_enabled:
                # For 3DS, we expect a redirect URL
                if result and isinstance(result, dict) and result.get('type') == 'ir.actions.act_url':
                    redirect_url = result.get('url')
                    _logger.info("PowerTranz: 3DS redirect URL for %s: %s", tx_sudo.reference, redirect_url)
                    processing_values['redirect_url'] = redirect_url
                else:
                    _logger.warning("PowerTranz: Expected redirect URL for 3DS transaction %s but got: %s", 
                                   tx_sudo.reference, result)
            else:
                # For non-3DS, the transaction should be processed directly
                _logger.info("PowerTranz: Non-3DS payment for %s, transaction state: %s", 
                            tx_sudo.reference, tx_sudo.state)
                
                # Add status information to processing values
                processing_values['state'] = tx_sudo.state
                processing_values['provider_reference'] = tx_sudo.provider_reference
                
                # Check transaction state and add appropriate result
                if tx_sudo.state == 'done':
                    _logger.info("PowerTranz: Transaction %s completed successfully", tx_sudo.reference)
                    processing_values['result'] = 'success'
                    processing_values['redirect_url'] = '/payment/status'
                elif tx_sudo.state in ('error', 'cancel'):
                    _logger.warning("PowerTranz: Transaction %s failed: %s", tx_sudo.reference, tx_sudo.state_message)
                    processing_values['result'] = 'error'
                    processing_values['error'] = tx_sudo.state_message
                    processing_values['redirect_url'] = '/payment/status?error=' + (tx_sudo.state_message or 'unknown')
                else:
                    _logger.warning("PowerTranz: Unexpected state %s for transaction %s", tx_sudo.state, tx_sudo.reference)
            
            _logger.info("PowerTranz: Returning processing values for %s: %s", tx_sudo.reference, processing_values)
            
            # Clean up card data if transaction is complete/error/cancelled
            if tx_sudo.state in ('done', 'error', 'cancel'):
                card_data_manager.remove(tx_sudo.reference)
                _logger.info("PowerTranz: Removed card data from memory for completed transaction %s", tx_sudo.reference)
            
            return processing_values
        except Exception as e:
            _logger.exception("Error in powertranz_create_transaction: %s", e)
            return {'error': {'message': str(e)}}
            
    def _get_tx_from_json_data(self, **data):
        """Get the transaction based on data from JSON.
        
        :param dict data: The transaction data
        :return: The transaction, as a sudoed recordset
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if the data is invalid
        """
        # Retrieve the reference and provider_id from the data
        reference = data.get('reference')
        provider_id = data.get('provider_id')
        
        if not reference or not provider_id:
            _logger.error("Missing required data to retrieve transaction: reference=%s, provider_id=%s", reference, provider_id)
            raise ValueError('Missing transaction reference or provider ID.')
        
        # Find the transaction
        tx_sudo = request.env['payment.transaction'].sudo().search([('reference', '=', reference)], limit=1)
        if not tx_sudo:
            _logger.error("No transaction found with reference %s", reference)
            raise ValueError('Transaction not found.')
        
        return tx_sudo

    @http.route('/payment/powertranz/return', type='http', auth='public', methods=['GET', 'POST'], csrf=False, website=True)
    def powertranz_return(self, **data):
        """ Process the notification data sent by PowerTranz after a transaction.

        :param dict data: The notification data
        """
        masked_data = mask_sensitive_data(data)
        _logger.info('PowerTranz return callback: %s', pprint.pformat(masked_data))

        # Try to find and process transaction if reference provided
        reference = data.get('orderIdentifier') or data.get('externalIdentifier')
        if reference:
            try:
                tx_sudo = request.env['payment.transaction'].sudo().search([
                    ('reference', '=', reference)
                ], limit=1)
                if tx_sudo and tx_sudo.state == 'done':
                    # Payment successful, clear cart
                    try:
                        if hasattr(request, 'website') and request.website:
                            request.website.sale_reset()
                            _logger.info("Cart cleared after PowerTranz return (tx: %s)", reference)
                    except Exception as cart_error:
                        _logger.warning("Could not clear cart in return: %s", cart_error)
            except Exception as e:
                _logger.warning("Error in return callback: %s", e)

        return request.redirect('/payment/status')
        
    @http.route('/payment/powertranz/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def powertranz_webhook(self, **data):
        """ Process the webhook notification sent by PowerTranz.
        
        :param dict data: The notification data
        """
        # This is a placeholder that will be implemented in a later prompt
        # For now, we just return a success response
        return '' 
        
    @http.route('/payment/powertranz/merchant_response', type='http', auth='public', methods=['POST'], csrf=False, website=True)
    def powertranz_merchant_response(self, **data):
        """Handle 3DS merchant response callback from PowerTranz FPI flow.

        This is the URL that PowerTranz will redirect to after 3DS processing.
        """
        masked_data = mask_sensitive_data(data)
        _logger.info('Received PowerTranz merchant response: %s', pprint.pformat(masked_data))

        # Validate required parameters
        required_params = ['externalIdentifier', 'orderIdentifier']
        missing_params = [param for param in required_params if param not in data]

        if missing_params:
            _logger.error("Missing parameters in merchant response: %s", missing_params)
            return request.redirect('/payment/status?error=invalid_parameters')

        # The transaction reference should be included in the response
        reference = data.get('externalIdentifier') or data.get('orderIdentifier')
        if not reference:
            _logger.error("No transaction reference in PowerTranz merchant response")
            return request.redirect('/payment/status?error=missing_reference')

        try:
            # Find the transaction by reference
            tx_sudo = request.env['payment.transaction'].sudo().search([('reference', '=', reference)], limit=1)
            if not tx_sudo:
                _logger.error("No transaction found for reference %s", reference)
                return request.redirect('/payment/status?error=no_transaction')

            # Process the payment data using Odoo 19 API
            tx_sudo._process('powertranz', data)

            # If payment succeeded, ensure cart is cleared as safety measure
            if tx_sudo.state == 'done':
                try:
                    if hasattr(request, 'website') and request.website:
                        request.website.sale_reset()
                        _logger.info("Cart cleared after successful PowerTranz 3DS payment")
                except Exception as cart_error:
                    _logger.warning("Could not clear cart after payment: %s", cart_error)

            # Redirect to payment status page
            return request.redirect('/payment/status')

        except Exception as e:
            _logger.exception("Error processing PowerTranz merchant response: %s", e)
            return request.redirect('/payment/status?error=processing')
        
    @http.route('/payment/powertranz/complete', type='http', auth='public', website=True, csrf=False)
    def powertranz_complete(self, **post):
        """Handle the 3DS completion step.
        
        This method is called after 3DS authentication, with a SPI token for completing the payment.
        """
        _logger.info("PowerTranz complete payment called with: %s", pprint.pformat(post))
        
        # Get the SPI token from the request
        spi_token = post.get('spi_token')
        if not spi_token:
            _logger.error("No SPI token provided for payment completion")
            return request.redirect('/payment/status?error=missing_token')
            
        # Find the transaction using the SPI token
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('powertranz_spi_token', '=', spi_token)
        ], limit=1)
        
        if not tx_sudo:
            _logger.error("No transaction found with SPI token: %s", spi_token)
            return request.redirect('/payment/status?error=transaction_not_found')
            
        _logger.info("Found transaction %s for SPI token %s", tx_sudo.reference, spi_token)
        
        # Create a simple HTML page with JavaScript to complete the payment
        # This is a common approach for 3DS completion flows
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Completing Payment - PowerTranz</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding-top: 50px; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .logo {{ margin-bottom: 20px; }}
                .status {{ font-size: 18px; margin: 20px 0; }}
                .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 30px; height: 30px; animation: spin 2s linear infinite; margin: 20px auto; }}
                @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="logo">
                    <img src="/payment_powertranz/static/src/img/powertranz_logo.png" alt="PowerTranz" height="40">
                </div>
                <h2>Completing Your Payment</h2>
                <div class="spinner"></div>
                <div class="status" id="status">Finalizing payment, please wait...</div>
            </div>
            
            <script>
                document.addEventListener('DOMContentLoaded', function() {{
                    const statusElement = document.getElementById('status');
                    const spiToken = '{spi_token}';
                    
                    statusElement.textContent = 'Sending payment request...';
                    
                    // Send the payment completion request to our server-side proxy
                    fetch('/payment/powertranz/proxy_payment', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }},
                        body: JSON.stringify({{
                            jsonrpc: "2.0",
                            method: "call",
                            params: {{
                                spi_token: spiToken
                            }}
                        }})
                    }})
                    .then(response => response.json())
                    .then(function(jsonRpcResult) {{
                        console.log('JSONRPC result:', jsonRpcResult);
                        statusElement.textContent = 'Processing payment result...';
                        
                        if (jsonRpcResult.error) {{
                            throw new Error('JSONRPC error: ' + JSON.stringify(jsonRpcResult.error));
                        }}
                        
                        const result = jsonRpcResult.result;
                        console.log('Payment result:', result);
                        
                        if (result.error) {{
                            // Handle error from proxy
                            throw new Error('Payment error: ' + (result.message || result.error));
                        }}
                        
                        // Get the payment response
                        const data = result.data;
                        statusElement.textContent = 'Payment processed, redirecting...';
                        
                        // Redirect back to Odoo with the transaction result
                        window.location.href = '/payment/status?tx_id={tx_sudo.id}&result=' + 
                            (data.Approved ? 'success' : 'error') + 
                            '&message=' + encodeURIComponent(data.ResponseMessage || '');
                    }})
                    .catch(function(error) {{
                        console.error('Error:', error);
                        statusElement.textContent = 'Error: ' + error.toString();
                        
                        // Log the error to the server
                        fetch('/payment/powertranz/log_error', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest'
                            }},
                            body: JSON.stringify({{
                                jsonrpc: "2.0",
                                method: "call",
                                params: {{
                                    error: error.toString(),
                                    tx_id: '{tx_sudo.id}',
                                    spi_token: spiToken
                                }}
                            }})
                        }});
                        
                        setTimeout(function() {{
                            window.location.href = '/payment/status?error=processing&message=' + encodeURIComponent(error.toString());
                        }}, 2000);
                    }});
                }});
            </script>
        </body>
        </html>
        """
        
        return html
        
    @http.route('/payment/powertranz/proxy_payment', type='jsonrpc', auth='public', csrf=False)
    def powertranz_proxy_payment(self, **data):
        """Server-side proxy to send payment request to PowerTranz.
        
        This endpoint handles the final step of 3DS payment processing.
        """
        import requests

        masked_data = mask_sensitive_data(data)
        _logger.info("PowerTranz proxy payment called with: %s", pprint.pformat(masked_data))
        
        spi_token = data.get('spi_token')
        if not spi_token:
            _logger.error("No SPI token provided for proxy payment")
            return {'error': 'missing_token'}
        
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('powertranz_spi_token', '=', spi_token)
        ], limit=1)
        
        if not tx_sudo:
            _logger.error("No transaction found for SPI token: %s", spi_token)
            return {'error': 'transaction_not_found'}
            
        try:
            provider_sudo = tx_sudo.provider_id
            base_api_url = provider_sudo.powertranz_api_url.rstrip('/')  # Remove trailing slash
            payment_url = f"{base_api_url}/Payment"
            
            # Get credentials from provider
            powertranz_id = provider_sudo.powertranz_id
            powertranz_password = provider_sudo.powertranz_password
            
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "PowerTranz-PowerTranzId": powertranz_id,
                "PowerTranz-PowerTranzPassword": powertranz_password  # Revert to original header name
            }
            
            _logger.info("Sending payment completion request to %s for transaction %s", 
                         payment_url, tx_sudo.reference)
            
            # Send the raw SPI token as the payload
            response = requests.post(
                payment_url,
                headers=headers,
                json=spi_token,
                timeout=30
            )
            
            _logger.info("Response for tx %s: status=%s, body=%s", 
                         tx_sudo.reference, response.status_code, response.text)
            
            if response.status_code < 400 and response.text:
                try:
                    payment_response = response.json()
                    
                    # Process the payment data using Odoo 19 API
                    tx_sudo._process('powertranz', payment_response)
                    
                    return {
                        'success': True,
                        'data': payment_response
                    }
                except Exception as e:
                    _logger.exception("Error processing payment response for tx %s: %s", 
                                      tx_sudo.reference, e)
                    return {
                        'error': 'processing_error',
                        'message': str(e)
                    }
            else:
                error_message = response.text or f"HTTP {response.status_code} with no body"
                _logger.error("Payment failed for tx %s: %s", tx_sudo.reference, error_message)
                return {
                    'error': 'api_error',
                    'status_code': response.status_code,
                    'message': error_message
                }
        except Exception as e:
            _logger.exception("Error in proxy payment for tx %s: %s", tx_sudo.reference, e)
            return {
                'error': 'exception',
                'message': str(e)
            }
            
    @http.route('/payment/powertranz/log_error', type='jsonrpc', auth='public', csrf=False)
    def powertranz_log_error(self, **data):
        """Log errors from the frontend payment completion."""
        masked_data = mask_sensitive_data(data)
        _logger.error("PowerTranz payment error: %s", pprint.pformat(masked_data))
        return {'status': 'ok'} 