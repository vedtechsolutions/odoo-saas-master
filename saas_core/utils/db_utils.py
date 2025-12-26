# -*- coding: utf-8 -*-
"""
Database utilities for SaaS platform.

Provides locking mechanisms, retry logic, and savepoint management
for robust database operations.
"""

import logging
import time
import functools
from contextlib import contextmanager

from odoo import api, SUPERUSER_ID
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Default retry settings
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2  # seconds
DEFAULT_LOCK_TIMEOUT = 300  # 5 minutes


class DatabaseLock:
    """
    PostgreSQL advisory lock wrapper for preventing concurrent operations.

    Usage:
        with DatabaseLock(cr, 'support_module_install'):
            # Critical section
            do_something()
    """

    def __init__(self, cr, lock_name, timeout=DEFAULT_LOCK_TIMEOUT):
        """
        Initialize the lock.

        Args:
            cr: Database cursor
            lock_name: Unique name for the lock (will be hashed to int)
            timeout: Lock acquisition timeout in seconds
        """
        self.cr = cr
        self.lock_name = lock_name
        self.timeout = timeout
        self.lock_id = self._name_to_id(lock_name)
        self.acquired = False

    def _name_to_id(self, name):
        """Convert lock name to a consistent integer ID."""
        # Use hash to get a consistent integer from the name
        return hash(name) % (2**31)

    def acquire(self):
        """Try to acquire the advisory lock."""
        try:
            # Set statement timeout for lock acquisition
            self.cr.execute(f"SET LOCAL lock_timeout = '{self.timeout}s'")

            # Try to acquire advisory lock (blocking)
            self.cr.execute(
                "SELECT pg_advisory_lock(%s)",
                [self.lock_id]
            )
            self.acquired = True
            _logger.debug(f"Lock acquired: {self.lock_name} (id={self.lock_id})")
            return True
        except Exception as e:
            _logger.warning(f"Failed to acquire lock {self.lock_name}: {e}")
            return False

    def release(self):
        """Release the advisory lock."""
        if self.acquired:
            try:
                self.cr.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    [self.lock_id]
                )
                self.acquired = False
                _logger.debug(f"Lock released: {self.lock_name}")
            except Exception as e:
                _logger.error(f"Failed to release lock {self.lock_name}: {e}")

    def __enter__(self):
        if not self.acquire():
            raise UserError(f"Could not acquire lock: {self.lock_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


class TryLock:
    """
    Non-blocking advisory lock - returns immediately if lock not available.

    Usage:
        with TryLock(cr, 'my_operation') as lock:
            if lock.acquired:
                do_something()
            else:
                # Lock not available, skip or handle
                pass
    """

    def __init__(self, cr, lock_name):
        self.cr = cr
        self.lock_name = lock_name
        self.lock_id = hash(lock_name) % (2**31)
        self.acquired = False

    def try_acquire(self):
        """Try to acquire lock without blocking."""
        try:
            self.cr.execute(
                "SELECT pg_try_advisory_lock(%s)",
                [self.lock_id]
            )
            result = self.cr.fetchone()
            self.acquired = result and result[0]
            if self.acquired:
                _logger.debug(f"TryLock acquired: {self.lock_name}")
            return self.acquired
        except Exception as e:
            _logger.warning(f"TryLock failed for {self.lock_name}: {e}")
            return False

    def release(self):
        if self.acquired:
            try:
                self.cr.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    [self.lock_id]
                )
                self.acquired = False
            except Exception as e:
                _logger.warning(f"Failed to release TryLock {self.lock_name}: {e}")
                self.acquired = False  # Mark as released anyway to avoid double-release attempts

    def __enter__(self):
        self.try_acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


@contextmanager
def savepoint(cr, name=None):
    """
    Create a savepoint for partial rollback on error.

    Usage:
        with savepoint(cr, 'my_operation'):
            # This will be rolled back if exception occurs
            do_something()
    """
    savepoint_name = name or f"sp_{int(time.time() * 1000)}"
    try:
        cr.execute(f"SAVEPOINT {savepoint_name}")
        yield
        cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
    except Exception:
        cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        raise


