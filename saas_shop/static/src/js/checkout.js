/** @odoo-module **/

import { rpc } from '@web/core/network/rpc';

/**
 * SaaS Shop Checkout JavaScript
 *
 * Handles subdomain validation and form submission.
 */

let subdomainValid = false;
let checkTimeout = null;
let isSubmitting = false;  // Prevent double-submit

function initConfigureForm() {
    const configForm = document.getElementById('saas_configure_form');
    if (!configForm) return;

    const subdomainInput = document.getElementById('subdomain');
    const feedback = document.getElementById('subdomain_feedback');
    const submitBtn = document.getElementById('btn_add_to_cart');

    if (!subdomainInput || !feedback || !submitBtn) {
        console.error('SaaS Configure: Missing form elements');
        return;
    }

    console.log('SaaS Configure: Form initialized');

    // Debounced subdomain check
    async function checkSubdomain(subdomain) {
        if (!subdomain || subdomain.length < 3) {
            feedback.innerHTML = '<span class="text-muted">Enter at least 3 characters</span>';
            feedback.className = 'form-text';
            subdomainValid = false;
            submitBtn.disabled = true;
            return;
        }

        feedback.innerHTML = '<span class="text-muted"><i class="fa fa-spinner fa-spin me-1"></i> Checking availability...</span>';

        try {
            const result = await rpc('/saas/check_subdomain', {
                subdomain: subdomain
            });

            if (result.available) {
                feedback.innerHTML = '<span class="text-success"><i class="fa fa-check me-1"></i> ' + result.message + '</span>';
                feedback.className = 'form-text text-success';
                subdomainValid = true;
                submitBtn.disabled = false;
            } else {
                feedback.innerHTML = '<span class="text-danger"><i class="fa fa-times me-1"></i> ' + result.message + '</span>';
                feedback.className = 'form-text text-danger';
                subdomainValid = false;
                submitBtn.disabled = true;
            }
        } catch (error) {
            console.error('Subdomain check error:', error);
            feedback.innerHTML = '<span class="text-danger">Error checking availability</span>';
            feedback.className = 'form-text text-danger';
            subdomainValid = false;
            submitBtn.disabled = true;
        }
    }

    // Normalize subdomain input (lowercase, no spaces, alphanumeric and hyphens only)
    subdomainInput.addEventListener('input', function(e) {
        let value = e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '');
        // Remove leading/trailing hyphens
        value = value.replace(/^-+|-+$/g, '');
        e.target.value = value;

        // Clear previous timeout
        if (checkTimeout) {
            clearTimeout(checkTimeout);
        }

        // Debounce the check
        checkTimeout = setTimeout(() => {
            checkSubdomain(value);
        }, 500);
    });

    // Form submission
    configForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        e.stopPropagation();

        // Prevent double-submit
        if (isSubmitting) {
            console.log('SaaS Configure: Ignoring duplicate submit');
            return false;
        }

        if (!subdomainValid) {
            return false;
        }

        // Lock submission immediately
        isSubmitting = true;
        submitBtn.disabled = true;
        const originalText = submitBtn.innerHTML;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin me-2"></i> Processing...';

        const formData = new FormData(configForm);
        const billingCycle = formData.get('billing_cycle') || 'monthly';

        try {
            const result = await rpc('/shop/saas/add_to_cart', {
                product_id: parseInt(formData.get('product_id')),
                subdomain: formData.get('subdomain'),
                odoo_version: formData.get('odoo_version'),
                billing_cycle: billingCycle
            });

            if (result.success) {
                // Keep isSubmitting true - we're navigating away
                window.location.href = result.redirect || '/shop/cart';
            } else {
                alert(result.message || 'An error occurred');
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
                isSubmitting = false;  // Allow retry
            }
        } catch (error) {
            console.error('Add to cart error:', error);
            alert('An error occurred. Please try again.');
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
            isSubmitting = false;  // Allow retry
        }

        return false;
    });

    // If subdomain already has a value (e.g., from browser autofill), validate it
    if (subdomainInput.value) {
        checkSubdomain(subdomainInput.value);
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initConfigureForm);
} else {
    // DOM already loaded, initialize immediately
    initConfigureForm();
}

// Also try to initialize after a short delay (backup for module loading timing)
setTimeout(initConfigureForm, 500);
