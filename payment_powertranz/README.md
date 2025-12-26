# PowerTranz Payment Acquirer for Odoo 18

This module integrates the PowerTranz payment gateway with Odoo 18, allowing you to accept online payments via PowerTranz directly from your Odoo instance.

## Features

*   **Payment Processing:** Handles standard payment authorization and capture.
*   **3D Secure:** Supports 3DS 2.x authentication flows (frictionless, fingerprinting, challenge).
*   **Tokenization:** Allows customers to save card details securely for future use.
*   **Recurring Payments:** 
    *   Supports Merchant-Managed recurring payments using Odoo's infrastructure.
    *   Supports PowerTranz-Managed recurring payments via API setup and webhooks.
*   **Manual Capture:** Option to authorize payments first and capture them later manually.
*   **Refunds:** Process full refunds directly from Odoo.
*   **Void:** Cancel authorized (but not captured) transactions.
*   **Test Mode:** Supports connecting to the PowerTranz staging environment for testing.
*   **Upgrade Framework:** Built-in migration framework for seamless upgrades to future versions.
*   **Secure Card Storage:** Uses an in-memory approach for handling sensitive card data to enhance security.

## Security Features

### In-Memory Card Data Processing

This module uses an in-memory approach for handling sensitive card data to enhance security:

- Card data (card number, expiry date, CVV) is never stored in the database
- Card information is stored in memory only for the duration of the transaction processing
- Automatic expiry mechanism cleans up card data after a configurable timeout
- Thread-safe implementation with locking mechanisms to handle concurrent requests
- Card data is completely removed from memory once a transaction is completed

This approach minimizes PCI compliance scope while maintaining the same transaction flow and API payload format.

## Technical Information

### Requirements

- Odoo 18.0
- Active PowerTranz merchant account
- HTTPS is enforced for all payment operations

### Configuration

1.  Navigate to `Accounting -> Configuration -> Payment Providers` or `Website -> Configuration -> Payment Providers`.
2.  Find `PowerTranz` in the list and open its configuration form.
3.  Set the `State` to `Enabled` (for production) or `Test Mode`.
4.  Go to the `Credentials` tab and enter your `PowerTranz ID` and `PowerTranz Password` obtained from PowerTranz. Optionally add the `Gateway Key` if provided.
5.  Go to the `Configuration` tab:
    *   Enable/disable `3D Secure` as needed.
    *   Choose the `Recurring Type` (`Merchant Managed` or `PowerTranz Managed`).
    *   Configure other standard payment provider options like `Allow Saving Payment Methods`, `Capture Amount Manually`, allowed countries, etc.
    *   The `Webhook URL` is displayed here. You **must** configure this URL in your PowerTranz merchant portal settings if you use PowerTranz Managed recurring payments.
6.  Click `Save`.
7.  Optionally, go to `Accounting -> Configuration -> Payment Methods` (or Website/Sales) and ensure the desired payment methods (like `Card`) are linked to the PowerTranz provider.

## Testing

*   Use the provider in `Test Mode` with your PowerTranz **staging/test** credentials.
*   PowerTranz provides specific test card numbers for various scenarios (success, failure, 3DS challenges, etc.). Refer to the PowerTranz documentation for these test card details.

## Development & Contributing

### Version Management

This module follows semantic versioning with the format `[Odoo Version].[Major].[Minor].[Patch]`:

- **Odoo Version**: The Odoo version this module is compatible with (e.g., 18.0)
- **Major**: Incremented for backward-incompatible changes
- **Minor**: Incremented for backward-compatible new features
- **Patch**: Incremented for backward-compatible bug fixes

### Upgrade Process

The module includes a built-in migration framework to ensure smooth upgrades:

1. Migration scripts are automatically executed when upgrading from one version to another
2. The `migrations` directory contains version-specific scripts that handle database schema changes
3. Use the version upgrade tool in the `tools` directory to prepare for a new version:
   ```bash
   python tools/version_upgrade.py --minor  # For a minor version upgrade
   ```

### Contributing

When contributing to this module, please:

1. Create a new branch for your feature or bugfix
2. Follow the Odoo 18 coding guidelines and PEP8 standards
3. Include appropriate tests for your changes
4. Update the CHANGELOG.md with your changes
5. Submit a pull request with a clear description of your changes

## Support

(Add contact information or support procedures).

## License

LGPL-3 

## Test Cards

For development and testing purposes, you can use the following test cards:

| Card Type | Card Number | Expiry | CVV | Behavior |
|-----------|-------------|--------|-----|----------|
| VISA | 4012000000020071 | 12/25 | 123 | Frictionless, will approve |
| MASTERCARD | 5200000000001005 | 12/25 | 123 | Frictionless, will approve |
| VISA | 4012000000020089 | 12/25 | 123 | Challenge flow, approve after 3DS |
| VISA | 4012000000020097 | 12/25 | 123 | Will decline after 3DS |

These test cards are provided by PowerTranz for testing different payment scenarios. 

## Credits

Developed by [Your Company Name]

PowerTranz is a registered trademark of [PowerTranz Owner].

## License

See LICENSE file for licensing information. 