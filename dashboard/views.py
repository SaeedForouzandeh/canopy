import csv
from urllib.parse import urlencode
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import CommentForm, EventForm, ExpenseForm, InvoiceForm, MessageForm, PreferenceForm, ProfileForm, ProjectForm, TaskForm
from .models import Activity, DirectMessage, Event, Expense, Invoice, Notification, Project, ProjectComment, Task, UserPreference
from .services import calendar_context, reports

SECTIONS = {
    'overview': 'نمای کلی', 'analytics': 'تحلیل و گزارش‌ها',
    'projects': 'پروژه‌ها', 'invoices': 'صورتحساب‌ها', 'expenses': 'هزینه‌ها',
    'tasks': 'کارها', 'calendar': 'تقویم', 'components': 'کتابخانه اجزا',
}
RECORDS = {
    'project': (Project, ProjectForm, 'projects'),
    'invoice': (Invoice, InvoiceForm, 'invoices'),
    'task': (Task, TaskForm, 'tasks'),
    'expense': (Expense, ExpenseForm, 'expenses'),
    'event': (Event, EventForm, 'calendar'),
}


def list_query(request, kind):
    model = RECORDS[kind][0]
    items = model.objects.all()
    query = request.GET.get('q', '').strip()
    search_fields = {
        'project': ['name', 'client', 'category'],
        'invoice': ['number', 'client'], 'expense': ['title', 'category'],
        'task': ['title'], 'event': ['title'],
    }
    if query:
        predicate = Q()
        for field in search_fields[kind]:
            predicate |= Q(**{f'{field}__icontains': query})
        items = items.filter(predicate)
    status = request.GET.get('status', '')
    if status and kind in {'project', 'invoice'}:
        items = items.filter(status=status)
    elif status and kind == 'task':
        if status in {'open', 'done'}:
            items = items.filter(completed=status == 'done')
        else:
            items = items.none()
    if request.GET.get('overdue') == '1' and kind in {'project', 'invoice', 'task'}:
        items = items.filter(due_date__lt=timezone.localdate())
        if kind == 'project':
            items = items.exclude(status='done')
        elif kind == 'invoice':
            items = items.filter(status='pending')
        else:
            items = items.filter(completed=False)
    sort_fields = {
        'project': {'name': 'name', 'due': 'due_date', 'budget': '-budget', 'recent': '-created_at'},
        'invoice': {'name': 'client', 'due': 'due_date', 'amount': '-amount', 'recent': '-issued_at'},
        'expense': {'name': 'title', 'amount': '-amount', 'recent': '-spent_at'},
        'task': {'name': 'title', 'due': 'due_date', 'recent': '-created_at'},
    }
    if kind in sort_fields:
        field = sort_fields[kind].get(request.GET.get('sort', 'recent'), sort_fields[kind]['recent'])
        items = items.order_by(field, '-pk')
    if kind == 'project':
        items = items.prefetch_related('members')
    elif kind == 'task':
        items = items.select_related('project', 'assignee')
    elif kind in {'invoice', 'expense'}:
        items = items.select_related('project')
    return items


@require_GET
def page(request, section='overview'):
    if section not in SECTIONS:
        raise Http404
    try:
        months = int(request.GET.get('months', 6))
    except ValueError:
        months = 6
    months = months if months in {3, 6, 12} else 6
    context = {
        'section': section, 'title': SECTIONS[section], 'today': timezone.localdate(),
        'query': request.GET.get('q', ''), 'selected_status': request.GET.get('status', ''),
        'selected_sort': request.GET.get('sort', 'recent'), 'months': months,
    }
    if section in {'overview', 'analytics', 'components'}:
        context.update(reports(months))
    if section == 'overview':
        context.update(
            projects=Project.objects.prefetch_related('members')[:5],
            tasks=Task.objects.select_related('assignee').filter(completed=False).order_by('due_date', '-pk')[:5],
            activities=Activity.objects.select_related('actor')[:6],
        )
    if section in {'projects', 'invoices', 'expenses', 'tasks'}:
        kind = {'projects': 'project', 'invoices': 'invoice', 'expenses': 'expense', 'tasks': 'task'}[section]
        paginated = Paginator(list_query(request, kind), 10).get_page(request.GET.get('page'))
        params = request.GET.copy()
        params.pop('page', None)
        context.update(page_obj=paginated, items=paginated.object_list, pagination_query=params.urlencode(), record_kind=kind)
        if section == 'projects':
            context['projects'] = paginated.object_list
            context['project_layout'] = 'board' if request.GET.get('layout') == 'board' else 'table'
            if context['project_layout'] == 'board':
                # Paginate within columns so a busy status cannot hide other columns.
                queryset = list_query(request, 'project')
                columns = []
                for status, label in Project.Status.choices:
                    column_page = Paginator(queryset.filter(status=status), 10).get_page(request.GET.get(f'{status}_page'))
                    column = {'status': status, 'label': label, 'page': column_page, 'count': column_page.paginator.count}
                    params = request.GET.copy()
                    for direction in ['previous', 'next']:
                        if getattr(column_page, f'has_{direction}')():
                            params[f'{status}_page'] = getattr(column_page, f'{direction}_page_number')()
                            column[f'{direction}_url'] = f'?{params.urlencode()}'
                    columns.append(column)
                context['board_columns'] = columns
        if section == 'tasks' and request.user.has_perm('dashboard.change_task'):
            context['assignees'] = get_user_model().objects.filter(is_active=True).order_by('username')
    if section == 'calendar':
        try:
            month = date.fromisoformat(request.GET.get('month', timezone.localdate().strftime('%Y-%m')) + '-01')
            # Keep previous/next navigation in a representable date range.
            if month.year < 1901 or month.year > 9998:
                raise ValueError
        except ValueError:
            month = timezone.localdate().replace(day=1)
        context.update(calendar_context(month))
    return render(request, 'dashboard/workspace.html', context)


