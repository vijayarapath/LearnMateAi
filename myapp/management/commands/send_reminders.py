from django.core.management.base import BaseCommand
from django.utils import timezone

from myapp.models import Notification, StudyTask


class Command(BaseCommand):
    help = "Creates a notification for each student with study tasks due today. Run daily from cron."

    def handle(self, *args, **opts):
        today = timezone.localdate()
        n = 0
        for owner_id in StudyTask.objects.filter(scheduled_date=today, completed=False, plan__is_active=True).values_list("plan__owner_id", flat=True).distinct():
            count = StudyTask.objects.filter(plan__owner_id=owner_id, scheduled_date=today, completed=False).count()
            if not Notification.objects.filter(user_id=owner_id, title="Study tasks today", created_at__date=today).exists():
                Notification.objects.create(user_id=owner_id, title="Study tasks today", body=f"You have {count} task(s) planned for today.", url="/planner/")
                n += 1
        self.stdout.write(f"Created {n} reminders.")
