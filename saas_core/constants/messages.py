# -*- coding: utf-8 -*-
"""
Message constants for validation errors, success messages, and email subjects.

Usage:
    from odoo.addons.saas_core.constants.messages import ValidationErrors
    raise ValidationError(ValidationErrors.SUBDOMAIN_INVALID)
"""


class ValidationErrors:
    """Validation error messages."""

    # Subdomain validation
    SUBDOMAIN_REQUIRED = "Subdomain is required."
    SUBDOMAIN_TOO_SHORT = "Subdomain must be at least 3 characters long."
    SUBDOMAIN_TOO_LONG = "Subdomain cannot exceed 30 characters."
    SUBDOMAIN_INVALID = "Subdomain can only contain lowercase letters, numbers, and hyphens."
    SUBDOMAIN_INVALID_START = "Subdomain must start with a letter or number."
    SUBDOMAIN_INVALID_END = "Subdomain must end with a letter or number."
    SUBDOMAIN_RESERVED = "This subdomain is reserved and cannot be used."
    SUBDOMAIN_EXISTS = "This subdomain is already in use."

    # Email validation
    EMAIL_REQUIRED = "Email address is required."
    EMAIL_INVALID = "Please enter a valid email address."

    # Plan validation
    PLAN_REQUIRED = "A subscription plan must be selected."
    PLAN_INACTIVE = "The selected plan is no longer available."
    PLAN_LIMIT_USERS = "User limit for this plan has been reached."
    PLAN_LIMIT_INSTANCES = "Instance limit for this plan has been reached."
    PLAN_LIMIT_STORAGE = "Storage limit for this plan has been reached."

    # Server validation
    SERVER_REQUIRED = "A tenant server must be assigned."
    SERVER_UNAVAILABLE = "The selected server is not available."
    SERVER_FULL = "The selected server has reached maximum capacity."
    SERVER_NO_PORTS = "No available ports on the selected server."

    # Instance validation
    INSTANCE_NOT_FOUND = "Instance not found."
    INSTANCE_ALREADY_RUNNING = "Instance is already running."
    INSTANCE_NOT_RUNNING = "Instance is not running."
    INSTANCE_SUSPENDED = "Instance is suspended. Please contact support."
    INSTANCE_TERMINATED = "Instance has been terminated."

    # Payment validation
    PAYMENT_REQUIRED = "Payment is required to continue."
    PAYMENT_FAILED = "Payment failed. Please try again."
    PAYMENT_METHOD_REQUIRED = "Please add a payment method."

    # General
    OPERATION_FAILED = "Operation failed. Please try again."
    PERMISSION_DENIED = "You do not have permission to perform this action."


class SuccessMessages:
    """Success messages for user notifications."""

    # Instance operations
    INSTANCE_CREATED = "Instance created successfully!"
    INSTANCE_PROVISIONING = "Instance is being provisioned. This may take a few minutes."
    INSTANCE_STARTED = "Instance started successfully."
    INSTANCE_STOPPED = "Instance stopped successfully."
    INSTANCE_RESTARTED = "Instance restarted successfully."
    INSTANCE_DELETED = "Instance has been deleted."

    # Subscription operations
    SUBSCRIPTION_CREATED = "Subscription activated successfully!"
    SUBSCRIPTION_UPGRADED = "Subscription upgraded successfully!"
    SUBSCRIPTION_DOWNGRADED = "Subscription will be downgraded at the end of the billing period."
    SUBSCRIPTION_CANCELLED = "Subscription cancelled. Access will continue until the end of the billing period."
    SUBSCRIPTION_RENEWED = "Subscription renewed successfully!"

    # Payment operations
    PAYMENT_SUCCESSFUL = "Payment processed successfully!"
    PAYMENT_METHOD_ADDED = "Payment method added successfully."
    PAYMENT_METHOD_REMOVED = "Payment method removed."

    # Backup operations
    BACKUP_STARTED = "Backup started. You will be notified when it completes."
    BACKUP_COMPLETED = "Backup completed successfully!"
    RESTORE_STARTED = "Restore started. Your instance will be temporarily unavailable."
    RESTORE_COMPLETED = "Restore completed successfully!"

    # General
    CHANGES_SAVED = "Changes saved successfully."
    EMAIL_SENT = "Email sent successfully."


class EmailSubjects:
    """Email subject lines."""

    # Welcome and onboarding
    WELCOME = "Welcome to VedTech SaaS Platform!"
    TRIAL_STARTED = "Your 14-Day Free Trial Has Started"
    INSTANCE_READY = "Your Odoo Instance is Ready!"

    # Billing
    INVOICE_CREATED = "New Invoice #{invoice_number}"
    PAYMENT_RECEIVED = "Payment Received - Thank You!"
    PAYMENT_FAILED = "Action Required: Payment Failed"
    PAYMENT_REMINDER = "Payment Reminder: Invoice #{invoice_number}"

    # Subscription
    SUBSCRIPTION_ACTIVATED = "Subscription Activated"
    SUBSCRIPTION_RENEWED = "Subscription Renewed"
    SUBSCRIPTION_CANCELLED = "Subscription Cancellation Confirmed"
    SUBSCRIPTION_EXPIRING = "Your Subscription is Expiring Soon"

    # Trial
    TRIAL_ENDING_SOON = "Your Trial Ends in {days} Days"
    TRIAL_EXPIRED = "Your Trial Has Expired"

    # Instance
    INSTANCE_SUSPENDED = "Instance Suspended - Action Required"
    INSTANCE_TERMINATED = "Instance Termination Notice"

    # Backup
    BACKUP_COMPLETED = "Backup Completed Successfully"
    BACKUP_FAILED = "Backup Failed - Action Required"

    # Support
    TICKET_CREATED = "Support Ticket #{ticket_number} Created"
    TICKET_UPDATED = "Update on Support Ticket #{ticket_number}"
    TICKET_RESOLVED = "Support Ticket #{ticket_number} Resolved"
