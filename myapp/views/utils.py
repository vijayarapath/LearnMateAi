from django.http import JsonResponse
from django.utils import timezone

from myapp.models import LearningActivity, Notification
from myapp.services.errors import AIError, ConsentRequired


def log_activity(user, kind, minutes=5, subject="", detail=""):
    LearningActivity.objects.create(student=user, kind=kind, minutes=minutes, subject=subject[:80], detail=detail[:200],
                                    occurred_on=timezone.localdate())


def notify(user, title, body="", url=""):
    Notification.objects.create(user=user, title=title[:140], body=body[:300], url=url[:200])


def require_ai_consent(user):
    if not user.profile.can_use_ai:
        raise ConsentRequired()


def error_response(exc, status=None):
    if isinstance(exc, AIError):
        code = {"not_configured": 503, "rate_limited": 429, "timeout": 504, "consent_required": 403}.get(exc.code, 502)
        return JsonResponse({"ok": False, "code": exc.code, "error": exc.message, "retryable": exc.retryable}, status=status or code)
    return JsonResponse({"ok": False, "code": "error", "error": str(exc)}, status=status or 400)
