from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework import serializers
from rest_framework.views import APIView

from myapp.models import Conversation, LANG_CHOICES, LEVEL_CHOICES, Message, SavedNote
from myapp.services.adapters import get_text_service
from myapp.services.errors import AIError
from myapp.services.ratelimit import rate_limited
from myapp.services.safety import TUTOR_SYSTEM, clean_text, looks_like_injection
from .utils import error_response, log_activity, require_ai_consent


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000, trim_whitespace=True)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    grade = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    subject = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    language = serializers.ChoiceField(choices=LANG_CHOICES, default="en")
    difficulty = serializers.ChoiceField(choices=LEVEL_CHOICES, default="medium")
    detail = serializers.ChoiceField(choices=["short", "detailed"], default="short")
    source = serializers.ChoiceField(choices=["text", "voice"], default="text")


def build_system(conv):
    lang = "Tamil" if conv.language == "ta" else "English"
    length = "Keep the answer short (under 120 words)." if conv.detail == "short" else "Give a detailed, step-by-step explanation with a worked example."
    return (f"{TUTOR_SYSTEM}\nReply in {lang}. Level: {conv.difficulty}. Student grade: {conv.grade or 'not given'}. "
            f"Subject: {conv.subject or 'general'}. {length} End with one short practice question.")


def ask_ai(user, conv, history_before=None):
    msgs = history_before if history_before is not None else list(conv.messages.order_by("-id")[:10])[::-1]
    payload = [{"role": m.role, "content": m.content} for m in msgs]
    return get_text_service().chat(payload, system=build_system(conv), user=user, max_tokens=1100 if conv.detail == "detailed" else 500)


def msg_json(m):
    return {"id": m.id, "role": m.role, "content": m.content, "feedback": m.feedback}


class AskView(APIView):
    @rate_limited("tutor")
    def post(self, request):
        s = AskSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            require_ai_consent(request.user)
        except AIError as exc:
            return error_response(exc)
        conv = None
        if d.get("conversation_id"):
            conv = get_object_or_404(Conversation, pk=d["conversation_id"], owner=request.user)
        if conv is None:
            conv = Conversation(owner=request.user, title=d["question"][:60])
        for f in ("grade", "subject", "language", "difficulty", "detail"):
            setattr(conv, f, d[f])
        conv.save()
        question = clean_text(d["question"], 2000)
        user_msg = Message.objects.create(conversation=conv, role="user", content=question, source=d["source"])
        try:
            answer = ask_ai(request.user, conv)
        except AIError as exc:
            resp = error_response(exc)
            resp.content = JsonResponse({"ok": False, "code": exc.code, "error": exc.message, "retryable": exc.retryable,
                                         "conversation_id": conv.id, "user_message": msg_json(user_msg)}).content
            return resp
        ai_msg = Message.objects.create(conversation=conv, role="assistant", content=answer)
        conv.save(update_fields=["updated_at"])
        log_activity(request.user, "voice" if d["source"] == "voice" else "tutor", 6, conv.subject, question[:120])
        return JsonResponse({"ok": True, "conversation_id": conv.id, "title": conv.title, "user_message": msg_json(user_msg),
                             "message": msg_json(ai_msg), "flag": looks_like_injection(question)})


class RegenerateView(APIView):
    @rate_limited("tutor")
    def post(self, request, pk):
        msg = get_object_or_404(Message, pk=pk, conversation__owner=request.user, role="assistant")
        try:
            require_ai_consent(request.user)
            earlier = list(msg.conversation.messages.filter(id__lt=msg.id).order_by("-id")[:10])[::-1]
            msg.content = ask_ai(request.user, msg.conversation, earlier)
        except AIError as exc:
            return error_response(exc)
        msg.feedback = 0
        msg.save()
        return JsonResponse({"ok": True, "message": msg_json(msg)})


class FeedbackView(APIView):
    def post(self, request, pk):
        msg = get_object_or_404(Message, pk=pk, conversation__owner=request.user, role="assistant")
        val = request.data.get("value")
        if val not in (1, -1, "1", "-1"):
            return JsonResponse({"ok": False, "error": "Value must be 1 or -1."}, status=400)
        msg.feedback = int(val)
        msg.save(update_fields=["feedback"])
        return JsonResponse({"ok": True})


class SaveNoteView(APIView):
    def post(self, request, pk):
        msg = get_object_or_404(Message, pk=pk, conversation__owner=request.user, role="assistant")
        prev = msg.conversation.messages.filter(id__lt=msg.id, role="user").order_by("-id").first()
        title = (request.data.get("title") or (prev.content[:80] if prev else "AI note"))[:140]
        note = SavedNote.objects.create(owner=request.user, title=title, body=msg.content, subject=msg.conversation.subject)
        return JsonResponse({"ok": True, "note_id": note.id})


@login_required
def tutor_page(request, pk=None):
    convs = Conversation.objects.filter(owner=request.user)[:20]
    current = get_object_or_404(Conversation, pk=pk, owner=request.user) if pk else None
    p = request.user.profile
    return render(request, "myapp/tutor.html", {
        "conversations": convs, "current": current, "messages_list": current.messages.all() if current else [],
        "defaults": current or {"grade": p.grade, "language": p.preferred_language, "difficulty": "medium", "detail": "short", "subject": ""},
        "langs": LANG_CHOICES, "levels": LEVEL_CHOICES,
    })


@login_required
def conversation_delete(request, pk):
    if request.method == "POST":
        get_object_or_404(Conversation, pk=pk, owner=request.user).delete()
    return redirect("tutor")


@login_required
def notes_page(request):
    return render(request, "myapp/notes.html", {"notes": SavedNote.objects.filter(owner=request.user)})


@login_required
def note_delete(request, pk):
    if request.method == "POST":
        get_object_or_404(SavedNote, pk=pk, owner=request.user).delete()
    return redirect("notes")
