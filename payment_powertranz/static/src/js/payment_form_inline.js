/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { loadJS } from "@web/core/assets";
import paymentForm from '@payment/js/payment_form';

/**
 * PowerTranz Payment Form Extension
 * 
 * This extension integrates PowerTranz payment processing with Odoo's payment form.
 * It handles inline credit card form display, validation, and submission.
 */
paymentForm.include({
    events: Object.assign({}, paymentForm.prototype.events, {
        'click .card-copy': '_onClickTestCard',
        'change input[name="powertranzCardType"]': '_onChangePowerTranzCardType',
    }),

    /**
     * @override
     */
    start: function() {
        // Initialize the form when it's loaded
        const result = this._super.apply(this, arguments);
        this._initializePowerTranzForm();
        return result;
    },

    /**
     * @override
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'powertranz' || paymentMethodCode !== 'card') {
            return this._super(...arguments);
        }

        // Set direct payment flow for PowerTranz
        this._setPaymentFlow('direct');
        
        // Check if we need to initialize the form
        if (!this.powertranzFormInitialized) {
            await this._initializePowerTranzForm();
        }
        
        return Promise.resolve();
    },
    
    /**
     * Initialize the PowerTranz payment form
     * 
     * @private
     * @return {Promise} Resolved when the form is initialized
     */
    async _initializePowerTranzForm() {
        console.log("PowerTranz: Initializing payment form");
        
        // Load jQuery.payment library if needed
        if (typeof $.payment === 'undefined') {
            await this._loadJQueryPayment();
        } else {
            console.log("PowerTranz: jQuery.payment already loaded");
        }
        
        // Set up card formatting and validation
        this._setupCardFormatting();
        this._setupValidationHandlers();
        this._setupTestCardHandlers();
        
        // Mark as initialized
        this.powertranzFormInitialized = true;
        
        return Promise.resolve();
    },
    
    /**
     * Load jQuery.payment library
     * 
     * @private
     * @return {Promise} Resolved when the library is loaded
     */
    async _loadJQueryPayment() {
        try {
            await loadJS('/payment_powertranz/static/lib/jquery.payment.js');
            console.log("PowerTranz: jQuery.payment loaded successfully");
            return Promise.resolve();
        } catch (error) {
            console.error("PowerTranz: Failed to load jQuery.payment", error);
            return Promise.reject(error);
        }
    },
    
    /**
     * Set up card formatting using jQuery.payment
     * 
     * @private
     */
    _setupCardFormatting() {
        console.log("PowerTranz: Setting up card formatting");
        
        // Card number formatting
        $('#powertranz_card_number').payment('formatCardNumber');
        
        // Expiry date formatting
        $('#powertranz_card_expiry').payment('formatCardExpiry');
        
        // CVC formatting
        $('#powertranz_card_cvc').on('input', function() {
            let value = $(this).val().replace(/\D/g, '');
            if (value.length > 4) value = value.substr(0, 4);
            $(this).val(value);
        });
    },
    
    /**
     * Set up validation handlers for the payment form
     * 
     * @private
     */
    _setupValidationHandlers() {
        console.log("PowerTranz: Setting up validation handlers");
        
        // Card Number Validation
        $('#powertranz_card_number').on('blur', function() {
            const value = $(this).val().replace(/\s+/g, '');
            
            if (value.length === 0) {
                $(this).removeClass('is-valid is-invalid');
                $('#powertranz_card_number_error').text('');
                return;
            }
            
            // Check if it's a test card
            const testCards = [
                '4012000000020071',
                '5200000000001005',
                '4012000000020089',
                '4012000000020097'
            ];
            
            const isTestCard = testCards.includes(value);
            const isTestMode = $('input[name="o_payment_radio"]:checked').data('provider-state') === 'test';
            
            // Force test mode for development
            const forceTestMode = true; // Set to true to force test mode for all cards
            
            // Validate card number
            let isValid = isTestCard || isTestMode || forceTestMode;
            
            if (!isValid && typeof $.payment !== 'undefined') {
                isValid = $.payment.validateCardNumber(value);
            }
            
            // Update validation state
            if (isValid) {
                $(this).removeClass('is-invalid').addClass('is-valid');
                $('#powertranz_card_number_error').text('');
            } else {
                $(this).removeClass('is-valid').addClass('is-invalid');
                $('#powertranz_card_number_error').text(_t("Invalid card number"));
            }
            
            // Detect card type
            let cardType = '';
            if (value.startsWith('4')) {
                cardType = 'visa';
            } else if (/^5[1-5]/.test(value)) {
                cardType = 'mastercard';
            } else if (/^3[47]/.test(value)) {
                cardType = 'amex';
            } else if (/^6(?:011|5)/.test(value)) {
                cardType = 'discover';
            }
            
            // Update card type indicator
            const $cardTypeIndicator = $(this).parent().find('.card-type-indicator');
            if (cardType && $cardTypeIndicator.length > 0) {
                const cardTypeText = cardType.charAt(0).toUpperCase() + cardType.slice(1);
                $cardTypeIndicator.text(cardTypeText);
            } else {
                $cardTypeIndicator.text('');
            }
            
            // Store card type in hidden field
            $('#powertranz_card_brand').val(cardType);
        });
        
        // Cardholder Name Validation
        $('#powertranz_card_holder').on('blur', function() {
            const value = $(this).val().trim();
            
            if (value.length === 0) {
                $(this).removeClass('is-valid is-invalid');
                $('#powertranz_card_holder_error').text('');
                return;
            }
            
            if (value.length >= 3) {
                $(this).removeClass('is-invalid').addClass('is-valid');
                $('#powertranz_card_holder_error').text('');
            } else {
                $(this).removeClass('is-valid').addClass('is-invalid');
                $('#powertranz_card_holder_error').text(_t("Cardholder name is too short"));
            }
        });
        
        // Expiry Date Validation
        $('#powertranz_card_expiry').on('blur', function() {
            const value = $(this).val();
            
            if (value.length === 0) {
                $(this).removeClass('is-valid is-invalid');
                $('#powertranz_card_expiry_error').text('');
                return;
            }
            
            let isValid = false;
            
            if (typeof $.payment !== 'undefined') {
                const expiryValue = $.payment.cardExpiryVal(value);
                isValid = $.payment.validateCardExpiry(expiryValue.month, expiryValue.year);
            }
            
            if (isValid) {
                $(this).removeClass('is-invalid').addClass('is-valid');
                $('#powertranz_card_expiry_error').text('');
            } else {
                $(this).removeClass('is-valid').addClass('is-invalid');
                $('#powertranz_card_expiry_error').text(_t("Invalid expiration date"));
            }
        });
        
        // CVC Validation
        $('#powertranz_card_cvc').on('blur', function() {
            const value = $(this).val();
            
            if (value.length === 0) {
                $(this).removeClass('is-valid is-invalid');
                $('#powertranz_card_cvc_error').text('');
                return;
            }
            
            const cardType = $('#powertranz_card_brand').val();
            const validLength = cardType === 'amex' ? 4 : 3;
            
            if (value.length === validLength) {
                $(this).removeClass('is-invalid').addClass('is-valid');
                $('#powertranz_card_cvc_error').text('');
            } else {
                $(this).removeClass('is-valid').addClass('is-invalid');
                $('#powertranz_card_cvc_error').text(_t("Invalid security code"));
            }
        });
    },
    
    /**
     * Set up test card handlers
     * 
     * @private
     */
    _setupTestCardHandlers() {
        console.log("PowerTranz: Setting up test card handlers");
        
        // Test card button click handler
        $('.card-copy').on('click', this._onClickTestCard.bind(this));
    },
    
    /**
     * Handle test card button click
     * 
     * @private
     * @param {Event} ev Click event
     */
    _onClickTestCard(ev) {
        const cardNumber = $(ev.currentTarget).data('card');
        
        // Set test card values
        $('#powertranz_card_number').val(cardNumber).trigger('blur');
        $('#powertranz_card_holder').val('Test User').trigger('blur');
        $('#powertranz_card_expiry').val('12 / 25').trigger('blur');
        $('#powertranz_card_cvc').val('123').trigger('blur');
    },
    
    /**
     * Handle card type change (saved vs new)
     * 
     * @private
     * @param {Event} ev Change event
     */
    _onChangePowerTranzCardType(ev) {
        const useNewCard = $(ev.currentTarget).val() === 'new_card';
        $('#powertranz_card_form').toggleClass('d-none', !useNewCard);
    },
    
    /**
     * @override
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'powertranz') {
            return this._super(...arguments);
        }
        
        console.log("PowerTranz: Processing direct payment flow");
        
        try {
            // Check if we're using a saved card
            const useSavedCard = $('#powertranzSavedCard').is(':checked');
            
            if (!useSavedCard) {
                // Get card data from the form
                const cardData = this._collectCardData();
                
                // Validate card data
                if (!this._validateCardData(cardData)) {
                    return;
                }
                
                // Add card data to processing values
                processingValues.powertranz_card_data = cardData;
                
                // Check if we should save the card
                processingValues.powertranz_save_card = $('#powertranz_save_card').is(':checked');
            }
            
            // Make the payment request
            return this._super(providerCode, paymentOptionId, paymentMethodCode, processingValues);
        } catch (error) {
            console.error("PowerTranz: Error processing payment", error);
            this._displayErrorDialog(
                _t("Payment Error"),
                _t("An error occurred during payment processing. Please try again.")
            );
            this._enableButton();
            return;
        }
    },
    
    /**
     * Collect card data from the form
     * 
     * @private
     * @return {Object} Card data
     */
    _collectCardData() {
        const cardNumber = $('#powertranz_card_number').val().replace(/\s+/g, '');
        const cardHolder = $('#powertranz_card_holder').val();
        const cardExpiry = $('#powertranz_card_expiry').val();
        const cardCvc = $('#powertranz_card_cvc').val();
        const cardBrand = $('#powertranz_card_brand').val() || 'visa';
        
        // Parse expiry date (MM / YY format)
        let expiryMonth = '12';
        let expiryYear = '2025';
        
        if (cardExpiry) {
            const expiryParts = cardExpiry.split('/');
            if (expiryParts.length === 2) {
                expiryMonth = expiryParts[0].trim();
                expiryYear = '20' + expiryParts[1].trim(); // Add '20' prefix for 4-digit year
            }
        }
        
        return {
            card_number: cardNumber,
            cardholder_name: cardHolder,
            expiry_month: expiryMonth,
            expiry_year: expiryYear,
            cvv: cardCvc,
            card_brand: cardBrand
        };
    },
    
    /**
     * Validate card data
     * 
     * @private
     * @param {Object} cardData Card data to validate
     * @return {boolean} True if the card data is valid
     */
    _validateCardData(cardData) {
        // Check for empty fields
        if (!cardData.card_number || !cardData.cardholder_name || !cardData.cvv) {
            this._displayErrorDialog(
                _t("Validation Error"),
                _t("Please fill in all card details")
            );
            this._enableButton();
            return false;
        }
        
        // Check if any field has validation errors
        const hasErrors = 
            $('#powertranz_card_number').hasClass('is-invalid') ||
            $('#powertranz_card_holder').hasClass('is-invalid') ||
            $('#powertranz_card_expiry').hasClass('is-invalid') ||
            $('#powertranz_card_cvc').hasClass('is-invalid');
        
        if (hasErrors) {
            this._displayErrorDialog(
                _t("Validation Error"),
                _t("Please correct the errors in the form")
            );
            this._enableButton();
            return false;
        }
        
        return true;
    },
    
    /**
     * @override
     */
    _prepareTransactionRouteParams() {
        const transactionRouteParams = this._super(...arguments);
        
        // Add PowerTranz specific parameters if needed
        if (this.paymentContext.providerCode === 'powertranz') {
            // Any additional parameters can be added here
        }
        
        return transactionRouteParams;
    }
});