def record_config(kind):
    try:
        return RECORDS[kind]
    except KeyError:
        raise Http404


def audit(user, description):
    Activity.objects.create(actor=user, description=description[:240])


def notify_assigned(record, actor):
    if isinstance(record, Project):
        recipients = record.members.exclude(pk=actor.pk)
        title, url = f'پروژه به‌روزرسانی شد: {record.name}', reverse('project_detail', args=[record.pk])
    elif isinstance(record, Event):
        recipients = record.participants.exclude(pk=actor.pk)
        title, url = f'رویداد: {record.title}', '/calendar/'
    elif isinstance(record, Task) and record.assignee and record.assignee_id != actor.pk:
        recipients = [record.assignee]
        title, url = f'کار برای شما: {record.title}', '/tasks/'
    else:
        return
    Notification.objects.bulk_create([Notification(recipient=user, title=title[:200], url=url) for user in recipients])


@login_required
@require_http_methods(['GET', 'POST'])
def record_form(request, kind, pk=None):
    model, form_class, section = record_config(kind)
    action = 'change' if pk else 'add'
    if not request.user.has_perm(f'dashboard.{action}_{model._meta.model_name}'):
        raise PermissionDenied
    instance = get_object_or_404(model, pk=pk) if pk else None
    initial = {}
    if not instance and kind == 'event':
        try:
            day = date.fromisoformat(request.GET.get('date', ''))
        except ValueError:
            day = timezone.localdate()
        initial = {'start': datetime.combine(day, datetime.min.time()).replace(hour=9), 'end': datetime.combine(day, datetime.min.time()).replace(hour=10)}
    elif not instance and kind == 'invoice':
        initial = {'issued_at': timezone.localdate()}
    form = form_class(request.POST if request.method == 'POST' else None, instance=instance, initial=initial)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            record = form.save()
            audit(request.user, f'{"ویرایش" if pk else "ایجاد"} {model._meta.verbose_name}: {record}')
            notify_assigned(record, request.user)
        messages.success(request, 'اطلاعات با موفقیت ذخیره شد.')
        return redirect('page', section=section)
    title = f'{"ویرایش" if pk else "ثبت"} {model._meta.verbose_name}'
    return render(request, 'dashboard/record_form.html', {'form': form, 'section': section, 'title': title, 'record': instance})


