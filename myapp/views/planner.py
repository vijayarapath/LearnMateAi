from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django import forms

from myapp.forms import StudyPlanForm
from myapp.models import StudyPlan, StudyTask
from myapp.services import planner as svc
from .utils import log_activity, notify


@login_required
def plan_list(request):
    return render(request, "myapp/plan_list.html", {"plans": StudyPlan.objects.filter(owner=request.user)})


@login_required
def plan_create(request):
    form = StudyPlanForm(request.POST or None, initial={"language": request.user.profile.preferred_language, "daily_minutes": 60})
    weak = svc.weak_topics(request.user)
    if request.method == "POST" and form.is_valid():
        data = {k: form.cleaned_data[k] for k in ("goal", "subject", "target_date", "daily_minutes", "level", "language")}
        data["topics"] = form.cleaned_data["topics_text"]
        plan = svc.create_plan(request.user, data)
        notify(request.user, "Study plan created", plan.goal, f"/planner/{plan.id}/")
        messages.success(request, f"Plan ready with {plan.tasks.count()} tasks.")
        return redirect("plan_detail", pk=plan.id)
    return render(request, "myapp/plan_create.html", {"form": form, "weak": weak})


@login_required
def plan_detail(request, pk):
    plan = get_object_or_404(StudyPlan, pk=pk, owner=request.user)
    days = {}
    for t in plan.tasks.all():
        days.setdefault(t.scheduled_date, []).append(t)
    return render(request, "myapp/plan_detail.html", {"plan": plan, "days": sorted(days.items()), "today": timezone.localdate(),
                  "overdue": plan.tasks.filter(completed=False, scheduled_date__lt=timezone.localdate()).count()})


@login_required
@require_POST
def plan_delete(request, pk):
    get_object_or_404(StudyPlan, pk=pk, owner=request.user).delete()
    return redirect("plan_list")


@login_required
@require_POST
def plan_reschedule(request, pk):
    plan = get_object_or_404(StudyPlan, pk=pk, owner=request.user)
    new_target = None
    raw = request.POST.get("target_date")
    if raw:
        try:
            new_target = forms.DateField().clean(raw)
        except forms.ValidationError:
            messages.error(request, "That date was not valid.")
            return redirect("plan_detail", pk=pk)
        if new_target <= timezone.localdate():
            messages.error(request, "Choose a date after today.")
            return redirect("plan_detail", pk=pk)
    n = svc.reschedule(plan, new_target)
    messages.success(request, f"Rescheduled {n} unfinished tasks.")
    return redirect("plan_detail", pk=pk)


@login_required
@require_POST
def task_toggle(request, pk):
    task = get_object_or_404(StudyTask, pk=pk, plan__owner=request.user)
    task.completed = not task.completed
    task.completed_at = timezone.now() if task.completed else None
    task.save(update_fields=["completed", "completed_at", "updated_at"])
    if task.completed:
        log_activity(request.user, "task", task.minutes, task.plan.subject, task.title)
    return JsonResponse({"ok": True, "completed": task.completed, "percent": task.plan.completion_percent})


class TaskForm(forms.ModelForm):
    class Meta:
        model = StudyTask
        fields = ["title", "scheduled_date", "minutes", "priority"]
        widgets = {"scheduled_date": forms.DateInput(attrs={"type": "date"})}


@login_required
def task_edit(request, pk):
    task = get_object_or_404(StudyTask, pk=pk, plan__owner=request.user)
    form = TaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("plan_detail", pk=task.plan_id)
    return render(request, "myapp/task_edit.html", {"form": form, "task": task})


@login_required
@require_POST
def task_add(request, pk):
    plan = get_object_or_404(StudyPlan, pk=pk, owner=request.user)
    form = TaskForm(request.POST)
    if form.is_valid():
        t = form.save(commit=False)
        t.plan = plan
        t.kind = "learn"
        t.save()
    else:
        messages.error(request, "Could not add the task. Check the title, date and minutes.")
    return redirect("plan_detail", pk=pk)


@login_required
@require_POST
def task_delete(request, pk):
    task = get_object_or_404(StudyTask, pk=pk, plan__owner=request.user)
    plan_id = task.plan_id
    task.delete()
    return redirect("plan_detail", pk=plan_id)
