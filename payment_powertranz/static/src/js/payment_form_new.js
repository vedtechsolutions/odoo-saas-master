/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { Component, onWillStart, useState } from "@odoo/owl";
import paymentForm from '@payment/js/payment_form';

/**
 * PowerTranz Payment Form Component
 * 
 * A clean implementation using OWL for the PowerTranz payment form
 * with proper test card handling and validation.
 */
export class PowerTranzPaymentForm extends Component {
    /**
     * @override
     */
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        
        // Get today's date for default recurring start date
        const today = new Date();
        const formattedDate = today.toISOString().split('T')[0];
        
        // Use useState for reactive state management
        this.state = useState({
            cardNumber: "",
            cardHolderName: "",
            expiryMonth: "",
            expiryYear: "",
            cardCvc: "",
            isLoading: false,
            errorMessage: "",
            saveToken: false,
            
            // Recurring payment fields
            setupPtRecurring: false,
            ptRecurringFrequency: "M", // Monthly by default
            ptRecurringStartDate: formattedDate,
            ptRecurringEndDate: "",
        });
        
        // Detect test mode
        this.isTestMode = this._detectTestMode();
        console.log("PowerTranz: Component initialized, test mode:", this.isTestMode);
        
        // Initialize component when it starts
        onWillStart(() => {
            console.log("PowerTranz: Component starting with props:", this.props);
            return Promise.resolve();
        });
    }
    
    /**
     * Detect if the payment provider is in test mode
     * 
     * @private
     * @return {boolean} True if in test mode
     */
    _detectTestMode() {
        // Check multiple sources to determine test mode
        return this.props.processingValues?.is_test_mode === true || 
               this.props.processingValues?.state === 'test' ||
               window.location.href.indexOf('test_mode=1') !== -1 ||
               document.querySelector('[data-provider-state="test"]') !== null;
    }
    
    /**
     * Process the payment through PowerTranz
     * 
     * @param {Event} ev Submit event
     */
    async processPayment(ev) {
        if (this.state.isLoading) {
            return;
        }
        
        // Validate form fields
        if (!this._validateForm()) {
            return;
        }
        
        this.state.isLoading = true;
        this.state.errorMessage = "";
        
        try {
            // Format card data for submission
            const cardData = this._prepareCardData();
            
            // Process payment with the PowerTranz API
            const processingValues = await this.rpc('/payment/powertranz/process_payment', {
                'provider_id': this.props.providerId,
                'reference': this.props.reference,
                'partner_id': this.props.partnerId,
                'token_id': this.props.tokenId || false,
                'card_data': cardData,
                'should_tokenize': this.state.saveToken,
                'recurring_payment': this._getRecurringPaymentData(),
            });
            
            // Process payment result
            if (processingValues.success) {
                // Payment success, redirect to the landing page if necessary
                if (processingValues.redirect_url) {
                    window.location = processingValues.redirect_url;
                } else {
                    // Payment completed successfully
                    if (this.props.onPaymentProcessed) {
                        this.props.onPaymentProcessed(processingValues.transaction_id);
                    } else {
                        // Fallback if callback is not available
                        window.location = '/payment/status';
                    }
                }
            } else {
                // Display error message
                this.state.errorMessage = processingValues.error || _t("Payment failed. Please try again.");
                this.state.isLoading = false;
                this.notification.add(this.state.errorMessage, {
                    type: 'danger',
                });
            }
        } catch (error) {
            this.state.errorMessage = _t("Payment processing error. Please try again later.");
            this.state.isLoading = false;
            this.notification.add(error.toString(), {
                title: _t("Payment Error"),
                type: 'danger',
            });
            console.error("PowerTranz payment error:", error);
        }
    }
    
    /**
     * Prepare card data for submission
     * 
     * @private
     * @return {Object} Card data object
     */
    _prepareCardData() {
        return {
            'card_number': this.state.cardNumber.replace(/\s/g, ''),
            'cardholder_name': this.state.cardHolderName,
            'expiry_month': this.state.expiryMonth,
            'expiry_year': '20' + this.state.expiryYear, // Add '20' prefix for 4-digit year
            'cvv': this.state.cardCvc,
        };
    }
    
    /**
     * Get recurring payment data if enabled
     * 
     * @private
     * @return {Object|false} Recurring payment data or false if not enabled
     */
    _getRecurringPaymentData() {
        if (this.state.setupPtRecurring && this.state.saveToken) {
            return {
                'enabled': true,
                'frequency': this.state.ptRecurringFrequency,
                'start_date': this.state.ptRecurringStartDate,
                'end_date': this.state.ptRecurringEndDate || null,
            };
        }
        return false;
    }
    
    /**
     * Validate form fields
     * 
     * @private
     * @return {boolean} True if the form is valid
     */
    _validateForm() {
        // Reset error message
        this.state.errorMessage = "";
        
        // Get clean card number
        const cardNumber = this.state.cardNumber.replace(/\s/g, '');
        
        // Validate card number
        if (!cardNumber) {
            this.state.errorMessage = _t("Please enter a card number");
            return false;
        }
        
        // Skip Luhn validation for test cards or in test mode
        if (!this.isTestMode && !this._isTestCard(cardNumber) && !this._validateLuhn(cardNumber)) {
            this.state.errorMessage = _t("The card number is invalid. Please check and try again.");
            return false;
        }
        
        // Validate cardholder name
        if (!this.state.cardHolderName || this.state.cardHolderName.trim().length < 3) {
            this.state.errorMessage = _t("Please enter a valid cardholder name");
            return false;
        }
        
        // Validate expiry date
        if (!this.state.expiryMonth || !this.state.expiryYear) {
            this.state.errorMessage = _t("Please enter a valid expiration date");
            return false;
        }
        
        const month = parseInt(this.state.expiryMonth, 10);
        const year = parseInt('20' + this.state.expiryYear, 10);
        
        if (month < 1 || month > 12) {
            this.state.errorMessage = _t("Please enter a valid month (1-12)");
            return false;
        }
        
        // Check if card is expired
        const now = new Date();
        const currentYear = now.getFullYear();
        const currentMonth = now.getMonth() + 1; // JS months are 0-indexed
        
        if (year < currentYear || (year === currentYear && month < currentMonth)) {
            this.state.errorMessage = _t("The card has expired");
            return false;
        }
        
        // Validate CVC
        if (!this.state.cardCvc) {
            this.state.errorMessage = _t("Please enter the card security code");
            return false;
        }
        
        // CVC should be 3-4 digits
        if (!/^\d{3,4}$/.test(this.state.cardCvc)) {
            this.state.errorMessage = _t("Security code should be 3 or 4 digits");
            return false;
        }
        
        // For recurring payments, validate that save card is checked
        if (this.state.setupPtRecurring && !this.state.saveToken) {
            this.state.errorMessage = _t("You must save your card to enable recurring payments");
            return false;
        }
        
        return true;
    }
    
    /**
     * Check if a card number is a known test card
     * 
     * @private
     * @param {string} cardNumber - The card number to check
     * @return {boolean} True if it's a test card
     */
    _isTestCard(cardNumber) {
        const testCards = [
            '4012000000020071',
            '5200000000001005',
            '4012000000020089',
            '4012000000020097'
        ];
        
        return testCards.includes(cardNumber);
    }
    
    /**
     * Validate a card number using the Luhn algorithm
     * 
     * @private
     * @param {string} cardNumber - The card number to validate
     * @return {boolean} True if the card number passes the Luhn check
     */
    _validateLuhn(cardNumber) {
        // Implement Luhn algorithm
        let sum = 0;
        let shouldDouble = false;
        
        // Loop through values starting from the rightmost digit
        for (let i = cardNumber.length - 1; i >= 0; i--) {
            let digit = parseInt(cardNumber.charAt(i));
            
            if (shouldDouble) {
                digit *= 2;
                if (digit > 9) {
                    digit -= 9;
                }
            }
            
            sum += digit;
            shouldDouble = !shouldDouble;
        }
        
        return (sum % 10) === 0;
    }
    
    /**
     * Format card number with spaces
     * 
     * @param {Event} ev Input event
     */
    onCardNumberInput(ev) {
        // Format card number with spaces every 4 digits
        let value = ev.target.value.replace(/\D/g, '');
        if (value.length > 16) {
            value = value.slice(0, 16);
        }
        
        // Add spaces every 4 digits
        value = value.replace(/(\d{4})(?=\d)/g, '$1 ');
        this.state.cardNumber = value;
    }
}

