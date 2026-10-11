"""Database-derived reporting; no fabricated values or fallback sample series."""
import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from .models import Event, Expense, Invoice, Project, Task


def month_offset(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def reports(months=6):
    today = timezone.localdate()
    first = month_offset(today, 1 - months)
    end = month_offset(today, 1)
    paid = Invoice.objects.filter(status=Invoice.Status.PAID).annotate(payment_date=Coalesce('paid_at', 'issued_at'))
    monthly_income = (
        paid.filter(payment_date__gte=first, payment_date__lt=end)
        .annotate(month=TruncMonth('payment_date'))
        .values('month').annotate(total=Sum('amount'))
    )
    monthly_expenses = (
        Expense.objects.filter(spent_at__gte=first, spent_at__lt=end)
        .annotate(month=TruncMonth('spent_at'))
        .values('month').annotate(total=Sum('amount'))
    )
    income = {row['month'].strftime('%Y-%m'): row['total'] for row in monthly_income}
    expenses = {row['month'].strftime('%Y-%m'): row['total'] for row in monthly_expenses}
    series = []
    for offset in range(months):
        key = month_offset(first, offset).strftime('%Y-%m')
        series.append({'label': key, 'income': income.get(key, 0), 'expense': expenses.get(key, 0)})
    revenue = sum(row['income'] for row in series)
    costs = sum(row['expense'] for row in series)
    previous_start = month_offset(first, -months)
    previous = paid.filter(payment_date__gte=previous_start, payment_date__lt=first).aggregate(total=Sum('amount'))['total'] or 0
    growth = round((revenue - previous) * 100 / previous, 1) if previous else None
    categories = list(Project.objects.values('category').annotate(count=Count('pk')).order_by('-count', 'category'))
    total = sum(row['count'] for row in categories)
    palette = ['#32694c', '#c9a45a', '#8ca596', '#7284a3', '#a48178', '#7c948c']
    gradient, position = [], 0
    for index, row in enumerate(categories):
        row['percentage'] = round(row['count'] * 100 / total, 1) if total else 0
        row['color'] = palette[index % len(palette)]
        next_position = position + row['count'] * 100 / total
        gradient.append(f"{row['color']} {position:.4f}% {next_position:.4f}%")
        position = next_position
    return {
        'chart_data': series,
        'period_revenue': revenue,
        'period_expense': costs,
        'net_income': revenue - costs,
        'growth': growth,
        'categories': categories,
        'donut_gradient': ','.join(gradient) if gradient else 'var(--line) 0% 100%',
        'project_count': total,
        'active_count': Project.objects.filter(status='active').count(),
        'paid_total': paid.aggregate(total=Sum('amount'))['total'] or 0,
        'pending_total': Invoice.objects.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0,
        'invoice_count': Invoice.objects.count(),
        'expense_total': Expense.objects.aggregate(total=Sum('amount'))['total'] or 0,
        'task_count': Task.objects.count(),
        'open_task_count': Task.objects.filter(completed=False).count(),
        'completed_task_count': Task.objects.filter(completed=True).count(),
        'overdue_projects': Project.objects.exclude(status='done').filter(due_date__lt=today).count(),
        'overdue_invoices': Invoice.objects.filter(status='pending', due_date__lt=today).count(),
    }


def calendar_context(month):
    start = datetime.combine(month, time.min, tzinfo=timezone.get_current_timezone())
    end = datetime.combine(month_offset(month, 1), time.min, tzinfo=timezone.get_current_timezone())
    cells = defaultdict(list)
    events = Event.objects.filter(start__lt=end, end__gt=start).select_related('project')
    for event in events:
        day = max(timezone.localtime(event.start).date(), month)
        last = min(timezone.localtime(event.end - timedelta(microseconds=1)).date(), end.date() - timedelta(days=1))
        while day <= last:
            cells[day].append({'kind': 'event', 'title': event.title, 'pk': event.pk, 'time': timezone.localtime(event.start).strftime('%H:%M')})
            day += timedelta(days=1)
    for project in Project.objects.exclude(status='done').filter(due_date__gte=month, due_date__lt=end.date()):
        cells[project.due_date].append({'kind': 'project', 'title': project.name, 'pk': project.pk})
    for task in Task.objects.filter(completed=False, due_date__gte=month, due_date__lt=end.date()):
        cells[task.due_date].append({'kind': 'task', 'title': task.title, 'pk': task.pk})
    for invoice in Invoice.objects.filter(status='pending', due_date__gte=month, due_date__lt=end.date()):
        cells[invoice.due_date].append({'kind': 'invoice', 'title': invoice.number, 'pk': invoice.pk})
    days = [
        {'date': day, 'in_month': day.month == month.month, 'is_today': day == timezone.localdate(), 'items': cells[day]}
        for week in calendar.Calendar(firstweekday=5).monthdatescalendar(month.year, month.month)
        for day in week
    ]
    return {
        'calendar_cells': days,
        'calendar_month': month.strftime('%Y-%m'),
        'previous_month': month_offset(month, -1).strftime('%Y-%m'),
        'next_month': month_offset(month, 1).strftime('%Y-%m'),
        'events': events,
    }
