/** @odoo-module **/

import { registry } from '@web/core/registry';
import { rpc } from '@web/core/network/rpc';

/**
 * SaaS Shop - Override WebsiteSale to intercept Add to Cart for SaaS products
 */

// Store SaaS product IDs globally
let saasProductIds = null;
let saasProductMap = {};

async function loadSaasProducts() {
    if (saasProductIds !== null) return;
    try {
        const result = await rpc('/saas/get_product_ids', {});
        saasProductIds = result.product_ids || [];
        saasProductMap = result.product_map || {};
    } catch (error) {
        console.error('Failed to load SaaS products:', error);
        saasProductIds = [];
    }
}

// Load SaaS products on page load
loadSaasProducts();

/**
 * Patch the WebsiteSale interaction to intercept SaaS product add-to-cart
 */
const originalInteractions = registry.category('public.interactions');

// Wait for the registry to be populated, then patch
const patchWebsiteSale = () => {
    const entries = originalInteractions.getEntries();
    const websiteSaleEntry = entries.find(([key]) => key === 'website_sale.website_sale');

    if (!websiteSaleEntry) {
        // Retry after a short delay if not found yet
        setTimeout(patchWebsiteSale, 100);
        return;
    }

    const [key, WebsiteSale] = websiteSaleEntry;
    const originalOnClickAdd = WebsiteSale.prototype.onClickAdd;

    WebsiteSale.prototype.onClickAdd = async function(ev) {
        // Make sure SaaS products are loaded
        await loadSaasProducts();

        // Get product template ID from the form
        const form = ev.currentTarget.closest('form') ||
                     ev.currentTarget.closest('.js_product')?.querySelector('form') ||
                     document.querySelector('form[action*="/shop/cart"]');

        let productTemplateId = null;

        if (form) {
            const input = form.querySelector('input[name="product_template_id"]');
            if (input) {
                productTemplateId = parseInt(input.value);
            }
        }

        // Also try to get from URL for product pages
        if (!productTemplateId) {
            const match = window.location.pathname.match(/\/shop\/[^/]+-(\d+)/);
            if (match) {
                productTemplateId = parseInt(match[1]);
            }
        }

        // Check if this is a SaaS product
        if (productTemplateId && saasProductIds.includes(productTemplateId)) {
            ev.preventDefault();
            ev.stopPropagation();
            const configureUrl = saasProductMap[productTemplateId] ||
                                `/shop/saas/configure?product_id=${productTemplateId}`;
            window.location.href = configureUrl;
            return;
        }

        // Not a SaaS product, proceed with original behavior
        return originalOnClickAdd.call(this, ev);
    };

    console.log('SaaS Shop: WebsiteSale patched successfully');
};

// Start patching when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', patchWebsiteSale);
} else {
    patchWebsiteSale();
}

/**
 * Also intercept clicks at document level as a fallback
 * This catches clicks that might bypass the Interaction system
 */
document.addEventListener('click', async function(ev) {
    const target = ev.target;

    // Check if this is an add-to-cart button
    const addButton = target.closest('#add_to_cart, .a-submit, .js_add_cart');
    if (!addButton) return;

    // Make sure SaaS products are loaded
    await loadSaasProducts();
    if (!saasProductIds || saasProductIds.length === 0) return;

    // Find product template ID
    let productTemplateId = null;

    const form = addButton.closest('form');
    if (form) {
        const input = form.querySelector('input[name="product_template_id"]');
        if (input) {
            productTemplateId = parseInt(input.value);
        }
    }

    if (!productTemplateId) {
        const match = window.location.pathname.match(/\/shop\/[^/]+-(\d+)/);
        if (match) {
            productTemplateId = parseInt(match[1]);
        }
    }

    // Check if SaaS product
    if (productTemplateId && saasProductIds.includes(productTemplateId)) {
        ev.preventDefault();
        ev.stopPropagation();
        ev.stopImmediatePropagation();
        const configureUrl = saasProductMap[productTemplateId] ||
                            `/shop/saas/configure?product_id=${productTemplateId}`;
        window.location.href = configureUrl;
        return false;
    }
}, true); // Use capture phase
