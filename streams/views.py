import hashlib
import json
import secrets
from collections import defaultdict

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.core.cache import cache
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from .models import PushControlToken, PushRoute, StreamMeta

API_URL = settings.SLS_API_URL if hasattr(settings, 'SLS_API_URL') else 'http://localhost:8789'
API_KEY = settings.SLS_API_KEY if hasattr(settings, 'SLS_API_KEY') else ''
INTERNAL_PUSH_PLAYER_PREFIX = "__pushsrc_"
INTERNAL_PUSH_PLAYER_DESC = "[internal push source]"


def conditional_login_required(view_func):
    def _wrapped_view(request, *args, **kwargs):
        if getattr(settings, 'REQUIRE_LOGIN', True):
            if not request.user.is_authenticated:
                return redirect('streams:login')
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _throttle_cache_keys(ip, username):
    key_base = f"login-throttle:{ip}:{(username or '').strip().lower() or '_'}"
    return f"{key_base}:attempts", f"{key_base}:lock"


def get_lockout_remaining(ip, username):
    if not settings.SLSPANEL_ENABLE_LOGIN_THROTTLE:
        return 0

    _attempt_key, lock_key = _throttle_cache_keys(ip, username)
    lock_until = cache.get(lock_key)
    if lock_until is None:
        return 0

    remaining = int(lock_until - timezone.now().timestamp())
    return max(0, remaining)


def register_login_failure(ip, username):
    if not settings.SLSPANEL_ENABLE_LOGIN_THROTTLE:
        return

    attempt_key, lock_key = _throttle_cache_keys(ip, username)
    attempts = cache.get(attempt_key, 0) + 1
    cache.set(attempt_key, attempts, timeout=settings.SLSPANEL_LOGIN_THROTTLE_WINDOW_SECONDS)

    if attempts >= settings.SLSPANEL_LOGIN_THROTTLE_MAX_ATTEMPTS:
        lock_until = int(timezone.now().timestamp()) + settings.SLSPANEL_LOGIN_LOCKOUT_SECONDS
        cache.set(lock_key, lock_until, timeout=settings.SLSPANEL_LOGIN_LOCKOUT_SECONDS)
        cache.delete(attempt_key)


def reset_login_throttle(ip, username):
    if not settings.SLSPANEL_ENABLE_LOGIN_THROTTLE:
        return
    attempt_key, lock_key = _throttle_cache_keys(ip, username)
    cache.delete_many([attempt_key, lock_key])


