# Changelog

All notable changes to the PowerTranz Payment module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Migration framework for future upgrades
- Version management system
- In-memory card data storage system to avoid database storage of sensitive information

### Security
- Major security enhancement: Card data (PAN, CVV, expiry) no longer stored in database
- Implemented thread-safe in-memory card data manager with automatic expiration mechanism
- Reduced PCI compliance scope by eliminating database storage of card data

## [18.0.1.2.0] - 2025-05-09
### Added
- Restored webhook security with HMAC-SHA256 authentication
- Re-added webhook secret field to payment provider configuration
- Added proper migration scripts for database schema updates

### Security
- Implemented secure signature verification for webhook requests
- Added backward compatibility for installations without webhook secret configured

## [18.0.1.1.0] - 2025-05-09
### Added
- Added email templates for recurring payment creation, successful payment, and cancellation
- Implemented idempotency checks to prevent duplicate transaction processing

### Fixed
- Improved error handling in webhook controller
- Temporarily removed webhook secret field to resolve upgrade issues
- Modified webhook controller to accept all requests without signature verification (temporary solution)

## [18.0.1.0.0] - 2025-05-09
### Added
- Initial release for Odoo 18
- Inline credit card payment processing integration
- Customer portal for PowerTranz recurring payments
- Support for merchant-managed and PowerTranz-managed recurring payments
- Email notifications for failed payments
- Webhook controller for handling PowerTranz notifications
