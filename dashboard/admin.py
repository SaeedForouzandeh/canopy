from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from .models import Activity, DirectMessage, Event, Expense, Invoice, Notification, Project, Task, UserPreference
from .services import reports


class CanopyAdminSite(admin.AdminSite):
    site_header = 'Canopy · Wiseland Studio'
    site_title = 'مدیریت Canopy'
    index_title = 'مرکز مدیریت فضای کاری'
    index_template = 'admin/canopy_index.html'

    def index(self, request, extra_context=None):
        context = {'summary': reports(), 'recent_activities': Activity.objects.select_related('actor')[:8]}
        context.update(extra_context or {})
        return super().index(request, extra_context=context)


site = CanopyAdminSite(name='admin')
site.register(get_user_model(), UserAdmin)
site.register(Group, GroupAdmin)

admin.site.site_header = 'Canopy · Wiseland Studio'
admin.site.site_title = 'مدیریت Canopy'
admin.site.index_title = 'مدیریت فضای کاری'

@admin.register(Project, site=site)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'client', 'status', 'progress', 'budget', 'due_date')
    list_filter = ('status', 'category')
    search_fields = ('name', 'client')
    list_editable = ('status', 'progress')
    filter_horizontal = ('members',)

@admin.register(Invoice, site=site)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'client', 'amount', 'status', 'issued_at', 'paid_at')
    list_filter = ('status',)
    search_fields = ('number', 'client')

@admin.register(Task, site=site)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'assignee', 'priority', 'due_date', 'completed')
    list_editable = ('completed',)
    list_filter = ('completed', 'priority')
    search_fields = ('title',)


@admin.register(Expense, site=site)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'amount', 'category', 'spent_at', 'project')
    list_filter = ('category', 'spent_at')
    search_fields = ('title', 'notes')


@admin.register(Event, site=site)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'start', 'end', 'project')
    search_fields = ('title',)
    filter_horizontal = ('participants',)
    date_hierarchy = 'start'


@admin.register(Activity, site=site)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('description', 'actor', 'created_at')
    readonly_fields = ('description', 'actor', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification, site=site)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'recipient', 'created_at', 'read_at')
    list_filter = ('read_at',)
    search_fields = ('title', 'recipient__username')


@admin.register(UserPreference, site=site)
class PreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'direction')
