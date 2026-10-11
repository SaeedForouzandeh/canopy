from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.conf import settings
from django.utils import timezone

class Project(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'در حال انجام'
        REVIEW = 'review', 'در انتظار بررسی'
        DONE = 'done', 'تکمیل شده'
    name = models.CharField('نام پروژه', max_length=160)
    client = models.CharField('کارفرما', max_length=100)
    category = models.CharField('دسته‌بندی', max_length=80, default='طراحی محصول')
    status = models.CharField('وضعیت', max_length=10, choices=Status.choices, default=Status.ACTIVE)
    progress = models.PositiveSmallIntegerField('پیشرفت', default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    budget = models.PositiveBigIntegerField('بودجه (تومان)', default=0)
    due_date = models.DateField('موعد تحویل')
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField('توضیحات', blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, verbose_name='اعضای تیم', related_name='workspace_projects')
    class Meta:
        verbose_name = 'پروژه'
        verbose_name_plural = 'پروژه‌ها'
        ordering = ['-created_at']
    def __str__(self):
        return self.name

class Invoice(models.Model):
    class Status(models.TextChoices):
        PAID = 'paid', 'پرداخت شده'
        PENDING = 'pending', 'در انتظار'
    number = models.CharField('شماره', max_length=30, unique=True)
    client = models.CharField('مشتری', max_length=100)
    amount = models.PositiveBigIntegerField('مبلغ (تومان)')
    status = models.CharField('وضعیت', max_length=10, choices=Status.choices, default=Status.PENDING)
    issued_at = models.DateField('تاریخ صدور')
    paid_at = models.DateField('تاریخ پرداخت', null=True, blank=True)
    due_date = models.DateField('مهلت پرداخت', null=True, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='پروژه')
    notes = models.TextField('یادداشت', blank=True)
    class Meta:
        verbose_name = 'صورتحساب'
        verbose_name_plural = 'صورتحساب‌ها'
        ordering = ['-issued_at']
    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if self.status == self.Status.PAID and not self.paid_at:
            self.paid_at = timezone.localdate()
        elif self.status == self.Status.PENDING:
            self.paid_at = None
        super().save(*args, **kwargs)

class Task(models.Model):
    title = models.CharField('عنوان', max_length=200)
    completed = models.BooleanField('انجام شده', default=False)
    due_date = models.DateField('موعد انجام', null=True, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='پروژه')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='مسئول', related_name='assigned_tasks')
    priority = models.CharField('اولویت', max_length=10, choices=[('low', 'کم'), ('normal', 'عادی'), ('high', 'زیاد')], default='normal')
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        verbose_name = 'کار'
        verbose_name_plural = 'کارها'
    def __str__(self):
        return self.title


class Expense(models.Model):
    title = models.CharField('عنوان هزینه', max_length=160)
    amount = models.PositiveBigIntegerField('مبلغ (تومان)', validators=[MinValueValidator(1)])
    category = models.CharField('دسته‌بندی', max_length=80, default='عمومی')
    spent_at = models.DateField('تاریخ هزینه', default=timezone.localdate)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='پروژه')
    notes = models.TextField('یادداشت', blank=True)

    class Meta:
        verbose_name = 'هزینه'
        verbose_name_plural = 'هزینه‌ها'
        ordering = ['-spent_at', '-pk']

    def __str__(self):
        return self.title


class Event(models.Model):
    title = models.CharField('عنوان رویداد', max_length=160)
    start = models.DateTimeField('شروع')
    end = models.DateTimeField('پایان')
    description = models.TextField('توضیحات', blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='پروژه')
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, verbose_name='شرکت‌کنندگان', related_name='workspace_events')

    class Meta:
        verbose_name = 'رویداد'
        verbose_name_plural = 'رویدادها'
        ordering = ['start']
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F('start')), name='event_end_after_start')]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.start and self.end and self.end <= self.start:
            raise ValidationError({'end': 'زمان پایان باید پس از شروع باشد.'})

    def __str__(self):
        return self.title


class DirectMessage(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_workspace_messages', verbose_name='فرستنده')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_workspace_messages', verbose_name='گیرنده')
    body = models.TextField('متن پیام', max_length=4000)
    sent_at = models.DateTimeField('زمان ارسال', auto_now_add=True)
    read_at = models.DateTimeField('زمان خواندن', null=True, blank=True)

    class Meta:
        verbose_name = 'پیام'
        verbose_name_plural = 'پیام‌ها'
        ordering = ['sent_at', 'pk']
        indexes = [models.Index(fields=['recipient', 'read_at']), models.Index(fields=['sender', 'recipient', 'sent_at'])]

    def __str__(self):
        return f'{self.sender} → {self.recipient}'


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workspace_notifications', verbose_name='گیرنده')
    title = models.CharField('عنوان', max_length=200)
    url = models.CharField('مسیر', max_length=200, blank=True)
    created_at = models.DateTimeField('زمان', auto_now_add=True)
    read_at = models.DateTimeField('خوانده شده', null=True, blank=True)

    class Meta:
        verbose_name = 'اعلان'
        verbose_name_plural = 'اعلان‌ها'
        ordering = ['-created_at', '-pk']


class Activity(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, verbose_name='کاربر')
    description = models.CharField('فعالیت', max_length=240)
    created_at = models.DateTimeField('زمان', auto_now_add=True)

    class Meta:
        verbose_name = 'فعالیت'
        verbose_name_plural = 'فعالیت‌ها'
        ordering = ['-created_at', '-pk']


class UserPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='canopy_preference', verbose_name='کاربر')
    theme = models.CharField('پوسته', max_length=10, choices=[('light', 'روشن'), ('dark', 'تیره')], default='light')
    direction = models.CharField('جهت نمایش', max_length=3, choices=[('rtl', 'راست‌به‌چپ'), ('ltr', 'چپ‌به‌راست')], default='rtl')

    class Meta:
        verbose_name = 'تنظیمات کاربر'
        verbose_name_plural = 'تنظیمات کاربران'


class ProjectComment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='comments', verbose_name='پروژه')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, verbose_name='نویسنده')
    body = models.TextField('یادداشت', max_length=2500)
    created_at = models.DateTimeField('زمان', auto_now_add=True)

    class Meta:
        verbose_name = 'یادداشت پروژه'
        verbose_name_plural = 'یادداشت‌های پروژه'
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return self.body[:60]