@login_required
@require_http_methods(['GET', 'POST'])
def record_delete(request, kind, pk):
    model, _, section = record_config(kind)
    if not request.user.has_perm(f'dashboard.delete_{model._meta.model_name}'):
        raise PermissionDenied
    record = get_object_or_404(model, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            audit(request.user, f'حذف {model._meta.verbose_name}: {record}')
            record.delete()
        messages.success(request, 'رکورد حذف شد.')
        return redirect('page', section=section)
    return render(request, 'dashboard/record_delete.html', {'record': record, 'section': section, 'title': f'حذف {model._meta.verbose_name}'})


def project_create(request):
    return record_form(request, 'project')


@require_GET
def project_detail(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('members'), pk=pk)
    invoices = project.invoice_set.all()
    can_discuss = can_discuss_project(request.user, project)
    return render(request, 'dashboard/project_detail.html', {
        'section': 'projects', 'title': project.name, 'project': project,
        'project_tasks': project.task_set.select_related('assignee').all(),
        'project_invoices': invoices, 'project_expenses': project.expense_set.all(),
        'received': invoices.filter(status='paid').aggregate(total=Sum('amount'))['total'] or 0,
        'cost': project.expense_set.aggregate(total=Sum('amount'))['total'] or 0,
        'can_discuss': can_discuss,
        'comment_form': CommentForm(),
        'comments_page': Paginator(project.comments.select_related('author'), 15).get_page(request.GET.get('comments_page')) if can_discuss else None,
    })


@require_POST
@login_required
@permission_required('dashboard.change_task', raise_exception=True)
def task_toggle(request, pk):
    with transaction.atomic():
        task = get_object_or_404(Task.objects.select_for_update(), pk=pk)
        task.completed = not task.completed
        task.save(update_fields=['completed'])
        audit(request.user, f'{"تکمیل" if task.completed else "بازگشایی"} کار: {task.title}')
    return redirect('page', section='tasks') if request.POST.get('return_to') == 'tasks' else redirect('overview')


@require_POST
@login_required
@permission_required('dashboard.change_invoice', raise_exception=True)
def invoice_pay(request, pk):
    with transaction.atomic():
        invoice = get_object_or_404(Invoice.objects.select_for_update(), pk=pk)
        if invoice.status != 'paid':
            invoice.status = 'paid'
            invoice.save()
            audit(request.user, f'ثبت پرداخت صورتحساب: {invoice.number}')
    messages.success(request, 'پرداخت صورتحساب ثبت شد.')
    return redirect('page', section='invoices')


@require_GET
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('project'), pk=pk)
    return render(request, 'dashboard/invoice_detail.html', {'invoice': invoice, 'title': invoice.number, 'section': 'invoices'})


def safe_csv(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


@require_GET
def invoice_export(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="canopy-invoices.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Number', 'Client', 'Amount (Toman)', 'Status', 'Date', 'Paid at'])
    for item in list_query(request, 'invoice'):
        writer.writerow([safe_csv(item.number), safe_csv(item.client), item.amount, item.get_status_display(), item.issued_at, item.paid_at or ''])
    return response


@login_required
@require_http_methods(['GET', 'POST'])
def settings_view(request):
    preference = UserPreference.objects.filter(user=request.user).first() or UserPreference(user=request.user)
    data = request.POST if request.method == 'POST' else None
    profile_form = ProfileForm(data, instance=request.user)
    preference_form = PreferenceForm(data, instance=preference)
    if request.method == 'POST' and profile_form.is_valid() and preference_form.is_valid():
        with transaction.atomic():
            profile_form.save()
            preference_form.save()
        messages.success(request, 'پروفایل و تنظیمات شما ذخیره شد.')
        return redirect('settings')
    return render(request, 'dashboard/settings.html', {'title': 'تنظیمات حساب', 'section': 'settings', 'profile_form': profile_form, 'preference_form': preference_form})


@login_required
@require_POST
def preference_update(request):
    preference = UserPreference.objects.filter(user=request.user).first() or UserPreference(user=request.user)
    form = PreferenceForm(request.POST, instance=preference)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)
    form.save()
    return JsonResponse({'saved': True})


def peer_for(request, value):
    try:
        pk = int(value)
    except (ValueError, TypeError):
        raise Http404
    return get_object_or_404(get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk), pk=pk)


