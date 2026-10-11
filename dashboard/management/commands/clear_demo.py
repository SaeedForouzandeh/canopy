"""Remove unchanged records from the original seed_demo fixture only."""
from django.core.management.base import BaseCommand
from django.db import transaction

from dashboard.models import Invoice, Project, Task


class Command(BaseCommand):
    help = 'Remove unchanged original demo records, retaining accounts and other data.'

    @transaction.atomic
    def handle(self, *args, **options):
        projects = [
            ('بازطراحی وب‌سایت آوا', 'آوا استودیو', 'active', 72, 48000000),
            ('اپلیکیشن مالی نوا', 'نوا فین‌تک', 'review', 90, 85000000),
            ('هویت بصری لومین', 'لومین', 'active', 45, 32000000),
            ('فروشگاه آنلاین برگ', 'برگ', 'done', 100, 64000000),
            ('داشبورد تحلیل داده', 'دیتا پلاس', 'active', 28, 56000000),
        ]
        count = 0
        for number, client, amount, status in [
            ('WL-1048', 'آوا استودیو', 24000000, 'paid'),
            ('WL-1047', 'نوا فین‌تک', 42500000, 'pending'),
            ('WL-1046', 'لومین', 16000000, 'paid'),
            ('WL-1045', 'برگ', 64000000, 'paid'),
        ]:
            deleted, _ = Invoice.objects.filter(number=number, client=client, amount=amount, status=status, project__isnull=True, notes='', due_date__isnull=True).delete()
            count += deleted
        for title in ['بررسی نسخه نهایی صفحه اصلی آوا', 'ارسال پروپوزال پروژه جدید', 'جلسه هماهنگی با تیم طراحی', 'به‌روزرسانی کتابخانه کامپوننت‌ها']:
            deleted, _ = Task.objects.filter(title=title, completed=False, assignee__isnull=True, project__isnull=True, due_date__isnull=True, priority='normal').delete()
            count += deleted
        for name, client, status, progress, budget in projects:
            for project in Project.objects.filter(name=name, client=client, status=status, progress=progress, budget=budget, description='', members__isnull=True):
                # Keep original demo projects if someone linked their own data to them.
                if any([project.invoice_set.exists(), project.task_set.exists(), project.expense_set.exists(), project.event_set.exists()]):
                    continue
                project.delete()
                count += 1
        self.stdout.write(self.style.SUCCESS(f'Removed {count} unchanged demo records. User accounts and custom content retained.'))
