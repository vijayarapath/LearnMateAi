"""Study plan scheduling. Pure Python, no AI needed, so it always works."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Avg
from django.utils import timezone

from myapp.models import QuizAnswer, StudyPlan, StudyTask

LEVEL_WEIGHT = {"beginner": 1.3, "intermediate": 1.0, "advanced": 0.8}


def weak_topics(user, limit=5):
    """Topics where the student's quiz accuracy is lowest (needs at least 2 answers)."""
    stats = {}
    for a in QuizAnswer.objects.filter(attempt__student=user, attempt__submitted_at__isnull=False).select_related("question"):
        t = a.question.topic
        if t:
            s = stats.setdefault(t, [0, 0])
            s[0] += a.is_correct
            s[1] += 1
    ranked = [(t, c / n) for t, (c, n) in stats.items() if n >= 2 and c / n < 0.7]
    return [t for t, _ in sorted(ranked, key=lambda x: x[1])[:limit]]


def build_schedule(topics, start, target, daily_minutes, level, weak=()):
    """Returns a list of task dicts. Learn sessions come first, revision follows, last day is a milestone."""
    days = max(1, (target - start).days + 1)
    topics = [t.strip() for t in topics if t.strip()]
    if not topics:
        return []
    ordered = sorted(topics, key=lambda t: (0 if t in weak else 1, topics.index(t)))
    per_topic = max(20, int(daily_minutes * LEVEL_WEIGHT.get(level, 1.0) * 0.6))
    tasks, day_i = [], 0

    def day(i):
        return start + timedelta(days=min(i, days - 1))

    learn_days = max(len(ordered), int(days * 0.65))
    step = max(1, learn_days // len(ordered))
    for idx, topic in enumerate(ordered):
        d = day(idx * step)
        prio = 1 if topic in weak else 2
        tasks.append(dict(title=f"Learn: {topic}", topic=topic, kind="learn", date=d, minutes=per_topic, priority=prio))
        tasks.append(dict(title=f"Practice questions: {topic}", topic=topic, kind="practice", date=d + timedelta(days=1) if days > 1 else d,
                          minutes=max(10, daily_minutes - per_topic), priority=prio,
                          practice_prompt=f"Write 5 practice questions on {topic} and check your answers."))
    for idx, topic in enumerate(ordered):
        rev_day = start + timedelta(days=min(days - 1, learn_days + idx * max(1, (days - learn_days) // max(1, len(ordered)))))
        tasks.append(dict(title=f"Revise: {topic}", topic=topic, kind="revise", date=rev_day, minutes=max(10, per_topic // 2), priority=2))
    tasks.append(dict(title="Milestone: take a full practice quiz and review mistakes", topic="", kind="milestone",
                      date=target, minutes=daily_minutes, priority=1))
    for t in tasks:
        t["date"] = min(max(t["date"], start), target)
    return tasks


@transaction.atomic
def create_plan(user, data):
    plan = StudyPlan.objects.create(owner=user, **data)
    weak = weak_topics(user)
    rows = build_schedule(plan.topics, plan.start_date, plan.target_date, plan.daily_minutes, plan.level, weak)
    StudyTask.objects.bulk_create([
        StudyTask(plan=plan, title=r["title"], topic=r["topic"], kind=r["kind"], scheduled_date=r["date"],
                  minutes=r["minutes"], priority=r["priority"], practice_prompt=r.get("practice_prompt", "")) for r in rows
    ])
    return plan


@transaction.atomic
def reschedule(plan, new_target=None):
    """Moves unfinished tasks from the past forward and, optionally, spreads them to a new target date."""
    today = timezone.localdate()
    pending = list(plan.tasks.filter(completed=False).order_by("scheduled_date", "priority", "id"))
    if not pending:
        return 0
    if new_target:
        plan.target_date = new_target
        plan.save(update_fields=["target_date", "updated_at"])
    start = max(today, plan.start_date)
    span = max(1, (plan.target_date - start).days + 1)
    for i, t in enumerate(pending):
        t.scheduled_date = start + timedelta(days=min(span - 1, i * span // len(pending)))
        t.save(update_fields=["scheduled_date", "updated_at"])
    return len(pending)
