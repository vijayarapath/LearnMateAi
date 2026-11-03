import re

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework.views import APIView

from myapp.models import GeneratedVisual
from myapp.services.adapters import MuseImageService
from myapp.services.errors import AIError
from myapp.services.ratelimit import rate_limited
from .utils import error_response, log_activity, require_ai_consent

BLOCKED = re.compile(r"\b(nude|nsfw|gore|porn|sexual|suicide|self[- ]harm|weapon|bomb|terror)\b", re.I)


@login_required
def visuals_page(request):
    return render(request, "myapp/visuals.html", {"items": GeneratedVisual.objects.filter(owner=request.user)[:24]})


@login_required
def visual_delete(request, pk):
    if request.method == "POST":
        get_object_or_404(GeneratedVisual, pk=pk, owner=request.user).delete()
    return redirect("visuals")


class GenerateView(APIView):
    @rate_limited("image")
    def post(self, request):
        prompt = (request.data.get("prompt") or "").strip()
        if len(prompt) < 8 or len(prompt) > 500:
            return JsonResponse({"ok": False, "error": "Describe the picture in 8 to 500 characters."}, status=400)
        if BLOCKED.search(prompt):
            return JsonResponse({"ok": False, "code": "unsafe", "error": "This prompt is not allowed. Ask for an educational picture instead."}, status=400)
        labels = [l.strip()[:40] for l in re.split(r"[,\n]", request.data.get("labels") or "") if l.strip()][:12]
        try:
            require_ai_consent(request.user)
        except AIError as exc:
            return error_response(exc)
        visual = GeneratedVisual.objects.create(owner=request.user, prompt=prompt, labels=labels)
        full = (f"Educational illustration for students: {prompt}. Clean, simple, accurate. "
                "Do not write any text or letters inside the image.")
        try:
            img = MuseImageService().generate(full, user=request.user)
        except AIError as exc:
            visual.status, visual.error = "failed", exc.message[:240]
            visual.save(update_fields=["status", "error"])
            return error_response(exc)
        visual.image.save(f"visual_{visual.id}.png", ContentFile(img), save=False)
        visual.status = "done"
        visual.save()
        log_activity(request.user, "visual", 4, "", prompt[:120])
        return JsonResponse({"ok": True, "id": visual.id, "url": f"/media-private/visual/{visual.id}/", "labels": labels})
