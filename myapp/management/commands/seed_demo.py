"""Creates demo users and classroom data. Quiz content here is hand-written seed data, not AI output."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from myapp.models import (Assignment, Course, Enrollment, LearningActivity, Notification, Question, Quiz, QuizAttempt, Subject, Topic)
from myapp.services import planner, quiz as qs

PASSWORD = "LearnMate#2026"

SUBJECTS = ["Mathematics", "Science", "English", "Commerce", "Computer Science"]

QUESTIONS = [
    ("Photosynthesis", "Which gas do plants take in for photosynthesis?", ["Oxygen", "Carbon dioxide", "Nitrogen", "Hydrogen"], "Carbon dioxide", "Plants use carbon dioxide and water to make glucose."),
    ("Photosynthesis", "Where does photosynthesis mainly happen in a plant cell?", ["Nucleus", "Mitochondria", "Chloroplast", "Ribosome"], "Chloroplast", "Chloroplasts hold the green pigment chlorophyll."),
    ("Photosynthesis", "What does a plant release during photosynthesis?", ["Oxygen", "Methane", "Carbon monoxide", "Helium"], "Oxygen", "Oxygen is a by-product of splitting water."),
    ("Water cycle", "What is the process of water turning into vapour called?", ["Condensation", "Evaporation", "Precipitation", "Collection"], "Evaporation", "Heat from the sun turns liquid water into vapour."),
    ("Water cycle", "Clouds form mainly through which process?", ["Condensation", "Melting", "Erosion", "Combustion"], "Condensation", "Vapour cools and condenses into tiny droplets."),
]


class Command(BaseCommand):
    help = "Seed demo data: admin, teacher, students, a class, quiz, plan and activity."

    def handle(self, *args, **opts):
        def user(name, first, role, email, **extra):
            u, created = User.objects.get_or_create(username=name, defaults={"first_name": first, "email": email, **extra})
            if created:
                u.set_password(PASSWORD)
                u.save()
            p = u.profile
            p.role = role
            p.ai_consent = True
            p.grade = p.grade or ("Grade 9" if role == "student" else "")
            p.save()
            return u

        admin = user("admin", "Site Admin", "admin", "admin@example.com", is_staff=True, is_superuser=True)
        teacher = user("teacher", "Meena Iyer", "teacher", "teacher@example.com")
        students = [user("asha", "Asha Raman", "student", "asha@example.com"), user("karthik", "Karthik S", "student", "karthik@example.com")]

        subjects = {n: Subject.objects.get_or_create(name=n)[0] for n in SUBJECTS}
        course, _ = Course.objects.get_or_create(title="Grade 9 Science", defaults={"subject": subjects["Science"], "teacher": teacher, "grade_level": "Grade 9",
                                                  "description": "Plants, water and the living world."})
        for i, t in enumerate(["Photosynthesis", "Water cycle", "Cells and tissues"]):
            Topic.objects.get_or_create(course=course, title=t, defaults={"order": i})
        for s in students:
            Enrollment.objects.get_or_create(course=course, student=s)

        quiz = Quiz.objects.filter(title="Science basics (seed)").first()
        if not quiz:
            cfg = {"title": "Science basics (seed)", "subject": "Science", "topic": "Photosynthesis and water cycle", "grade": "Grade 9",
                   "difficulty": "easy", "question_type": "mcq"}
            quiz = qs.save_quiz(teacher, cfg, [{"text": q[1], "options": q[2], "answer": q[3], "explanation": q[4], "topic": q[0]} for q in QUESTIONS],
                                ai_generated=False, course=course, published=True)
        Assignment.objects.get_or_create(course=course, title="Draw and label the water cycle", defaults={"due_date": timezone.localdate() + timedelta(days=5), "quiz": quiz})

        today = timezone.localdate()
        for i, s in enumerate(students):
            if not LearningActivity.objects.filter(student=s).exists():
                for d in range(6):
                    LearningActivity.objects.create(student=s, kind="tutor" if d % 2 else "quiz", minutes=15 + 5 * ((d + i) % 4), subject="Science",
                                                    detail="Seed activity", occurred_on=today - timedelta(days=d))
            if not QuizAttempt.objects.filter(student=s, quiz=quiz).exists():
                att = QuizAttempt.objects.create(quiz=quiz, student=s, total=quiz.questions.count())
                answers = {str(q.id): (q.correct_answer if (j + i) % 3 else "Wrong") for j, q in enumerate(quiz.questions.all())}
                qs.grade_attempt(att, answers)
        asha = students[0]
        if not asha.study_plans.exists():
            planner.create_plan(asha, {"goal": "Finish Grade 9 Science unit", "subject": "Science", "topics": ["Photosynthesis", "Water cycle", "Cells and tissues"],
                                       "target_date": today + timedelta(days=14), "daily_minutes": 45, "level": "beginner", "language": "en"})
        Notification.objects.get_or_create(user=asha, title="Welcome to LearnMate AI", defaults={"body": "Start with your study plan.", "url": "/planner/"})
        self.stdout.write(self.style.SUCCESS(f"Seeded. Log in with admin / teacher / asha / karthik. Password for all: {PASSWORD}"))
