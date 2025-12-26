# -*- coding: utf-8 -*-
"""
Extend Sale Order for SaaS provisioning.

Uses async queue-based provisioning to avoid blocking payment flow
and serialization errors during concurrent transactions.
"""

import logging

from odoo import models, fields, api, SUPERUSER_ID

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.states import InstanceState, SubscriptionState

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    """Extend Sale Order with SaaS provisioning."""

    _inherit = 'sale.order'

    # SaaS related fields
    saas_instance_ids = fields.One2many(
        ModelNames.INSTANCE,
        'sale_order_id',
        string='SaaS Instances',
        help='Instances provisioned from this order',
    )
    saas_instance_count = fields.Integer(
        string='Instance Count',
        compute='_compute_saas_instance_count',
    )
    has_saas_products = fields.Boolean(
        string='Has SaaS Products',
        compute='_compute_has_saas_products',
        search='_search_has_saas_products',
        store=False,  # Non-stored to avoid write conflicts during cart updates
    )
    saas_provisioning_state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('failed', 'Failed'),
        ],
        string='Provisioning State',
        default=False,  # No default - only set when order is confirmed
        help='State of SaaS instance provisioning',
    )

    @api.depends('saas_instance_ids')
    def _compute_saas_instance_count(self):
        for order in self:
            order.saas_instance_count = len(order.saas_instance_ids)

    @api.depends('order_line.product_id.is_saas_plan', 'order_line.product_id.is_saas_addon')
    def _compute_has_saas_products(self):
        for order in self:
            order.has_saas_products = any(
                line.product_id.product_tmpl_id.is_saas_plan or
                line.product_id.product_tmpl_id.is_saas_addon
                for line in order.order_line
                if line.product_id
            )

    def _search_has_saas_products(self, operator, value):
        """Search method to allow filtering by has_saas_products in domains."""
        # Normalize the search condition
        if operator == '=' and value is True:
            search_positive = True
        elif operator == '=' and value is False:
            search_positive = False
        elif operator == '!=' and value is True:
            search_positive = False
        elif operator == '!=' and value is False:
            search_positive = True
        else:
            search_positive = bool(value)

        # Find orders with SaaS products via subquery on order lines
        self.env.cr.execute("""
            SELECT DISTINCT so.id
            FROM sale_order so
            JOIN sale_order_line sol ON sol.order_id = so.id
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pt.is_saas_plan = TRUE OR pt.is_saas_addon = TRUE
        """)
        order_ids = [row[0] for row in self.env.cr.fetchall()]

        if search_positive:
            return [('id', 'in', order_ids)]
        else:
            return [('id', 'not in', order_ids)]

    def action_confirm(self):
        """Override to queue SaaS provisioning after order confirmation."""
        res = super().action_confirm()

        for order in self:
            if order.has_saas_products:
                # Queue provisioning - don't do it synchronously
                order._queue_saas_provisioning()

        return res

    def _queue_saas_provisioning(self):
        """Queue SaaS instance provisioning for async processing."""
        self.ensure_one()

        # Mark as pending provisioning
        self.write({'saas_provisioning_state': 'pending'})

        _logger.info(f"Queued SaaS provisioning for order {self.name}")

        # Trigger immediate processing via new transaction
        # This runs after current transaction commits
        self.env.cr.postcommit.add(
            lambda: self._trigger_async_provisioning()
        )

    def _trigger_async_provisioning(self):
        """Trigger async provisioning in a new transaction."""
        try:
            # Use a new cursor to avoid transaction conflicts
            with self.env.registry.cursor() as new_cr:
                new_env = api.Environment(new_cr, SUPERUSER_ID, {})
                order = new_env['sale.order'].browse(self.id)
                if order.exists() and order.saas_provisioning_state == 'pending':
                    order._provision_saas_instances_safe()
                    new_cr.commit()
        except Exception as e:
            _logger.error(f"Async provisioning failed for order {self.id}: {e}")

    def _provision_saas_instances_safe(self):
        """Provision SaaS instances with proper error handling.

        Workflow:
        1. Create and post invoice FIRST
        2. Send invoice to customer
        3. Create subscription (pending) and mark as paid
        4. Create instance and queue provisioning
        5. Welcome email is sent after provisioning completes (in queue)
        """
        self.ensure_one()

        # Mark as processing
        self.write({'saas_provisioning_state': 'processing'})
        self.env.cr.commit()

        # STEP 1: Create and post invoice FIRST (before provisioning)
        invoice = None
        if self.invoice_status == 'to invoice':
            invoice = self._create_and_send_invoice()
            if invoice:
                _logger.info(f"Invoice {invoice.name} created and sent for order {self.name}")

        Instance = self.env[ModelNames.INSTANCE]
        Subscription = self.env[ModelNames.SUBSCRIPTION]

        all_success = True

        for line in self.order_line:
            if not line.product_id:
                continue

            product = line.product_id.product_tmpl_id

            # Only process SaaS plan products
            if not product.is_saas_plan or not product.saas_plan_id:
                continue

            plan = product.saas_plan_id
            subdomain = line.saas_subdomain

            if not subdomain:
                _logger.warning(
                    f"Order {self.name} line {line.id}: No subdomain specified for plan {plan.code}"
                )
                continue

            # Validate customer email is available
            admin_email = self.partner_id.email or self.partner_invoice_id.email
            if not admin_email:
                _logger.error(
                    f"Order {self.name}: No email address for customer {self.partner_id.name}"
                )
                all_success = False
                continue

            # Check if instance already exists for this line
            existing = Instance.search([
                ('sale_order_line_id', '=', line.id)
            ], limit=1)
            if existing:
                _logger.info(
                    f"Instance already exists for order line {line.id}: {existing.subdomain}"
                )
                continue

            # Get billing cycle
            billing_cycle = 'monthly'
            try:
                billing_cycle = line.product_id._get_billing_cycle() or 'monthly'
            except Exception as e:
                _logger.debug(f"Could not get billing cycle for product {line.product_id.name}: {e}")

            # Determine trial status
            is_trial = plan.is_trial

            # Create a queue task early to track this provisioning attempt
            # This ensures failures are visible in Failed Tasks even if instance creation fails
            Queue = self.env[ModelNames.QUEUE]
            queue_task = None
            try:
                queue_task = Queue.create({
                    'action': 'provision',
                    'sale_order_id': self.id,
                    'priority': '2',  # High priority for new instances
                    'state': 'processing',
                })
                self.env.cr.commit()
            except Exception as q_err:
                _logger.warning(f"Could not create tracking queue task: {q_err}")

            try:
                # STEP 2: Create subscription FIRST (as pending)
                subscription_vals = {
                    'partner_id': self.partner_id.id,
                    'plan_id': plan.id,
                    'billing_cycle': billing_cycle,
                    'state': SubscriptionState.TRIAL if is_trial else SubscriptionState.DRAFT,
                    'payment_status': 'pending',
                }

                subscription = Subscription.with_context(
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                ).create(subscription_vals)
                self.env.cr.commit()
                _logger.info(f"Created subscription {subscription.reference}")

                # STEP 3: Mark subscription as paid (since payment was successful)
                if not is_trial:
                    subscription.action_activate()  # Sets state to ACTIVE
                    subscription.action_mark_paid()  # Sets payment_status to 'paid'
                    self.env.cr.commit()
                    _logger.info(f"Subscription {subscription.reference} marked as paid")

                # STEP 4: Create instance
                instance_vals = {
                    'name': f"{self.partner_id.name} - {subdomain}",
                    'subdomain': subdomain,
                    'partner_id': self.partner_id.id,
                    'plan_id': plan.id,
                    'odoo_version': line.saas_odoo_version or '19',
                    'is_trial': is_trial,
                    'admin_email': admin_email,
                    'sale_order_id': self.id,
                    'sale_order_line_id': line.id,
                }

                instance = Instance.create(instance_vals)
                self.env.cr.commit()
                _logger.info(f"Created instance {instance.subdomain} for order {self.name}")

                # Link subscription to instance
                subscription.write({'instance_id': instance.id})
                self.env.cr.commit()

                # Delete the tracking queue task - the real one will be created by action_provision
                if queue_task:
                    queue_task.unlink()
                    self.env.cr.commit()

                # STEP 5: Trigger provisioning (welcome email sent after completion)
                try:
                    instance.action_provision()
                    self.env.cr.commit()
                except Exception as prov_error:
                    _logger.warning(f"Provisioning trigger issue: {prov_error}")

            except Exception as e:
                import traceback
                error_tb = traceback.format_exc()
                _logger.error(f"Failed to provision instance for order {self.name}: {e}")
                all_success = False

                # Mark the tracking queue task as failed so it shows in Failed Tasks
                if queue_task:
                    try:
                        # Refresh the queue task (it was committed)
                        queue_task = Queue.browse(queue_task.id)
                        if queue_task.exists():
                            queue_task.write({
                                'state': 'failed',
                                'error_message': str(e),
                                'error_traceback': error_tb,
                                'completed_date': fields.Datetime.now(),
                            })
                            self.env.cr.commit()
                    except Exception as q_err:
                        _logger.warning(f"Could not update queue task with failure: {q_err}")

                self.env.cr.rollback()

        # Update final state
        final_state = 'done' if all_success else 'failed'
        self.write({'saas_provisioning_state': final_state})

    def _create_and_send_invoice(self):
        """Create, post, and send invoice to customer.

        Returns:
            account.move: The created invoice or None if failed
        """
        self.ensure_one()
        try:
            # Create invoice
            invoice = self._create_invoices()
            if not invoice:
                return None

            # Post the invoice
            invoice.action_post()
            _logger.info(f"Invoice {invoice.name} created and posted for order {self.name}")

            # Try to reconcile with existing payment
            self._reconcile_saas_payment(invoice)

            # Send invoice to customer via email with PDF attachment
            try:
                # Use Odoo's built-in invoice sending which includes PDF
                template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
                if template:
                    # Generate the invoice PDF report and attach it
                    report = self.env.ref('account.account_invoices', raise_if_not_found=False)
                    if report:
                        # Ensure report is attached to template
                        if report not in template.report_template_ids:
                            template.write({'report_template_ids': [(4, report.id)]})

                    # Send with attachment
                    template.send_mail(
                        invoice.id,
                        force_send=True,
                        email_values={'email_to': self.partner_id.email}
                    )
                    _logger.info(f"Invoice {invoice.name} with PDF sent to {self.partner_id.email}")
                else:
                    _logger.warning("Invoice email template not found")
            except Exception as mail_error:
                _logger.warning(f"Could not send invoice email: {mail_error}")

            return invoice

        except Exception as e:
            _logger.error(f"Failed to create invoice for order {self.name}: {e}")
            return None

    def _create_saas_invoice(self):
        """Deprecated - use _create_and_send_invoice instead."""
        return self._create_and_send_invoice()

    def _reconcile_saas_payment(self, invoice):
        """Reconcile invoice with payment from transaction."""
        self.ensure_one()
        try:
            # Get payment transaction
            transactions = self.transaction_ids.filtered(lambda t: t.state == 'done')
            if not transactions:
                return

            for tx in transactions:
                if tx.payment_id and invoice:
                    # Get receivable lines
                    payment_lines = tx.payment_id.move_id.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                    )
                    invoice_lines = invoice.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                    )
                    if payment_lines and invoice_lines:
                        (payment_lines + invoice_lines).reconcile()
                        _logger.info(f"Reconciled payment {tx.payment_id.name} with invoice {invoice.name}")
        except Exception as e:
            _logger.warning(f"Could not reconcile payment for order {self.name}: {e}")

    @api.model
    def cron_process_pending_provisioning(self):
        """Cron job to process pending SaaS provisioning."""
        # Query without has_saas_products (computed field, not stored)
        pending_orders = self.search([
            ('saas_provisioning_state', '=', 'pending'),
            ('state', '=', 'sale'),
        ], limit=20)

        # Filter in Python for orders with SaaS products
        saas_orders = pending_orders.filtered(lambda o: o.has_saas_products)

        for order in saas_orders[:10]:  # Process max 10 at a time
            try:
                order._provision_saas_instances_safe()
                self.env.cr.commit()
            except Exception as e:
                _logger.error(f"Cron provisioning failed for {order.name}: {e}")
                self.env.cr.rollback()

        return True

    def action_retry_provisioning(self):
        """Manual action to retry failed provisioning."""
        self.ensure_one()
        self.write({'saas_provisioning_state': 'pending'})
        self._provision_saas_instances_safe()
        return True

    def action_view_saas_instances(self):
        """View SaaS instances created from this order."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'SaaS Instances',
            'res_model': ModelNames.INSTANCE,
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'create': False},
        }
