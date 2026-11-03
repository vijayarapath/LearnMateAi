from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (Assignment, Course, LANG_CHOICES, LEVEL_CHOICES, LearningMaterial, Profile, Question, Quiz, StudyPlan,
                     Subject, Topic)

TEXTISH = {"class": "form-control"}


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=60, label="Full name")
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[("student", "Student"), ("teacher", "Teacher"), ("admin", "Admin")])
    grade = forms.CharField(max_length=40, required=False, label="Grade or year", help_text="For example: Grade 9 or B.Com Year 2")
    is_minor = forms.BooleanField(required=False, label="I am under 18")

    class Meta:
        model = User
        fields = ("username", "first_name", "email", "role", "grade", "is_minor", "password1", "password2")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        choices = [("student", "Student")]
        if getattr(settings, "TEACHER_SELF_SIGNUP", False):
            choices.append(("teacher", "Teacher"))
        if getattr(settings, "ADMIN_SELF_SIGNUP", True):
            choices.append(("admin", "Admin"))
        self.fields["role"].choices = choices
        if len(choices) == 1:
            self.fields["role"].initial = "student"

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Log in or reset your password.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        role = self.cleaned_data["role"]
        if role == "admin":
            user.is_staff = True
        if commit:
            user.save()
            p = user.profile
            p.role = role
            p.grade = self.cleaned_data.get("grade", "")
            p.is_minor = self.cleaned_data.get("is_minor", False)
            p.save()
        return user


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=60, label="Full name")
    email = forms.EmailField()

    class Meta:
        model = Profile
        fields = ["photo", "grade", "preferred_language", "bio", "is_minor", "ai_consent", "guardian_consent"]
        labels = {
            "ai_consent": "Allow AI features",
            "guardian_consent": "A parent or guardian has agreed to AI features",
            "is_minor": "I am under 18",
        }
        help_texts = {
            "ai_consent": "Your questions and uploads are sent to the AI provider your school configured. Turn this off to stop.",
            "photo": "JPG or PNG, up to 3 MB.",
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        u = self.instance.user
        self.fields["first_name"].initial = u.first_name
        self.fields["email"].initial = u.email
        self.order_fields(["first_name", "email", "photo", "grade", "preferred_language", "bio", "is_minor", "ai_consent", "guardian_consent"])

    def clean_photo(self):
        f = self.cleaned_data.get("photo")
        if f and hasattr(f, "size"):
            if f.size > 3 * 1024 * 1024:
                raise forms.ValidationError("Photo is larger than 3 MB.")
            from PIL import Image
            try:
                Image.open(f).verify()
                f.seek(0)
            except Exception:
                raise forms.ValidationError("This file is not a readable image.")
        return f

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.user_id).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email

    def save(self, commit=True):
        p = super().save(commit=False)
        u = p.user
        u.first_name = self.cleaned_data["first_name"]
        u.email = self.cleaned_data["email"]
        if commit:
            u.save()
            p.save()
        return p


class QuizCreateForm(forms.Form):
    subject = forms.CharField(max_length=80)
    topic = forms.CharField(max_length=140)
    grade = forms.CharField(max_length=40, required=False, label="Grade or level")
    count = forms.IntegerField(min_value=3, max_value=20, initial=5, label="Number of questions")
    difficulty = forms.ChoiceField(choices=LEVEL_CHOICES, initial="medium")
    question_type = forms.ChoiceField(choices=Quiz.QTYPES, label="Question type")
    timer_minutes = forms.IntegerField(min_value=1, max_value=180, required=False, label="Timer (minutes)", help_text="Leave empty for no timer.")
    material = forms.ModelChoiceField(queryset=LearningMaterial.objects.none(), required=False, label="Use learning material", empty_label="None")
    image = forms.ModelChoiceField(queryset=None, required=False, label="Use a textbook upload", empty_label="None")
    course = forms.ModelChoiceField(queryset=Course.objects.none(), required=False, label="Class", empty_label="Not for a class")
    publish = forms.BooleanField(required=False, label="Publish to the class now")

    def __init__(self, user, *a, **kw):
        super().__init__(*a, **kw)
        from .models import UploadedImage
        self.user = user
        self.fields["image"].queryset = UploadedImage.objects.filter(owner=user, status="done")
        if user.profile.role == "teacher" or user.profile.is_admin_role:
            courses = Course.objects.filter(teacher=user)
            self.fields["course"].queryset = courses
            self.fields["material"].queryset = LearningMaterial.objects.filter(course__in=courses)
        else:
            enrolled = Course.objects.filter(enrollments__student=user)
            self.fields["material"].queryset = LearningMaterial.objects.filter(course__in=enrolled, is_flagged=False)
            del self.fields["course"]
            del self.fields["publish"]


class ManualQuestionForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), label="Question")
    options = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Options (one per line)",
                              help_text="Multiple choice needs at least 2 options. Leave empty for short answer.")
    correct_answer = forms.CharField(max_length=300, label="Correct answer")
    explanation = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    topic = forms.CharField(required=False, max_length=140)

    def __init__(self, qtype, *a, **kw):
        super().__init__(*a, **kw)
        self.qtype = qtype

    def clean(self):
        data = super().clean()
        opts = [o.strip() for o in (data.get("options") or "").splitlines() if o.strip()]
        ans = (data.get("correct_answer") or "").strip()
        if self.qtype == "mcq":
            if len(opts) < 2:
                self.add_error("options", "Add at least two options.")
            elif ans.lower() not in [o.lower() for o in opts]:
                self.add_error("correct_answer", "The correct answer must match one of the options.")
        elif self.qtype == "tf":
            opts = ["True", "False"]
            if ans.lower() not in ("true", "false"):
                self.add_error("correct_answer", "Use True or False.")
        data["option_list"] = opts
        return data


class StudyPlanForm(forms.ModelForm):
    topics_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Topics to complete", help_text="One topic per line.")

    class Meta:
        model = StudyPlan
        fields = ["goal", "subject", "target_date", "daily_minutes", "level", "language"]
        widgets = {"target_date": forms.DateInput(attrs={"type": "date"})}
        labels = {"daily_minutes": "Study time per day (minutes)", "level": "Current knowledge level", "language": "Preferred language"}

    def clean_target_date(self):
        d = self.cleaned_data["target_date"]
        if d <= timezone.localdate():
            raise forms.ValidationError("Choose a date after today.")
        if d > timezone.localdate() + timedelta(days=365):
            raise forms.ValidationError("Plans can run for up to a year.")
        return d

    def clean_topics_text(self):
        topics = [t.strip() for t in self.cleaned_data["topics_text"].splitlines() if t.strip()]
        if not topics:
            raise forms.ValidationError("Add at least one topic.")
        if len(topics) > 40:
            raise forms.ValidationError("Use 40 topics or fewer per plan.")
        return topics


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["subject", "title", "description", "grade_level"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["subject"].queryset = Subject.objects.filter(is_active=True)


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["title", "instructions", "due_date", "quiz"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}), "instructions": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, course, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["quiz"].queryset = Quiz.objects.filter(course=course)
        self.fields["quiz"].required = False


ALLOWED_MATERIAL_EXT = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".docx", ".pptx"}


class MaterialForm(forms.ModelForm):
    class Meta:
        model = LearningMaterial
        fields = ["title", "file", "text_content"]
        widgets = {"text_content": forms.Textarea(attrs={"rows": 5})}
        labels = {"text_content": "Text for quiz generation"}

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if f and hasattr(f, "size"):
            import os
            if os.path.splitext(f.name)[1].lower() not in ALLOWED_MATERIAL_EXT:
                raise forms.ValidationError("Upload a PDF, TXT, MD, DOCX, PPTX, JPG or PNG file.")
            if f.size > settings.MAX_MATERIAL_UPLOAD_MB * 1024 * 1024:
                raise forms.ValidationError(f"Files must be under {settings.MAX_MATERIAL_UPLOAD_MB} MB.")
        return f

    def clean(self):
        d = super().clean()
        if not d.get("file") and not d.get("text_content"):
            raise forms.ValidationError("Add a file or paste some text.")
        return d


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "description"]
