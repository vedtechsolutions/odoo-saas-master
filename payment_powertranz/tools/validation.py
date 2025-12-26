# -*- coding: utf-8 -*-

import re
import logging
from datetime import datetime
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Regular expressions for validation
CARD_NUMBER_REGEX = r'^[0-9]{13,19}$'  # 13-19 digits
CVV_REGEX = r'^[0-9]{3,4}$'  # 3-4 digits
EXPIRY_MONTH_REGEX = r'^(0[1-9]|1[0-2])$'  # 01-12
EXPIRY_YEAR_REGEX = r'^(2[0-9])$'  # 20-29 (2-digit year)
FULL_YEAR_REGEX = r'^20[2-9][0-9]$'  # 2020-2099 (4-digit year)
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
AMOUNT_REGEX = r'^[0-9]+(\.[0-9]{1,2})?$'  # Positive number with up to 2 decimal places

def validate_card_data(card_data, raise_exception=True):
    """Validate credit card data.
    
    Args:
        card_data (dict): Dictionary containing card data with keys:
            - card_number: The card number
            - cvv: The CVV/CVC code
            - expiry_month: The expiry month (01-12)
            - expiry_year: The expiry year (2-digit or 4-digit)
            - cardholder_name: The cardholder name
        raise_exception (bool): Whether to raise an exception on validation failure
            
    Returns:
        tuple: (is_valid, error_message)
    """
    errors = []
    
    # Check required fields
    required_fields = ['card_number', 'cvv', 'expiry_month', 'expiry_year', 'cardholder_name']
    for field in required_fields:
        if field not in card_data or not card_data[field]:
            errors.append(_("Missing required field: %s") % field)
    
    if errors:
        error_message = "; ".join(errors)
        if raise_exception:
            raise ValidationError(error_message)
        return False, error_message
    
    # Validate card number (Luhn algorithm)
    card_number = card_data['card_number'].replace(' ', '')
    if not re.match(CARD_NUMBER_REGEX, card_number):
        error = _("Invalid card number format")
        if raise_exception:
            raise ValidationError(error)
        return False, error
        
    if not validate_luhn(card_number):
        error = _("Card number failed Luhn check")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Validate CVV
    cvv = card_data['cvv']
    if not re.match(CVV_REGEX, cvv):
        error = _("Invalid CVV format (must be 3-4 digits)")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Validate expiry date
    expiry_month = card_data['expiry_month']
    expiry_year = card_data['expiry_year']
    
    # Handle 2-digit or 4-digit year
    if len(expiry_year) == 2:
        if not re.match(EXPIRY_YEAR_REGEX, expiry_year):
            error = _("Invalid expiry year format (must be 2 digits)")
            if raise_exception:
                raise ValidationError(error)
            return False, error
        full_year = int("20" + expiry_year)
    else:
        if not re.match(FULL_YEAR_REGEX, expiry_year):
            error = _("Invalid expiry year format (must be 4 digits)")
            if raise_exception:
                raise ValidationError(error)
            return False, error
        full_year = int(expiry_year)
    
    if not re.match(EXPIRY_MONTH_REGEX, expiry_month):
        error = _("Invalid expiry month format (must be 01-12)")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Check if card is expired
    current_date = datetime.now()
    card_expiry = datetime(full_year, int(expiry_month), 1)
    if card_expiry.year < current_date.year or (card_expiry.year == current_date.year and card_expiry.month < current_date.month):
        error = _("Card has expired")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Validate cardholder name
    cardholder_name = card_data['cardholder_name'].strip()
    if len(cardholder_name) < 3:
        error = _("Cardholder name is too short")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    return True, ""

def validate_luhn(card_number):
    """Validate a card number using the Luhn algorithm.
    
    Args:
        card_number (str): The card number to validate
        
    Returns:
        bool: True if the card number passes the Luhn check, False otherwise
    """
    digits = [int(d) for d in card_number]
    checksum = 0
    
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:  # Odd position (0-indexed from the right)
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    
    return checksum % 10 == 0

def validate_amount(amount, min_amount=0.01, max_amount=None, currency=None, raise_exception=True):
    """Validate a payment amount.
    
    Args:
        amount (float): The amount to validate
        min_amount (float): The minimum allowed amount
        max_amount (float): The maximum allowed amount, or None for no maximum
        currency (str): The currency code (for error messages)
        raise_exception (bool): Whether to raise an exception on validation failure
            
    Returns:
        tuple: (is_valid, error_message)
    """
    if not isinstance(amount, (int, float)) or amount < min_amount:
        error = _("Amount must be at least %s%s") % (min_amount, f" {currency}" if currency else "")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    if max_amount and amount > max_amount:
        error = _("Amount cannot exceed %s%s") % (max_amount, f" {currency}" if currency else "")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    return True, ""

