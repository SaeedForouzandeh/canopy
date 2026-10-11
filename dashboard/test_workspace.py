import csv
import io

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from .models import Activity, Invoice, Notification, Project, ProjectComment, Task


class WorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_superuser('workspace-owner', '', 'test-password')
        cls.member = user_model.objects.create_user('workspace-member')
        cls.outsider = user_model.objects.create_user('workspace-outsider')
        cls.project = Project.objects.create(name='Workspace project', client='Client', due_date=timezone.localdate())
        cls.project.members.add(cls.member)

    def test_kanban_has_all_columns_and_statuses(self):
        Project.objects.create(name='Completed project', client='Client', due_date=timezone.localdate(), status='done')
        response = self.client.get('/projects/?layout=board')
        self.assertContains(response, 'kanban-grid')
        self.assertContains(response, 'Workspace project')
        self.assertContains(response, 'Completed project')
        self.assertEqual(len(response.context['board_columns']), 3)
        self.assertEqual(sum(column['count'] for column in response.context['board_columns']), 2)

    def test_kanban_columns_paginate_independently(self):
        for index in range(12):
            Project.objects.create(name=f'Active {index}', client='Client', due_date=timezone.localdate())
        Project.objects.create(name='Visible review', client='Client', due_date=timezone.localdate(), status='review')
        response = self.client.get('/projects/?layout=board&active_page=2')
        columns = {column['status']: column for column in response.context['board_columns']}
        self.assertEqual(len(columns['active']['page']), 3)
        self.assertEqual(columns['review']['count'], 1)
        self.assertContains(response, 'Visible review')

    def test_status_move_persists_and_logs_notification(self):
        self.client.force_login(self.owner)
        response = self.client.post(f'/projects/{self.project.pk}/status/', {'status': 'review', 'expected_status': 'active'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, 'review')
        self.assertEqual(Activity.objects.count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.member).exists())

    def test_status_move_rejects_invalid_and_stale_state(self):
        self.client.force_login(self.owner)
        for payload, expected in [({'status': 'unknown'}, 400), ({'status': 'done', 'expected_status': 'review'}, 409)]:
            response = self.client.post(f'/projects/{self.project.pk}/status/', payload, HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, expected)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, 'active')
        self.assertEqual(Activity.objects.count(), 0)

    def test_unprivileged_user_cannot_move_or_bulk_update(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(f'/projects/{self.project.pk}/status/', {'status': 'done'}).status_code, 403)
        self.assertEqual(self.client.post('/bulk/task/', {'ids': [1], 'action': 'complete'}).status_code, 403)

    def test_bulk_completion_and_assignment(self):
        self.client.force_login(self.owner)
        tasks = [Task.objects.create(title=f'Bulk {index}') for index in range(2)]
        ids = [task.pk for task in tasks]
        self.assertRedirects(self.client.post('/bulk/task/', {'ids': ids, 'action': 'assign', 'assignee': self.member.pk}), '/tasks/')
        self.assertEqual(Task.objects.filter(assignee=self.member).count(), 2)
        self.assertEqual(Notification.objects.filter(recipient=self.member).count(), 2)
        self.assertRedirects(self.client.post('/bulk/task/', {'ids': ids, 'action': 'complete'}), '/tasks/')
        self.assertEqual(Task.objects.filter(completed=True).count(), 2)
        self.assertRedirects(self.client.post('/bulk/task/', {'ids': ids, 'action': 'reopen'}), '/tasks/')
        self.assertEqual(Task.objects.filter(completed=True).count(), 0)

    def test_bulk_invalid_selection_changes_nothing(self):
        self.client.force_login(self.owner)
        task = Task.objects.create(title='Remain open')
        for payload in [
            {'ids': [task.pk, 999999], 'action': 'complete'},
            {'ids': ['bad'], 'action': 'complete'},
            {'ids': [], 'action': 'complete'},
            {'ids': [task.pk], 'action': 'assign', 'assignee': 'bad'},
            {'ids': [task.pk], 'action': 'delete'},
            {'ids': [task.pk] * 101, 'action': 'complete'},
        ]:
            self.assertEqual(self.client.post('/bulk/task/', payload).status_code, 400)
        task.refresh_from_db()
        self.assertFalse(task.completed)
        self.assertIsNone(task.assignee)
        self.assertFalse(Activity.objects.exists())

    def test_invoice_bulk_payment_is_idempotent(self):
        self.client.force_login(self.owner)
        invoice = Invoice.objects.create(number='BULK-1', client='Client', amount=500, issued_at=timezone.localdate())
        for _ in range(2):
            self.assertRedirects(self.client.post('/bulk/invoice/', {'ids': [invoice.pk], 'action': 'paid'}), '/invoices/')
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'paid')
        self.assertEqual(invoice.paid_at, timezone.localdate())
        self.assertEqual(Activity.objects.count(), 1)

    def test_project_comments_are_private_and_persistent(self):
        self.client.force_login(self.member)
        self.assertRedirects(self.client.post(f'/projects/{self.project.pk}/comments/', {'body': 'Private project discussion'}), f'/projects/{self.project.pk}/')
        self.assertContains(self.client.get(f'/projects/{self.project.pk}/'), 'Private project discussion')
        self.client.force_login(self.outsider)
        self.assertNotContains(self.client.get(f'/projects/{self.project.pk}/'), 'Private project discussion')
        self.assertEqual(self.client.post(f'/projects/{self.project.pk}/comments/', {'body': 'Unauthorized'}).status_code, 403)
        self.client.logout()
        self.assertNotContains(self.client.get(f'/projects/{self.project.pk}/'), 'Private project discussion')

    def test_comment_validation_escaping_and_delete_authorization(self):
        self.client.force_login(self.member)
        self.client.post(f'/projects/{self.project.pk}/comments/', {'body': '   '})
        self.client.post(f'/projects/{self.project.pk}/comments/', {'body': 'A' * 2501})
        self.assertFalse(ProjectComment.objects.exists())
        self.client.post(f'/projects/{self.project.pk}/comments/', {'body': '<script>unsafe</script>'})
        comment = ProjectComment.objects.get()
        response = self.client.get(f'/projects/{self.project.pk}/')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>unsafe</script>')
        self.project.members.add(self.outsider)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(f'/comments/{comment.pk}/delete/').status_code, 403)
        self.client.force_login(self.member)
        self.assertRedirects(self.client.post(f'/comments/{comment.pk}/delete/'), f'/projects/{self.project.pk}/')
        self.assertFalse(ProjectComment.objects.exists())

    def test_global_search_and_financial_export(self):
        Invoice.objects.create(number='WORKSPACE-INVOICE', client='Workspace client', amount=350, issued_at=timezone.localdate(), status='paid')
        Task.objects.create(title='Workspace task')
        response = self.client.get('/search/', {'q': 'Workspace'})
        self.assertContains(response, 'Workspace project')
        self.assertContains(response, 'WORKSPACE-INVOICE')
        self.assertContains(response, 'Workspace task')
        response = self.client.get('/reports/export/?months=3')
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 4)
        self.assertEqual(int(rows[-1][1]), 350)

    def test_new_mutations_require_csrf_and_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for path in [f'/projects/{self.project.pk}/status/', '/bulk/task/', f'/projects/{self.project.pk}/comments/']:
            self.assertEqual(client.get(path).status_code, 405)
            self.assertEqual(client.post(path, {}).status_code, 403)
