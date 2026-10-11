import csv
import io
from datetime import date
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from .models import Invoice, Project, Task

class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', verbosity=0)
        cls.admin = get_user_model().objects.create_superuser('owner', 'owner@example.test', 'test-only-password')
        cls.viewer = get_user_model().objects.create_user('viewer', password='test-only-password')

    def test_pages_and_admin_render(self):
        for url in ['/', '/analytics/', '/projects/', '/invoices/', '/expenses/', '/tasks/', '/calendar/', '/components/', '/accounts/login/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.admin)
        for url in ['/admin/', '/admin/dashboard/project/', '/projects/new/', '/messages/', '/settings/', '/notifications/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_unknown_page_is_404(self):
        self.assertEqual(self.client.get('/missing/').status_code, 404)

    def test_search_filters_projects(self):
        response = self.client.get('/projects/', {'q': 'آوا'})
        self.assertContains(response, 'بازطراحی وب‌سایت آوا')
        self.assertNotContains(response, 'اپلیکیشن مالی نوا')

    def test_anonymous_and_unprivileged_users_cannot_mutate(self):
        task = Task.objects.first()
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/toggle/').status_code, 302)
        self.assertEqual(self.client.get('/projects/new/').status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/toggle/').status_code, 403)
        self.assertEqual(self.client.post('/projects/new/', {}).status_code, 403)
        task.refresh_from_db()
        self.assertFalse(task.completed)

    def test_task_toggle_requires_post_and_saves(self):
        self.client.force_login(self.admin)
        task = Task.objects.first()
        self.assertEqual(self.client.get(f'/tasks/{task.pk}/toggle/').status_code, 405)
        self.assertRedirects(self.client.post(f'/tasks/{task.pk}/toggle/'), '/')
        task.refresh_from_db()
        self.assertTrue(task.completed)

    def test_project_form_validation_and_persistence(self):
        self.client.force_login(self.admin)
        before = Project.objects.count()
        self.assertEqual(self.client.post('/projects/new/', {'name': 'Incomplete'}).status_code, 200)
        self.assertEqual(Project.objects.count(), before)
        response = self.client.post('/projects/new/', {'name': 'Test project', 'client': 'Client', 'category': 'Web', 'budget': '1500', 'due_date': date.today().isoformat(), 'status': 'active', 'progress': '0'})
        self.assertRedirects(response, '/projects/')
        self.assertEqual(Project.objects.get(name='Test project').budget, 1500)

    def test_csv_export_and_demo_idempotence(self):
        response = self.client.get('/invoices/export/')
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0][2], 'Amount (Toman)')
        count = Project.objects.count()
        call_command('seed_demo', verbosity=0)
        self.assertEqual(Project.objects.count(), count)

    def test_csv_does_not_evaluate_user_text_as_a_formula(self):
        Invoice.objects.create(number='=1+1', client='@SUM(1,1)', amount=1, issued_at=date.today())
        response = self.client.get('/invoices/export/')
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        row = next(row for row in rows if row[2] == '1')
        self.assertEqual(row[0], "'=1+1")
        self.assertEqual(row[1], "'@SUM(1,1)")
