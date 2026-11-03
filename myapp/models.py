import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

ROLE_STUDENT, ROLE_TEACHER, ROLE_ADMIN = "student", "teacher", "admin"
ROLE_CHOICES = [(ROLE_STUDENT, "Student"), (ROLE_TEACHER, "Teacher"), (ROLE_ADMIN, "Administrator")]
LANG_CHOICES = [("en", "English"), ("ta", "Tamil")]
LEVEL_CHOICES = [("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")]


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------- accounts
class Profile(Timestamped):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_STUDENT, db_index=True)
    photo = models.ImageField(upload_to="profile_photos/", blank=True)
    grade = models.CharField(max_length=40, blank=True, help_text="For example: Grade 9, B.Com Year 2")
    preferred_language = models.CharField(max_length=2, choices=LANG_CHOICES, default="en")
    bio = models.CharField(max_length=240, blank=True)
    ai_consent = models.BooleanField(
        default=False, help_text="Allows questions and uploads to be sent to the configured AI provider."
    )
    guardian_consent = models.BooleanField(default=False)
    is_minor = models.BooleanField(default=False)
    sidebar_collapsed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.role})"

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def can_use_ai(self):
        """AI features need consent; minors also need guardian consent."""
        if not self.ai_consent:
            return False
        return self.guardian_consent if self.is_minor else True

    @property
    def is_student(self):
        return self.role == ROLE_STUDENT

    @property
    def is_teacher(self):
        return self.role == ROLE_TEACHER

    @property
    def is_admin_role(self):
        return self.role == ROLE_ADMIN or self.user.is_superuser


# ---------------------------------------------------------------- courses
class Subject(Timestamped):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Course(Timestamped):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="courses")
    teacher = models.ForeignKey(User, on_delete=models.PROTECT, related_name="taught_courses")
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    grade_level = models.CharField(max_length=40, blank=True)
    join_code = models.CharField(max_length=8, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    students = models.ManyToManyField(User, through="Enrollment", related_name="courses")

    class Meta:
        ordering = ["title"]

    def save(self, *args, **kwargs):
        if not self.join_code:
            self.join_code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Enrollment(Timestamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments")

    class Meta:
        unique_together = [("course", "student")]

    def __str__(self):
        return f"{self.student} in {self.course}"


class Topic(Timestamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="topics")
    title = models.CharField(max_length=140)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["course", "order", "title"]

    def __str__(self):
        return self.title


class TopicProgress(Timestamped):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="topic_progress")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="progress")
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = [("student", "topic")]


class LearningMaterial(Timestamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=160)
    file = models.FileField(upload_to="materials/", blank=True)
    text_content = models.TextField(blank=True, help_text="Plain text used for quiz generation.")
    is_flagged = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Assignment(Timestamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assignments")
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True)
    due_date = models.DateField()
    quiz = models.ForeignKey("Quiz", null=True, blank=True, on_delete=models.SET_NULL, related_name="assignments")

    class Meta:
        ordering = ["due_date"]

    def __str__(self):
        return self.title


# ---------------------------------------------------------------- tutor
class Conversation(Timestamped):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=140, default="New conversation")
    grade = models.CharField(max_length=40, blank=True)
    subject = models.CharField(max_length=80, blank=True)
    language = models.CharField(max_length=2, choices=LANG_CHOICES, default="en")
    difficulty = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="medium")
    detail = models.CharField(max_length=10, default="short", choices=[("short", "Short"), ("detailed", "Detailed")])

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.title


class Message(Timestamped):
    ROLE = [("user", "User"), ("assistant", "AI tutor")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE)
    content = models.TextField()
    feedback = models.SmallIntegerField(default=0, help_text="1 helpful, -1 not helpful")
    source = models.CharField(max_length=20, default="text", help_text="text | voice | image")

    class Meta:
        ordering = ["created_at", "id"]


class SavedNote(Timestamped):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes")
    title = models.CharField(max_length=140)
    body = models.TextField()
    subject = models.CharField(max_length=80, blank=True)
    from_ai = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]


# ---------------------------------------------------------------- materials / images
class UploadedImage(Timestamped):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="uploaded_images")
    image = models.ImageField(upload_to="textbook/%Y/%m/")
    title = models.CharField(max_length=140, blank=True)
    subject = models.CharField(max_length=80, blank=True)
    crop_box = models.JSONField(null=True, blank=True)
    explanation = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, default="uploaded", choices=[("uploaded", "Uploaded"), ("done", "Done"), ("failed", "Failed")]
    )
    error = models.CharField(max_length=240, blank=True)
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]


class ExtractedContent(Timestamped):
    source = models.OneToOneField(UploadedImage, on_delete=models.CASCADE, related_name="extracted")
    text = models.TextField(blank=True)
    segments = models.JSONField(default=list, blank=True, help_text="Regions returned by the segmentation model")
    notes = models.TextField(blank=True)
    summary = models.TextField(blank=True)


