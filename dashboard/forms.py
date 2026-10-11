from django import forms
from django.contrib.auth import get_user_model
from .models import Event, Expense, Invoice, Project, Task, UserPreference

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'client', 'category', 'status', 'progress', 'budget', 'due_date', 'description', 'members']
        widgets = {'due_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}), 'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['members'].queryset = get_user_model().objects.filter(is_active=True)


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['number', 'client', 'project', 'amount', 'status', 'issued_at', 'due_date', 'paid_at', 'notes']
        widgets = {name: forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}) for name in ['issued_at', 'due_date', 'paid_at']}
        widgets['notes'] = forms.Textarea(attrs={'rows': 3})

    def clean(self):
        data = super().clean()
        if data.get('paid_at') and data.get('issued_at') and data['paid_at'] < data['issued_at']:
            self.add_error('paid_at', 'تاریخ پرداخت نمی‌تواند قبل از صدور باشد.')
        return data


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'project', 'assignee', 'priority', 'due_date', 'completed']
        widgets = {'due_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = get_user_model().objects.filter(is_active=True)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['title', 'amount', 'category', 'spent_at', 'project', 'notes']
        widgets = {'spent_at': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}), 'notes': forms.Textarea(attrs={'rows': 3})}


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'start', 'end', 'project', 'participants', 'description']
        widgets = {
            'start': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'end': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['participants'].queryset = get_user_model().objects.filter(is_active=True)


class ProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']


class PreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ['theme', 'direction']


class MessageForm(forms.Form):
    body = forms.CharField(label='پیام', max_length=4000, strip=True, widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'پیام خود را بنویسید…'}))


class CommentForm(forms.Form):
    body = forms.CharField(label='یادداشت پروژه', max_length=2500, strip=True, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'یادداشت یا نتیجه بررسی پروژه را بنویسید…'}))
