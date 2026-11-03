import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from myapp.models import Question, Quiz, QuizAttempt, StudyPlan, StudyTask, LearningActivity, Enrollment
from myapp.services import analytics, planner, quiz as qs
from myapp.services.errors import AIBadResponse
from .helpers import AI_SETTINGS, ClearCacheMixin, make_course, make_user
from .test_ai import fake

GOOD = {"questions": [
    {"text": "Which gas do plants absorb?", "options": ["Oxygen", "Carbon dioxide", "Helium"], "answer": "carbon dioxide", "explanation": "CO2 is used.", "topic": "Photosynthesis"},
    {"text": "Where does it happen?", "options": ["Chloroplast", "Nucleus"], "answer": "Chloroplast", "explanation": "", "topic": "Photosynthesis"},
    {"text": "Broken: answer not in options", "options": ["A", "B"], "answer": "C"},
    {"text": "Duplicate options", "options": ["A", "a"], "answer": "A"},
]}


class QuizValidationTests(TestCase):
    def test_validate_keeps_only_well_formed_mcq(self):
        out = qs.validate_payload(GOOD, "mcq", 5)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["answer"], "Carbon dioxide")  # normalised to the real option text

    def test_validate_rejects_empty_or_garbage(self):
        for bad in ({}, {"questions": []}, {"questions": ["x"]}, []):
            with self.assertRaises(AIBadResponse):
                qs.validate_payload(bad, "mcq", 5)

    def test_true_false_and_short(self):
        tf = qs.validate_payload({"questions": [{"text": "Sky is blue", "answer": "true"}, {"text": "bad", "answer": "maybe"}]}, "tf", 5)
        self.assertEqual(tf[0]["options"], ["True", "False"])
        self.assertEqual(len(tf), 1)
        short = qs.validate_payload({"questions": [{"text": "Capital of France?", "answer": "Paris"}]}, "short", 5)
        self.assertEqual(short[0]["options"], [])

    def test_count_is_capped(self):
        many = {"questions": [{"text": f"q{i}", "answer": "Paris"} for i in range(30)]}
        self.assertEqual(len(qs.validate_payload(many, "short", 3)), 3)


