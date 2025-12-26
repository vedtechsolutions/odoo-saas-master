# -*- coding: utf-8 -*-
"""
Portal controllers for SaaS customer self-service.
"""

from collections import OrderedDict
from operator import itemgetter

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError


class SaasPortal(CustomerPortal):
    """Customer portal for SaaS services."""

    def _prepare_home_portal_values(self, counters):
        """Add SaaS counters to portal home."""
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'instance_count' in counters:
            values['instance_count'] = request.env['saas.instance'].search_count([
                ('partner_id', '=', partner.id),
                ('state', 'not in', ['terminated']),
            ])

        if 'subscription_count' in counters:
            values['subscription_count'] = request.env['saas.subscription'].search_count([
                ('partner_id', '=', partner.id),
                ('state', 'not in', ['cancelled', 'expired']),
            ])

        if 'ticket_count' in counters:
            values['ticket_count'] = request.env['saas.ticket'].search_count([
                ('partner_id', '=', partner.id),
            ])

        return values

    # ==================== INSTANCES ====================

    def _instance_get_page_view_values(self, instance, access_token, **kwargs):
        """Prepare values for instance detail page."""
        values = {
            'instance': instance,
            'page_name': 'instance',
            'user': request.env.user,
        }
        return self._get_page_view_values(
            instance, access_token, values, 'my_instances_history', False, **kwargs
        )

    @http.route(['/my/instances', '/my/instances/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_instances(self, page=1, sortby=None, filterby=None, **kw):
        """List customer instances."""
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        Instance = request.env['saas.instance']

        domain = [
            ('partner_id', '=', partner.id),
            ('state', 'not in', ['terminated']),
        ]

        # Sorting
        searchbar_sortings = {
            'date': {'label': _('Newest First'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'name'},
            'state': {'label': _('Status'), 'order': 'state'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # Filtering
        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'running': {'label': _('Running'), 'domain': [('state', '=', 'running')]},
            'stopped': {'label': _('Stopped'), 'domain': [('state', '=', 'stopped')]},
        }
        if not filterby:
            filterby = 'all'
        domain = domain + searchbar_filters[filterby]['domain']

        # Count
        instance_count = Instance.search_count(domain)

        # Pager
        pager = portal_pager(
            url='/my/instances',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=instance_count,
            page=page,
            step=self._items_per_page,
        )

        # Get instances
        instances = Instance.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager['offset'],
        )

        values.update({
            'instances': instances,
            'page_name': 'instances',
            'default_url': '/my/instances',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items(), key=lambda x: x[1]['label'])),
            'filterby': filterby,
        })

        return request.render('saas_portal.portal_my_instances', values)

    @http.route(['/my/instances/<int:instance_id>'],
                type='http', auth='user', website=True)
    def portal_my_instance(self, instance_id, access_token=None, **kw):
        """Instance detail page."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = self._instance_get_page_view_values(instance_sudo, access_token, **kw)
        return request.render('saas_portal.portal_my_instance', values)

    @http.route(['/my/instances/<int:instance_id>/action/<string:action>'],
                type='http', auth='user', website=True)
    def portal_instance_action(self, instance_id, action, access_token=None, **kw):
        """Handle instance actions from portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        # Perform action
        if action == 'start' and instance_sudo.state == 'stopped':
            instance_sudo.action_start()
        elif action == 'stop' and instance_sudo.state == 'running':
            instance_sudo.action_stop()
        elif action == 'restart' and instance_sudo.state == 'running':
            instance_sudo.action_restart()

        return request.redirect(f'/my/instances/{instance_id}')

    # ==================== SUBSCRIPTIONS ====================

    def _subscription_get_page_view_values(self, subscription, access_token, **kwargs):
        """Prepare values for subscription detail page."""
        values = {
            'subscription': subscription,
            'page_name': 'subscription',
            'user': request.env.user,
        }
        return self._get_page_view_values(
            subscription, access_token, values, 'my_subscriptions_history', False, **kwargs
        )

    @http.route(['/my/subscriptions', '/my/subscriptions/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_subscriptions(self, page=1, sortby=None, filterby=None, **kw):
        """List customer subscriptions."""
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        Subscription = request.env['saas.subscription']

        domain = [('partner_id', '=', partner.id)]

        # Sorting
        searchbar_sortings = {
            'date': {'label': _('Newest First'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'name'},
            'state': {'label': _('Status'), 'order': 'state'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # Filtering
        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'active': {'label': _('Active'), 'domain': [('state', 'in', ['trial', 'active'])]},
            'inactive': {'label': _('Inactive'), 'domain': [('state', 'in', ['cancelled', 'expired', 'suspended'])]},
        }
        if not filterby:
            filterby = 'all'
        domain = domain + searchbar_filters[filterby]['domain']

        # Count
        subscription_count = Subscription.search_count(domain)

        # Pager
        pager = portal_pager(
            url='/my/subscriptions',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=subscription_count,
            page=page,
            step=self._items_per_page,
        )

        # Get subscriptions
        subscriptions = Subscription.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager['offset'],
        )

        values.update({
            'subscriptions': subscriptions,
            'page_name': 'subscriptions',
            'default_url': '/my/subscriptions',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items(), key=lambda x: x[1]['label'])),
            'filterby': filterby,
        })

        return request.render('saas_portal.portal_my_subscriptions', values)

    @http.route(['/my/subscriptions/<int:subscription_id>'],
                type='http', auth='user', website=True)
    def portal_my_subscription(self, subscription_id, access_token=None, **kw):
        """Subscription detail page."""
        try:
            subscription_sudo = self._document_check_access(
                'saas.subscription', subscription_id, access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = self._subscription_get_page_view_values(subscription_sudo, access_token, **kw)
        return request.render('saas_portal.portal_my_subscription', values)

    # ==================== TICKETS ====================

    def _ticket_get_page_view_values(self, ticket, access_token, **kwargs):
        """Prepare values for ticket detail page."""
        values = {
            'ticket': ticket,
            'page_name': 'ticket',
            'user': request.env.user,
        }
        return self._get_page_view_values(
            ticket, access_token, values, 'my_tickets_history', False, **kwargs
        )

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_tickets(self, page=1, sortby=None, filterby=None, **kw):
        """List customer tickets."""
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        Ticket = request.env['saas.ticket']

        domain = [('partner_id', '=', partner.id)]

        # Sorting
        searchbar_sortings = {
            'date': {'label': _('Newest First'), 'order': 'create_date desc'},
            'name': {'label': _('Subject'), 'order': 'name'},
            'state': {'label': _('Status'), 'order': 'state'},
            'priority': {'label': _('Priority'), 'order': 'priority desc'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # Filtering
        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'open': {'label': _('Open'), 'domain': [('state', 'in', ['new', 'open', 'in_progress', 'pending'])]},
            'closed': {'label': _('Closed'), 'domain': [('state', 'in', ['resolved', 'closed'])]},
        }
        if not filterby:
            filterby = 'all'
        domain = domain + searchbar_filters[filterby]['domain']

        # Count
        ticket_count = Ticket.search_count(domain)

        # Pager
        pager = portal_pager(
            url='/my/tickets',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=ticket_count,
            page=page,
            step=self._items_per_page,
        )

        # Get tickets
        tickets = Ticket.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager['offset'],
        )

        values.update({
            'tickets': tickets,
            'page_name': 'tickets',
            'default_url': '/my/tickets',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items(), key=lambda x: x[1]['label'])),
            'filterby': filterby,
        })

        return request.render('saas_portal.portal_my_tickets', values)

    @http.route(['/my/tickets/<int:ticket_id>'],
                type='http', auth='user', website=True)
    def portal_my_ticket(self, ticket_id, access_token=None, **kw):
        """Ticket detail page."""
        try:
            ticket_sudo = self._document_check_access(
                'saas.ticket', ticket_id, access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = self._ticket_get_page_view_values(ticket_sudo, access_token, **kw)

        # Get categories for new ticket form
        values['categories'] = request.env['saas.ticket.category'].sudo().search([
            ('active', '=', True)
        ])

        return request.render('saas_portal.portal_my_ticket', values)

    @http.route(['/my/tickets/new'], type='http', auth='user', website=True)
    def portal_new_ticket(self, **kw):
        """New ticket form."""
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id

        # Get categories
        categories = request.env['saas.ticket.category'].sudo().search([
            ('active', '=', True)
        ])

        # Get customer's instances for reference
        instances = request.env['saas.instance'].search([
            ('partner_id', '=', partner.id),
            ('state', 'not in', ['terminated']),
        ])

        values.update({
            'page_name': 'new_ticket',
            'categories': categories,
            'instances': instances,
            'error': {},
            'error_message': [],
            'post': {},
        })

        return request.render('saas_portal.portal_new_ticket', values)

    @http.route(['/my/tickets/create'], type='http', auth='user', website=True, methods=['POST'])
    def portal_create_ticket(self, **post):
        """Create ticket from portal."""
        partner = request.env.user.partner_id

        # Validate
        error = {}
        error_message = []

        if not post.get('name'):
            error['name'] = True
            error_message.append(_('Subject is required.'))

        if not post.get('description'):
            error['description'] = True
            error_message.append(_('Description is required.'))

        if error:
            values = self._prepare_portal_layout_values()
            categories = request.env['saas.ticket.category'].sudo().search([
                ('active', '=', True)
            ])
            instances = request.env['saas.instance'].search([
                ('partner_id', '=', partner.id),
                ('state', 'not in', ['terminated']),
            ])
            values.update({
                'page_name': 'new_ticket',
                'categories': categories,
                'instances': instances,
                'error': error,
                'error_message': error_message,
                'post': post,
            })
            return request.render('saas_portal.portal_new_ticket', values)

        # Create ticket
        ticket_vals = {
            'name': post.get('name'),
            'description': post.get('description'),
            'partner_id': partner.id,
            'priority': post.get('priority', '1'),
        }

        if post.get('category_id'):
            ticket_vals['category_id'] = int(post['category_id'])

        if post.get('instance_id'):
            ticket_vals['instance_id'] = int(post['instance_id'])

        ticket = request.env['saas.ticket'].sudo().create(ticket_vals)

        return request.redirect(f'/my/tickets/{ticket.id}?message=created')

    @http.route(['/my/tickets/<int:ticket_id>/reply'], type='http', auth='user', website=True, methods=['POST'])
    def portal_ticket_reply(self, ticket_id, **post):
        """Add reply to ticket from portal."""
        try:
            ticket_sudo = self._document_check_access('saas.ticket', ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if post.get('message'):
            ticket_sudo.portal_add_message(post['message'])

        return request.redirect(f'/my/tickets/{ticket_id}')

    @http.route(['/my/tickets/<int:ticket_id>/close'], type='http', auth='user', website=True)
    def portal_ticket_close(self, ticket_id, **kw):
        """Close ticket from portal."""
        try:
            ticket_sudo = self._document_check_access('saas.ticket', ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if ticket_sudo.state == 'resolved':
            ticket_sudo.action_close()

        return request.redirect(f'/my/tickets/{ticket_id}')

    @http.route(['/my/tickets/<int:ticket_id>/reopen'], type='http', auth='user', website=True)
    def portal_ticket_reopen(self, ticket_id, **kw):
        """Reopen ticket from portal."""
        try:
            ticket_sudo = self._document_check_access('saas.ticket', ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if ticket_sudo.state in ['resolved', 'closed']:
            ticket_sudo.action_reopen()

        return request.redirect(f'/my/tickets/{ticket_id}')

    # ==================== BACKUPS (Read-Only) ====================

    @http.route(['/my/instances/<int:instance_id>/backups',
                 '/my/instances/<int:instance_id>/backups/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_instance_backups(self, instance_id, page=1, sortby=None, **kw):
        """List backups for an instance (read-only view)."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = self._prepare_portal_layout_values()
        Backup = request.env['saas.backup'].sudo()

        domain = [
            ('instance_id', '=', instance_id),
            ('state', 'in', ['completed', 'pending', 'in_progress']),
        ]

        # Sorting
        searchbar_sortings = {
            'date': {'label': _('Newest First'), 'order': 'create_date desc'},
            'size': {'label': _('Size'), 'order': 'total_size desc'},
            'state': {'label': _('Status'), 'order': 'state'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # Count
        backup_count = Backup.search_count(domain)

        # Pager
        pager = portal_pager(
            url=f'/my/instances/{instance_id}/backups',
            url_args={'sortby': sortby},
            total=backup_count,
            page=page,
            step=self._items_per_page,
        )

        # Get backups
        backups = Backup.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager['offset'],
        )

        values.update({
            'instance': instance_sudo,
            'backups': backups,
            'page_name': 'instance_backups',
            'default_url': f'/my/instances/{instance_id}/backups',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
        })

        return request.render('saas_portal.portal_instance_backups', values)

    @http.route(['/my/instances/<int:instance_id>/backups/<int:backup_id>/download'],
                type='http', auth='user', website=True)
    def portal_backup_download(self, instance_id, backup_id, **kw):
        """Download a backup (S3 presigned URL redirect)."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        # Get backup and verify it belongs to this instance
        Backup = request.env['saas.backup'].sudo()
        backup = Backup.browse(backup_id)

        if not backup.exists() or backup.instance_id.id != instance_id:
            return request.redirect(f'/my/instances/{instance_id}/backups?error=not_found')

        if backup.state != 'completed':
            return request.redirect(f'/my/instances/{instance_id}/backups?error=not_ready')

        # Only S3 backups can be downloaded via portal
        if backup.storage_type != 's3':
            return request.redirect(f'/my/instances/{instance_id}/backups?error=local_only')

        # Generate presigned URL (1 hour expiry)
        download_url = backup._generate_s3_presigned_url(expiration=3600)

        if not download_url:
            return request.redirect(f'/my/instances/{instance_id}/backups?error=url_failed')

        # Redirect to S3 download
        return request.redirect(download_url)

    # ==================== SUBSCRIPTION UPGRADE/DOWNGRADE ====================

    @http.route(['/my/subscriptions/<int:subscription_id>/change-plan'],
                type='http', auth='user', website=True)
    def portal_subscription_change_plan(self, subscription_id, **kw):
        """Show available plans for upgrade/downgrade."""
        try:
            subscription_sudo = self._document_check_access(
                'saas.subscription', subscription_id
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        # Only allow plan change for active/trial subscriptions
        if subscription_sudo.state not in ['trial', 'active']:
            return request.redirect(
                f'/my/subscriptions/{subscription_id}?error=cannot_change_plan'
            )

        values = self._prepare_portal_layout_values()

        # Get available plans (excluding current plan)
        Plan = request.env['saas.plan'].sudo()
        available_plans = Plan.search([
            ('id', '!=', subscription_sudo.plan_id.id),
        ], order='monthly_price')

        values.update({
            'subscription': subscription_sudo,
            'current_plan': subscription_sudo.plan_id,
            'available_plans': available_plans,
            'page_name': 'change_plan',
            'error': kw.get('error'),
        })

        return request.render('saas_portal.portal_subscription_change_plan', values)

    @http.route(['/my/subscriptions/<int:subscription_id>/calculate-proration'],
                type='http', auth='user', website=True, methods=['POST'])
    def portal_calculate_proration(self, subscription_id, **post):
        """Calculate proration for plan change and show confirmation."""
        try:
            subscription_sudo = self._document_check_access(
                'saas.subscription', subscription_id
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        new_plan_id = post.get('new_plan_id')
        if not new_plan_id:
            return request.redirect(
                f'/my/subscriptions/{subscription_id}/change-plan?error=no_plan_selected'
            )

        Plan = request.env['saas.plan'].sudo()
        new_plan = Plan.browse(int(new_plan_id))

        if not new_plan.exists():
            return request.redirect(
                f'/my/subscriptions/{subscription_id}/change-plan?error=invalid_plan'
            )

        # Calculate proration
        ProrationCalc = request.env['saas.proration.calculator'].sudo()
        calc = ProrationCalc.create({
            'subscription_id': subscription_sudo.id,
            'new_plan_id': new_plan.id,
        })

        values = self._prepare_portal_layout_values()
        values.update({
            'subscription': subscription_sudo,
            'current_plan': subscription_sudo.plan_id,
            'new_plan': new_plan,
            'proration': calc,
            'page_name': 'confirm_plan_change',
        })

        return request.render('saas_portal.portal_subscription_confirm_change', values)

    @http.route(['/my/subscriptions/<int:subscription_id>/apply-plan-change'],
                type='http', auth='user', website=True, methods=['POST'])
    def portal_apply_plan_change(self, subscription_id, **post):
        """Apply the plan change with proration."""
        try:
            subscription_sudo = self._document_check_access(
                'saas.subscription', subscription_id
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        new_plan_id = post.get('new_plan_id')
        if not new_plan_id:
            return request.redirect(
                f'/my/subscriptions/{subscription_id}/change-plan?error=no_plan_selected'
            )

        Plan = request.env['saas.plan'].sudo()
        new_plan = Plan.browse(int(new_plan_id))

        if not new_plan.exists():
            return request.redirect(
                f'/my/subscriptions/{subscription_id}/change-plan?error=invalid_plan'
            )

        # Create proration calculator and apply change
        ProrationCalc = request.env['saas.proration.calculator'].sudo()
        calc = ProrationCalc.create({
            'subscription_id': subscription_sudo.id,
            'new_plan_id': new_plan.id,
        })

        try:
            calc.action_apply_change()
            return request.redirect(
                f'/my/subscriptions/{subscription_id}?message=plan_changed'
            )
        except Exception as e:
            return request.redirect(
                f'/my/subscriptions/{subscription_id}/change-plan?error={str(e)}'
            )
