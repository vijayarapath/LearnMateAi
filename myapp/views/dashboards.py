from datetime import timedelta

from django.db.models import Avg, Count
from django.shortcuts import render
from django.utils import timezone

from myapp.models import (Assignment, Conversation, Course, Enrollment, Message, QuizAttempt, StudyTask, Quiz, AIRequestLog,
                          LearningMaterial, GeneratedVisual)
from myapp.services import analytics


def student_dashboard(request):
    u = request.user
    today = timezone.localdate()
    ctx = {
        "stats": analytics.student_stats(u),
        "weekly": analytics.weekly_activity(u),
        "courses": Course.objects.filter(enrollments__student=u, is_active=True).select_related("subject")[:6],
        "recent_questions": Message.objects.filter(conversation__owner=u, role="user").select_related("conversation")[:5],
        "tasks": StudyTask.objects.filter(plan__owner=u, plan__is_active=True, completed=False, scheduled_date__lte=today + timedelta(days=7))
                 .select_related("plan")[:6],
        "recommended": analytics.recommended_topics(u),
        "attempts": QuizAttempt.objects.filter(student=u, submitted_at__isnull=False).select_related("quiz")[:5],
        "due": Assignment.objects.filter(course__enrollments__student=u, due_date__gte=today)[:4],
    }
    return render(request, "myapp/dashboard_student.html", ctx)


def teacher_dashboard(request):
    u = request.user
    courses = Course.objects.filter(teacher=u).annotate(n=Count("enrollments"))
    student_ids = Enrollment.objects.filter(course__teacher=u).values_list("student_id", flat=True).distinct()
    attempts = QuizAttempt.objects.filter(quiz__course__teacher=u, submitted_at__isnull=False)
    ctx = {
        "courses": courses,
        "student_count": len(set(student_ids)),
        "avg": round(attempts.aggregate(a=Avg("percent"))["a"] or 0),
        "attempt_count": attempts.count(),
        "recent_attempts": attempts.select_related("quiz", "student")[:8],
        "upcoming": Assignment.objects.filter(course__teacher=u, due_date__gte=timezone.localdate())[:6],
    }
    return render(request, "myapp/dashboard_teacher.html", ctx)


def admin_dashboard(request):
    ctx = {"s": analytics.platform_stats(), "flagged": LearningMaterial.objects.filter(is_flagged=True).count() +
           GeneratedVisual.objects.filter(is_flagged=True).count()}
    return render(request, "myapp/dashboard_admin.html", ctx)
