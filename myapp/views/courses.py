from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from myapp.forms import AssignmentForm, CourseForm, MaterialForm
from myapp.models import Assignment, Course, Enrollment, LearningMaterial, QuizAttempt, StudyPlan, Topic, TopicProgress
from myapp.services import analytics
from myapp.services.access import role_required, teacher_course_or_404
from .utils import notify


# ---------------------------------------------------------------- students
@role_required("student")
def my_courses(request):
    return render(request, "myapp/my_courses.html", {"courses": Course.objects.filter(enrollments__student=request.user).select_related("subject", "teacher")})


@role_required("student")
@require_POST
def join_course(request):
    code = (request.POST.get("code") or "").strip().upper()
    course = Course.objects.filter(join_code=code, is_active=True).first()
    if not course:
        messages.error(request, "No class uses that code. Check it with your teacher.")
    else:
        _, created = Enrollment.objects.get_or_create(course=course, student=request.user)
        messages.success(request, f"You joined {course.title}." if created else "You are already in this class.")
        if created:
            notify(course.teacher, "New student joined", f"{request.user.profile.display_name} joined {course.title}", f"/teacher/classes/{course.id}/")
    return redirect("my_courses")


@role_required("student")
def course_view(request, pk):
    course = get_object_or_404(Course, pk=pk, enrollments__student=request.user)
    done = set(TopicProgress.objects.filter(student=request.user, completed=True).values_list("topic_id", flat=True))
    return render(request, "myapp/course_student.html", {
        "course": course, "topics": course.topics.all(), "done": done,
        "materials": course.materials.filter(is_flagged=False), "assignments": course.assignments.all(),
        "quizzes": course.quizzes.filter(published=True)})


@role_required("student")
@require_POST
def topic_toggle(request, pk):
    topic = get_object_or_404(Topic, pk=pk, course__enrollments__student=request.user)
    tp, _ = TopicProgress.objects.get_or_create(student=request.user, topic=topic)
    tp.completed = not tp.completed
    tp.save()
    return redirect("course_view", pk=topic.course_id)


@role_required("student")
def progress(request):
    u = request.user
    attempts = QuizAttempt.objects.filter(student=u, submitted_at__isnull=False).order_by("created_at")
    perf = analytics.topic_performance(u)
    return render(request, "myapp/progress.html", {
        "stats": analytics.student_stats(u), "weekly": analytics.weekly_activity(u), "perf": perf,
        "trend": {"labels": [a.created_at.strftime("%d %b") for a in attempts[:20]], "values": [a.percent for a in attempts[:20]]},
        "plans": StudyPlan.objects.filter(owner=u, is_active=True)})


# ---------------------------------------------------------------- teachers
@role_required("teacher", "admin")
def teacher_courses(request):
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.teacher = request.user
        c.save()
        messages.success(request, f"Class created. Students join with the code {c.join_code}.")
        return redirect("teacher_course", pk=c.id)
    courses = Course.objects.filter(teacher=request.user).annotate(n=Count("enrollments"))
    return render(request, "myapp/teacher_courses.html", {"courses": courses, "form": form})


@role_required("teacher", "admin")
def teacher_course(request, pk):
    course = teacher_course_or_404(request.user, pk)
    return render(request, "myapp/teacher_course.html", {
        "course": course, "enrollments": course.enrollments.select_related("student__profile"),
        "assignments": course.assignments.all(), "materials": course.materials.all(), "quizzes": course.quizzes.all(),
        "topics": course.topics.all(), "assignment_form": AssignmentForm(course), "material_form": MaterialForm()})


@role_required("teacher", "admin")
@require_POST
def enroll_student(request, pk):
    course = teacher_course_or_404(request.user, pk)
    ident = (request.POST.get("identifier") or "").strip()
    student = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident), profile__role="student").first() if ident else None
    if not student:
        messages.error(request, "No student account matches that username or email.")
    else:
        _, created = Enrollment.objects.get_or_create(course=course, student=student)
        if created:
            notify(student, "You were added to a class", course.title, f"/courses/{course.id}/")
        messages.success(request, f"{student.profile.display_name} is enrolled.")
    return redirect("teacher_course", pk=pk)


@role_required("teacher", "admin")
@require_POST
def unenroll_student(request, pk, student_id):
    course = teacher_course_or_404(request.user, pk)
    Enrollment.objects.filter(course=course, student_id=student_id).delete()
    return redirect("teacher_course", pk=pk)


@role_required("teacher", "admin")
@require_POST
def topic_add(request, pk):
    course = teacher_course_or_404(request.user, pk)
    title = (request.POST.get("title") or "").strip()[:140]
    if title:
        Topic.objects.create(course=course, title=title, order=course.topics.count())
    return redirect("teacher_course", pk=pk)


@role_required("teacher", "admin")
@require_POST
def assignment_add(request, pk):
    course = teacher_course_or_404(request.user, pk)
    form = AssignmentForm(course, request.POST)
    if form.is_valid():
        a = form.save(commit=False)
        a.course = course
        a.save()
        for e in course.enrollments.select_related("student"):
            notify(e.student, "New assignment: " + a.title, f"Due {a.due_date:%d %b}", f"/courses/{course.id}/")
        messages.success(request, "Assignment created.")
    else:
        messages.error(request, "Could not create the assignment. Add a title and a due date.")
    return redirect("teacher_course", pk=pk)


@role_required("teacher", "admin")
@require_POST
def material_add(request, pk):
    course = teacher_course_or_404(request.user, pk)
    form = MaterialForm(request.POST, request.FILES)
    if form.is_valid():
        m = form.save(commit=False)
        m.course, m.uploaded_by = course, request.user
        m.save()
        messages.success(request, "Material added.")
    else:
        messages.error(request, "; ".join(sum(form.errors.values(), [])))
    return redirect("teacher_course", pk=pk)


@role_required("teacher", "admin")
@require_POST
def material_delete(request, pk):
    m = get_object_or_404(LearningMaterial, pk=pk)
    teacher_course_or_404(request.user, m.course_id)
    cid = m.course_id
    m.delete()
    return redirect("teacher_course", pk=cid)


@role_required("teacher", "admin")
def teacher_reports(request):
    courses = Course.objects.filter(teacher=request.user)
    cid = request.GET.get("course")
    course = teacher_course_or_404(request.user, cid) if cid else courses.first()
    report = analytics.class_report(course) if course else None
    return render(request, "myapp/teacher_reports.html", {"courses": courses, "course": course, "report": report})


@role_required("teacher", "admin")
def student_report(request, course_id, student_id):
    """Teachers see quiz results and plan progress for students in their own class. Chats and notes stay private."""
    course = teacher_course_or_404(request.user, course_id)
    enrollment = get_object_or_404(Enrollment, course=course, student_id=student_id)
    s = enrollment.student
    attempts = QuizAttempt.objects.filter(student=s, quiz__course=course, submitted_at__isnull=False).select_related("quiz")
    return render(request, "myapp/student_report.html", {
        "course": course, "s": s, "attempts": attempts, "weekly": analytics.weekly_activity(s),
        "stats": analytics.student_stats(s), "plans": StudyPlan.objects.filter(owner=s, is_active=True)})
