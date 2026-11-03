from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from myapp.forms import ProfileForm, RegisterForm
from myapp.models import (Conversation, Course, GeneratedVisual, LearningMaterial, Notification, Quiz, SavedNote, StudyPlan,
                          UploadedImage, Profile)
from myapp.services import analytics


def permission_denied(request, exception=None):
    return render(request, "myapp/error.html", {"code": 403, "title": "You can't open this page",
                  "message": "Your account does not have access to this page."}, status=403)


def not_found(request, exception=None):
    return render(request, "myapp/error.html", {"code": 404, "title": "Page not found",
                  "message": "The page may have moved, or the link may be wrong."}, status=404)


def server_error(request):
    return render(request, "myapp/error.html", {"code": 500, "title": "Something went wrong",
                  "message": "We logged the problem. Try again in a moment."}, status=500)


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your account is ready. Turn on AI features in your profile when you want to use the tutor.")
        return redirect("home")
    return render(request, "myapp/auth/register.html", {"form": form})


@login_required
def profile_view(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user.profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("profile")
    return render(request, "myapp/profile.html", {"form": form})


@login_required
def home(request):
    from . import dashboards
    p = request.user.profile
    if p.is_admin_role:
        return dashboards.admin_dashboard(request)
    if p.is_teacher:
        return dashboards.teacher_dashboard(request)
    return dashboards.student_dashboard(request)


@login_required
def search(request):
    q = (request.GET.get("q") or "").strip()[:80]
    results = {}
    if len(q) >= 2:
        u = request.user
        results["Notes"] = SavedNote.objects.filter(owner=u).filter(Q(title__icontains=q) | Q(body__icontains=q))[:8]
        results["Conversations"] = Conversation.objects.filter(owner=u, title__icontains=q)[:8]
        results["Quizzes"] = Quiz.objects.filter(owner=u).filter(Q(title__icontains=q) | Q(topic__icontains=q))[:8]
        results["Study plans"] = StudyPlan.objects.filter(owner=u).filter(Q(goal__icontains=q) | Q(subject__icontains=q))[:8]
        mine = Course.objects.filter(Q(teacher=u) | Q(enrollments__student=u)).distinct()
        results["Courses"] = mine.filter(Q(title__icontains=q) | Q(subject__name__icontains=q))[:8]
    total = sum(len(list(v)) for v in results.values())
    return render(request, "myapp/search.html", {"q": q, "results": results, "total": total})


@login_required
def notifications_view(request):
    if request.method == "POST":
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return redirect("notifications")
    return render(request, "myapp/notifications.html", {"items": Notification.objects.filter(user=request.user)[:100]})


@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    return redirect(n.url or "notifications")


@login_required
def private_media(request, kind, pk):
    """Serves uploads only to people allowed to see them. Nothing is exposed under a public MEDIA_URL."""
    u = request.user
    if kind == "textbook":
        obj = get_object_or_404(UploadedImage, pk=pk, owner=u)
        f = obj.image
    elif kind == "visual":
        obj = get_object_or_404(GeneratedVisual, pk=pk)
        if obj.owner_id != u.id and not u.profile.is_admin_role:
            raise Http404
        f = obj.image
    elif kind == "photo":
        f = get_object_or_404(Profile, pk=pk).photo
    elif kind == "material":
        obj = get_object_or_404(LearningMaterial, pk=pk)
        allowed = (obj.course.teacher_id == u.id or u.profile.is_admin_role
                   or (obj.course.enrollments.filter(student=u).exists() and not obj.is_flagged))
        if not allowed:
            raise Http404
        f = obj.file
    else:
        raise Http404
    if not f:
        raise Http404
    resp = FileResponse(f.open("rb"))
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, max-age=300"
    if kind == "material":
        resp["Content-Disposition"] = f'attachment; filename="{f.name.split("/")[-1]}"'
    return resp
