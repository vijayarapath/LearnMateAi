"""Quiz generation, validation and server-side scoring."""
import re

from django.db import transaction
from django.utils import timezone

from myapp.models import Question, QuizAnswer, QuizAttempt, Quiz
from .adapters import get_text_service, parse_json_block
from .errors import AIBadResponse
from .safety import clean_text, wrap_untrusted

MAX_QUESTIONS = 20


class QuizValidationError(AIBadResponse):
    pass


def build_prompt(quiz_cfg, material_text=""):
    qtype = {"mcq": "multiple choice with exactly 4 options", "tf": "true or false", "short": "short answer (1 to 4 words)"}[quiz_cfg["question_type"]]
    parts = [
        f"Create {quiz_cfg['count']} {quiz_cfg['difficulty']} {qtype} questions for {quiz_cfg['grade'] or 'general'} level students.",
        f"Subject: {quiz_cfg['subject']}. Topic: {quiz_cfg['topic']}.",
        "Reply with JSON only, in this shape: "
        '{"questions":[{"text":"...","options":["..."],"answer":"...","explanation":"...","topic":"..."}]}.',
        "For multiple choice, 'answer' must be exactly one of the options. For true or false, options are [\"True\",\"False\"]. "
        "For short answer, use an empty options list.",
    ]
    if material_text:
        parts.append("Base the questions only on this material:\n" + wrap_untrusted(material_text))
    return "\n".join(parts)


def validate_payload(payload, qtype, expected):
    """Returns a clean list of question dicts or raises QuizValidationError."""
    items = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        raise QuizValidationError("The AI did not return any questions. Try again.")
    clean = []
    for raw in items[:MAX_QUESTIONS]:
        if not isinstance(raw, dict):
            continue
        text = clean_text(str(raw.get("text", "")), 600)
        answer = clean_text(str(raw.get("answer", "")), 300)
        expl = clean_text(str(raw.get("explanation", "")), 800)
        topic = clean_text(str(raw.get("topic", "")), 140)
        options = [clean_text(str(o), 300) for o in raw.get("options") or [] if str(o).strip()]
        if not text or not answer:
            continue
        if qtype == "mcq":
            if len(options) < 2 or len(set(o.lower() for o in options)) != len(options):
                continue
            match = next((o for o in options if o.lower() == answer.lower()), None)
            if not match:
                continue
            answer = match
        elif qtype == "tf":
            options = ["True", "False"]
            if answer.lower() not in ("true", "false"):
                continue
            answer = answer.capitalize()
        else:
            options = []
        clean.append({"text": text, "options": options, "answer": answer, "explanation": expl, "topic": topic})
    if not clean:
        raise QuizValidationError("The AI questions were not in a usable format. Try again.")
    return clean[:expected]


def generate_questions(cfg, material_text="", user=None):
    svc = get_text_service()
    reply = svc.chat([{"role": "user", "content": build_prompt(cfg, material_text)}],
                     system="You write accurate quiz questions. Output JSON only.", user=user, max_tokens=2500, temperature=0.3)
    return validate_payload(parse_json_block(reply), cfg["question_type"], cfg["count"])


@transaction.atomic
def save_quiz(owner, cfg, questions, ai_generated=True, **extra):
    quiz = Quiz.objects.create(
        owner=owner, title=cfg.get("title") or f"{cfg['subject']}: {cfg['topic']}", subject=cfg["subject"], topic=cfg["topic"],
        grade=cfg.get("grade", ""), difficulty=cfg["difficulty"], question_type=cfg["question_type"],
        timer_minutes=cfg.get("timer_minutes") or None, ai_generated=ai_generated, **extra,
    )
    Question.objects.bulk_create([
        Question(quiz=quiz, order=i, qtype=cfg["question_type"], text=q["text"], options=q["options"],
                 correct_answer=q["answer"], explanation=q["explanation"], topic=q["topic"] or cfg["topic"])
        for i, q in enumerate(questions)
    ])
    return quiz


def _norm(s):
    return re.sub(r"[^\w\s]", "", (s or "").lower(), flags=re.U).strip()


def is_correct(question, given):
    if question.qtype in ("mcq", "tf"):
        return _norm(given) == _norm(question.correct_answer)
    return _norm(given) == _norm(question.correct_answer) and bool(_norm(given))


@transaction.atomic
def grade_attempt(attempt, answers):
    """answers = {question_id: given}. The score is computed here, never taken from the client."""
    if attempt.is_submitted:
        return attempt
    questions = list(attempt.quiz.questions.all())
    rows, score = [], 0
    for q in questions:
        given = str(answers.get(str(q.id), answers.get(q.id, "")))[:500]
        ok = is_correct(q, given)
        score += ok
        rows.append(QuizAnswer(attempt=attempt, question=q, given=given, is_correct=ok))
    QuizAnswer.objects.bulk_create(rows)
    attempt.score, attempt.total = score, len(questions)
    attempt.percent = round(100 * score / len(questions), 1) if questions else 0
    attempt.submitted_at = timezone.now()
    attempt.save()
    return attempt


def topic_breakdown(attempt):
    out = {}
    for a in attempt.answers.select_related("question"):
        t = a.question.topic or attempt.quiz.topic
        row = out.setdefault(t, {"topic": t, "correct": 0, "total": 0})
        row["total"] += 1
        row["correct"] += a.is_correct
    for row in out.values():
        row["percent"] = round(100 * row["correct"] / row["total"])
    return sorted(out.values(), key=lambda r: r["percent"])


@transaction.atomic
def retry_incorrect_quiz(attempt, user):
    """Builds a new private quiz from the questions the student got wrong."""
    wrong = [a.question for a in attempt.answers.select_related("question") if not a.is_correct]
    if not wrong:
        return None
    src = attempt.quiz
    quiz = Quiz.objects.create(owner=user, title=f"Retry: {src.title}"[:160], subject=src.subject, topic=src.topic, grade=src.grade,
                               difficulty=src.difficulty, question_type=src.question_type, ai_generated=False)
    Question.objects.bulk_create([
        Question(quiz=quiz, order=i, qtype=q.qtype, text=q.text, options=q.options, correct_answer=q.correct_answer,
                 explanation=q.explanation, topic=q.topic) for i, q in enumerate(wrong)
    ])
    return quiz