// Define static properties for the component
PowerTranzPaymentForm.template = "payment_powertranz.PowerTranzPaymentForm";
PowerTranzPaymentForm.props = {
    providerId: { type: Number, optional: true },
    reference: { type: String, optional: true },
    partnerId: { type: Number, optional: true },
    tokenId: { type: Number, optional: true },
    processingValues: { type: Object, optional: true },
    onPaymentProcessed: { type: Function, optional: true },
};

// Register the component in the payment form registry
registry.category("payment_form_components").add("powertranz", PowerTranzPaymentForm);

// PowerTranz payment form integration with Odoo's payment form
paymentForm.include({
    /**
     * @override
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        console.log("PowerTranz: _prepareInlineForm called with", providerCode, "provider ID:", providerId);
        
        if (providerCode !== 'powertranz') {
            return this._super(...arguments);
        } else if (flow === 'token') {
            return Promise.resolve();
        }
        
        // Set direct payment flow for PowerTranz
        this._setPaymentFlow('direct');
        
        // Make sure the processing values are properly initialized
        if (this.processingValues) {
            // Check if we're in test mode
            const isTestMode = this.processingValues.state === 'test' || 
                              window.location.href.indexOf('test_mode=1') !== -1;
            
            // Add test mode flag to processing values
            this.processingValues.is_test_mode = isTestMode;
            
            // Make sure recurring payment options are properly initialized
            this.processingValues.powertranz_recurring_type = this.processingValues.powertranz_recurring_type || 'powertranz';
            
            console.log("PowerTranz: Provider test mode:", isTestMode);
        }
        
        // Find the payment form container
        const $paymentForm = $('form.o_payment_form, .oe_website_sale_payment, #payment_method').first();
        
        if ($paymentForm.length) {
            console.log("PowerTranz: Found payment form container");
            
            // Create a container for the OWL component
            const $container = $('<div>').addClass('powertranz-card-form mt-4 p-3 border rounded');
            $paymentForm.append($container);
            
            // The OWL component will be mounted by Odoo's payment form handler
        } else {
            console.log("PowerTranz: Could not find payment form container");
        }
        
        return Promise.resolve();
    },
    
    /**
     * @override
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'powertranz') {
            return this._super(...arguments);
        }
        
        console.log("PowerTranz: Processing direct payment flow");
        
        // The actual processing will be handled by the OWL component
        // This method is just a placeholder to ensure compatibility with Odoo's payment flow
        
        return processingValues;
    }
});
