from datetime import date, timedelta
from django.core.management.base import BaseCommand
from dashboard.models import Project, Invoice, Task

class Command(BaseCommand):
    help = 'Create reusable sample content without creating login credentials.'
    def handle(self, *args, **options):
        for name, client, category, status, progress, budget, days in [('بازطراحی وب‌سایت آوا', 'آوا استودیو', 'طراحی وب‌سایت', 'active', 72, 48000000, 12), ('اپلیکیشن مالی نوا', 'نوا فین‌تک', 'طراحی محصول', 'review', 90, 85000000, 5), ('هویت بصری لومین', 'لومین', 'برندینگ', 'active', 45, 32000000, 18), ('فروشگاه آنلاین برگ', 'برگ', 'توسعه وب', 'done', 100, 64000000, 2), ('داشبورد تحلیل داده', 'دیتا پلاس', 'طراحی محصول', 'active', 28, 56000000, 25)]:
            Project.objects.get_or_create(name=name, defaults={'client': client, 'category': category, 'status': status, 'progress': progress, 'budget': budget, 'due_date': date.today() + timedelta(days=days)})
        for i, client, amount, status in [(1048, 'آوا استودیو', 24000000, 'paid'), (1047, 'نوا فین‌تک', 42500000, 'pending'), (1046, 'لومین', 16000000, 'paid'), (1045, 'برگ', 64000000, 'paid')]:
            Invoice.objects.get_or_create(number=f'WL-{i}', defaults={'client': client, 'amount': amount, 'status': status, 'issued_at': date.today() - timedelta(days=1048-i)})
        for title in ['بررسی نسخه نهایی صفحه اصلی آوا', 'ارسال پروپوزال پروژه جدید', 'جلسه هماهنگی با تیم طراحی', 'به‌روزرسانی کتابخانه کامپوننت‌ها']:
            Task.objects.get_or_create(title=title)
        self.stdout.write(self.style.SUCCESS('Canopy demo content is ready.'))
