import hashlib
import json
import secrets

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from .models import PushControlToken, PushRoute

API_URL = settings.SLS_API_URL if hasattr(settings, 'SLS_API_URL') else 'http://localhost:8789'
API_KEY = settings.SLS_API_KEY if hasattr(settings, 'SLS_API_KEY') else ''


def conditional_login_required(view_func):
    def _wrapped_view(request, *args, **kwargs):
        if getattr(settings, 'REQUIRE_LOGIN', True):
            if not request.user.is_authenticated:
                return redirect('streams:login')
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def login_view(request):
    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('streams:index')
        error = _("Invalid credentials")
    return render(request, 'login.html', {'error': error})


def logout_view(request):
    request.session.flush()
    return redirect('streams:login')


def call_api(method, endpoint, data=None):
    headers = {
        'Authorization': f'Bearer {API_KEY}'
    }
    url = f"{API_URL}{endpoint}"
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=5)
        elif method == 'POST':
            response = requests.post(url, json=data, headers=headers, timeout=5)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers, timeout=5)
        else:
            return None, "Unsupported method"
        return response.status_code, response.json() if response.content else {}
    except Exception as exc:
        return None, str(exc)


def get_stream_entries():
    _code, res = call_api('GET', '/api/stream-ids')
    return res.get("data") if res and isinstance(res, dict) and "data" in res else []


def map_publishers(entries):
    publisher_map = {}
    for entry in entries:
        pub = entry.get("publisher")
        player = entry.get("player")
        desc = entry.get("description", "")
        if not pub:
            continue

        if pub not in publisher_map:
            publisher_map[pub] = {"publisher": pub, "player": [], "description": ""}

        if player:
            player_obj = {"key": player, "description": desc}
            if player_obj not in publisher_map[pub]["player"]:
                publisher_map[pub]["player"].append(player_obj)

        if not publisher_map[pub]["description"] and desc:
            publisher_map[pub]["description"] = desc

    streams = list(publisher_map.values())
    for stream in streams:
        if stream["player"]:
            stream["main_player"] = stream["player"][0]["key"]
            stream["main_description"] = stream["player"][0]["description"]
        else:
            stream["main_player"] = None
            stream["main_description"] = ""

    return streams


def push_state_badge(state):
    if state == 'running':
        return 'success'
    if state in {'retrying', 'error'}:
        return 'danger'
    if state in {'idle', 'stopped'}:
        return 'secondary'
    return 'warning'


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def internal_token_ok(request):
    configured = getattr(settings, 'PUSH_INTERNAL_TOKEN', '')
    if not configured:
        return False, JsonResponse({"status": "error", "message": "PUSH_INTERNAL_TOKEN is not configured"}, status=503)

    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return False, HttpResponseForbidden("Missing bearer token")

    provided = auth_header.split(' ', 1)[1]
    if not secrets.compare_digest(provided, configured):
        return False, HttpResponseForbidden("Invalid token")

    return True, None


def control_token_ok(request, publisher):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, JsonResponse({"ok": False, "summary": "missing bearer token"}, status=401)

    provided = auth_header.split(' ', 1)[1]
    token_hash = hash_token(provided)

    token = PushControlToken.objects.filter(token_hash=token_hash, publisher=publisher, active=True).first()
    if token is None:
        return None, JsonResponse({"ok": False, "summary": "invalid or inactive control token"}, status=403)

    token.last_used_at = timezone.now()
    token.save(update_fields=['last_used_at'])
    return token, None


def summarize_state(route, publisher):
    return {
        "ok": True,
        "publisher": publisher,
        "enabled": bool(route.enabled),
        "runner_state": route.runner_state,
        "summary": f"push {'enabled' if route.enabled else 'disabled'} ({route.runner_state})",
        "timestamp": timezone.now().isoformat(),
    }