@login_required
@require_http_methods(['GET', 'POST'])
def inbox(request):
    contacts = get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk).order_by('first_name', 'username')
    if request.GET.get('q'):
        query = request.GET['q'].strip()
        contacts = contacts.filter(Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    value = request.POST.get('recipient') if request.method == 'POST' else request.GET.get('with')
    peer = peer_for(request, value) if value else None
    form = MessageForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if peer is None:
            raise Http404
        if form.is_valid():
            with transaction.atomic():
                DirectMessage.objects.create(sender=request.user, recipient=peer, body=form.cleaned_data['body'])
                Notification.objects.create(recipient=peer, title=f'پیام جدید از {request.user.get_full_name() or request.user.username}'[:200], url=f'/messages/?with={request.user.pk}')
            return redirect(f'/messages/?with={peer.pk}')
    thread = DirectMessage.objects.none()
    if peer:
        thread = DirectMessage.objects.filter(Q(sender=request.user, recipient=peer) | Q(sender=peer, recipient=request.user)).order_by('-sent_at', '-pk')
    history = Paginator(thread, 50).get_page(request.GET.get('page'))
    chat_messages = list(reversed(history.object_list))
    return render(request, 'dashboard/inbox.html', {
        'title': 'پیام‌های خصوصی', 'section': 'messages', 'contacts': contacts,
        'peer': peer, 'message_form': form, 'chat_messages': chat_messages,
        'history': history, 'last_message_id': chat_messages[-1].pk if chat_messages else 0,
    })


@login_required
@require_GET
def message_poll(request):
    peer = peer_for(request, request.GET.get('with'))
    try:
        since = max(0, int(request.GET.get('since', 0)))
    except ValueError:
        return JsonResponse({'error': 'Invalid cursor'}, status=400)
    thread = DirectMessage.objects.filter(Q(sender=request.user, recipient=peer) | Q(sender=peer, recipient=request.user), pk__gt=since).order_by('pk')[:50]
    return JsonResponse({'messages': [
        {'id': item.pk, 'body': item.body, 'outgoing': item.sender_id == request.user.pk, 'time': timezone.localtime(item.sent_at).strftime('%Y/%m/%d %H:%M')}
        for item in thread
    ]})


@login_required
@require_POST
def message_read(request):
    peer = peer_for(request, request.POST.get('with'))
    # Acknowledge only messages actually rendered; a concurrent new message stays unread.
    try:
        through = max(0, int(request.POST.get('through', 0)))
    except ValueError:
        return JsonResponse({'error': 'Invalid cursor'}, status=400)
    DirectMessage.objects.filter(sender=peer, recipient=request.user, read_at__isnull=True, pk__lte=through).update(read_at=timezone.now())
    if not DirectMessage.objects.filter(sender=peer, recipient=request.user, read_at__isnull=True).exists():
        Notification.objects.filter(recipient=request.user, url=f'/messages/?with={peer.pk}', read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({'saved': True})


@login_required
@require_GET
def notifications_view(request):
    notifications = Paginator(Notification.objects.filter(recipient=request.user), 15).get_page(request.GET.get('page'))
    return render(request, 'dashboard/notifications.html', {'title': 'اعلان‌ها', 'section': 'notifications', 'page_obj': notifications})


@login_required
@require_POST
def notification_read(request, pk=None):
    notifications = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
    if pk is not None:
        get_object_or_404(Notification, pk=pk, recipient=request.user)
        notifications = notifications.filter(pk=pk)
    notifications.update(read_at=timezone.now())
    return redirect('notifications')


@login_required
@require_GET
def team_view(request):
    users = get_user_model().objects.filter(is_active=True).annotate(
        project_total=Count('workspace_projects', distinct=True),
        task_total=Count('assigned_tasks', filter=Q(assigned_tasks__completed=False), distinct=True),
    ).order_by('first_name', 'username')
    query = request.GET.get('q', '').strip()
    if query:
        users = users.filter(Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    return render(request, 'dashboard/team.html', {
        'title': 'اعضای تیم', 'section': 'team', 'query': query,
        'page_obj': Paginator(users, 12).get_page(request.GET.get('page')),
    })


@require_POST
@login_required
@permission_required('dashboard.change_project', raise_exception=True)
def project_status(request, pk):
    status = request.POST.get('status')
    if status not in Project.Status.values:
        return JsonResponse({'error': 'وضعیت پروژه معتبر نیست.'}, status=400)
    with transaction.atomic():
        project = get_object_or_404(Project.objects.select_for_update(), pk=pk)
        expected = request.POST.get('expected_status')
        if expected and project.status != expected:
            return JsonResponse({'error': 'پروژه توسط کاربر دیگری تغییر کرده است؛ صفحه را تازه کنید.'}, status=409)
        if project.status != status:
            project.status = status
            project.save(update_fields=['status'])
            audit(request.user, f'تغییر وضعیت پروژه: {project.name} · {project.get_status_display()}')
            notify_assigned(project, request.user)
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'saved': True, 'status': status})
    return redirect('/projects/?layout=board')


@require_POST
@login_required
def bulk_update(request, kind):
    if kind not in {'task', 'invoice'}:
        raise Http404
    model = Task if kind == 'task' else Invoice
    if not request.user.has_perm(f'dashboard.change_{kind}'):
        raise PermissionDenied
    try:
        raw_ids = request.POST.getlist('ids')
        if not 1 <= len(raw_ids) <= 100:
            raise ValueError
        selected = {int(pk) for pk in raw_ids}
        if any(pk <= 0 or pk > 9223372036854775807 for pk in selected):
            raise ValueError
    except ValueError:
        return JsonResponse({'error': 'بین ۱ تا ۱۰۰ رکورد معتبر انتخاب کنید.'}, status=400)
    action = request.POST.get('action')
    actions = {'task': {'complete', 'reopen', 'assign'}, 'invoice': {'paid'}}
    if action not in actions[kind]:
        return JsonResponse({'error': 'عملیات معتبر نیست.'}, status=400)
    assignee = None
    if action == 'assign':
        try:
            assignee = get_user_model().objects.get(pk=int(request.POST.get('assignee', '')), is_active=True)
        except (ValueError, get_user_model().DoesNotExist):
            return JsonResponse({'error': 'مسئول فعال را انتخاب کنید.'}, status=400)
    changed = 0
    with transaction.atomic():
        records = list(model.objects.select_for_update().filter(pk__in=selected))
        if len(records) != len(selected):
            return JsonResponse({'error': 'یکی از رکوردهای انتخاب‌شده وجود ندارد؛ صفحه را تازه کنید.'}, status=400)
        for record in records:
            if kind == 'task':
                if action == 'assign':
                    if record.assignee_id == assignee.pk:
                        continue
                    record.assignee = assignee
                else:
                    completed = action == 'complete'
                    if record.completed == completed:
                        continue
                    record.completed = completed
                record.save()
                if action == 'assign':
                    notify_assigned(record, request.user)
            else:
                if record.status == 'paid':
                    continue
                record.status = 'paid'
                record.save()
            audit(request.user, f'عملیات گروهی {model._meta.verbose_name}: {record}')
            changed += 1
    messages.success(request, f'{changed} رکورد تغییر کرد.')
    return redirect('page', section='tasks' if kind == 'task' else 'invoices')


def can_discuss_project(user, project):
    return user.is_authenticated and (
        user.has_perm('dashboard.change_project') or project.members.filter(pk=user.pk).exists()
    )


@require_POST
@login_required
def comment_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if not can_discuss_project(request.user, project):
        raise PermissionDenied
    form = CommentForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'یادداشت خالی نباشد و حداکثر ۲۵۰۰ کاراکتر داشته باشد.')
        return redirect('project_detail', pk=pk)
    with transaction.atomic():
        ProjectComment.objects.create(project=project, author=request.user, body=form.cleaned_data['body'])
        audit(request.user, f'افزودن یادداشت به پروژه: {project.name}')
        recipients = project.members.exclude(pk=request.user.pk)
        Notification.objects.bulk_create([
            Notification(recipient=user, title=f'یادداشت جدید: {project.name}'[:200], url=reverse('project_detail', args=[pk]))
            for user in recipients
        ])
    return redirect('project_detail', pk=pk)


