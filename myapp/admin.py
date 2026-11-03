from django.contrib import admin

from . import models

admin.site.site_header = "LearnMate AI administration"


@admin.register(models.Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "grade", "ai_consent", "is_minor")
    list_filter = ("role", "ai_consent", "is_minor")
    search_fields = ("user__username", "user__email")


@admin.register(models.AIRequestLog)
class AIRequestLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "service", "model_name", "ok", "error_code", "latency_ms")
    list_filter = ("service", "ok")
    readonly_fields = [f.name for f in models.AIRequestLog._meta.fields]

    def has_add_permission(self, request):
        return False


for m in [models.Subject, models.Course, models.Enrollment, models.Topic, models.LearningMaterial,
          models.Assignment, models.Quiz, models.StudyPlan, models.GeneratedVisual, models.Notification]:
    admin.site.register(m)
