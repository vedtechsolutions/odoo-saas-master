# -*- coding: utf-8 -*-

import logging
import json
import pprint
from .security import mask_sensitive_data

_logger = logging.getLogger(__name__)

def log_request(logger, level, msg, *args, **kwargs):
    """Log a request with sensitive data masked.
    
    Args:
        logger: The logger to use
        level: The logging level (e.g., logging.INFO)
        msg: The message format string
        *args: The arguments to the message format string
        **kwargs: Additional keyword arguments
            - request_data: The request data to mask
            - response_data: The response data to mask
    """
    request_data = kwargs.pop('request_data', None)
    response_data = kwargs.pop('response_data', None)
    
    # Create new args with masked data
    new_args = list(args)
    
    # Mask request data if present
    if request_data is not None:
        masked_request = mask_sensitive_data(request_data)
        if 'request_data' in msg:
            # Find the position of request_data in the format string
            try:
                pos = msg.index('request_data')
                # Find the corresponding position in args
                for i, arg in enumerate(args):
                    if arg == request_data:
                        new_args[i] = masked_request
                        break
            except ValueError:
                # If request_data is not in the format string, append it
                msg += "\nRequest data: %s"
                new_args.append(pprint.pformat(masked_request))
        else:
            # If request_data is not in the format string, append it
            msg += "\nRequest data: %s"
            new_args.append(pprint.pformat(masked_request))
    
    # Mask response data if present
    if response_data is not None:
        masked_response = mask_sensitive_data(response_data)
        if 'response_data' in msg:
            # Find the position of response_data in the format string
            try:
                pos = msg.index('response_data')
                # Find the corresponding position in args
                for i, arg in enumerate(args):
                    if arg == response_data:
                        new_args[i] = masked_response
                        break
            except ValueError:
                # If response_data is not in the format string, append it
                msg += "\nResponse data: %s"
                new_args.append(pprint.pformat(masked_response))
        else:
            # If response_data is not in the format string, append it
            msg += "\nResponse data: %s"
            new_args.append(pprint.pformat(masked_response))
    
    # Log the message with masked data
    logger.log(level, msg, *new_args, **kwargs)

def log_payment_info(logger, message, transaction, data=None, level=logging.INFO):
    """Log payment information with sensitive data masked.
    
    Args:
        logger: The logger to use
        message: The message to log
        transaction: The payment transaction
        data: Additional data to include in the log
        level: The logging level (default: logging.INFO)
    """
    tx_info = {
        'reference': transaction.reference,
        'amount': transaction.amount,
        'currency': transaction.currency_id.name,
        'partner': transaction.partner_id.name if transaction.partner_id else 'Unknown',
        'state': transaction.state,
    }
    
    # Add masked data if provided
    if data:
        masked_data = mask_sensitive_data(data)
        logger.log(level, f"{message} - Transaction: {tx_info}, Data: {pprint.pformat(masked_data)}")
    else:
        logger.log(level, f"{message} - Transaction: {tx_info}")

def safe_pformat(data):
    """Format data for logging with sensitive information masked.
    
    Args:
        data: The data to format
        
    Returns:
        str: The formatted data with sensitive information masked
    """
    if data is None:
        return 'None'
        
    masked_data = mask_sensitive_data(data)
    return pprint.pformat(masked_data)
