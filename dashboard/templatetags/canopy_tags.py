from django import template

register = template.Library()

@register.filter
def money(value):
    """Group Toman amounts consistently, independent of Django locale settings."""
    return f'{int(value):,}'.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


@register.filter
def weekdays(value):
    return value.split(',')


@register.filter
def display_name(user):
    if user is None:
        return 'تعیین نشده'
    return user.get_full_name() or user.username
