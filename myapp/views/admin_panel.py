import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from myapp.forms import SubjectForm
from myapp.models import AIRequestLog, GeneratedVisual, LearningMaterial, Profile, ROLE_CHOICES, Subject
from myapp.services.access import role_required
from myapp.services.adapters import (LocalMuseModelService, MuseImageService, MuseSparkService, MuseVoiceTranscribeService,
                                     MuseWonderService, SAM31Service)


@role_required("admin")
def users(request):
    q = (request.GET.get("q") or "").strip()
    qs = User.objects.select_related("profile").order_by("-date_joined")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "myapp/admin_users.html", {"page": page, "q": q, "roles": ROLE_CHOICES})


@role_required("admin")
@require_POST
def user_update(request, pk):
    u = get_object_or_404(User, pk=pk)
    action = request.POST.get("action")
    if u == request.user and action in ("deactivate", "role"):
        messages.error(request, "You cannot change your own role or deactivate your own account here.")
    elif action == "role" and request.POST.get("role") in dict(ROLE_CHOICES):
        u.profile.role = request.POST["role"]
        u.profile.save(update_fields=["role"])
        messages.success(request, f"{u.username} is now {request.POST['role']}.")
    elif action in ("deactivate", "activate"):
        u.is_active = action == "activate"
        u.save(update_fields=["is_active"])
        messages.success(request, f"{u.username} was {'activated' if u.is_active else 'deactivated'}.")
    return redirect("admin_users")


@role_required("admin")
def subjects(request):
    form = SubjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Subject added.")
        return redirect("admin_subjects")
    return render(request, "myapp/admin_subjects.html", {"subjects": Subject.objects.all(), "form": form})


@role_required("admin")
@require_POST
def subject_toggle(request, pk):
    s = get_object_or_404(Subject, pk=pk)
    s.is_active = not s.is_active
    s.save(update_fields=["is_active"])
    return redirect("admin_subjects")


@role_required("admin")
def moderation(request):
    return render(request, "myapp/admin_moderation.html", {
        "materials": LearningMaterial.objects.select_related("course")[:40], "visuals": GeneratedVisual.objects.select_related("owner")[:40]})


@role_required("admin")
@require_POST
def moderation_toggle(request, kind, pk):
    obj = get_object_or_404(LearningMaterial if kind == "material" else GeneratedVisual, pk=pk)
    obj.is_flagged = not obj.is_flagged
    obj.save(update_fields=["is_flagged"])
    return redirect("admin_moderation")


@role_required("admin")
def ai_logs(request):
    qs = AIRequestLog.objects.select_related("user")
    if request.GET.get("service"):
        qs = qs.filter(service=request.GET["service"])
    if request.GET.get("status") == "errors":
        qs = qs.filter(ok=False)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    services = AIRequestLog.objects.values_list("service", flat=True).distinct()
    return render(request, "myapp/admin_ai_logs.html", {"page": page, "services": services})


def _dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


@role_required("admin")
def config(request):
    """Shows WHICH services are configured. Keys and prompts are never displayed."""
    svc = [("Muse Spark (tutor, quizzes)", MuseSparkService().is_configured()), ("Muse Wonder (image reading)", MuseWonderService().is_configured()),
           ("Muse Image (illustrations)", MuseImageService().is_configured()), ("Muse Voice Transcribe", MuseVoiceTranscribeService().is_configured()),
           ("SAM 3.1 (diagram regions)", SAM31Service().is_configured()), ("Local model server", LocalMuseModelService().is_configured())]
    return render(request, "myapp/admin_config.html", {
        "services": svc, "text_provider": settings.META_AI["TEXT_PROVIDER"], "limits": settings.AI_RATE_LIMITS,
        "retention": settings.RETENTION_DAYS, "storage_mb": round(_dir_size(settings.MEDIA_ROOT) / 1048576, 2),
        "uploads": {"image": settings.MAX_IMAGE_UPLOAD_MB, "audio": settings.MAX_AUDIO_UPLOAD_MB, "material": settings.MAX_MATERIAL_UPLOAD_MB},
        "debug": settings.DEBUG})
