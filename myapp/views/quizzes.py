import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from myapp.forms import ManualQuestionForm, QuizCreateForm
from myapp.models import Question, Quiz, QuizAttempt
from myapp.services import quiz as qs
from myapp.services.access import student_visible_quiz
from myapp.services.errors import AIError
from myapp.services.ratelimit import hit
from .utils import log_activity, notify, require_ai_consent


@login_required
def quiz_list(request):
    u = request.user
    mine = Quiz.objects.filter(owner=u)
    shared = Quiz.objects.filter(published=True, course__enrollments__student=u).exclude(owner=u).distinct()
    attempts = QuizAttempt.objects.filter(student=u, submitted_at__isnull=False).select_related("quiz")[:10]
    return render(request, "myapp/quiz_list.html", {"mine": mine[:30], "shared": shared[:30], "attempts": attempts})


@login_required
def quiz_create(request):
    form = QuizCreateForm(request.user, request.POST or None, initial={"grade": request.user.profile.grade})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ok, wait = hit(request.user.pk, "quiz")
        if not ok:
            messages.error(request, f"You reached the hourly quiz limit. Try again in {max(1, wait // 60)} min.")
            return render(request, "myapp/quiz_create.html", {"form": form})
        text = ""
        if d.get("material"):
            text = d["material"].text_content
        if d.get("image") and hasattr(d["image"], "extracted"):
            text = d["image"].extracted.text
        try:
            require_ai_consent(request.user)
            cfg = {k: d[k] for k in ("subject", "topic", "grade", "count", "difficulty", "question_type", "timer_minutes")}
            questions = qs.generate_questions(cfg, text, request.user)
        except AIError as exc:
            messages.error(request, exc.message)
            return render(request, "myapp/quiz_create.html", {"form": form, "retry": True})
        course = d.get("course")
        quiz = qs.save_quiz(request.user, cfg, questions, course=course, source_material=d.get("material"), source_image=d.get("image"),
                            published=bool(d.get("publish") and course))
        if quiz.published:
            for e in course.enrollments.select_related("student"):
                notify(e.student, "New quiz: " + quiz.title, course.title, f"/quizzes/{quiz.id}/")
        messages.success(request, f"Created {len(questions)} questions. AI-generated questions can contain mistakes, so check them before relying on them.")
        return redirect("quiz_detail", pk=quiz.id)
    return render(request, "myapp/quiz_create.html", {"form": form})


