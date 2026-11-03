"""Central authorisation helpers. Every view and API calls these instead of re-implementing checks."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from myapp.models import Course, ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER


def role_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            p = getattr(request.user, "profile", None)
            if not p:
                raise PermissionDenied
            role = ROLE_ADMIN if p.is_admin_role else p.role
            if role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def teacher_course_or_404(user, pk):
    """Teachers only reach their own courses. Admins can reach any."""
    qs = Course.objects.all() if user.profile.is_admin_role else Course.objects.filter(teacher=user)
    return get_object_or_404(qs, pk=pk)


def student_visible_quiz(user, quiz):
    """A student may open a quiz they own, or a published quiz in a course they are enrolled in."""
    if quiz.owner_id == user.id:
        return True
    return bool(quiz.published and quiz.course_id and quiz.course.enrollments.filter(student=user).exists())
