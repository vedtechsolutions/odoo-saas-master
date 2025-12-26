# -*- coding: utf-8 -*-

import logging
from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.fields import Domain

# Import validation tools
from odoo.addons.payment_powertranz.tools.validation import (
    validate_request_parameters, sanitize_input, validate_recurring_data
)

_logger = logging.getLogger(__name__)

class PowertranzPortal(CustomerPortal):
    """PowerTranz Portal Controller for recurring payment management."""
    
    def _enforce_https(self):
        """Enforce HTTPS for payment endpoints.
        
        This method checks if the current request is using HTTPS.
        If not, it checks if we're in development mode or using a local/development domain.
        In production, it returns a redirect to the portal home page with an error message.
        
        Returns:
            werkzeug.Response or None: Redirect response if not HTTPS in production, None otherwise
        """
        # Log detailed connection information for debugging
        _logger.info(
            "Connection details - Scheme: %s, Host: %s, Path: %s, Headers: %s",
            request.httprequest.scheme,
            request.httprequest.host,
            request.httprequest.path,
            {k: v for k, v in request.httprequest.headers.items() if k.lower() in ['x-forwarded-proto', 'x-forwarded-for', 'x-real-ip', 'host']}
        )
        
        # Check for secure connection, considering proxy headers
        is_secure = request.httprequest.scheme == 'https'
        
        # Also check X-Forwarded-Proto header which is set by proxies
        forwarded_proto = request.httprequest.headers.get('X-Forwarded-Proto')
        if forwarded_proto:
            is_secure = is_secure or forwarded_proto.lower() == 'https'
        
        if not is_secure:
            # Get the current domain
            host = request.httprequest.host.split(':')[0]
            
            # Check if we're in a development/test environment
            is_dev_environment = (
                host in ['localhost', '127.0.0.1'] or  # Local development
                '.test' in host or                     # Test domain
                '.dev' in host or                      # Dev domain
                '.local' in host or                    # Local domain
                host == 'ja.klutchjaorganics.com' or   # Add your specific domain
                request.env['ir.config_parameter'].sudo().get_param('web.base.url').startswith('http://') # System configured for HTTP
            )
            
            # Log the attempt but allow it in development environments
            if is_dev_environment:
                _logger.info(
                    "HTTP connection to payment endpoint %s allowed for domain %s",
                    request.httprequest.path,
                    host
                )
                return None
            
            # In production, enforce HTTPS
            _logger.warning(
                "Insecure connection attempt (HTTP) to payment endpoint %s from %s",
                request.httprequest.path,
                request.httprequest.remote_addr
            )
            return request.redirect('/my?error_message=' + _('Secure connection required for payment operations.'))
        
        # Connection is secure, proceed normally
        return None
    
    def _prepare_home_portal_values(self, counters):
        """Prepare portal home values with recurring payment counter."""
        values = super()._prepare_home_portal_values(counters)

        if 'recurring_count' in counters:
            values['recurring_count'] = request.env['powertranz.recurring'].search_count([
                ('partner_id', '=', request.env.user.partner_id.id),
                ('state', 'in', ['active', 'paused']),
            ])

        return values
    
    @http.route(['/my/recurring', '/my/recurring/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_recurring(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, search=None, search_in='all', **kw):
        """Display the list of recurring payments for the current user."""
        # Enforce HTTPS for this endpoint
        https_redirect = self._enforce_https()
        if https_redirect:
            return https_redirect
        
        # Sanitize input parameters
        page = int(sanitize_input(page)) if isinstance(page, str) and page.isdigit() else page
        date_begin = sanitize_input(date_begin)
        date_end = sanitize_input(date_end)
        sortby = sanitize_input(sortby)
        filterby = sanitize_input(filterby)
        search = sanitize_input(search)
        search_in = sanitize_input(search_in)
        
        # Validate parameters
        valid_search_in = ['all', 'name', 'reference']
        if search_in and search_in not in valid_search_in:
            search_in = 'all'
            
        values = self._prepare_portal_layout_values()
        RecurringPayment = request.env['powertranz.recurring']
        
        domain = [
            ('partner_id', '=', request.env.user.partner_id.id),
        ]
        
        # Filter by status
        if filterby == 'active':
            domain += [('state', '=', 'active')]
        elif filterby == 'paused':
            domain += [('state', '=', 'paused')]
        elif filterby == 'all':
            domain += [('state', 'in', ['active', 'paused', 'cancelled', 'completed'])]
        else:  # default: active and paused
            domain += [('state', 'in', ['active', 'paused'])]
            
        # Search
        if search and search_in:
            search_domain = []
            if search_in in ('all', 'name'):
                search_domain = Domain.OR([search_domain, [('name', 'ilike', search)]])
            if search_in in ('all', 'reference'):
                search_domain = Domain.OR([search_domain, [('powertranz_recurring_identifier', 'ilike', search)]])
            domain += search_domain
            
        # Count for pager
        recurring_count = RecurringPayment.search_count(domain)
        
        # Pager
        pager = portal_pager(
            url="/my/recurring",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby, 'filterby': filterby, 'search': search, 'search_in': search_in},
            total=recurring_count,
            page=page,
            step=self._items_per_page
        )
        
        # Default order by
        if not sortby:
            sortby = 'date'
        sort_order = 'create_date desc'
        if sortby == 'amount':
            sort_order = 'amount desc'
        elif sortby == 'name':
            sort_order = 'name'
        elif sortby == 'next_date':
            sort_order = 'next_payment_date'
            
        # Content
        recurring_payments = RecurringPayment.search(
            domain,
            order=sort_order,
            limit=self._items_per_page,
            offset=pager['offset']
        )
        
        values.update({
            'recurring_payments': recurring_payments,
            'page_name': 'recurring',
            'pager': pager,
            'default_url': '/my/recurring',
            'searchbar_sortings': {
                'date': {'label': _('Date'), 'order': 'create_date desc'},
                'name': {'label': _('Reference'), 'order': 'name'},
                'amount': {'label': _('Amount'), 'order': 'amount desc'},
                'next_date': {'label': _('Next Payment'), 'order': 'next_payment_date'},
            },
            'searchbar_filters': {
                'all': {'label': _('All'), 'domain': [('state', 'in', ['active', 'paused', 'cancelled', 'completed'])]},
                'active': {'label': _('Active'), 'domain': [('state', '=', 'active')]},
                'paused': {'label': _('Paused'), 'domain': [('state', '=', 'paused')]},
                'active_paused': {'label': _('Active & Paused'), 'domain': [('state', 'in', ['active', 'paused'])]},
            },
            'searchbar_inputs': {
                'all': {'input': 'all', 'label': _('Search in All')},
                'name': {'input': 'name', 'label': _('Search in Reference')},
                'reference': {'input': 'reference', 'label': _('Search in PowerTranz Reference')},
            },
            'sortby': sortby,
            'filterby': filterby or 'active_paused',
            'search': search,
            'search_in': search_in,
        })
        
        return request.render("payment_powertranz.portal_my_recurring_payments", values)
    
    @http.route(['/my/recurring/<int:recurring_id>'], type='http', auth="user", website=True)
    def portal_recurring_detail(self, recurring_id, **kw):
        """Display the detail of a recurring payment."""
        # Enforce HTTPS for this endpoint
        https_redirect = self._enforce_https()
        if https_redirect:
            return https_redirect
        
        # Sanitize and validate recurring_id
        try:
            recurring_id = int(sanitize_input(recurring_id)) if isinstance(recurring_id, str) else recurring_id
            if recurring_id <= 0:
                return request.redirect('/my/recurring')
        except (ValueError, TypeError):
            return request.redirect('/my/recurring')
            
        try:
            recurring_sudo = self._document_check_access('powertranz.recurring', recurring_id)
        except (AccessError, MissingError):
            return request.redirect('/my/recurring')
            
        values = {
            'page_name': 'recurring',
            'recurring': recurring_sudo,
        }
        
        # Get transaction history
        values['transactions'] = recurring_sudo.transaction_ids.sorted(key=lambda r: r.create_date, reverse=True)
        
        return request.render("payment_powertranz.portal_recurring_detail", values)
    
    @http.route(['/my/recurring/action/<int:recurring_id>/<string:action>'], type='http', auth="user", website=True)
    def portal_recurring_action(self, recurring_id, action, **kw):
        """Handle actions on recurring payments (pause, resume, cancel)."""
        # Enforce HTTPS for this endpoint
        https_redirect = self._enforce_https()
        if https_redirect:
            return https_redirect
        
        # Sanitize and validate input parameters
        recurring_id = int(sanitize_input(recurring_id)) if isinstance(recurring_id, str) and recurring_id.isdigit() else recurring_id
        action = sanitize_input(action)
        
        # Validate action parameter
        valid_actions = ['pause', 'resume', 'cancel']
        if action not in valid_actions:
            _logger.warning("Invalid recurring payment action attempted: %s", action)
            return request.redirect('/my/recurring')
            
        try:
            recurring_sudo = self._document_check_access('powertranz.recurring', recurring_id)
        except (AccessError, MissingError):
            return request.redirect('/my/recurring')
            
        # Process the action
        try:
            if action == 'pause' and recurring_sudo.state == 'active':
                recurring_sudo.action_pause()
            elif action == 'resume' and recurring_sudo.state == 'paused':
                recurring_sudo.action_resume()
            elif action == 'cancel' and recurring_sudo.state in ['active', 'paused']:
                recurring_sudo.action_cancel()
            else:
                _logger.warning(
                    "Invalid state transition attempted: action=%s, current_state=%s", 
                    action, recurring_sudo.state
                )
        except Exception as e:
            _logger.exception("Error processing recurring payment action: %s", e)
        
        return request.redirect('/my/recurring/%s' % recurring_id)