@conditional_login_required
def index(request):
    entries = get_stream_entries()
    streams = map_publishers(entries)

    routes_by_publisher = {route.publisher: route for route in PushRoute.objects.all()}
    token_count = {}
    for row in PushControlToken.objects.filter(active=True).values('publisher'):
        key = row['publisher']
        token_count[key] = token_count.get(key, 0) + 1

    for stream in streams:
        route = routes_by_publisher.get(stream['publisher'])
        push = {
            'destination_url': '',
            'enabled': False,
            'runner_state': 'stopped',
            'runner_badge': push_state_badge('stopped'),
            'last_error': '',
            'token_count': token_count.get(stream['publisher'], 0),
            'new_control_token': request.session.pop(f"control_token_{stream['publisher']}", None),
        }
        if route is not None:
            push.update({
                'destination_url': route.destination_url,
                'enabled': route.enabled,
                'runner_state': route.runner_state,
                'runner_badge': push_state_badge(route.runner_state),
                'last_error': route.last_error,
            })
        stream['push'] = push

    context = {
        'streams': streams,
        'srt_publish_port': settings.SRT_PUBLISH_PORT,
        'srt_player_port': settings.SRT_PLAYER_PORT,
        'srtla_publish_port': settings.SRTLA_PUBLISH_PORT,
        'sls_domain_ip': settings.SLS_DOMAIN_IP,
        'sls_stats_port': settings.SLS_STATS_PORT,
        'base_url': request.build_absolute_uri('/').rstrip('/'),
    }
    return render(request, 'index.html', context)


@conditional_login_required
def streams_status_json(request):
    entries = get_stream_entries()
    publisher_map = {}
    for entry in entries:
        pub = entry.get("publisher")
        player = entry.get("player")
        desc = entry.get("description", "")
        if not pub:
            continue
        if pub not in publisher_map:
            publisher_map[pub] = {"publisher": pub, "player": [], "description": desc}
        if desc:
            publisher_map[pub]["description"] = desc
        if player and player not in publisher_map[pub]["player"]:
            publisher_map[pub]["player"].append(player)
    streams = list(publisher_map.values())
    return JsonResponse({"streams": streams})


@conditional_login_required
def sls_stats(request, player_key):
    try:
        url = f"http://{settings.SLS_STATS_DOMAIN_IP}:{settings.SLS_STATS_PORT}/stats/{player_key}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return JsonResponse(data)
    except Exception:
        return JsonResponse({"error": "Failed to fetch stats", "status": "error"}, status=500)


@conditional_login_required
def create_stream(request):
    if request.method == "POST":
        publisher_key = request.POST.get("publisher")
        if not publisher_key:
            publisher_key = 'live_' + secrets.token_hex(16)
        player_key = request.POST.get("player")
        if not player_key:
            player_key = 'play_' + secrets.token_hex(16)
        description = request.POST.get("description", "")
        data = {
            "publisher": publisher_key,
            "player": player_key,
            "description": description,
        }
        code, _res = call_api('POST', '/api/stream-ids', data)
        if code and 200 <= code < 300:
            return redirect('streams:index')
        return render(request, 'create_stream.html', {'error': _("API error"), 'data': data})
    return render(request, 'create_stream.html')


@conditional_login_required
def add_player(request):
    if request.method == "POST":
        if 'confirm' in request.POST:
            publisher_key = request.POST.get("publisher_key")
            player_key = request.POST.get("player_key")
            description = request.POST.get("description")
            data = {"publisher": publisher_key, "player": player_key, "description": description}
            code, _res = call_api('POST', '/api/stream-ids', data)
            if code and 200 <= code < 300:
                return redirect('streams:index')
            return render(request, 'add_player.html', {
                'error': _("API error"),
                'publisher_key': publisher_key,
                'player_key': player_key,
                'description': description,
            })

        publisher_key = request.POST.get("publisher_key")
        player_key = 'play_' + secrets.token_hex(16)
        description = request.POST.get("description", "")
        return render(request, 'add_player.html', {
            'publisher_key': publisher_key,
            'player_key': player_key,
            'description': description,
        })

    publisher_key = request.GET.get("publisher_key", "")
    player_key = 'play_' + secrets.token_hex(16)
    return render(request, 'add_player.html', {
        "publisher_key": publisher_key,
        "player_key": player_key,
        "description": ""
    })


@conditional_login_required
def delete_stream(request, publisher_key):
    entries = get_stream_entries()
    player_keys = [entry["player"] for entry in entries if entry.get("publisher") == publisher_key and entry.get("player")]
    for play_key in player_keys:
        call_api('DELETE', f'/api/stream-ids/{play_key}')
    PushRoute.objects.filter(publisher=publisher_key).delete()
    PushControlToken.objects.filter(publisher=publisher_key).update(active=False)
    return redirect('streams:index')