def login_view(request):
    error = None
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password')
        client_ip = get_client_ip(request)
        remaining = get_lockout_remaining(client_ip, username)
        if remaining > 0:
            minutes = max(1, (remaining + 59) // 60)
            error = _("Too many login attempts. Try again in %(minutes)s minute(s).") % {"minutes": minutes}
            return render(request, 'login.html', {'error': error})

        user = authenticate(request, username=username, password=password)
        if user is not None:
            reset_login_throttle(client_ip, username)
            login(request, user)
            return redirect('streams:index')
        register_login_failure(client_ip, username)
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

        if player and not player.startswith(INTERNAL_PUSH_PLAYER_PREFIX):
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


def normalize_group_name(raw_value):
    return (raw_value or '').strip()


def apply_stream_layout(streams):
    meta_by_publisher = {
        row.publisher: row
        for row in StreamMeta.objects.filter(
            publisher__in=[stream['publisher'] for stream in streams]
        )
    }

    ordered = []
    for default_index, stream in enumerate(streams):
        meta = meta_by_publisher.get(stream['publisher'])
        stream['group_name'] = normalize_group_name(meta.group_name if meta else '')
        stream['sort_order'] = meta.sort_order if meta else default_index
        ordered.append(stream)

    ordered.sort(key=lambda item: (item['group_name'].lower(), item['sort_order'], item['publisher']))
    return ordered


def build_stream_groups(streams):
    grouped = defaultdict(list)
    for stream in streams:
        group_key = stream.get('group_name') or ''
        grouped[group_key].append(stream)

    groups = []
    for key in sorted(grouped.keys(), key=lambda value: (value == '', value.lower())):
        groups.append({
            'name': key,
            'label': key or 'Ungrouped',
            'streams': grouped[key],
        })
    return groups


def build_hidden_push_player_key(publisher):
    digest = hashlib.sha1(publisher.encode("utf-8")).hexdigest()[:20]
    return f"{INTERNAL_PUSH_PLAYER_PREFIX}{digest}"


def ensure_hidden_push_source(route, entries=None):
    if entries is None:
        entries = get_stream_entries()

    had_existing_source = bool(route.source_player_key.strip()) if route.source_player_key else False
    source_key = route.source_player_key.strip() if route.source_player_key else ""
    if not source_key:
        source_key = build_hidden_push_player_key(route.publisher)

    for entry in entries:
        if entry.get("publisher") == route.publisher and entry.get("player") == source_key:
            if route.source_player_key != source_key:
                route.source_player_key = source_key
                route.save(update_fields=["source_player_key", "updated_at"])
            return source_key, entries

    create_payload = {
        "publisher": route.publisher,
        "player": source_key,
        "description": INTERNAL_PUSH_PLAYER_DESC,
    }
    code, _res = call_api("POST", "/api/stream-ids", create_payload)
    if code and 200 <= code < 300:
        route.source_player_key = source_key
        route.save(update_fields=["source_player_key", "updated_at"])
        return source_key, get_stream_entries()

    refreshed_entries = get_stream_entries()
    for entry in refreshed_entries:
        if entry.get("publisher") == route.publisher and entry.get("player") == source_key:
            route.source_player_key = source_key
            route.save(update_fields=["source_player_key", "updated_at"])
            return source_key, refreshed_entries

    for entry in entries:
        if entry.get("publisher") == route.publisher and entry.get("player") == source_key:
            route.source_player_key = source_key
            route.save(update_fields=["source_player_key", "updated_at"])
            return source_key, entries

    if had_existing_source:
        # Keep previously-known source key when transient API checks fail.
        return source_key, entries

    return "", entries


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
    provided = ''
    if auth_header.startswith('Bearer '):
        provided = auth_header.split(' ', 1)[1]
    elif request.GET.get('token'):
        provided = request.GET.get('token', '')

    if not provided:
        return None, JsonResponse({"ok": False, "summary": "missing token"}, status=401)

    token_hash = hash_token(provided)

    token = PushControlToken.objects.filter(token_hash=token_hash, publisher=publisher, active=True).first()
    if token is None:
        return None, JsonResponse({"ok": False, "summary": "invalid or inactive control token"}, status=403)

    token.last_used_at = timezone.now()
    token.save(update_fields=['last_used_at'])
    return token, None


def summarize_state(route, publisher):
    message = (route.last_error or '').strip()
    summary = message if message else f"push {'enabled' if route.enabled else 'disabled'} ({route.runner_state})"
    return {
        "ok": True,
        "publisher": publisher,
        "enabled": bool(route.enabled),
        "runner_state": route.runner_state,
        "runner_badge": push_state_badge(route.runner_state),
        "summary": summary,
        "destination_url": route.destination_url,
        "source_player_key": route.source_player_key,
        "relay_bitrate_kbps": route.relay_bitrate_kbps,
        "relay_uptime_seconds": route.relay_uptime_seconds,
        "retry_in_seconds": route.retry_in_seconds,
        "last_exit_code": route.last_exit_code,
        "runner_updated_at": route.runner_updated_at.isoformat() if route.runner_updated_at else None,
        "timestamp": timezone.now().isoformat(),
    }


@conditional_login_required
def index(request):
    entries = get_stream_entries()
    streams = apply_stream_layout(map_publishers(entries))

    routes_by_publisher = {route.publisher: route for route in PushRoute.objects.all()}
    token_count = {}
    for row in PushControlToken.objects.filter(active=True).values('publisher'):
        key = row['publisher']
        token_count[key] = token_count.get(key, 0) + 1

    for stream in streams:
        route = routes_by_publisher.get(stream['publisher'])
        push = {
            'destination_url': '',
            'source_player_key': '',
            'enabled': False,
            'runner_state': 'stopped',
            'runner_badge': push_state_badge('stopped'),
            'last_error': 'push disabled',
            'token_count': token_count.get(stream['publisher'], 0),
            'new_control_token': request.session.pop(f"control_token_{stream['publisher']}", None),
            'relay_bitrate_kbps': 0,
            'relay_uptime_seconds': 0,
            'retry_in_seconds': 0,
            'last_exit_code': None,
            'runner_updated_at': None,
        }
        if route is not None:
            push.update({
                'destination_url': route.destination_url,
                'source_player_key': route.source_player_key,
                'enabled': route.enabled,
                'runner_state': route.runner_state,
                'runner_badge': push_state_badge(route.runner_state),
                'last_error': route.last_error or ('relay active' if route.runner_state == 'running' else ''),
                'relay_bitrate_kbps': route.relay_bitrate_kbps,
                'relay_uptime_seconds': route.relay_uptime_seconds,
                'retry_in_seconds': route.retry_in_seconds,
                'last_exit_code': route.last_exit_code,
                'runner_updated_at': route.runner_updated_at.isoformat() if route.runner_updated_at else None,
            })
        stream['push'] = push

    context = {
        'stream_groups': build_stream_groups(streams),
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
def api_push_routes_status(request):
    if request.method != 'GET':
        return HttpResponseBadRequest('GET required')

    routes = []
    for route in PushRoute.objects.all():
        state_message = (route.last_error or '').strip()
        if not state_message:
            if route.runner_state == 'running':
                state_message = 'relay active'
            elif route.enabled:
                state_message = f"push enabled ({route.runner_state})"
            else:
                state_message = "push disabled"
        routes.append({
            "publisher": route.publisher,
            "enabled": bool(route.enabled),
            "runner_state": route.runner_state,
            "runner_badge": push_state_badge(route.runner_state),
            "last_error": state_message,
            "destination_url": route.destination_url,
            "source_player_key": route.source_player_key,
            "relay_bitrate_kbps": route.relay_bitrate_kbps,
            "relay_uptime_seconds": route.relay_uptime_seconds,
            "retry_in_seconds": route.retry_in_seconds,
            "last_exit_code": route.last_exit_code,
            "runner_updated_at": route.runner_updated_at.isoformat() if route.runner_updated_at else None,
        })

    return JsonResponse({"status": "success", "routes": routes})


@conditional_login_required
def update_stream_group(request, publisher_key):
    if request.method != 'POST':
        return redirect('streams:index')

    group_name = normalize_group_name(request.POST.get('group_name'))
    meta, _created = StreamMeta.objects.get_or_create(publisher=publisher_key)
    meta.group_name = group_name
    if _created and meta.sort_order == 0:
        meta.sort_order = StreamMeta.objects.count()
    meta.save(update_fields=['group_name', 'sort_order', 'updated_at'])
    return redirect('streams:index')


@conditional_login_required
def save_stream_layout(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest('Invalid JSON')

    layout = payload.get('layout')
    if not isinstance(layout, list):
        return HttpResponseBadRequest('layout must be a list')

    known_publishers = {row['publisher'] for row in map_publishers(get_stream_entries())}
    sort_counter = 0
    for row in layout:
        publisher = row.get('publisher')
        if publisher not in known_publishers:
            continue

        group_name = normalize_group_name(row.get('group_name'))
        order = row.get('sort_order')
        if not isinstance(order, int):
            order = sort_counter

        meta, _created = StreamMeta.objects.get_or_create(publisher=publisher)
        meta.group_name = group_name
        meta.sort_order = order
        meta.save(update_fields=['group_name', 'sort_order', 'updated_at'])
        sort_counter += 1

    return JsonResponse({'status': 'success'})


@conditional_login_required
def sls_publisher_stats(request, publisher_key):
    try:
        url = f"http://{settings.SLS_STATS_DOMAIN_IP}:{settings.SLS_STATS_PORT}/stats/publisher/{publisher_key}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return JsonResponse(data)
    except Exception:
        return JsonResponse({"error": "Failed to fetch publisher stats", "status": "error"}, status=500)


@conditional_login_required
def sls_consumer_stats(request, player_key):
    try:
        url = f"http://{settings.SLS_STATS_DOMAIN_IP}:{settings.SLS_STATS_PORT}/stats/consumers/{player_key}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return JsonResponse(data)
    except Exception:
        return JsonResponse({"error": "Failed to fetch consumer stats", "status": "error"}, status=500)


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
    StreamMeta.objects.filter(publisher=publisher_key).delete()
    return redirect('streams:index')


@conditional_login_required
def delete_player(request, player_key):
    if player_key.startswith(INTERNAL_PUSH_PLAYER_PREFIX):
        return redirect('streams:index')
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
            next_enabled = not route.enabled
            if next_enabled:
                source_key, _entries = ensure_hidden_push_source(route)
                if not source_key:
                    route.enabled = False
                    route.last_error = 'Failed to prepare internal push source player key'
                else:
                    route.enabled = True
                    route.last_error = ''
            else:
                route.enabled = False
                route.last_error = ''
                route.retry_in_seconds = 0

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
    routes = []
    for route in PushRoute.objects.all():
        source_key, entries = ensure_hidden_push_source(route, entries)
        if route.enabled and not source_key:
            route.last_error = "internal push source key is currently unavailable (auto-retrying)"
            route.save(update_fields=["last_error", "updated_at"])
        routes.append({
            'publisher': route.publisher,
            'player': source_key,
            'source_stream_id': source_key,
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
    try:
        route.relay_bitrate_kbps = float(payload.get('relay_bitrate_kbps', route.relay_bitrate_kbps) or 0)
    except (TypeError, ValueError):
        route.relay_bitrate_kbps = 0
    try:
        route.relay_uptime_seconds = int(payload.get('relay_uptime_seconds', route.relay_uptime_seconds) or 0)
    except (TypeError, ValueError):
        route.relay_uptime_seconds = 0
    try:
        route.retry_in_seconds = int(payload.get('retry_in_seconds', route.retry_in_seconds) or 0)
    except (TypeError, ValueError):
        route.retry_in_seconds = 0
    route.last_exit_code = payload.get('last_exit_code', route.last_exit_code)
    route.runner_updated_at = timezone.now()
    route.save()

    return JsonResponse({'status': 'success'})


@csrf_exempt
def api_push_enable(request, publisher_key):
    if request.method not in {'POST', 'GET'}:
        return HttpResponseBadRequest('POST or GET required')

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

    source_key, _entries = ensure_hidden_push_source(route)
    if not source_key:
        return JsonResponse({
            "ok": False,
            "publisher": publisher_key,
            "enabled": False,
            "runner_state": route.runner_state,
            "summary": "cannot enable push: internal source key setup failed",
            "timestamp": timezone.now().isoformat(),
        }, status=500)

    route.enabled = True
    route.last_error = ''
    route.save()
    return JsonResponse(summarize_state(route, publisher_key))


@csrf_exempt
def api_push_disable(request, publisher_key):
    if request.method not in {'POST', 'GET'}:
        return HttpResponseBadRequest('POST or GET required')

    _token, error = control_token_ok(request, publisher_key)
    if error is not None:
        return error

    route, _created = PushRoute.objects.get_or_create(publisher=publisher_key)
    route.enabled = False
    route.retry_in_seconds = 0
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