@require_POST
@login_required
def comment_delete(request, pk):
    comment = get_object_or_404(ProjectComment.objects.select_related('project'), pk=pk)
    if not can_discuss_project(request.user, comment.project):
        raise PermissionDenied
    if comment.author_id != request.user.pk and not request.user.has_perm('dashboard.delete_projectcomment'):
        raise PermissionDenied
    project_id = comment.project_id
    with transaction.atomic():
        audit(request.user, f'حذف یادداشت پروژه: {comment.project.name}')
        comment.delete()
    return redirect('project_detail', pk=project_id)


@require_GET
def global_search(request):
    query = request.GET.get('q', '').strip()
    results = []
    if query:
        for kind, title in [('project', 'پروژه‌ها'), ('invoice', 'صورتحساب‌ها'), ('task', 'کارها'), ('expense', 'هزینه‌ها'), ('event', 'رویدادها')]:
            queryset = list_query(request, kind)
            rows = []
            for record in queryset[:10]:
                if kind == 'project':
                    url = reverse('project_detail', args=[record.pk])
                elif kind == 'invoice':
                    url = reverse('invoice_detail', args=[record.pk])
                elif kind == 'event':
                    url = f'/calendar/?month={timezone.localtime(record.start):%Y-%m}'
                else:
                    # Encode user input so ampersands do not change the query.
                    url = f'/{RECORDS[kind][2]}/?{urlencode({"q": query})}'
                rows.append({'record': record, 'url': url})
            results.append({'title': title, 'rows': rows, 'count': queryset.count()})
    return render(request, 'dashboard/search.html', {'title': 'جستجوی سراسری', 'section': 'search', 'query': query, 'results': results})


@require_GET
def report_export(request):
    try:
        months = int(request.GET.get('months', 6))
    except ValueError:
        months = 6
    result = reports(months if months in {3, 6, 12} else 6)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="canopy-financial-report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Month', 'Received income (Toman)', 'Expenses (Toman)', 'Net income (Toman)'])
    for point in result['chart_data']:
        writer.writerow([point['label'], point['income'], point['expense'], point['income'] - point['expense']])
    return response