# ---------------------------------------------------------------- quizzes
class Quiz(Timestamped):
    QTYPES = [("mcq", "Multiple choice"), ("tf", "True or false"), ("short", "Short answer")]
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quizzes")
    course = models.ForeignKey(Course, null=True, blank=True, on_delete=models.SET_NULL, related_name="quizzes")
    title = models.CharField(max_length=160)
    subject = models.CharField(max_length=80)
    topic = models.CharField(max_length=140)
    grade = models.CharField(max_length=40, blank=True)
    difficulty = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="medium")
    question_type = models.CharField(max_length=6, choices=QTYPES, default="mcq")
    timer_minutes = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(180)])
    source_material = models.ForeignKey(LearningMaterial, null=True, blank=True, on_delete=models.SET_NULL)
    source_image = models.ForeignKey(UploadedImage, null=True, blank=True, on_delete=models.SET_NULL)
    ai_generated = models.BooleanField(default=False)
    published = models.BooleanField(default=False, help_text="Teachers publish quizzes so enrolled students can take them")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Question(Timestamped):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField(default=0)
    qtype = models.CharField(max_length=6, choices=Quiz.QTYPES, default="mcq")
    text = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_answer = models.CharField(max_length=300)
    explanation = models.TextField(blank=True)
    topic = models.CharField(max_length=140, blank=True)

    class Meta:
        ordering = ["quiz", "order", "id"]


class QuizAttempt(Timestamped):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quiz_attempts")
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    percent = models.FloatField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    retry_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="retries")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["student", "-created_at"])]

    @property
    def is_submitted(self):
        return self.submitted_at is not None


class QuizAnswer(Timestamped):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    given = models.CharField(max_length=500, blank=True)
    is_correct = models.BooleanField(default=False)

    class Meta:
        unique_together = [("attempt", "question")]


# ---------------------------------------------------------------- study planner
class StudyPlan(Timestamped):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_plans")
    goal = models.CharField(max_length=200)
    subject = models.CharField(max_length=80)
    topics = models.JSONField(default=list)
    start_date = models.DateField(default=timezone.localdate)
    target_date = models.DateField()
    daily_minutes = models.PositiveIntegerField(validators=[MinValueValidator(10), MaxValueValidator(720)])
    level = models.CharField(max_length=12, choices=[("beginner", "Beginner"), ("intermediate", "Intermediate"), ("advanced", "Advanced")], default="beginner")
    language = models.CharField(max_length=2, choices=LANG_CHOICES, default="en")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.goal

    @property
    def completion_percent(self):
        total = self.tasks.count()
        if not total:
            return 0
        return round(100 * self.tasks.filter(completed=True).count() / total)


class StudyTask(Timestamped):
    KINDS = [("learn", "Learn"), ("practice", "Practice"), ("revise", "Revise"), ("milestone", "Milestone")]
    plan = models.ForeignKey(StudyPlan, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    topic = models.CharField(max_length=140, blank=True)
    kind = models.CharField(max_length=10, choices=KINDS, default="learn")
    scheduled_date = models.DateField(db_index=True)
    minutes = models.PositiveIntegerField(default=30)
    priority = models.PositiveSmallIntegerField(default=2, help_text="1 high, 3 low")
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    practice_prompt = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["scheduled_date", "priority", "id"]


class LearningActivity(Timestamped):
    KINDS = [
        ("tutor", "AI question"), ("quiz", "Quiz"), ("image", "Textbook image"), ("voice", "Voice question"),
        ("task", "Study task"), ("visual", "Visual"), ("lesson", "Lesson"),
    ]
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(max_length=10, choices=KINDS)
    minutes = models.PositiveSmallIntegerField(default=5)
    subject = models.CharField(max_length=80, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    occurred_on = models.DateField(default=timezone.localdate, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["student", "occurred_on"])]


# ---------------------------------------------------------------- visuals / notifications / logs
class GeneratedVisual(Timestamped):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="visuals")
    prompt = models.CharField(max_length=600)
    image = models.ImageField(upload_to="visuals/%Y/%m/", blank=True)
    labels = models.JSONField(default=list, blank=True, help_text="Labels drawn in HTML/SVG, not inside the image")
    status = models.CharField(max_length=10, default="pending", choices=[("pending", "Pending"), ("done", "Done"), ("failed", "Failed")])
    error = models.CharField(max_length=240, blank=True)
    is_flagged = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class Notification(Timestamped):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]


class AIRequestLog(Timestamped):
    """Metadata only. Prompts and responses are never stored here."""
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="ai_logs")
    service = models.CharField(max_length=20, db_index=True)
    model_name = models.CharField(max_length=80, blank=True)
    ok = models.BooleanField(default=True, db_index=True)
    error_code = models.CharField(max_length=40, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    input_chars = models.PositiveIntegerField(default=0)
    output_chars = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["service", "-created_at"])]