def _get_quiz(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not (student_visible_quiz(request.user, quiz) or (request.user.profile.is_teacher and quiz.course and quiz.course.teacher_id == request.user.id)
            or request.user.profile.is_admin_role):
        raise PermissionDenied
    return quiz


@login_required
def quiz_detail(request, pk):
    quiz = _get_quiz(request, pk)
    can_edit = quiz.owner_id == request.user.id
    form = ManualQuestionForm(quiz.question_type) if can_edit else None
    last = QuizAttempt.objects.filter(quiz=quiz, student=request.user, submitted_at__isnull=False).first()
    return render(request, "myapp/quiz_detail.html", {"quiz": quiz, "can_edit": can_edit, "form": form, "last": last,
                  "show_answers": can_edit or request.user.profile.is_admin_role})


@login_required
@require_POST
def question_add(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, owner=request.user)
    form = ManualQuestionForm(quiz.question_type, request.POST)
    if form.is_valid():
        d = form.cleaned_data
        Question.objects.create(quiz=quiz, order=quiz.questions.count(), qtype=quiz.question_type, text=d["text"], options=d["option_list"],
                                correct_answer=d["correct_answer"].strip(), explanation=d["explanation"], topic=d["topic"] or quiz.topic)
        messages.success(request, "Question added.")
    else:
        messages.error(request, "Fix the highlighted fields: " + "; ".join(sum(form.errors.values(), [])))
    return redirect("quiz_detail", pk=pk)


@login_required
@require_POST
def question_delete(request, pk):
    q = get_object_or_404(Question, pk=pk, quiz__owner=request.user)
    quiz_id = q.quiz_id
    q.delete()
    return redirect("quiz_detail", pk=quiz_id)


@login_required
@require_POST
def quiz_publish(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, owner=request.user, course__isnull=False)
    quiz.published = not quiz.published
    quiz.save(update_fields=["published"])
    if quiz.published:
        for e in quiz.course.enrollments.select_related("student"):
            notify(e.student, "New quiz: " + quiz.title, quiz.course.title, f"/quizzes/{quiz.id}/")
    return redirect("quiz_detail", pk=pk)


@login_required
@require_POST
def quiz_delete(request, pk):
    get_object_or_404(Quiz, pk=pk, owner=request.user).delete()
    return redirect("quiz_list")


@login_required
@require_POST
def quiz_start(request, pk):
    quiz = _get_quiz(request, pk)
    if not quiz.questions.exists():
        messages.error(request, "This quiz has no questions yet.")
        return redirect("quiz_detail", pk=pk)
    if request.user.profile.is_teacher and quiz.owner_id != request.user.id:
        raise PermissionDenied
    attempt = QuizAttempt.objects.filter(quiz=quiz, student=request.user, submitted_at__isnull=True).first() or \
        QuizAttempt.objects.create(quiz=quiz, student=request.user, total=quiz.questions.count())
    return redirect("quiz_take", attempt_id=attempt.id)


@login_required
def quiz_take(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, student=request.user)
    if attempt.is_submitted:
        return redirect("quiz_result", attempt_id=attempt.id)
    quiz = attempt.quiz
    # Correct answers and explanations are deliberately NOT sent to the browser.
    data = [{"id": q.id, "text": q.text, "type": q.qtype, "options": q.options} for q in quiz.questions.all()]
    remaining = None
    if quiz.timer_minutes:
        end = attempt.started_at + timedelta(minutes=quiz.timer_minutes)
        remaining = max(0, int((end - timezone.now()).total_seconds()))
    return render(request, "myapp/quiz_take.html", {"attempt": attempt, "quiz": quiz, "questions_json": data, "remaining": remaining})


@login_required
@require_POST
def quiz_submit(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, student=request.user)
    try:
        answers = json.loads(request.body or "{}").get("answers", {})
        if not isinstance(answers, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"ok": False, "error": "Answers were not valid."}, status=400)
    quiz = attempt.quiz
    if quiz.timer_minutes and timezone.now() > attempt.started_at + timedelta(minutes=quiz.timer_minutes, seconds=60):
        answers = {}  # time ran out: late answers are not accepted
    qs.grade_attempt(attempt, answers)
    log_activity(request.user, "quiz", max(5, quiz.questions.count() * 1), quiz.subject, quiz.title)
    return JsonResponse({"ok": True, "url": f"/quizzes/attempt/{attempt.id}/result/"})


@login_required
def quiz_result(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, student=request.user)
    if not attempt.is_submitted:
        return redirect("quiz_take", attempt_id=attempt.id)
    rows = attempt.answers.select_related("question").order_by("question__order")
    breakdown = qs.topic_breakdown(attempt)
    return render(request, "myapp/quiz_result.html", {"attempt": attempt, "rows": rows, "breakdown": breakdown,
                  "chart": {"labels": [b["topic"] for b in breakdown], "values": [b["percent"] for b in breakdown]},
                  "has_wrong": any(not r.is_correct for r in rows)})


@login_required
@require_POST
def quiz_retry(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, student=request.user, submitted_at__isnull=False)
    quiz = qs.retry_incorrect_quiz(attempt, request.user)
    if not quiz:
        messages.info(request, "You got everything right. Nothing to retry.")
        return redirect("quiz_result", attempt_id=attempt.id)
    new = QuizAttempt.objects.create(quiz=quiz, student=request.user, total=quiz.questions.count(), retry_of=attempt)
    return redirect("quiz_take", attempt_id=new.id)
