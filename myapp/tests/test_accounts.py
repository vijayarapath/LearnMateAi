from django.test import TestCase, Client
from django.urls import reverse

from myapp.models import Profile
from .helpers import make_course, make_user, ClearCacheMixin


class AuthTests(ClearCacheMixin, TestCase):
    def test_register_creates_student_profile_and_logs_in(self):
        r = self.client.post(reverse("register"), {
            "username": "newbie", "first_name": "New Bie", "email": "n@example.com", "role": "student", "grade": "Grade 8",
            "password1": "Str0ng-Pass-99", "password2": "Str0ng-Pass-99"})
        self.assertRedirects(r, reverse("home"))
        p = Profile.objects.get(user__username="newbie")
        self.assertEqual(p.role, "student")
        self.assertFalse(p.ai_consent)  # AI is opt-in

    from django.test import override_settings

    @override_settings(TEACHER_SELF_SIGNUP=False)
    def test_cannot_self_register_as_teacher_by_default(self):
        r = self.client.post(reverse("register"), {
            "username": "sneaky", "first_name": "S", "email": "s@example.com", "role": "teacher",
            "password1": "Str0ng-Pass-99", "password2": "Str0ng-Pass-99"})
        self.assertEqual(r.status_code, 200)  # form re-rendered with an error
        self.assertFalse(Profile.objects.filter(user__username="sneaky").exists())

    @override_settings(TEACHER_SELF_SIGNUP=True)
    def test_can_self_register_as_teacher_when_enabled(self):
        r = self.client.post(reverse("register"), {
            "username": "prof", "first_name": "Professor", "email": "prof@example.com", "role": "teacher",
            "password1": "Str0ng-Pass-99", "password2": "Str0ng-Pass-99"})
        self.assertRedirects(r, reverse("home"))
        p = Profile.objects.get(user__username="prof")
        self.assertEqual(p.role, "teacher")

    @override_settings(ADMIN_SELF_SIGNUP=True)
    def test_can_self_register_as_admin_when_enabled(self):
        r = self.client.post(reverse("register"), {
            "username": "boss", "first_name": "Boss Admin", "email": "boss@example.com", "role": "admin",
            "password1": "Str0ng-Pass-99", "password2": "Str0ng-Pass-99"})
        self.assertRedirects(r, reverse("home"))
        p = Profile.objects.get(user__username="boss")
        self.assertEqual(p.role, "admin")
        self.assertTrue(p.is_admin_role)
        self.assertTrue(p.user.is_staff)


    def test_duplicate_email_rejected(self):
        make_user("a")
        r = self.client.post(reverse("register"), {"username": "b", "first_name": "B", "email": "a@example.com", "role": "student",
                                                    "password1": "Str0ng-Pass-99", "password2": "Str0ng-Pass-99"})
        self.assertContains(r, "already exists")

    def test_login_logout(self):
        make_user("sam")
        self.assertTrue(self.client.login(username="sam", password="Pass-12345-x"))
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)

    def test_password_reset_sends_email(self):
        from django.core import mail
        make_user("sam")
        self.client.post(reverse("password_reset"), {"email": "sam@example.com"})
        self.assertEqual(len(mail.outbox), 1)

    def test_csrf_enforced_on_forms(self):
        make_user("sam")
        c = Client(enforce_csrf_checks=True)
        c.login(username="sam", password="Pass-12345-x")
        self.assertEqual(c.post(reverse("profile"), {}).status_code, 403)

    def test_csrf_enforced_on_api(self):
        make_user("sam")
        c = Client(enforce_csrf_checks=True)
        c.login(username="sam", password="Pass-12345-x")
        self.assertEqual(c.post(reverse("api_tutor_ask"), {"question": "hi"}, content_type="application/json").status_code, 403)

    def test_profile_minor_needs_guardian_consent(self):
        u = make_user("kid")
        p = u.profile
        p.is_minor = True
        p.save()
        self.assertFalse(p.can_use_ai)
        p.guardian_consent = True
        self.assertTrue(p.can_use_ai)


class RolePermissionTests(ClearCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.student = make_user("stu")
        self.other = make_user("other")
        self.teacher = make_user("tea", "teacher")
        self.teacher2 = make_user("tea2", "teacher")
        self.admin = make_user("adm", "admin")
        self.course = make_course(self.teacher)

    def login(self, u):
        self.client.login(username=u.username, password="Pass-12345-x")

    def test_anonymous_redirected_everywhere(self):
        for name in ("home", "tutor", "quiz_list", "plan_list", "textbook", "visuals", "notes", "progress", "teacher_courses", "admin_users"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_student_blocked_from_teacher_and_admin_areas(self):
        self.login(self.student)
        for name in ("teacher_courses", "teacher_reports", "admin_users", "admin_ai_logs", "admin_config"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_teacher_blocked_from_admin_and_student_only_pages(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("admin_users")).status_code, 403)
        self.assertEqual(self.client.get(reverse("progress")).status_code, 403)

    def test_teacher_cannot_open_another_teachers_class(self):
        self.login(self.teacher2)
        self.assertEqual(self.client.get(reverse("teacher_course", args=[self.course.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("enroll_student", args=[self.course.pk]), {"identifier": "stu"}).status_code, 404)

    def test_teacher_report_only_for_enrolled_students_in_own_class(self):
        from myapp.models import Enrollment
        Enrollment.objects.create(course=self.course, student=self.student)
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("student_report", args=[self.course.pk, self.student.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("student_report", args=[self.course.pk, self.other.pk])).status_code, 404)

    def test_admin_can_change_role_but_not_own(self):
        self.login(self.admin)
        self.client.post(reverse("admin_user_update", args=[self.student.pk]), {"action": "role", "role": "teacher"})
        self.student.profile.refresh_from_db()
        self.assertEqual(self.student.profile.role, "teacher")
        self.client.post(reverse("admin_user_update", args=[self.admin.pk]), {"action": "role", "role": "student"})
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.role, "admin")

    def test_student_cannot_read_another_students_conversation_or_note(self):
        from myapp.models import Conversation, SavedNote
        conv = Conversation.objects.create(owner=self.other, title="private")
        note = SavedNote.objects.create(owner=self.other, title="n", body="b")
        self.login(self.student)
        self.assertEqual(self.client.get(reverse("tutor_conversation", args=[conv.pk])).status_code, 404)
        self.client.post(reverse("note_delete", args=[note.pk]))
        self.assertTrue(SavedNote.objects.filter(pk=note.pk).exists())

    def test_private_media_isolated(self):
        from myapp.models import UploadedImage
        from .helpers import png_upload
        img = UploadedImage.objects.create(owner=self.other, image=png_upload())
        self.login(self.student)
        self.assertEqual(self.client.get(reverse("private_media", args=["textbook", img.pk])).status_code, 404)
        self.login(self.other)
        self.assertEqual(self.client.get(reverse("private_media", args=["textbook", img.pk])).status_code, 200)

    def test_dashboards_render_for_each_role(self):
        for u in (self.student, self.teacher, self.admin):
            self.client.logout()
            self.login(u)
            self.assertEqual(self.client.get(reverse("home")).status_code, 200)