@override_settings(META_AI=AI_SETTINGS)
class QuizFlowTests(ClearCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.u = make_user("stu")
        self.client.login(username="stu", password="Pass-12345-x")

    def form(self, **kw):
        d = {"subject": "Science", "topic": "Photosynthesis", "grade": "Grade 9", "count": 5, "difficulty": "medium", "question_type": "mcq"}
        d.update(kw)
        return d

    @mock.patch("myapp.services.base.requests.post", return_value=fake(200, {"choices": [{"message": {"content": "```json\n" + json.dumps(GOOD) + "\n```"}}]}))
    def test_generate_take_and_server_side_scoring(self, _):
        r = self.client.post(reverse("quiz_create"), self.form())
        quiz = Quiz.objects.get()
        self.assertRedirects(r, reverse("quiz_detail", args=[quiz.pk]))
        self.assertTrue(quiz.ai_generated)
        # start, then check the page never leaks answers
        r = self.client.post(reverse("quiz_start", args=[quiz.pk]))
        attempt = QuizAttempt.objects.get()
        page = self.client.get(reverse("quiz_take", args=[attempt.pk]))
        self.assertNotContains(page, "explanation")
        self.assertNotContains(page, "correct_answer")
        q1, q2 = quiz.questions.all()
        # client tries to cheat by sending a score: it is ignored
        r = self.client.post(reverse("quiz_submit", args=[attempt.pk]), json.dumps({"answers": {str(q1.pk): "Carbon dioxide", str(q2.pk): "Nucleus"}, "score": 99}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        attempt.refresh_from_db()
        self.assertEqual((attempt.score, attempt.total, attempt.percent), (1, 2, 50.0))
        # double submit does not change the score
        self.client.post(reverse("quiz_submit", args=[attempt.pk]), json.dumps({"answers": {str(q1.pk): "Oxygen", str(q2.pk): "Nucleus"}}), content_type="application/json")
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 1)
        self.assertEqual(attempt.answers.count(), 2)
        # result page and retry-incorrect
        self.assertEqual(self.client.get(reverse("quiz_result", args=[attempt.pk])).status_code, 200)
        r = self.client.post(reverse("quiz_retry", args=[attempt.pk]))
        retry_attempt = QuizAttempt.objects.exclude(pk=attempt.pk).get()
        self.assertEqual(retry_attempt.quiz.questions.count(), 1)
        self.assertEqual(retry_attempt.retry_of, attempt)

    @override_settings(META_AI={**AI_SETTINGS, "API_KEY": ""})
    def test_generation_without_credentials_shows_error_and_creates_nothing(self):
        r = self.client.post(reverse("quiz_create"), self.form())
        self.assertContains(r, "not configured")
        self.assertEqual(Quiz.objects.count(), 0)

    @mock.patch("myapp.services.base.requests.post", return_value=fake(200, {"choices": [{"message": {"content": "sorry, no json"}}]}))
    def test_unusable_ai_output_is_rejected(self, _):
        r = self.client.post(reverse("quiz_create"), self.form())
        self.assertContains(r, "structured data")
        self.assertEqual(Quiz.objects.count(), 0)

    def test_form_validation(self):
        r = self.client.post(reverse("quiz_create"), self.form(count=99))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Quiz.objects.count(), 0)

    def test_cannot_take_or_submit_for_other_students(self):
        other = make_user("other")
        quiz = qs.save_quiz(other, {"subject": "S", "topic": "T", "difficulty": "easy", "question_type": "short"}, [{"text": "q", "options": [], "answer": "a", "explanation": "", "topic": ""}], ai_generated=False)
        self.assertEqual(self.client.get(reverse("quiz_detail", args=[quiz.pk])).status_code, 403)
        att = QuizAttempt.objects.create(quiz=quiz, student=other, total=1)
        self.assertEqual(self.client.get(reverse("quiz_take", args=[att.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("quiz_submit", args=[att.pk]), "{}", content_type="application/json").status_code, 404)

    def test_published_class_quiz_visible_only_to_enrolled(self):
        teacher = make_user("tea", "teacher")
        course = make_course(teacher)
        quiz = qs.save_quiz(teacher, {"subject": "S", "topic": "T", "difficulty": "easy", "question_type": "short"}, [{"text": "q", "options": [], "answer": "a", "explanation": "", "topic": ""}], ai_generated=False, course=course, published=True)
        self.assertEqual(self.client.get(reverse("quiz_detail", args=[quiz.pk])).status_code, 403)
        Enrollment.objects.create(course=course, student=self.u)
        self.assertEqual(self.client.get(reverse("quiz_detail", args=[quiz.pk])).status_code, 200)
        quiz.published = False
        quiz.save()
        self.assertEqual(self.client.get(reverse("quiz_detail", args=[quiz.pk])).status_code, 403)

    def test_timer_rejects_late_answers(self):
        quiz = qs.save_quiz(self.u, {"subject": "S", "topic": "T", "difficulty": "easy", "question_type": "short", "timer_minutes": 1}, [{"text": "q", "options": [], "answer": "a", "explanation": "", "topic": ""}], ai_generated=False)
        att = QuizAttempt.objects.create(quiz=quiz, student=self.u, total=1, started_at=timezone.now() - timedelta(minutes=5))
        q = quiz.questions.get()
        self.client.post(reverse("quiz_submit", args=[att.pk]), json.dumps({"answers": {str(q.pk): "a"}}), content_type="application/json")
        att.refresh_from_db()
        self.assertEqual(att.score, 0)

    def test_manual_question_add_validates(self):
        quiz = qs.save_quiz(self.u, {"subject": "S", "topic": "T", "difficulty": "easy", "question_type": "mcq"}, [], ai_generated=False)
        self.client.post(reverse("question_add", args=[quiz.pk]), {"text": "2+2?", "options": "3\n4", "correct_answer": "5"})
        self.assertEqual(quiz.questions.count(), 0)
        self.client.post(reverse("question_add", args=[quiz.pk]), {"text": "2+2?", "options": "3\n4", "correct_answer": "4"})
        self.assertEqual(quiz.questions.count(), 1)

    def test_short_answer_matching_ignores_case_and_punctuation(self):
        q = Question(qtype="short", correct_answer="Photosynthesis")
        self.assertTrue(qs.is_correct(q, " photosynthesis! "))
        self.assertFalse(qs.is_correct(q, ""))


class PlannerTests(ClearCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.u = make_user("stu")
        self.client.login(username="stu", password="Pass-12345-x")
        self.today = timezone.localdate()

    def data(self, **kw):
        d = {"goal": "Pass Science", "subject": "Science", "topics_text": "Cells\nPlants\nWater cycle", "target_date": (self.today + timedelta(days=10)).isoformat(),
             "daily_minutes": 60, "level": "beginner", "language": "en"}
        d.update(kw)
        return d

    def test_create_plan_builds_ordered_schedule(self):
        r = self.client.post(reverse("plan_create"), self.data())
        plan = StudyPlan.objects.get()
        self.assertRedirects(r, reverse("plan_detail", args=[plan.pk]))
        tasks = list(plan.tasks.all())
        kinds = {t.kind for t in tasks}
        self.assertEqual(kinds, {"learn", "practice", "revise", "milestone"})
        for t in tasks:
            self.assertGreaterEqual(t.scheduled_date, plan.start_date)
            self.assertLessEqual(t.scheduled_date, plan.target_date)
        self.assertEqual(tasks[-1].kind, "milestone")

    def test_validation(self):
        for bad in ({"target_date": self.today.isoformat()}, {"topics_text": "   "}, {"daily_minutes": 1}):
            self.client.post(reverse("plan_create"), self.data(**bad))
        self.assertEqual(StudyPlan.objects.count(), 0)

    def test_weak_topics_are_scheduled_first(self):
        quiz = qs.save_quiz(self.u, {"subject": "S", "topic": "T", "difficulty": "easy", "question_type": "short"},
                            [{"text": f"q{i}", "options": [], "answer": "a", "explanation": "", "topic": "Water cycle"} for i in range(3)], ai_generated=False)
        att = QuizAttempt.objects.create(quiz=quiz, student=self.u, total=3)
        qs.grade_attempt(att, {})
        self.assertEqual(planner.weak_topics(self.u), ["Water cycle"])
        self.client.post(reverse("plan_create"), self.data())
        first_learn = StudyPlan.objects.get().tasks.filter(kind="learn").first()
        self.assertEqual(first_learn.topic, "Water cycle")
        self.assertEqual(first_learn.priority, 1)

    def test_toggle_task_updates_progress_and_activity(self):
        self.client.post(reverse("plan_create"), self.data())
        plan = StudyPlan.objects.get()
        t = plan.tasks.first()
        r = self.client.post(reverse("api_task_toggle", args=[t.pk]))
        self.assertTrue(r.json()["completed"])
        self.assertGreater(r.json()["percent"], 0)
        self.assertEqual(LearningActivity.objects.filter(student=self.u, kind="task").count(), 1)
        self.client.post(reverse("api_task_toggle", args=[t.pk]))
        t.refresh_from_db()
        self.assertFalse(t.completed)

    def test_edit_add_delete_task_and_reschedule(self):
        self.client.post(reverse("plan_create"), self.data())
        plan = StudyPlan.objects.get()
        t = plan.tasks.first()
        self.client.post(reverse("task_edit", args=[t.pk]), {"title": "Renamed", "scheduled_date": self.today.isoformat(), "minutes": 25, "priority": 1})
        t.refresh_from_db()
        self.assertEqual(t.title, "Renamed")
        n = plan.tasks.count()
        self.client.post(reverse("task_add", args=[plan.pk]), {"title": "Extra", "scheduled_date": self.today.isoformat(), "minutes": 15, "priority": 2})
        self.assertEqual(plan.tasks.count(), n + 1)
        new_target = self.today + timedelta(days=20)
        self.client.post(reverse("plan_reschedule", args=[plan.pk]), {"target_date": new_target.isoformat()})
        plan.refresh_from_db()
        self.assertEqual(plan.target_date, new_target)
        self.assertLessEqual(max(plan.tasks.values_list("scheduled_date", flat=True)), new_target)
        self.client.post(reverse("task_delete", args=[t.pk]))
        self.assertEqual(plan.tasks.count(), n)

    def test_other_students_cannot_touch_plan(self):
        self.client.post(reverse("plan_create"), self.data())
        plan = StudyPlan.objects.get()
        t = plan.tasks.first()
        make_user("other")
        self.client.logout()
        self.client.login(username="other", password="Pass-12345-x")
        self.assertEqual(self.client.get(reverse("plan_detail", args=[plan.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("api_task_toggle", args=[t.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("plan_delete", args=[plan.pk])).status_code, 404)
        self.assertEqual(StudyPlan.objects.count(), 1)


class AnalyticsTests(ClearCacheMixin, TestCase):
    def test_streak_and_weekly_and_stats_use_real_data(self):
        u = make_user("stu")
        today = timezone.localdate()
        for d in range(3):
            LearningActivity.objects.create(student=u, kind="tutor", minutes=30, occurred_on=today - timedelta(days=d))
        self.assertEqual(analytics.streak(u), 3)
        w = analytics.weekly_activity(u)
        self.assertEqual(w["values"][-1], 30)
        self.assertEqual(sum(w["values"]), 90)
        s = analytics.student_stats(u)
        self.assertEqual(s["hours"], 1.5)
        self.assertIsNone(s["quiz_avg"])

    def test_streak_zero_after_gap(self):
        u = make_user("stu")
        LearningActivity.objects.create(student=u, kind="tutor", occurred_on=timezone.localdate() - timedelta(days=3))
        self.assertEqual(analytics.streak(u), 0)

    def test_class_report_scoped_to_course(self):
        t = make_user("tea", "teacher")
        s = make_user("stu")
        course = make_course(t)
        Enrollment.objects.create(course=course, student=s)
        quiz = qs.save_quiz(t, {"subject": "S", "topic": "T", "difficulty": "easy", "question_type": "short"}, [{"text": "q", "options": [], "answer": "a", "explanation": "", "topic": "Cells"}], ai_generated=False, course=course, published=True)
        att = QuizAttempt.objects.create(quiz=quiz, student=s, total=1)
        qs.grade_attempt(att, {})
        rep = analytics.class_report(course)
        self.assertEqual(rep["weak_topics"][0]["topic"], "Cells")
        self.assertEqual(rep["students"][0]["avg"], 0)


class CommandTests(TestCase):
    def test_seed_demo_and_purge(self):
        from django.core.management import call_command
        from myapp.models import AIRequestLog
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)  # idempotent
        self.assertEqual(Quiz.objects.filter(title__contains="seed").count(), 1)
        old = AIRequestLog.objects.create(service="x")
        AIRequestLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        call_command("purge_old_data", verbosity=0)
        self.assertFalse(AIRequestLog.objects.filter(pk=old.pk).exists())
        call_command("send_reminders", verbosity=0)
