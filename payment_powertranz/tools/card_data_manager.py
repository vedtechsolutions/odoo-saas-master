# -*- coding: utf-8 -*-
import logging
import uuid
import time
import threading
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

# In-memory storage for card data 
# This uses a dictionary with transaction reference as key and card data as value
# Data is automatically expired after a configurable timeout
class CardDataManager:
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CardDataManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance
    
    def _initialize(self):
        self._card_data = {}  # {tx_reference: {'data': {card_data}, 'expiry': timestamp}}
        self._cleanup_interval = 300  # Cleanup every 5 minutes (300 seconds)
        self._data_expiry = 900  # Card data expires after 15 minutes (900 seconds)
        self._last_cleanup = time.time()
        self._enabled = True
    
    def store(self, tx_reference, card_data):
        """Store card data in memory with an expiration time
        
        Args:
            tx_reference: Transaction reference as string
            card_data: Dictionary containing card data
        
        Returns:
            str: A secure token that can be used to retrieve the card data
        """
        if not self._enabled:
            _logger.warning("In-memory card data storage is disabled. Not storing card data.")
            return None
            
        # Create a secure token for this data
        token = str(uuid.uuid4())
        
        # Store the card data with expiration
        with self._lock:
            self._cleanup_expired()
            self._card_data[tx_reference] = {
                'token': token,
                'data': card_data,
                'expiry': time.time() + self._data_expiry
            }
            
        _logger.info(
            "Card data for transaction %s stored in memory (will expire in %d seconds)",
            tx_reference, self._data_expiry
        )
        return token
        
    def retrieve(self, tx_reference, token=None):
        """Retrieve card data from memory.
        
        Args:
            tx_reference: Transaction reference as string
            token: Optional token to validate against
            
        Returns:
            dict: Card data dictionary or None if not found or expired
        """
        with self._lock:
            self._cleanup_expired()
            
            if tx_reference not in self._card_data:
                _logger.warning("No card data found for transaction %s", tx_reference)
                return None
                
            stored_data = self._card_data[tx_reference]
            
            # Verify token if provided
            if token and stored_data['token'] != token:
                _logger.warning("Invalid token for card data retrieval (tx: %s)", tx_reference)
                return None
                
            # Check if expired
            if time.time() > stored_data['expiry']:
                _logger.info("Card data for transaction %s has expired", tx_reference)
                del self._card_data[tx_reference]
                return None
                
            # Return a copy of the data to prevent modification
            return dict(stored_data['data'])
    
    def remove(self, tx_reference):
        """Explicitly remove card data after use.
        
        Args:
            tx_reference: Transaction reference as string
        """
        with self._lock:
            if tx_reference in self._card_data:
                del self._card_data[tx_reference]
                _logger.info("Card data for transaction %s removed from memory", tx_reference)
    
    def _cleanup_expired(self):
        """Clean up expired card data."""
        current_time = time.time()
        
        # Only run cleanup periodically
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
            
        self._last_cleanup = current_time
        expired_refs = []
        
        for tx_ref, data in self._card_data.items():
            if current_time > data['expiry']:
                expired_refs.append(tx_ref)
        
        for tx_ref in expired_refs:
            del self._card_data[tx_ref]
            
        if expired_refs:
            _logger.info("Cleaned up expired card data for %d transactions", len(expired_refs))

# Singleton instance
card_data_manager = CardDataManager() 