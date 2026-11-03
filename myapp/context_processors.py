from .models import Notification


def shell(request):
    """Adds sidebar nav, unread notifications and role flags to every template."""
    if not request.user.is_authenticated or not hasattr(request.user, "profile"):
        return {}
    p = request.user.profile
    role = "admin" if p.is_admin_role else p.role
    nav = {
        "student": [
            ("home", "Dashboard", "bi-grid"), ("tutor", "AI tutor", "bi-chat-dots"), ("textbook", "Textbook upload", "bi-image"),
            ("quiz_list", "Quizzes", "bi-patch-question"), ("plan_list", "Study planner", "bi-calendar-check"),
            ("visuals", "Visual generator", "bi-brush"), ("my_courses", "Courses", "bi-book"), ("notes", "Saved notes", "bi-bookmark"),
            ("progress", "Progress", "bi-graph-up"),
        ],
        "teacher": [
            ("home", "Overview", "bi-grid"), ("teacher_courses", "Classes", "bi-people"), ("quiz_list", "Quizzes", "bi-patch-question"),
            ("teacher_reports", "Reports", "bi-bar-chart"),
        ],
        "admin": [
            ("home", "Overview", "bi-grid"), ("admin_users", "Users", "bi-person-gear"), ("admin_subjects", "Subjects", "bi-collection"),
            ("admin_moderation", "Moderation", "bi-shield-check"), ("admin_ai_logs", "AI requests", "bi-activity"),
            ("admin_config", "Configuration", "bi-sliders"),
        ],
    }[role]
    unread = Notification.objects.filter(user=request.user, is_read=False)
    return {
        "role": role, "nav": nav, "profile": p,
        "unread_count": unread.count(), "recent_notifications": Notification.objects.filter(user=request.user)[:6],
    }
