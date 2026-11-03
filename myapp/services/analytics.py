from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from myapp.models import (Conversation, Course, LearningActivity, Message, Notification, QuizAnswer, QuizAttempt,
                          StudyPlan, StudyTask, TopicProgress)
from .planner import weak_topics


def streak(user):
    days = set(LearningActivity.objects.filter(student=user).values_list("occurred_on", flat=True))
    today = timezone.localdate()
    cur = today if today in days else today - timedelta(days=1)
    n = 0
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def weekly_activity(user):
    today = timezone.localdate()
    start = today - timedelta(days=6)
    rows = LearningActivity.objects.filter(student=user, occurred_on__gte=start).values("occurred_on").annotate(m=Sum("minutes"))
    by_day = {r["occurred_on"]: r["m"] for r in rows}
    labels, values = [], []
    for i in range(7):
        d = start + timedelta(days=i)
        labels.append(d.strftime("%a"))
        values.append(by_day.get(d, 0))
    return {"labels": labels, "values": values}


def student_stats(user):
    minutes = LearningActivity.objects.filter(student=user).aggregate(m=Sum("minutes"))["m"] or 0
    attempts = QuizAttempt.objects.filter(student=user, submitted_at__isnull=False)
    avg = attempts.aggregate(a=Avg("percent"))["a"]
    plan_tasks = StudyTask.objects.filter(plan__owner=user, plan__is_active=True)
    total_tasks = plan_tasks.count()
    done_tasks = plan_tasks.filter(completed=True).count()
    return {
        "streak": streak(user),
        "hours": round(minutes / 60, 1),
        "lessons": TopicProgress.objects.filter(student=user, completed=True).count() + StudyTask.objects.filter(plan__owner=user, completed=True, kind="learn").count(),
        "quiz_avg": round(avg) if avg is not None else None,
        "quiz_count": attempts.count(),
        "plan_percent": round(100 * done_tasks / total_tasks) if total_tasks else None,
    }


def recommended_topics(user):
    recs = [{"topic": t, "reason": "Low quiz accuracy"} for t in weak_topics(user)]
    if not recs:
        for c in Course.objects.filter(enrollments__student=user)[:3]:
            done = set(TopicProgress.objects.filter(student=user, completed=True).values_list("topic_id", flat=True))
            nxt = c.topics.exclude(id__in=done).first()
            if nxt:
                recs.append({"topic": nxt.title, "reason": f"Next in {c.title}"})
    return recs[:5]


def topic_performance(user):
    d = defaultdict(lambda: [0, 0])
    for a in QuizAnswer.objects.filter(attempt__student=user, attempt__submitted_at__isnull=False).select_related("question"):
        t = a.question.topic or a.question.quiz.topic
        d[t][0] += a.is_correct
        d[t][1] += 1
    rows = [{"topic": t, "percent": round(100 * c / n), "answered": n} for t, (c, n) in d.items()]
    return sorted(rows, key=lambda r: r["percent"])


def class_report(course):
    """Aggregate view for teachers. Only call with a course the teacher owns."""
    student_ids = list(course.enrollments.values_list("student_id", flat=True))
    answers = QuizAnswer.objects.filter(attempt__student_id__in=student_ids, attempt__quiz__course=course, attempt__submitted_at__isnull=False).select_related("question")
    d = defaultdict(lambda: [0, 0])
    for a in answers:
        d[a.question.topic or "General"][0] += a.is_correct
        d[a.question.topic or "General"][1] += 1
    topics = sorted(({"topic": t, "percent": round(100 * c / n), "answered": n} for t, (c, n) in d.items()), key=lambda r: r["percent"])
    rows = []
    for s in User.objects.filter(id__in=student_ids).select_related("profile"):
        att = QuizAttempt.objects.filter(student=s, quiz__course=course, submitted_at__isnull=False)
        plan = StudyPlan.objects.filter(owner=s, is_active=True).first()
        rows.append({"student": s, "avg": round(att.aggregate(a=Avg("percent"))["a"] or 0) if att.exists() else None,
                     "attempts": att.count(), "plan_percent": plan.completion_percent if plan else None,
                     "streak": streak(s)})
    return {"students": rows, "weak_topics": topics[:8], "topic_chart": {"labels": [t["topic"] for t in topics[:8]], "values": [t["percent"] for t in topics[:8]]}}


def platform_stats():
    from myapp.models import AIRequestLog, GeneratedVisual, Profile, UploadedImage
    from django.db.models import Count
    since = timezone.now() - timedelta(days=7)
    logs = AIRequestLog.objects.filter(created_at__gte=since)
    by_service = list(logs.values("service").annotate(n=Count("id"), avg=Avg("latency_ms")).order_by("-n"))
    errs = list(logs.filter(ok=False).values("service", "error_code").annotate(n=Count("id")).order_by("-n")[:8])
    return {
        "users": User.objects.count(),
        "students": Profile.objects.filter(role="student").count(),
        "teachers": Profile.objects.filter(role="teacher").count(),
        "courses": Course.objects.count(),
        "ai_requests_7d": logs.count(),
        "ai_errors_7d": logs.filter(ok=False).count(),
        "by_service": by_service,
        "errors": errs,
        "images": UploadedImage.objects.count() + GeneratedVisual.objects.count(),
    }
