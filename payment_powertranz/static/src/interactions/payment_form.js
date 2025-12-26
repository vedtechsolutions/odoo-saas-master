/** @odoo-module **/

import { _t } from '@web/core/l10n/translation';
import { rpc, RPCError } from '@web/core/network/rpc';
import { patch } from '@web/core/utils/patch';

import { PaymentForm } from '@payment/interactions/payment_form';

patch(PaymentForm.prototype, {

    setup() {
        super.setup();
        this.powertranzData = {}; // Store the form data of each instantiated payment method.
    },

    // #=== DOM MANIPULATION ===#

    /**
     * Prepare the inline form of PowerTranz for direct payment.
     *
     * @private
     * @param {number} providerId - The id of the selected payment option's provider.
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The online payment flow of the selected payment option.
     * @return {void}
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'powertranz') {
            await super._prepareInlineForm(...arguments);
            return;
        }

        // Check if the inline form values were already extracted.
        if (flow === 'token') {
            return; // Don't show the form for tokens.
        } else if (this.powertranzData[paymentOptionId]) {
            this._setPaymentFlow('direct'); // Overwrite the flow even if no re-instantiation.
            return; // Don't re-extract the data if already done for this payment method.
        }

        // Overwrite the flow of the selected payment method.
        this._setPaymentFlow('direct');

        // Extract and deserialize the inline form values.
        const radio = document.querySelector('input[name="o_payment_radio"]:checked');
        const inlineForm = this._getInlineForm(radio);
        const powertranzForm = inlineForm?.querySelector('[name="o_powertranz_form"]');

        if (powertranzForm) {
            this.powertranzData[paymentOptionId] = JSON.parse(
                powertranzForm.dataset['powertranzInlineFormValues'] || '{}'
            );
            this.powertranzData[paymentOptionId].form = powertranzForm;
        } else {
            this.powertranzData[paymentOptionId] = { form: inlineForm };
        }

        // Initialize card formatting
        this._powertranzInitCardFormatting(paymentOptionId);
    },

    // #=== PAYMENT FLOW ===#

    /**
     * Validate the inline form inputs before initiating the payment flow.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The payment flow of the selected payment option.
     * @return {void}
     */
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'powertranz' || flow === 'token') {
            // Tokens are handled by the generic flow
            await super._initiatePaymentFlow(...arguments);
            return;
        }

        const inputs = this._powertranzGetInlineFormInputs(paymentOptionId);
        if (!inputs) {
            this._displayErrorDialog(_t("Payment Error"), _t("Card form not found."));
            this._enableButton();
            return;
        }

        // Validate required inputs (exclude form element and null values)
        const requiredInputs = [inputs.card, inputs.holder, inputs.expiry, inputs.cvc].filter(el => el !== null);
        if (!requiredInputs.every(element => element && typeof element.reportValidity === 'function' && element.reportValidity())) {
            this._enableButton(); // The submit button is disabled at this point, enable it
            return;
        }

        // Validate card number with Luhn algorithm
        const cardNumber = inputs.card?.value?.replace(/\s/g, '') || '';
        if (!this._powertranzValidateLuhn(cardNumber)) {
            inputs.card?.classList.add('is-invalid');
            this._displayErrorDialog(_t("Card Validation Error"), _t("Please enter a valid card number."));
            this._enableButton();
            return;
        }

        await super._initiatePaymentFlow(...arguments);
    },

    /**
     * Process the direct payment flow for PowerTranz.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'powertranz') {
            await super._processDirectFlow(...arguments);
            return;
        }

        // Get card data from inline form
        const inputs = this._powertranzGetInlineFormInputs(paymentOptionId);
        if (!inputs) {
            this._displayErrorDialog(_t("Payment Error"), _t("Card form not found."));
            this._enableButton();
            return;
        }

        // Parse expiry date (MM / YY format)
        const expiryParts = (inputs.expiry?.value || '').split('/');
        const expiryMonth = expiryParts[0]?.trim() || '';
        const expiryYear = expiryParts[1]?.trim() || '';

        // Get provider ID from stored data or processingValues
        const providerId = this.powertranzData[paymentOptionId]?.providerId || processingValues.provider_id;

        // Check if recurring is enabled - if so, we MUST save the card
        const setupRecurring = inputs.setupRecurring?.checked || false;
        const saveCard = inputs.saveCard?.checked || setupRecurring; // Auto-enable save if recurring is checked

        console.log('PowerTranz: Form submission - saveCard:', saveCard, 'setupRecurring:', setupRecurring);

        // Prepare payment data (using powertranz_ prefix to match controller expectations)
        const paymentData = {
            reference: processingValues.reference,
            partner_id: processingValues.partner_id,
            provider_id: providerId,
            access_token: processingValues.access_token,
            powertranz_card_number: (inputs.card?.value || '').replace(/\s/g, ''),
            powertranz_card_holder: inputs.holder?.value || '',
            powertranz_card_expiry_month: expiryMonth,
            powertranz_card_expiry_year: expiryYear.length === 2 ? '20' + expiryYear : expiryYear,
            powertranz_card_cvc: inputs.cvc?.value || '',
            powertranz_save_card: saveCard,
        };

        // Add recurring payment data if enabled
        if (setupRecurring) {
            paymentData.powertranz_recurring = {
                enabled: true,
                frequency: inputs.recurringFreq?.value || 'M',
                start_date: inputs.recurringStart?.value || '',
                end_date: inputs.recurringEnd?.value || '',
            };
            console.log('PowerTranz: Recurring payment data:', paymentData.powertranz_recurring);
        }

        try {
            const result = await this.waitFor(rpc('/payment/powertranz/create_transaction', paymentData));

            if (result.error) {
                this._displayErrorDialog(_t("Payment Error"), result.error);
                this._enableButton();
                return;
            }

            // Handle 3DS redirect if needed
            if (result.redirect_url) {
                window.location.href = result.redirect_url;
            } else {
                // Payment completed, go to status page
                window.location.href = '/payment/status';
            }
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("Payment Error"), error.data?.message || _t("Payment processing failed."));
                this._enableButton();
            } else {
                return Promise.reject(error);
            }
        }
    },

    // #=== HELPERS ===#

    /**
     * Return all relevant inline form inputs for PowerTranz.
     *
     * @private
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @return {Object|null} - An object mapping the name of inline form inputs to their DOM element
     */
    _powertranzGetInlineFormInputs(paymentOptionId) {
        const formData = this.powertranzData[paymentOptionId];
        if (!formData?.form) {
            // Try to find the form globally as a fallback
            const globalForm = document.querySelector('[name="o_powertranz_form"]');
            if (globalForm) {
                return {
                    form: globalForm,
                    card: globalForm.querySelector('#o_powertranz_card') || document.getElementById('o_powertranz_card'),
                    holder: globalForm.querySelector('#o_powertranz_holder') || document.getElementById('o_powertranz_holder'),
                    expiry: globalForm.querySelector('#o_powertranz_expiry') || document.getElementById('o_powertranz_expiry'),
                    cvc: globalForm.querySelector('#o_powertranz_cvc') || document.getElementById('o_powertranz_cvc'),
                    saveCard: globalForm.querySelector('#o_powertranz_save_card') || document.getElementById('o_powertranz_save_card'),
                    setupRecurring: globalForm.querySelector('#o_powertranz_setup_recurring'),
                    recurringFreq: globalForm.querySelector('#o_powertranz_recurring_freq'),
                    recurringStart: globalForm.querySelector('#o_powertranz_recurring_start'),
                    recurringEnd: globalForm.querySelector('#o_powertranz_recurring_end'),
                };
            }
            return null;
        }
        const form = formData.form;
        return {
            form: form,
            card: form.querySelector('#o_powertranz_card') || document.getElementById('o_powertranz_card'),
            holder: form.querySelector('#o_powertranz_holder') || document.getElementById('o_powertranz_holder'),
            expiry: form.querySelector('#o_powertranz_expiry') || document.getElementById('o_powertranz_expiry'),
            cvc: form.querySelector('#o_powertranz_cvc') || document.getElementById('o_powertranz_cvc'),
            saveCard: form.querySelector('#o_powertranz_save_card') || document.getElementById('o_powertranz_save_card'),
            setupRecurring: form.querySelector('#o_powertranz_setup_recurring'),
            recurringFreq: form.querySelector('#o_powertranz_recurring_freq'),
            recurringStart: form.querySelector('#o_powertranz_recurring_start'),
            recurringEnd: form.querySelector('#o_powertranz_recurring_end'),
        };
    },

    /**
     * Initialize card input formatting.
     *
     * @private
     * @param {number} paymentOptionId - The id of the selected payment option.
     */
    _powertranzInitCardFormatting(paymentOptionId) {
        const inputs = this._powertranzGetInlineFormInputs(paymentOptionId);
        if (!inputs) return;

        // Card number formatting (add spaces every 4 digits)
        if (inputs.card) {
            inputs.card.addEventListener('input', (e) => {
                let value = e.target.value.replace(/\D/g, '');
                if (value.length > 16) value = value.slice(0, 16);
                value = value.replace(/(\d{4})(?=\d)/g, '$1 ');
                e.target.value = value;

                // Update validation state
                const cleanValue = value.replace(/\s/g, '');
                if (cleanValue.length === 0) {
                    e.target.classList.remove('is-valid', 'is-invalid');
                } else if (cleanValue.length >= 13 && this._powertranzValidateLuhn(cleanValue)) {
                    e.target.classList.remove('is-invalid');
                    e.target.classList.add('is-valid');
                } else {
                    e.target.classList.remove('is-valid');
                    e.target.classList.add('is-invalid');
                }
            });
        }

        // Expiry date formatting (MM / YY)
        if (inputs.expiry) {
            inputs.expiry.addEventListener('input', (e) => {
                let value = e.target.value.replace(/\D/g, '');
                if (value.length > 4) value = value.slice(0, 4);
                if (value.length > 2) {
                    value = value.slice(0, 2) + ' / ' + value.slice(2);
                }
                e.target.value = value;

                // Validate
                if (value.length >= 7) {
                    const parts = value.split('/');
                    const month = parseInt(parts[0]?.trim() || '0', 10);
                    if (month >= 1 && month <= 12) {
                        e.target.classList.remove('is-invalid');
                        e.target.classList.add('is-valid');
                    } else {
                        e.target.classList.remove('is-valid');
                        e.target.classList.add('is-invalid');
                    }
                } else {
                    e.target.classList.remove('is-valid', 'is-invalid');
                }
            });
        }

        // CVC formatting (3-4 digits only)
        if (inputs.cvc) {
            inputs.cvc.addEventListener('input', (e) => {
                let value = e.target.value.replace(/\D/g, '');
                if (value.length > 4) value = value.slice(0, 4);
                e.target.value = value;

                if (value.length >= 3) {
                    e.target.classList.remove('is-invalid');
                    e.target.classList.add('is-valid');
                } else if (value.length > 0) {
                    e.target.classList.remove('is-valid');
                    e.target.classList.add('is-invalid');
                } else {
                    e.target.classList.remove('is-valid', 'is-invalid');
                }
            });
        }

        // Holder name validation
        if (inputs.holder) {
            inputs.holder.addEventListener('input', (e) => {
                const value = e.target.value.trim();
                if (value.length >= 3) {
                    e.target.classList.remove('is-invalid');
                    e.target.classList.add('is-valid');
                } else if (value.length > 0) {
                    e.target.classList.remove('is-valid');
                    e.target.classList.add('is-invalid');
                } else {
                    e.target.classList.remove('is-valid', 'is-invalid');
                }
            });
        }

        // Recurring payment toggle
        if (inputs.setupRecurring) {
            inputs.setupRecurring.addEventListener('change', (e) => {
                const recurringDetails = document.querySelector('.o_powertranz_recurring_details');
                if (recurringDetails) {
                    recurringDetails.style.display = e.target.checked ? 'block' : 'none';
                }
                // Auto-check save card if recurring is enabled
                if (e.target.checked && inputs.saveCard) {
                    inputs.saveCard.checked = true;
                }
            });
        }

        // Uncheck recurring if save card is unchecked
        if (inputs.saveCard) {
            inputs.saveCard.addEventListener('change', (e) => {
                if (!e.target.checked && inputs.setupRecurring) {
                    inputs.setupRecurring.checked = false;
                    const recurringDetails = document.querySelector('.o_powertranz_recurring_details');
                    if (recurringDetails) {
                        recurringDetails.style.display = 'none';
                    }
                }
            });
        }
    },

    /**
     * Validate a card number using the Luhn algorithm.
     *
     * @private
     * @param {string} cardNumber - The card number to validate.
     * @return {boolean} - True if the card number is valid.
     */
    _powertranzValidateLuhn(cardNumber) {
        // Known test cards bypass Luhn
        const testCards = [
            '4012000000020071',
            '5200000000001005',
            '4012000000020089',
            '4012000000020097'
        ];
        if (testCards.includes(cardNumber)) {
            return true;
        }

        // Check if in test mode
        const isTestMode = document.querySelector('[data-provider-state="test"]') !== null;
        if (isTestMode) {
            return true; // Bypass validation in test mode
        }

        // Luhn algorithm
        let sum = 0;
        let shouldDouble = false;
        for (let i = cardNumber.length - 1; i >= 0; i--) {
            let digit = parseInt(cardNumber.charAt(i), 10);
            if (shouldDouble) {
                digit *= 2;
                if (digit > 9) digit -= 9;
            }
            sum += digit;
            shouldDouble = !shouldDouble;
        }
        return (sum % 10) === 0;
    },

});
