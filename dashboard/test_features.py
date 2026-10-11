from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.utils import timezone

from .models import Activity, DirectMessage, Event, Expense, Invoice, Notification, Project, Task, UserPreference
from .services import calendar_context, month_offset, reports


class FeatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_superuser('owner', 'owner@example.test', 'test-password')
        cls.member = user_model.objects.create_user('member', password='test-password')
        cls.other = user_model.objects.create_user('other', password='test-password')

    def login(self, user=None):
        self.client.force_login(user or self.owner)

    def project_data(self, **changes):
        data = {'name': 'Real project', 'client': 'Real client', 'category': 'Web', 'status': 'active', 'progress': 25, 'budget': 5000, 'due_date': timezone.localdate().isoformat()}
        data.update(changes)
        return data

    def test_empty_reports_have_no_fabricated_metrics(self):
        result = reports()
        for key in ['project_count', 'paid_total', 'pending_total', 'expense_total', 'task_count', 'period_revenue', 'period_expense']:
            self.assertEqual(result[key], 0)
        self.assertEqual(result['categories'], [])
        self.assertIsNone(result['growth'])
        self.assertTrue(all(point['income'] == point['expense'] == 0 for point in result['chart_data']))
        response = self.client.get('/')
        self.assertNotContains(response, '۲۴۸٫۵')
        self.assertNotContains(response, 'داده نمایشی')

    def test_analytics_uses_payment_date_and_actual_expenses(self):
        today = timezone.localdate()
        last_month = month_offset(today, -1)
        Invoice.objects.create(number='P1', client='Client', amount=1000, status='paid', issued_at=last_month, paid_at=today)
        Invoice.objects.create(number='P2', client='Client', amount=9000, status='pending', issued_at=today)
        Expense.objects.create(title='Hosting', amount=300, spent_at=today)
        result = reports(3)
        self.assertEqual(result['paid_total'], 1000)
        self.assertEqual(result['pending_total'], 9000)
        self.assertEqual(result['period_expense'], 300)
        self.assertEqual(result['net_income'], 700)
        self.assertEqual(result['chart_data'][-1]['income'], 1000)
        self.assertEqual(result['chart_data'][-2]['income'], 0)

    def test_real_growth_and_category_distribution(self):
        today = timezone.localdate()
        for number, amount, paid in [('old', 100, month_offset(today, -3)), ('new', 150, today)]:
            Invoice.objects.create(number=number, client='Client', amount=amount, status='paid', issued_at=paid, paid_at=paid)
        for name, category in [('A', 'Web'), ('B', 'Web'), ('C', 'Brand')]:
            Project.objects.create(name=name, client='Client', category=category, due_date=today)
        result = reports(3)
        self.assertEqual(result['growth'], 50)
        self.assertEqual(result['categories'][0]['count'], 2)
        self.assertAlmostEqual(sum(row['percentage'] for row in result['categories']), 100, places=1)

    def test_crud_project_members_audit_and_notifications(self):
        self.login()
        self.assertRedirects(self.client.post('/projects/new/', self.project_data(members=[self.member.pk])), '/projects/')
        project = Project.objects.get(name='Real project')
        self.assertTrue(project.members.filter(pk=self.member.pk).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.member).exists())
        self.assertEqual(Activity.objects.count(), 1)
        self.assertRedirects(self.client.post(f'/records/project/{project.pk}/edit/', self.project_data(progress=90)), '/projects/')
        project.refresh_from_db()
        self.assertEqual(project.progress, 90)
        self.assertEqual(self.client.get(f'/projects/{project.pk}/').status_code, 200)
        # GET only confirms; POST performs deletion.
        self.assertEqual(self.client.get(f'/records/project/{project.pk}/delete/').status_code, 200)
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())
        self.assertRedirects(self.client.post(f'/records/project/{project.pk}/delete/'), '/projects/')
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())
        self.assertEqual(Activity.objects.count(), 3)

    def test_task_assignment_and_completion(self):
        self.login()
        response = self.client.post('/records/task/new/', {'title': 'Task', 'priority': 'high', 'assignee': self.member.pk, 'due_date': timezone.localdate()})
        self.assertRedirects(response, '/tasks/')
        task = Task.objects.get(title='Task')
        self.assertTrue(Notification.objects.filter(recipient=self.member, url='/tasks/').exists())
        self.assertRedirects(self.client.post(f'/tasks/{task.pk}/toggle/', {'return_to': 'tasks'}), '/tasks/')
        self.assertEqual(reports()['completed_task_count'], 1)

    def test_invoice_payment_is_idempotent_and_printable(self):
        self.login()
        today = timezone.localdate()
        self.assertRedirects(self.client.post('/records/invoice/new/', {'number': 'REAL-1', 'client': 'Client', 'amount': 800, 'status': 'pending', 'issued_at': today}), '/invoices/')
        invoice = Invoice.objects.get(number='REAL-1')
        self.assertEqual(self.client.get(f'/invoices/{invoice.pk}/').status_code, 200)
        for _ in range(2):
            self.assertRedirects(self.client.post(f'/invoices/{invoice.pk}/pay/'), '/invoices/')
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_at, today)
        self.assertEqual(reports()['paid_total'], 800)
        self.assertEqual(Activity.objects.filter(description__contains='ثبت پرداخت').count(), 1)

    def test_expense_create_edit_delete_and_report(self):
        self.login()
        data = {'title': 'Server', 'amount': 100, 'category': 'Infrastructure', 'spent_at': timezone.localdate()}
        self.assertRedirects(self.client.post('/records/expense/new/', data), '/expenses/')
        expense = Expense.objects.get()
        data['amount'] = 200
        self.assertRedirects(self.client.post(f'/records/expense/{expense.pk}/edit/', data), '/expenses/')
        self.assertEqual(reports()['expense_total'], 200)
        self.assertRedirects(self.client.post(f'/records/expense/{expense.pk}/delete/'), '/expenses/')
        self.assertEqual(reports()['expense_total'], 0)

    def test_event_validation_and_real_month_calendar(self):
        self.login()
        data = {'title': 'Meeting', 'start': '2028-02-29T10:00', 'end': '2028-02-29T09:00', 'participants': [self.member.pk]}
        self.assertEqual(self.client.post('/records/event/new/', data).status_code, 200)
        self.assertEqual(Event.objects.count(), 0)
        data['end'] = '2028-03-01T12:00'
        self.assertRedirects(self.client.post('/records/event/new/', data), '/calendar/')
        result = calendar_context(date(2028, 2, 1))
        days = [cell for cell in result['calendar_cells'] if cell['in_month']]
        self.assertEqual(len(days), 29)
        self.assertEqual(days[-1]['items'][0]['title'], 'Meeting')
        march = calendar_context(date(2028, 3, 1))
        self.assertEqual(next(cell for cell in march['calendar_cells'] if cell['date'] == date(2028, 3, 1))['items'][0]['title'], 'Meeting')
        self.assertTrue(Notification.objects.filter(recipient=self.member, url='/calendar/').exists())

    def test_calendar_includes_project_and_task_deadlines(self):
        today = timezone.localdate()
        Project.objects.create(name='Deadline project', client='Client', due_date=today)
        Task.objects.create(title='Deadline task', due_date=today)
        Invoice.objects.create(number='Due invoice', client='Client', amount=100, issued_at=today, due_date=today)
        result = calendar_context(today.replace(day=1))
        cell = next(cell for cell in result['calendar_cells'] if cell['date'] == today)
        self.assertEqual({item['kind'] for item in cell['items']}, {'task', 'project', 'invoice'})

    def test_private_pages_require_login(self):
        for url in ['/settings/', '/messages/', '/notifications/', '/messages/poll/?with=1']:
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_unprivileged_users_cannot_manage_records(self):
        self.login(self.member)
        for kind in ['project', 'invoice', 'expense', 'event', 'task']:
            self.assertEqual(self.client.post(f'/records/{kind}/new/', {}).status_code, 403)
        self.member.user_permissions.add(Permission.objects.get(codename='add_project'))
        self.client.force_login(self.member)
        self.assertRedirects(self.client.post('/projects/new/', self.project_data()), '/projects/')

    def test_preferences_and_profile_are_persisted_per_user(self):
        self.login(self.member)
        self.assertRedirects(self.client.post('/settings/', {'first_name': 'Member', 'last_name': 'One', 'email': 'member@example.test', 'theme': 'dark', 'direction': 'rtl'}), '/settings/')
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, 'Member')
        self.assertEqual(UserPreference.objects.get(user=self.member).theme, 'dark')
        self.assertContains(self.client.get('/'), 'data-theme="dark"')
        self.assertEqual(self.client.post('/preferences/update/', {'theme': 'bogus', 'direction': 'rtl'}).status_code, 400)
        self.assertEqual(UserPreference.objects.get(user=self.member).theme, 'dark')

    def test_messages_are_persistent_private_and_escaped(self):
        self.login(self.member)
        self.assertRedirects(self.client.post('/messages/', {'recipient': self.owner.pk, 'body': '<script>alert(1)</script>'}), f'/messages/?with={self.owner.pk}')
        message = DirectMessage.objects.get()
        self.assertEqual(message.sender, self.member)
        self.assertEqual(message.recipient, self.owner)
        self.assertTrue(Notification.objects.filter(recipient=self.owner).exists())
        self.assertNotContains(self.client.get(f'/messages/?with={self.owner.pk}'), '<script>alert(1)</script>')
        self.assertContains(self.client.get(f'/messages/?with={self.owner.pk}'), '&lt;script&gt;')
        self.login(self.other)
        self.assertEqual(self.client.get(f'/messages/poll/?with={self.owner.pk}').json()['messages'], [])
        self.login(self.owner)
        self.assertEqual(len(self.client.get(f'/messages/poll/?with={self.member.pk}').json()['messages']), 1)

    def test_read_acknowledges_only_visible_messages_and_own_notifications(self):
        first = DirectMessage.objects.create(sender=self.member, recipient=self.owner, body='First')
        second = DirectMessage.objects.create(sender=self.member, recipient=self.owner, body='Concurrent second')
        self.login(self.owner)
        self.client.post('/messages/read/', {'with': self.member.pk, 'through': first.pk})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNotNone(first.read_at)
        self.assertIsNone(second.read_at)
        foreign = Notification.objects.create(recipient=self.member, title='Private')
        self.assertEqual(self.client.post(f'/notifications/{foreign.pk}/read/').status_code, 404)

    def test_empty_message_and_self_message_rejected(self):
        self.login(self.member)
        self.assertEqual(self.client.post('/messages/', {'recipient': self.owner.pk, 'body': '   '}).status_code, 200)
        self.assertEqual(DirectMessage.objects.count(), 0)
        self.assertEqual(self.client.post('/messages/', {'recipient': self.member.pk, 'body': 'Self'}).status_code, 404)

    def test_pagination_status_filter_and_csv_filter(self):
        today = timezone.localdate()
        for index in range(12):
            Project.objects.create(name=f'Project {index}', client='Client', due_date=today)
        self.assertEqual(len(self.client.get('/projects/').context['items']), 10)
        self.assertEqual(len(self.client.get('/projects/?page=2').context['items']), 2)
        Invoice.objects.create(number='PAID', client='Client', amount=10, status='paid', issued_at=today)
        Invoice.objects.create(number='PENDING', client='Client', amount=20, issued_at=today)
        response = self.client.get('/invoices/export/?status=pending')
        self.assertIn('PENDING', response.content.decode('utf-8-sig'))
        self.assertNotIn('PAID', response.content.decode('utf-8-sig'))

    def test_csrf_blocks_mutations_without_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post('/records/project/new/', self.project_data()).status_code, 403)
        self.assertEqual(client.post('/messages/', {'recipient': self.member.pk, 'body': 'No token'}).status_code, 403)

    def test_clear_demo_keeps_users_and_custom_content(self):
        call_command('seed_demo', verbosity=0)
        Project.objects.create(name='Own project', client='Client', due_date=timezone.localdate())
        call_command('clear_demo', verbosity=0)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(Project.objects.get().name, 'Own project')
        self.assertTrue(get_user_model().objects.filter(username='owner').exists())

    def test_admin_has_live_summary_and_new_models(self):
        self.login()
        self.assertContains(self.client.get('/admin/'), 'admin-stats')
        for model in ['expense', 'event', 'notification', 'task', 'invoice', 'project', 'userpreference']:
            self.assertEqual(self.client.get(f'/admin/dashboard/{model}/').status_code, 200)

    def test_team_counts_do_not_multiply_with_multiple_relations(self):
        today = timezone.localdate()
        for index in range(2):
            project = Project.objects.create(name=f'Team project {index}', client='Client', due_date=today)
            project.members.add(self.member)
        for index in range(3):
            Task.objects.create(title=f'Assigned {index}', assignee=self.member)
        self.login()
        response = self.client.get('/team/?q=member')
        member = response.context['page_obj'].object_list[0]
        self.assertEqual(member.project_total, 2)
        self.assertEqual(member.task_total, 3)

    def test_project_delete_retains_related_financial_records(self):
        self.login()
        today = timezone.localdate()
        project = Project.objects.create(name='Archive project', client='Client', due_date=today)
        invoice = Invoice.objects.create(number='Retain', client='Client', amount=10, issued_at=today, project=project)
        task = Task.objects.create(title='Retain task', project=project)
        self.client.post(f'/records/project/{project.pk}/delete/')
        invoice.refresh_from_db()
        task.refresh_from_db()
        self.assertIsNone(invoice.project)
        self.assertIsNone(task.project)

    def test_task_and_project_validation_reject_invalid_progress_or_amount(self):
        self.login()
        response = self.client.post('/projects/new/', self.project_data(progress=101))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.exists())
        response = self.client.post('/records/expense/new/', {'title': 'Invalid expense', 'amount': -1, 'category': 'Hosting', 'spent_at': timezone.localdate()})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Expense.objects.exists())

    def test_password_change_keeps_session_and_replaces_password(self):
        self.login(self.member)
        response = self.client.post('/accounts/password/', {
            'old_password': 'test-password',
            'new_password1': 'Canopy-Unique-2026-Password!',
            'new_password2': 'Canopy-Unique-2026-Password!',
        })
        self.assertRedirects(response, '/settings/')
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('Canopy-Unique-2026-Password!'))
        self.assertEqual(self.client.get('/settings/').status_code, 200)
