from .models import DirectMessage, Notification, Project, UserPreference


def workspace(request):
    context = {'project_count': Project.objects.count(), 'ui_theme': 'light', 'ui_direction': 'rtl'}
    if request.user.is_authenticated:
        preference = UserPreference.objects.filter(user=request.user).first()
        if preference:
            context.update(ui_theme=preference.theme, ui_direction=preference.direction)
        context.update(
            user_display=request.user.get_full_name() or request.user.username,
            unread_message_count=DirectMessage.objects.filter(recipient=request.user, read_at__isnull=True).count(),
            unread_notification_count=Notification.objects.filter(recipient=request.user, read_at__isnull=True).count(),
            notifications=Notification.objects.filter(recipient=request.user)[:5],
        )
    return context
