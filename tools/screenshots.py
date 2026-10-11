"""Capture real Chrome screenshots and smoke-test UI interactions.

Requires a running local Django server, websockets, and Google Chrome.
The temporary screenshot administrator and browser profile are removed on exit.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canopy.settings')
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client
from dashboard.models import Activity, DirectMessage, Project, Task
from dashboard.services import reports
import websockets

BASE_URL = os.environ.get('SCREENSHOT_URL', 'http://127.0.0.1:8000')
OUTPUT = ROOT / 'docs' / 'screenshots'
CHROME = os.environ.get('CHROME_PATH') or shutil.which('google-chrome') or shutil.which('chromium') or r'C:\Program Files\Google\Chrome\Application\chrome.exe'

async def capture(websocket_url, session_key, peer_id, expected_chart, create_workflow):
    async with websockets.connect(websocket_url, max_size=30_000_000) as ws:
        sequence = 0
        async def command(method, params=None):
            nonlocal sequence
            sequence += 1
            await ws.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
            while True:
                result = json.loads(await ws.recv())
                if result.get('id') == sequence:
                    if 'error' in result:
                        raise RuntimeError(result['error'])
                    return result.get('result', {})

        async def evaluate(expression):
            result = await command('Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
            if 'exceptionDetails' in result:
                raise RuntimeError(result['exceptionDetails'])
            return result.get('result', {}).get('value')

        async def navigate(path):
            await command('Page.navigate', {'url': BASE_URL + path})
            for _ in range(80):
                await asyncio.sleep(.1)
                if await evaluate("document.readyState === 'complete' && location.pathname === " + json.dumps(urlsplit(path).path)):
                    break
            else:
                raise RuntimeError(f'Page did not load: {path}')
            await evaluate('document.fonts.ready.then(() => true)')
            await asyncio.sleep(.25)

        async def screenshot(name, width, height, mobile=False):
            await command('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
            await asyncio.sleep(.3)
            params = {'format': 'png', 'captureBeyondViewport': False}
            result = await command('Page.captureScreenshot', params)
            (OUTPUT / name).write_bytes(base64.b64decode(result['data']))
            print(f'Saved {name}', flush=True)

        await command('Page.enable')
        await command('Runtime.enable')
        await command('Network.setCookie', {'name': settings.SESSION_COOKIE_NAME, 'value': session_key, 'url': BASE_URL, 'httpOnly': True, 'sameSite': 'Lax'})
        await command('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1250, 'deviceScaleFactor': 1, 'mobile': False})
        await navigate('/')
        actual_chart = await evaluate("JSON.parse(document.querySelector('#financial-data').textContent)")
        assert actual_chart == expected_chart, 'Rendered financial series must match database aggregates.'
        assert await evaluate("!!document.querySelector('#financial-chart svg')"), 'Chart failed to render.'
        assert await evaluate("document.fonts.check('14px Vazirmatn')"), 'Local font unavailable.'
        # Both independent scrollers must have their bars at the menu-side boundary.
        await command('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 720, 'deviceScaleFactor': 1, 'mobile': False})
        scroll_check = await evaluate("""(() => {
          const menu = document.querySelector('#sidebar');
          const center = document.querySelector('#content-scroll');
          const menuRect = menu.getBoundingClientRect();
          const centerRect = center.getBoundingClientRect();
          const directions = getComputedStyle(menu).direction === 'ltr' && getComputedStyle(center).direction === 'ltr';
          center.scrollTop = 180;
          const centerMovedAlone = center.scrollTop > 0 && menu.scrollTop === 0;
          const previousCenter = center.scrollTop;
          menu.scrollTop = 80;
          const menuMovedAlone = menu.scrollTop > 0 && center.scrollTop === previousCenter;
          menu.scrollTop = 0; center.scrollTop = 0;
          return {directions, centerMovedAlone, menuMovedAlone,
            menuOnRight: Math.abs(menuRect.right - innerWidth) < 2,
            adjacent: Math.abs(centerRect.right - menuRect.left) < 2,
            bodyDoesNotScroll: document.scrollingElement.scrollHeight <= innerHeight};
        })()""")
        assert all(scroll_check.values()), f'Independent scroll layout failed: {scroll_check}'
        ltr_check = await evaluate("""(() => {
          document.documentElement.dir = 'ltr';
          const menu = document.querySelector('#sidebar');
          const center = document.querySelector('#content-scroll');
          const result = Math.abs(menu.getBoundingClientRect().left) < 2 &&
            Math.abs(center.getBoundingClientRect().left - menu.getBoundingClientRect().right) < 2 &&
            getComputedStyle(menu).direction === 'rtl' && getComputedStyle(center).direction === 'rtl';
          document.documentElement.dir = 'rtl';
          return result;
        })()""")
        assert ltr_check, 'Independent scrolling must mirror in LTR.'
        await screenshot('independent-scrolls.png', 1440, 720)
        await screenshot('dashboard-light.png', 1440, 1700)
        await evaluate("document.querySelector('#theme-toggle').click()")
        await asyncio.sleep(.5)
        assert await evaluate("document.documentElement.dataset.theme === 'dark'")
        await screenshot('dashboard-dark.png', 1440, 1700)
        await evaluate("document.querySelector('#theme-toggle').click()")
        await asyncio.sleep(.5)
        await screenshot('dashboard-mobile.png', 390, 1000, True)
        assert await evaluate('document.documentElement.scrollWidth <= 390'), 'Mobile viewport overflow.'
        await evaluate("document.querySelector('#menu-toggle').click()")
        assert await evaluate("document.querySelector('#sidebar').classList.contains('open')")
        await evaluate("document.querySelector('#overlay').click()")
        await command('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        await navigate('/components/')
        await screenshot('components.png', 1440, 1000)
        await navigate('/projects/')
        await screenshot('projects.png', 1440, 1000)
        await navigate('/projects/?layout=board')
        assert await evaluate("document.querySelectorAll('.kanban-column').length === 3"), 'Kanban columns not rendered.'
        await screenshot('kanban.png', 1440, 1000)
        await navigate('/calendar/')
        await screenshot('calendar.png', 1440, 1000)
        await navigate(f'/messages/?with={peer_id}')
        await screenshot('messages.png', 1440, 1000)
        submitted = await evaluate("""(async () => {
          const form = document.querySelector('#message-compose');
          form.querySelector('textarea').value = '<script>unsafe</script>';
          const response = await fetch('/messages/', {method:'POST', body:new FormData(form), credentials:'same-origin'});
          return response.ok && response.redirected;
        })()""")
        assert submitted, 'Message POST failed.'
        await navigate(f'/messages/?with={peer_id}')
        assert await evaluate("document.querySelector('.chat-log').textContent.includes('<script>unsafe</script>') && !document.querySelector('.chat-log script')"), 'Messages must be persisted and escaped.'
        await navigate('/settings/')
        saved = await evaluate("""(async () => {
          const form = document.querySelector('#account-settings');
          form.querySelector('[name=theme]').value = 'dark';
          const response = await fetch('/settings/', {method:'POST', body:new FormData(form), credentials:'same-origin'});
          return response.ok && response.redirected;
        })()""")
        assert saved, 'Settings POST failed.'
        await navigate('/projects/')
        assert await evaluate("document.documentElement.dataset.theme === 'dark'"), 'Theme not persisted.'
        await evaluate("document.querySelector('#theme-toggle').click()")
        await asyncio.sleep(.5)
        # Check responsive overflow on every application section.
        await command('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 900, 'deviceScaleFactor': 1, 'mobile': True})
        for path in ['/projects/', '/projects/?layout=board', '/invoices/', '/expenses/', '/tasks/', '/calendar/', '/messages/', '/settings/', '/team/', '/notifications/', '/search/?q=check']:
            await navigate(path)
            assert await evaluate('document.documentElement.scrollWidth <= 390'), f'Mobile viewport overflow: {path}'
        await command('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        await command('Network.deleteCookies', {'name': settings.SESSION_COOKIE_NAME, 'url': BASE_URL})
        await navigate('/accounts/login/')
        await screenshot('login.png', 1440, 1000)
        await command('Network.setCookie', {'name': settings.SESSION_COOKIE_NAME, 'value': session_key, 'url': BASE_URL, 'httpOnly': True, 'sameSite': 'Lax'})
        await navigate('/admin/')
        assert await evaluate("!!document.querySelector('#content-main')"), 'Admin login failed.'
        await screenshot('django-admin.png', 1440, 1000)
        assert await evaluate("!!document.querySelector('.admin-stats')"), 'Live admin summary not found.'
        assert await evaluate('document.documentElement.scrollWidth <= 1440'), 'Admin viewport overflow.'
        # Test actual card drag and detached bulk checkboxes using disposable records.
        project_id, task_id = await asyncio.to_thread(create_workflow)
        await navigate('/invoices/')
        assert await evaluate("""(() => {
          document.querySelector('#search-shortcut').click();
          return document.activeElement === document.querySelector('.search-box input');
        })()"""), 'Clickable search shortcut failed.'
        assert await evaluate("""(() => {
          document.activeElement.blur();
          document.dispatchEvent(new KeyboardEvent('keydown', {key:'ن',code:'KeyK',ctrlKey:true,bubbles:true,cancelable:true}));
          return document.activeElement === document.querySelector('.search-box input');
        })()"""), 'Search shortcut with Persian keyboard failed.'
        await evaluate("document.querySelector('.search-box input').value = 'Browser-check'; document.querySelector('.search-submit').click(); true")
        for _ in range(50):
            await asyncio.sleep(.1)
            if await evaluate("location.pathname === '/search/' && document.readyState === 'complete'"):
                break
        assert await evaluate(f"!!document.querySelector('.search-results a[href=\"/projects/{project_id}/\"]')"), 'Header search did not return stored project.'
        await navigate('/projects/?layout=board')
        await evaluate(f"""(() => {{
          const card = document.querySelector('[data-project-id="{project_id}"]');
          const column = document.querySelector('.kanban-column[data-status="review"]');
          const transfer = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {{bubbles:true, cancelable:true, dataTransfer:transfer}}));
          column.dispatchEvent(new DragEvent('dragover', {{bubbles:true, cancelable:true, dataTransfer:transfer}}));
          column.dispatchEvent(new DragEvent('drop', {{bubbles:true, cancelable:true, dataTransfer:transfer}}));
          return true;
        }})()""")
        await asyncio.sleep(1)
        await navigate('/projects/?layout=board')
        assert await evaluate(f"!!document.querySelector('.kanban-column[data-status=review] [data-project-id=\"{project_id}\"]')"), 'Dragged project status not persisted.'
        await navigate('/tasks/')
        bulk_saved = await evaluate(f"""(async () => {{
          const box = document.querySelector('.record-checkbox[value="{task_id}"]');
          box.checked = true; box.dispatchEvent(new Event('change', {{bubbles:true}}));
          if (document.querySelector('#bulk-submit').disabled) return {{error:'disabled'}};
          const form = document.querySelector('#bulk-form');
          const payload = new FormData(form);
          if (payload.getAll('ids').join(',') !== '{task_id}') return {{error:'ids',ids:payload.getAll('ids')}};
          const response = await fetch(form.getAttribute('action'), {{method:'POST',body:payload,credentials:'same-origin'}});
          return {{ok:response.ok,redirected:response.redirected,status:response.status}};
        }})()""")
        assert bulk_saved.get('ok') and bulk_saved.get('redirected'), f'Bulk selection/form submission failed: {bulk_saved}'
        print('Browser checks passed: header search/shortcut/Persian keyboard, independent scroll geometry/movement, kanban, database reports, chat/settings, mobile, admin.', flush=True)

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    user = get_user_model().objects.create_superuser(f'preview-{uuid.uuid4().hex[:8]}', '', None)
    peer = get_user_model().objects.create_user(f'conversation-check-{uuid.uuid4().hex[:8]}')
    client = Client()
    client.force_login(user)
    session_key = client.session.session_key
    workflow_ids = {}
    def create_workflow():
        project = Project.objects.create(name=f'Browser-check-{uuid.uuid4().hex[:8]}', client='Browser validation', due_date=django.utils.timezone.localdate())
        workflow_ids['project'] = project.pk
        task = Task.objects.create(title=f'Browser-check-{uuid.uuid4().hex[:8]}', project=project)
        workflow_ids['task'] = task.pk
        return project.pk, task.pk
    try:
        with tempfile.TemporaryDirectory(prefix='canopy-chrome-') as profile:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            process = subprocess.Popen([CHROME, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=9223', f'--user-data-dir={profile}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=1) as response:
                            pages = json.load(response)
                        target = next(page for page in pages if page['type'] == 'page')
                        break
                    except (OSError, StopIteration):
                        time.sleep(.1)
                else:
                    raise RuntimeError('Chrome debugging endpoint not available.')
                expected_chart = reports()['chart_data']
                asyncio.run(capture(target['webSocketDebuggerUrl'], session_key, peer.pk, expected_chart, create_workflow))
                assert DirectMessage.objects.filter(sender=user, recipient=peer, body='<script>unsafe</script>').exists()
                assert Project.objects.get(pk=workflow_ids['project']).status == 'review'
                assert Task.objects.get(pk=workflow_ids['task']).completed
            finally:
                process.terminate()
                process.wait(timeout=15)
                time.sleep(1)
    finally:
        Session.objects.filter(session_key=session_key).delete()
        Activity.objects.filter(actor=user).delete()
        Task.objects.filter(pk=workflow_ids.get('task')).delete()
        Project.objects.filter(pk=workflow_ids.get('project')).delete()
        user.delete()
        peer.delete()

if __name__ == '__main__':
    main()
