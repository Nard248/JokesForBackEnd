import json
from functools import wraps

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from community_lab import services
from community_lab.models import DemoState
from community_lab.snapshot import build_snapshot


def demo_only(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if (getattr(settings, "COMMUNITY_LAB_ENABLED", False) is not True
                or getattr(settings, "SETTINGS_MODULE", "") != "community_lab.settings"):
            return JsonResponse({"error": "Community lab is available only under its isolated demo settings."}, status=403)
        return view(request, *args, **kwargs)
    return guarded


@require_GET
@never_cache
@ensure_csrf_cookie
@demo_only
def snapshot_view(request):
    # Sharing the state-row lock makes a snapshot internally consistent with mutations.
    with transaction.atomic():
        state = DemoState.objects.select_for_update().filter(pk=1).first()
        if state is None:
            return JsonResponse({"error": "Run seed_community_lab to prepare this synthetic demo."}, status=503)
        return JsonResponse(build_snapshot(state))


def mutation(operation):
    @require_POST
    @never_cache
    @csrf_protect
    @demo_only
    def view(request):
        try:
            if request.content_type != "application/json":
                raise services.InputError("Send a JSON object with application/json content type.", 415)
            data = json.loads(request.body)
            if not isinstance(data, dict):
                raise services.InputError("The request body must be a JSON object.")
            with transaction.atomic():
                # Serializes local demo mutations, including duplicate-key checks.
                state = DemoState.objects.select_for_update().filter(pk=1).first()
                if state is None:
                    raise services.InputError("Run seed_community_lab before using the demo.", 503)
                if operation(state, data):
                    state.revision += 1
                    state.save(update_fields=["revision", "simulated_at"])
                return JsonResponse(build_snapshot(state))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "The request body must be valid UTF-8 JSON."}, status=400)
        except RequestDataTooBig:
            return JsonResponse({"error": "Request bodies are limited to 4 KiB."}, status=413)
        except services.InputError as exc:
            return JsonResponse({"error": str(exc)}, status=exc.status)
    return view


simulate_view = mutation(services.simulate)
share_view = mutation(services.share)
membership_view = mutation(services.membership)
advance_view = mutation(services.advance)
