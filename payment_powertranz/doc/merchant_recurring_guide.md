# PowerTranz Merchant-Managed Recurring Payments Guide

This guide explains how to use the merchant-managed recurring payments feature in the PowerTranz payment module for Odoo 18.

## Overview

Merchant-managed recurring payments allow you to:

1. Process recurring payments on a schedule defined by your Odoo system
2. Maintain full control over when payments are processed
3. Implement custom business logic for payment retries, pausing, and resuming
4. Provide customers with a portal to manage their recurring payments

## How It Works

1. **Initial Payment**: Customer makes a payment and opts to save their card for recurring payments
2. **Token Creation**: The system creates a payment token from the card details
3. **Recurring Setup**: A recurring payment record is created with the specified frequency
4. **Scheduled Processing**: Odoo's cron job processes due payments automatically
5. **Retry Mechanism**: Failed payments are retried based on your configuration

## Configuration

### Provider Settings

1. Go to **Invoicing → Configuration → Payment Providers**
2. Select the **PowerTranz** provider
3. Configure your PowerTranz credentials:
   - Merchant ID
   - Merchant Password
   - API Key
   - API URL

### Recurring Payment Settings

The recurring payment system has several configurable parameters:

- **Max Retry Count**: Number of times to retry failed payments (default: 3)
- **Days Between Retries**: Number of days to wait before retrying (default: 3)
- **Cron Job Frequency**: How often to check for due payments (default: daily)

## Customer Experience

### Checkout Process

1. Customer enters their card details on the checkout page
2. They select the "Save card for future payments" option
3. They can optionally enable recurring payments by checking "Set up recurring payments"
4. They select a frequency (Monthly, Weekly, etc.) and start date

### Customer Portal

Customers can manage their recurring payments through the portal:

1. View all active and paused recurring payments
2. See payment history for each recurring payment
3. Pause, resume, or cancel recurring payments
4. Update payment methods for recurring payments

## Backend Management

### Viewing Recurring Payments

1. Go to **Invoicing → Customers → Recurring Payments**
2. View all recurring payments with their status, next payment date, etc.
3. Filter by customer, status, or payment method

### Managing Recurring Payments

From the recurring payments list, you can:

1. **Activate** draft recurring payments
2. **Pause** active recurring payments
3. **Resume** paused recurring payments
4. **Cancel** any recurring payment
5. **View payment history** for each recurring payment

### Manual Processing

You can manually process a recurring payment:

1. Open the recurring payment record
2. Click the **Process Now** button to immediately process the payment

## Troubleshooting

### Failed Payments

If a payment fails:

1. The system will automatically retry based on your configuration
2. After the maximum retries, the recurring payment will be paused
3. An email notification is sent to the customer
4. You can manually resume the recurring payment after addressing the issue

### Logging

Detailed logs are available in the Odoo logs with the tag `powertranz.recurring`.

## Testing

You can test the recurring payment functionality using test cards:

- Test Card Number: `4012000000020071`
- Expiry Date: Any future date
- CVV: Any 3 digits

## Best Practices

1. Set reasonable retry intervals to avoid excessive failed payment attempts
2. Monitor the recurring payments dashboard regularly
3. Ensure your cron jobs are running properly
4. Test the full payment flow before going live

For any issues or questions, please contact your Odoo administrator or PowerTranz support.
