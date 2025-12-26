# -*- coding: utf-8 -*-

# Currency codes (ISO-4217 Numeric)
# Based on PowerTranz documentation or common usage
# Add more as needed
POWERTANZ_CURRENCY_CODES = {
    'USD': '840',
    'EUR': '978',
    'GBP': '826',
    'CAD': '124',
    'AUD': '036',
    'JPY': '392',
    'CHF': '756',
    'JMD': '388',
    'MXN': '484',
    'NZD': '554',
    'ZAR': '710',
    'INR': '356',
    'BRL': '076',
    
    # Add other currencies supported by PowerTranz
}

# Country codes (ISO-3166-1 Numeric)
# Based on PowerTranz documentation or common usage
# Add more as needed
POWERTANZ_COUNTRY_CODES = {
    'US': '840',
    'GB': '826',
    'CA': '124',
    'AU': '036',
    'JP': '392',
    'CH': '756',
    'DE': '276',
    'FR': '250',
    'IT': '380',
    'ES': '724',
    'JM': '388',
    'MX': '484',
    'NZ': '554',
    'ZA': '710',
    'IN': '356',
    'BR': '076',
    
    # Add other countries relevant to PowerTranz usage
}

# Add other constants like response codes, auth statuses etc. later

# Example 3DS Statuses (align with field definition later)
# PT_3DS_PENDING = 'pending'
# PT_3DS_FINGERPRINT = 'fingerprint'
# PT_3DS_CHALLENGE = 'challenge'
# PT_3DS_AUTHENTICATED = 'authenticated'
# PT_3DS_FAILED = 'failed' 