def retry_on_error(max_retries=DEFAULT_MAX_RETRIES, delay=DEFAULT_RETRY_DELAY,
                   exceptions=(Exception,), on_retry=None):
    """
    Decorator to retry a function on failure.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds
        exceptions: Tuple of exception types to catch
        on_retry: Callback function(attempt, exception) called before retry

    Usage:
        @retry_on_error(max_retries=3, delay=2)
        def flaky_operation():
            # May fail sometimes
            pass
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        _logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for "
                            f"{func.__name__}: {e}. Retrying in {delay}s..."
                        )
                        if on_retry:
                            on_retry(attempt + 1, e)
                        time.sleep(delay)
                    else:
                        _logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}"
                        )
            raise last_exception
        return wrapper
    return decorator


def retry_database_operation(cr, func, max_retries=DEFAULT_MAX_RETRIES,
                             delay=DEFAULT_RETRY_DELAY):
    """
    Execute a database operation with retry and savepoint.

    Args:
        cr: Database cursor
        func: Function to execute (receives cr as argument)
        max_retries: Maximum retry attempts
        delay: Delay between retries

    Returns:
        Result of func() on success

    Raises:
        Last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        savepoint_name = f"retry_sp_{attempt}_{int(time.time() * 1000)}"
        try:
            cr.execute(f"SAVEPOINT {savepoint_name}")
            result = func(cr)
            cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            return result
        except Exception as e:
            last_exception = e
            try:
                cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            except Exception as rollback_error:
                _logger.warning(f"Failed to rollback savepoint {savepoint_name}: {rollback_error}")

            if attempt < max_retries:
                _logger.warning(
                    f"Database operation failed (attempt {attempt + 1}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                _logger.error(f"All retry attempts failed: {e}")

    raise last_exception


class CronLock:
    """
    Lock mechanism specifically for cron jobs to prevent overlapping runs.

    Uses a database table to track running cron jobs.

    Usage:
        with CronLock(env, 'support_module_installer'):
            # Only one instance of this cron runs at a time
            install_modules()
    """

    def __init__(self, env, cron_name, timeout_minutes=30):
        """
        Initialize cron lock.

        Args:
            env: Odoo environment
            cron_name: Unique identifier for this cron job
            timeout_minutes: Consider lock stale after this many minutes
        """
        self.env = env
        self.cron_name = cron_name
        self.timeout_minutes = timeout_minutes
        self.lock_acquired = False

    def acquire(self):
        """Try to acquire the cron lock."""
        ICP = self.env['ir.config_parameter'].sudo()
        lock_key = f'cron.lock.{self.cron_name}'
        lock_time_key = f'cron.lock.{self.cron_name}.time'

        current_time = time.time()

        # Check if lock exists and is not stale
        existing_lock = ICP.get_param(lock_key)
        if existing_lock:
            lock_time = float(ICP.get_param(lock_time_key, 0))
            age_minutes = (current_time - lock_time) / 60

            if age_minutes < self.timeout_minutes:
                _logger.info(
                    f"Cron lock {self.cron_name} held by another process "
                    f"(age: {age_minutes:.1f} min)"
                )
                return False
            else:
                _logger.warning(
                    f"Cron lock {self.cron_name} is stale "
                    f"(age: {age_minutes:.1f} min), stealing it"
                )

        # Acquire lock
        import socket
        lock_value = f"{socket.gethostname()}:{time.time()}"
        ICP.set_param(lock_key, lock_value)
        ICP.set_param(lock_time_key, str(current_time))
        self.lock_acquired = True

        _logger.info(f"Cron lock acquired: {self.cron_name}")
        return True

    def release(self):
        """Release the cron lock."""
        if self.lock_acquired:
            ICP = self.env['ir.config_parameter'].sudo()
            lock_key = f'cron.lock.{self.cron_name}'
            lock_time_key = f'cron.lock.{self.cron_name}.time'

            ICP.set_param(lock_key, False)
            ICP.set_param(lock_time_key, False)
            self.lock_acquired = False

            _logger.info(f"Cron lock released: {self.cron_name}")

    def __enter__(self):
        if not self.acquire():
            raise UserError(f"Cron job {self.cron_name} is already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def with_cron_lock(cron_name, timeout_minutes=30, skip_if_locked=True):
    """
    Decorator for cron job methods to ensure single execution.

    Args:
        cron_name: Unique name for this cron job
        timeout_minutes: Lock timeout
        skip_if_locked: If True, skip silently when locked; if False, raise error

    Usage:
        @with_cron_lock('my_cron_job')
        def my_cron_method(self):
            # Only one instance runs at a time
            pass
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = CronLock(self.env, cron_name, timeout_minutes)
            if not lock.acquire():
                if skip_if_locked:
                    _logger.info(f"Skipping {cron_name} - already running")
                    return True
                else:
                    raise UserError(f"Cron {cron_name} is already running")

            try:
                return func(self, *args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator
