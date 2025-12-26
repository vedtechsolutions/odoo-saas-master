# -*- coding: utf-8 -*-
"""
Resource Usage REST API (T-108)

Provides REST endpoints for querying instance resource usage metrics.
Secured via API key authentication with rate limiting.

Endpoints:
    GET /api/v1/usage/instances - List all instances with usage summary
    GET /api/v1/usage/instance/<id> - Get detailed usage for specific instance
    GET /api/v1/usage/instance/<id>/history - Get usage history
    POST /api/v1/usage/instance/<id>/collect - Trigger metric collection
    GET /api/v1/usage/summary - Platform-wide usage summary
"""

import json
import logging
import time
from collections import defaultdict
from functools import wraps
from threading import Lock

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# API Key parameter name in ir.config_parameter
API_KEY_PARAM = 'saas.resource_api_key'

# Rate limiting configuration (T-146)
RATE_LIMIT_REQUESTS = 100  # Max requests per window
RATE_LIMIT_WINDOW = 60     # Window in seconds (1 minute)


class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, max_requests=RATE_LIMIT_REQUESTS, window_seconds=RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = Lock()

    def is_allowed(self, client_id):
        """Check if request is allowed for client."""
        now = time.time()
        window_start = now - self.window_seconds

        with self.lock:
            # Clean old requests
            self.requests[client_id] = [
                t for t in self.requests[client_id] if t > window_start
            ]

            # Check limit
            if len(self.requests[client_id]) >= self.max_requests:
                return False, self.max_requests - len(self.requests[client_id])

            # Record request
            self.requests[client_id].append(now)
            remaining = self.max_requests - len(self.requests[client_id])
            return True, remaining

    def get_reset_time(self, client_id):
        """Get time until rate limit resets."""
        if client_id in self.requests and self.requests[client_id]:
            oldest = min(self.requests[client_id])
            return int(oldest + self.window_seconds - time.time())
        return 0


# Global rate limiter instance
_rate_limiter = RateLimiter()


def json_response(data, status=200, headers=None):
    """Return a JSON response with proper headers."""
    response_headers = {'Access-Control-Allow-Origin': '*'}
    if headers:
        response_headers.update(headers)
    return Response(
        json.dumps(data, default=str),
        status=status,
        mimetype='application/json',
        headers=response_headers
    )


def rate_limit_required(func):
    """Decorator to enforce rate limiting."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Use API key as client identifier (or IP if no key)
        api_key = request.httprequest.headers.get('X-API-Key') or \
                  request.params.get('api_key')
        client_id = api_key or request.httprequest.remote_addr

        allowed, remaining = _rate_limiter.is_allowed(client_id)

        if not allowed:
            reset_time = _rate_limiter.get_reset_time(client_id)
            _logger.warning(f"Rate limit exceeded for client: {client_id[:16]}...")
            return json_response({
                'error': 'Rate limit exceeded',
                'message': f'Too many requests. Please wait {reset_time} seconds.',
                'retry_after': reset_time,
            }, status=429, headers={
                'X-RateLimit-Limit': str(RATE_LIMIT_REQUESTS),
                'X-RateLimit-Remaining': '0',
                'X-RateLimit-Reset': str(int(time.time()) + reset_time),
                'Retry-After': str(reset_time),
            })

        # Add rate limit headers to successful responses
        response = func(*args, **kwargs)
        if hasattr(response, 'headers'):
            response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT_REQUESTS)
            response.headers['X-RateLimit-Remaining'] = str(remaining)
        return response
    return wrapper


def api_key_required(func):
    """Decorator to require API key authentication."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get API key from header or query parameter
        api_key = request.httprequest.headers.get('X-API-Key') or \
                  request.params.get('api_key')

        if not api_key:
            return json_response({
                'error': 'Missing API key',
                'message': 'Provide API key via X-API-Key header or api_key parameter'
            }, status=401)

        # Validate API key
        ICP = request.env['ir.config_parameter'].sudo()
        valid_key = ICP.get_param(API_KEY_PARAM)

        if not valid_key:
            _logger.warning("Resource API key not configured in system parameters")
            return json_response({
                'error': 'API not configured',
                'message': 'Contact administrator to configure API access'
            }, status=503)

        if api_key != valid_key:
            _logger.warning(f"Invalid API key attempt: {api_key[:8]}...")
            return json_response({
                'error': 'Invalid API key',
                'message': 'The provided API key is not valid'
            }, status=403)

        return func(*args, **kwargs)
    return wrapper


class ResourceUsageAPI(http.Controller):
    """REST API controller for resource usage metrics."""

    @http.route('/api/v1/usage/instances', type='http', auth='none', methods=['GET'], csrf=False)
    @rate_limit_required
    @api_key_required
    def get_instances_usage(self, **kwargs):
        """
        Get usage summary for all instances.

        Query parameters:
            state: Filter by instance state (running, stopped, etc.)
            plan_id: Filter by plan ID
            limit: Max results (default 100)
            offset: Pagination offset (default 0)

        Returns:
            JSON array of instances with usage data
        """
        try:
            Instance = request.env['saas.instance'].sudo()

            # Build domain from filters
            domain = []
            if kwargs.get('state'):
                domain.append(('state', '=', kwargs['state']))
            if kwargs.get('plan_id'):
                domain.append(('plan_id', '=', int(kwargs['plan_id'])))

            # Pagination
            limit = min(int(kwargs.get('limit', 100)), 500)
            offset = int(kwargs.get('offset', 0))

            instances = Instance.search(domain, limit=limit, offset=offset, order='name')
            total = Instance.search_count(domain)

            result = []
            for inst in instances:
                result.append(self._format_instance_usage(inst))

            return json_response({
                'success': True,
                'total': total,
                'limit': limit,
                'offset': offset,
                'data': result,
            })

        except Exception as e:
            _logger.error(f"Error in get_instances_usage: {e}")
            return json_response({
                'error': 'Internal error',
                'message': str(e)
            }, status=500)

    @http.route('/api/v1/usage/instance/<int:instance_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @rate_limit_required
    @api_key_required
    def get_instance_usage(self, instance_id, **kwargs):
        """
        Get detailed usage for a specific instance.

        Path parameters:
            instance_id: Instance ID

        Returns:
            JSON object with detailed usage metrics
        """
        try:
            Instance = request.env['saas.instance'].sudo()
            instance = Instance.browse(instance_id)

            if not instance.exists():
                return json_response({
                    'error': 'Not found',
                    'message': f'Instance {instance_id} not found'
                }, status=404)

            # Get detailed metrics
            data = self._format_instance_usage(instance, detailed=True)

            return json_response({
                'success': True,
                'data': data,
            })

        except Exception as e:
            _logger.error(f"Error in get_instance_usage: {e}")
            return json_response({
                'error': 'Internal error',
                'message': str(e)
            }, status=500)

    @http.route('/api/v1/usage/instance/<int:instance_id>/history', type='http', auth='none', methods=['GET'], csrf=False)
    @rate_limit_required
    @api_key_required
    def get_instance_usage_history(self, instance_id, **kwargs):
        """
        Get usage history for a specific instance.

        Path parameters:
            instance_id: Instance ID

        Query parameters:
            metric: Metric type (cpu, memory, disk) - default: all
            days: Number of days of history (default 7, max 30)
            interval: Grouping interval (hour, day) - default: hour

        Returns:
            JSON object with historical usage data
        """
        try:
            Instance = request.env['saas.instance'].sudo()
            instance = Instance.browse(instance_id)

            if not instance.exists():
                return json_response({
                    'error': 'Not found',
                    'message': f'Instance {instance_id} not found'
                }, status=404)

            # Parameters
            metric_filter = kwargs.get('metric')
            days = min(int(kwargs.get('days', 7)), 30)
            interval = kwargs.get('interval', 'hour')

            # Get usage logs
            UsageLog = request.env['saas.usage.log'].sudo()
            from datetime import datetime, timedelta
            date_from = datetime.now() - timedelta(days=days)

            domain = [
                ('instance_id', '=', instance_id),
                ('timestamp', '>=', date_from.strftime('%Y-%m-%d %H:%M:%S')),
            ]

            if metric_filter:
                MetricType = request.env['saas.metric.type'].sudo()
                metric_type = MetricType.search([('code', '=', metric_filter)], limit=1)
                if metric_type:
                    domain.append(('metric_type_id', '=', metric_type.id))

            logs = UsageLog.search(domain, order='timestamp asc')

            # Format history data
            history = []
            for log in logs:
                history.append({
                    'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                    'metric': log.metric_type_id.code if log.metric_type_id else 'unknown',
                    'value': log.value,
                    'unit': log.metric_type_id.unit if log.metric_type_id else None,
                })

            return json_response({
                'success': True,
                'instance_id': instance_id,
                'instance_name': instance.name,
                'days': days,
                'data_points': len(history),
                'data': history,
            })

        except Exception as e:
            _logger.error(f"Error in get_instance_usage_history: {e}")
            return json_response({
                'error': 'Internal error',
                'message': str(e)
            }, status=500)

    @http.route('/api/v1/usage/instance/<int:instance_id>/collect', type='http', auth='none', methods=['POST'], csrf=False)
    @rate_limit_required
    @api_key_required
    def trigger_metric_collection(self, instance_id, **kwargs):
        """
        Trigger immediate metric collection for an instance.

        Path parameters:
            instance_id: Instance ID

        Returns:
            JSON object with collection result
        """
        try:
            Instance = request.env['saas.instance'].sudo()
            instance = Instance.browse(instance_id)

            if not instance.exists():
                return json_response({
                    'error': 'Not found',
                    'message': f'Instance {instance_id} not found'
                }, status=404)

            if instance.state != 'running':
                return json_response({
                    'error': 'Instance not running',
                    'message': f'Instance is in state: {instance.state}'
                }, status=400)

            # Trigger collection
            success = instance.collect_metrics()

            if success:
                # Return updated metrics
                data = self._format_instance_usage(instance, detailed=True)
                return json_response({
                    'success': True,
                    'message': 'Metrics collected successfully',
                    'data': data,
                })
            else:
                return json_response({
                    'success': False,
                    'message': 'Metric collection failed - check server logs',
                }, status=500)

        except Exception as e:
            _logger.error(f"Error in trigger_metric_collection: {e}")
            return json_response({
                'error': 'Internal error',
                'message': str(e)
            }, status=500)

    @http.route('/api/v1/usage/summary', type='http', auth='none', methods=['GET'], csrf=False)
    @rate_limit_required
    @api_key_required
    def get_platform_summary(self, **kwargs):
        """
        Get platform-wide usage summary.

        Returns:
            JSON object with aggregated platform metrics
        """
        try:
            Instance = request.env['saas.instance'].sudo()

            # Count instances by state
            states = {}
            for state in ['draft', 'pending', 'running', 'stopped', 'suspended', 'terminated', 'error']:
                states[state] = Instance.search_count([('state', '=', state)])

            # Get running instances for resource calculation
            running = Instance.search([('state', '=', 'running')])

            # Aggregate resource usage
            total_cpu = 0.0
            total_memory = 0.0
            total_disk = 0.0
            instances_with_metrics = 0

            for inst in running:
                if hasattr(inst, 'cpu_usage') and inst.cpu_usage:
                    total_cpu += inst.cpu_usage
                    instances_with_metrics += 1
                if hasattr(inst, 'memory_usage'):
                    total_memory += inst.memory_usage or 0
                if hasattr(inst, 'disk_usage'):
                    total_disk += inst.disk_usage or 0

            # Get server info
            Server = request.env['saas.tenant.server'].sudo()
            servers = Server.search([])
            server_info = []
            for server in servers:
                server_info.append({
                    'id': server.id,
                    'name': server.name,
                    'state': server.state,
                    'instance_count': Instance.search_count([
                        ('server_id', '=', server.id),
                        ('state', '=', 'running')
                    ]),
                })

            return json_response({
                'success': True,
                'data': {
                    'instances': {
                        'total': sum(states.values()),
                        'by_state': states,
                    },
                    'resources': {
                        'avg_cpu_percent': round(total_cpu / max(instances_with_metrics, 1), 2),
                        'avg_memory_percent': round(total_memory / max(instances_with_metrics, 1), 2),
                        'avg_disk_percent': round(total_disk / max(instances_with_metrics, 1), 2),
                        'instances_with_metrics': instances_with_metrics,
                    },
                    'servers': server_info,
                    'timestamp': request.env.cr.now().isoformat(),
                },
            })

        except Exception as e:
            _logger.error(f"Error in get_platform_summary: {e}")
            return json_response({
                'error': 'Internal error',
                'message': str(e)
            }, status=500)

    @http.route('/api/v1/usage/instance/<subdomain_or_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @rate_limit_required
    @api_key_required
    def get_instance_by_subdomain(self, subdomain_or_id, **kwargs):
        """
        Get usage for instance by subdomain or ID.

        Path parameters:
            subdomain_or_id: Instance subdomain (string) or ID (integer)

        Returns:
            JSON object with usage metrics
        """
        try:
            Instance = request.env['saas.instance'].sudo()

            # Try to parse as integer ID first
            try:
                instance_id = int(subdomain_or_id)
                instance = Instance.browse(instance_id)
            except ValueError:
                # Treat as subdomain
                instance = Instance.search([('subdomain', '=', subdomain_or_id)], limit=1)

            if not instance.exists():
                return json_response({
                    'error': 'Not found',
                    'message': f'Instance "{subdomain_or_id}" not found'
                }, status=404)

            data = self._format_instance_usage(instance, detailed=True)

            return json_response({
                'success': True,
                'data': data,
            })

        except Exception as e:
            _logger.error(f"Error in get_instance_by_subdomain: {e}")
            return json_response({
                'error': 'Internal error',
                'message': str(e)
            }, status=500)

    def _format_instance_usage(self, instance, detailed=False):
        """Format instance usage data for API response."""
        data = {
            'id': instance.id,
            'name': instance.name,
            'subdomain': instance.subdomain,
            'full_domain': instance.full_domain,
            'state': instance.state,
            'plan': instance.plan_id.name if instance.plan_id else None,
            'plan_id': instance.plan_id.id if instance.plan_id else None,
        }

        # Add resource usage if available
        if hasattr(instance, 'cpu_usage'):
            data['cpu_usage_percent'] = instance.cpu_usage or 0
        if hasattr(instance, 'memory_usage'):
            data['memory_usage_percent'] = instance.memory_usage or 0
        if hasattr(instance, 'disk_usage'):
            data['disk_usage_percent'] = instance.disk_usage or 0
        if hasattr(instance, 'user_count'):
            data['active_users'] = instance.user_count or 0

        # Add health status if available
        if hasattr(instance, 'health_status'):
            data['health_status'] = instance.health_status

        if detailed:
            # Add more details
            data['server'] = {
                'id': instance.server_id.id if instance.server_id else None,
                'name': instance.server_id.name if instance.server_id else None,
            }
            data['container'] = {
                'id': instance.container_id,
                'name': instance.container_name,
            }
            data['ports'] = {
                'http': instance.port_http if hasattr(instance, 'port_http') else None,
                'longpolling': instance.port_longpolling if hasattr(instance, 'port_longpolling') else None,
            }
            data['created_at'] = instance.create_date.isoformat() if instance.create_date else None

            # Add plan limits
            if instance.plan_id:
                plan = instance.plan_id
                data['limits'] = {
                    'users': getattr(plan, 'user_limit', 0),
                    'storage_db_gb': getattr(plan, 'storage_db_limit_gb', 0),
                    'storage_files_gb': getattr(plan, 'storage_files_limit_gb', 0),
                    'ram_mb': getattr(plan, 'ram_limit_mb', 0),
                    'cpu_cores': getattr(plan, 'cpu_limit', 0),
                }

            # Add current metrics from usage_metric_ids if available
            if hasattr(instance, 'usage_metric_ids'):
                metrics = {}
                for metric in instance.usage_metric_ids:
                    metrics[metric.metric_code] = {
                        'current': metric.current_value,
                        'limit': metric.limit_value,
                        'percent': metric.usage_percent,
                        'status': metric.status,
                        'last_updated': metric.last_updated.isoformat() if metric.last_updated else None,
                    }
                data['metrics'] = metrics

            # Add alerts if available
            if hasattr(instance, 'active_alert_count'):
                data['alerts'] = {
                    'active': instance.active_alert_count,
                    'total': instance.total_alert_count if hasattr(instance, 'total_alert_count') else 0,
                }

        return data