def validate_recurring_data(recurring_data, raise_exception=True):
    """Validate recurring payment data.
    
    Args:
        recurring_data (dict): Dictionary containing recurring payment data with keys:
            - frequency: The payment frequency code
            - start_date: The start date (YYYY-MM-DD)
            - end_date: The end date (YYYY-MM-DD), optional
            - management_type: The management type (merchant or powertranz)
        raise_exception (bool): Whether to raise an exception on validation failure
            
    Returns:
        tuple: (is_valid, error_message)
    """
    errors = []
    
    # Check required fields
    required_fields = ['frequency', 'start_date', 'management_type']
    for field in required_fields:
        if field not in recurring_data or not recurring_data[field]:
            errors.append(_("Missing required field: %s") % field)
    
    if errors:
        error_message = "; ".join(errors)
        if raise_exception:
            raise ValidationError(error_message)
        return False, error_message
    
    # Validate frequency
    valid_frequencies = ['D', 'W', 'F', 'M', 'B', 'Q', 'S', 'Y']
    if recurring_data['frequency'] not in valid_frequencies:
        error = _("Invalid frequency code. Must be one of: %s") % ", ".join(valid_frequencies)
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Validate management type
    valid_management_types = ['merchant', 'powertranz']
    if recurring_data['management_type'] not in valid_management_types:
        error = _("Invalid management type. Must be one of: %s") % ", ".join(valid_management_types)
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Validate start date
    try:
        start_date = datetime.strptime(recurring_data['start_date'], '%Y-%m-%d').date()
    except ValueError:
        error = _("Invalid start date format. Must be YYYY-MM-DD")
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    # Validate end date if provided
    if 'end_date' in recurring_data and recurring_data['end_date']:
        try:
            end_date = datetime.strptime(recurring_data['end_date'], '%Y-%m-%d').date()
            if end_date <= start_date:
                error = _("End date must be after start date")
                if raise_exception:
                    raise ValidationError(error)
                return False, error
        except ValueError:
            error = _("Invalid end date format. Must be YYYY-MM-DD")
            if raise_exception:
                raise ValidationError(error)
            return False, error
    
    return True, ""

def validate_webhook_data(webhook_data, raise_exception=True):
    """Validate webhook notification data.
    
    Args:
        webhook_data (dict): Dictionary containing webhook notification data
        raise_exception (bool): Whether to raise an exception on validation failure
            
    Returns:
        tuple: (is_valid, error_message)
    """
    # Check for minimum required fields in webhook data
    required_fields = ['transactionId', 'orderIdentifier']
    missing_fields = [field for field in required_fields if field not in webhook_data]
    
    if missing_fields:
        error = _("Missing required fields in webhook data: %s") % ", ".join(missing_fields)
        if raise_exception:
            raise ValidationError(error)
        return False, error
    
    return True, ""

def sanitize_input(value, input_type='text'):
    """Sanitize user input to prevent injection attacks.
    
    Args:
        value: The input value to sanitize
        input_type: The type of input ('text', 'html', 'json', etc.)
            
    Returns:
        The sanitized input value
    """
    if value is None:
        return value
        
    if input_type == 'text':
        # For plain text, remove any HTML or script tags
        if isinstance(value, str):
            # Remove HTML tags
            value = re.sub(r'<[^>]*>', '', value)
            # Replace potentially dangerous characters
            value = value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            value = value.replace('"', '&quot;').replace("'", '&#x27;')
    
    return value

def validate_request_parameters(params, required_params=None, optional_params=None, raise_exception=True):
    """Validate request parameters.
    
    Args:
        params (dict): The parameters to validate
        required_params (list): List of required parameter names
        optional_params (list): List of optional parameter names
        raise_exception (bool): Whether to raise an exception on validation failure
            
    Returns:
        tuple: (is_valid, error_message)
    """
    errors = []
    
    # Check required parameters
    if required_params:
        for param in required_params:
            if param not in params or params[param] is None or params[param] == '':
                errors.append(_("Missing required parameter: %s") % param)
    
    # Check for unexpected parameters
    if required_params or optional_params:
        allowed_params = set((required_params or []) + (optional_params or []))
        unexpected_params = [param for param in params if param not in allowed_params]
        if unexpected_params:
            errors.append(_("Unexpected parameters: %s") % ", ".join(unexpected_params))
    
    if errors:
        error_message = "; ".join(errors)
        if raise_exception:
            raise ValidationError(error_message)
        return False, error_message
    
    return True, ""
