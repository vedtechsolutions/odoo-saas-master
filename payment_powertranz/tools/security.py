# -*- coding: utf-8 -*-

import copy
import re
import logging

_logger = logging.getLogger(__name__)

def mask_sensitive_data(data, deep_copy=True):
    """Mask sensitive data in logs.
    
    This function takes a dictionary and masks sensitive fields like credit card numbers,
    CVV codes, passwords, etc. to prevent them from being logged in plain text.
    
    Args:
        data (dict): The data dictionary to mask
        deep_copy (bool): Whether to create a deep copy of the data before masking
        
    Returns:
        dict: A copy of the data with sensitive fields masked
    """
    if not data:
        return data
        
    # Create a copy to avoid modifying the original data
    if deep_copy:
        try:
            masked_data = copy.deepcopy(data)
        except (TypeError, ValueError):
            # If data cannot be deep copied (e.g., contains non-serializable objects)
            _logger.warning("Could not deep copy data for masking, using shallow copy")
            if isinstance(data, dict):
                masked_data = data.copy()
            else:
                return data  # Cannot mask non-dictionary data safely
    else:
        if isinstance(data, dict):
            masked_data = data.copy()
        else:
            return data  # Cannot mask non-dictionary data
    
    # List of sensitive field names (case-insensitive)
    sensitive_fields = [
        # Card data
        'card_number', 'cardnumber', 'pan', 'primary_account_number',
        'cvv', 'cvc', 'cvv2', 'cvc2', 'security_code', 'card_security_code',
        'card_verification', 'verification_value',
        
        # Authentication
        'password', 'secret', 'api_key', 'apikey', 'api_secret', 'apisecret',
        'access_token', 'accesstoken', 'token', 'secret_key', 'secretkey',
        
        # Personal data
        'ssn', 'social_security', 'tax_id', 'taxid',
    ]
    
    # Process dictionary recursively
    if isinstance(masked_data, dict):
        for key, value in list(masked_data.items()):
            # Check if the key is in the sensitive fields list
            key_lower = key.lower() if isinstance(key, str) else ''
            
            # Recursively process nested dictionaries
            if isinstance(value, dict):
                masked_data[key] = mask_sensitive_data(value, deep_copy=False)
            
            # Recursively process lists
            elif isinstance(value, list):
                masked_data[key] = [
                    mask_sensitive_data(item, deep_copy=False) if isinstance(item, dict) else item
                    for item in value
                ]
            
            # Mask credit card numbers
            elif isinstance(value, str) and any(field in key_lower for field in ['card_number', 'cardnumber', 'pan']):
                masked_data[key] = mask_card_number(value)
            
            # Mask CVV/CVC
            elif isinstance(value, str) and any(field in key_lower for field in ['cvv', 'cvc', 'security_code']):
                masked_data[key] = '***'
            
            # Mask other sensitive data
            elif isinstance(value, str) and any(field in key_lower for field in sensitive_fields):
                if len(value) > 6:
                    masked_data[key] = value[:2] + '*' * (len(value) - 4) + value[-2:]
                else:
                    masked_data[key] = '******'
    
    # Special handling for PowerTranz specific structures
    if isinstance(masked_data, dict):
        # Handle PowerTranz card data structure
        if 'card' in masked_data and isinstance(masked_data['card'], dict):
            card_data = masked_data['card']
            if 'number' in card_data and isinstance(card_data['number'], str):
                card_data['number'] = mask_card_number(card_data['number'])
            if 'securityCode' in card_data and isinstance(card_data['securityCode'], str):
                card_data['securityCode'] = '***'
        
        # Handle PowerTranz credentials
        if 'powertranz_id' in masked_data and isinstance(masked_data['powertranz_id'], str):
            masked_data['powertranz_id'] = mask_credential(masked_data['powertranz_id'])
        if 'powertranz_password' in masked_data and isinstance(masked_data['powertranz_password'], str):
            masked_data['powertranz_password'] = '******'
        
        # Handle card data in transaction fields
        if 'powertranz_card_number' in masked_data and isinstance(masked_data['powertranz_card_number'], str):
            masked_data['powertranz_card_number'] = mask_card_number(masked_data['powertranz_card_number'])
        if 'powertranz_card_cvc' in masked_data and isinstance(masked_data['powertranz_card_cvc'], str):
            masked_data['powertranz_card_cvc'] = '***'
    
    return masked_data

def mask_card_number(card_number):
    """Mask a credit card number.
    
    Args:
        card_number (str): The card number to mask
        
    Returns:
        str: The masked card number
    """
    if not card_number or not isinstance(card_number, str):
        return card_number
        
    # Remove any non-digit characters
    digits_only = re.sub(r'\D', '', card_number)
    
    # If it's not a valid length for a card number, return as is
    if len(digits_only) < 13 or len(digits_only) > 19:
        return card_number
    
    # Keep first 6 and last 4 digits, mask the rest
    return digits_only[:6] + '*' * (len(digits_only) - 10) + digits_only[-4:]

def mask_credential(credential):
    """Mask a credential like an API key or merchant ID.
    
    Args:
        credential (str): The credential to mask
        
    Returns:
        str: The masked credential
    """
    if not credential or not isinstance(credential, str):
        return credential
        
    if len(credential) <= 8:
        return '*' * len(credential)
    
    # Show first 2 and last 2 characters
    return credential[:2] + '*' * (len(credential) - 4) + credential[-2:]
