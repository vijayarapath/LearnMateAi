from django.http import JsonResponse
from rest_framework.views import APIView

from myapp.services.adapters import MuseVoiceTranscribeService
from myapp.services.errors import AIError
from myapp.services.ratelimit import rate_limited
from myapp.services.safety import UploadRejected, validate_audio
from .utils import error_response, require_ai_consent


class TranscribeView(APIView):
    """Audio is read into memory, sent for transcription and discarded. It is never written to disk or the database."""
    @rate_limited("voice")
    def post(self, request):
        try:
            require_ai_consent(request.user)
            upload = request.FILES.get("audio")
            if not upload:
                raise UploadRejected("No recording was received.")
            data, ctype = validate_audio(upload)
            lang = request.data.get("language", "")
            lang = lang if lang in ("en", "ta") else ""
            text = MuseVoiceTranscribeService().transcribe(data, upload.name or "question.webm", ctype, lang, user=request.user)
        except UploadRejected as exc:
            return JsonResponse({"ok": False, "code": "invalid_upload", "error": str(exc)}, status=400)
        except AIError as exc:
            return error_response(exc)
        if not text:
            return JsonResponse({"ok": False, "code": "empty", "error": "We could not hear a question. Try again or type it.", "retryable": True}, status=422)
        return JsonResponse({"ok": True, "text": text})
