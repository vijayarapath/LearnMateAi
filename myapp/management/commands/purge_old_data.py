from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from myapp.models import AIRequestLog, Notification


class Command(BaseCommand):
    help = "Deletes old AI request logs and read notifications according to RETENTION settings."

    def handle(self, *args, **opts):
        r = settings.RETENTION_DAYS
        now = timezone.now()
        a, _ = AIRequestLog.objects.filter(created_at__lt=now - timedelta(days=r["ai_request_logs"])).delete()
        n, _ = Notification.objects.filter(is_read=True, created_at__lt=now - timedelta(days=r["read_notifications"])).delete()
        self.stdout.write(f"Removed {a} AI logs and {n} notifications.")