@conditional_login_required
def delete_player(request, player_key):
    call_api('DELETE', f'/api/stream-ids/{player_key}')
    return redirect('streams:index')


@conditional_login_required
def update_push_route(request, publisher_key):
    if request.method != 'POST':
        return redirect('streams:index')

    route, _created = PushRoute.objects.get_or_create(publisher=publisher_key)
    action = request.POST.get('action', 'save')

    if action == 'save':
        destination_url = request.POST.get('destination_url', '').strip()
        if destination_url and not destination_url.startswith('srt://'):
            route.last_error = 'Destination URL must start with srt://'
        else:
            route.destination_url = destination_url
            if not destination_url:
                route.enabled = False
            route.last_error = ''
    elif action == 'toggle':
        if not route.destination_url:
            route.enabled = False
            route.last_error = 'Set a destination URL before enabling push'
        else:
            route.enabled = not route.enabled
            route.last_error = ''

    route.save()
    return redirect('streams:index')


@conditional_login_required
def create_control_token(request, publisher_key):
    if request.method != 'POST':
        return redirect('streams:index')

    label = request.POST.get('token_label', '').strip()
    token = secrets.token_urlsafe(32)
    PushControlToken.objects.create(
        publisher=publisher_key,
        label=label,
        token_hash=hash_token(token),
        active=True,
    )
    request.session[f"control_token_{publisher_key}"] = token
    return redirect('streams:index')


@conditional_login_required
def revoke_control_tokens(request, publisher_key):
    if request.method != 'POST':
        return redirect('streams:index')

    PushControlToken.objects.filter(publisher=publisher_key, active=True).update(active=False)
    return redirect('streams:index')


@csrf_exempt
def internal_push_routes(request):
    if request.method != 'GET':
        return HttpResponseBadRequest('GET required')

    ok, response = internal_token_ok(request)
    if not ok:
        return response

    entries = get_stream_entries()
    publisher_to_player = {}
    for stream in map_publishers(entries):
        if stream.get('main_player'):
            publisher_to_player[stream['publisher']] = stream['main_player']

    routes = []
    for route in PushRoute.objects.all():
        routes.append({
            'publisher': route.publisher,
            'player': publisher_to_player.get(route.publisher),
            'destination_url': route.destination_url,
            'enabled': route.enabled,
            'runner_state': route.runner_state,
            'last_error': route.last_error,
        })

    return JsonResponse({'status': 'success', 'data': routes})


@csrf_exempt
def internal_push_status(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    ok, response = internal_token_ok(request)
    if not ok:
        return response

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON')

    publisher = payload.get('publisher')
    if not publisher:
        return HttpResponseBadRequest('publisher is required')

    route, _created = PushRoute.objects.get_or_create(publisher=publisher)
    route.runner_state = payload.get('state', route.runner_state)
    route.last_error = payload.get('last_error', route.last_error)
    route.runner_updated_at = timezone.now()
    route.save()

    return JsonResponse({'status': 'success'})


@csrf_exempt
def api_push_enable(request, publisher_key):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    _token, error = control_token_ok(request, publisher_key)
    if error is not None:
        return error

    route, _created = PushRoute.objects.get_or_create(publisher=publisher_key)
    if not route.destination_url:
        return JsonResponse({
            "ok": False,
            "publisher": publisher_key,
            "enabled": False,
            "runner_state": route.runner_state,
            "summary": "cannot enable push: destination URL is empty",
            "timestamp": timezone.now().isoformat(),
        }, status=400)

    route.enabled = True
    route.last_error = ''
    route.save()
    return JsonResponse(summarize_state(route, publisher_key))


@csrf_exempt
def api_push_disable(request, publisher_key):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    _token, error = control_token_ok(request, publisher_key)
    if error is not None:
        return error

    route, _created = PushRoute.objects.get_or_create(publisher=publisher_key)
    route.enabled = False
    route.save()
    return JsonResponse(summarize_state(route, publisher_key))


@csrf_exempt
def api_push_status(request, publisher_key):
    if request.method != 'GET':
        return HttpResponseBadRequest('GET required')

    _token, error = control_token_ok(request, publisher_key)
    if error is not None:
        return error

    route, _created = PushRoute.objects.get_or_create(publisher=publisher_key)
    return JsonResponse(summarize_state(route, publisher_key))
