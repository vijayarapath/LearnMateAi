 HEAD
# LearnMate AI — Smart Learning Platform

A Django 5 + Bootstrap 5 education platform with an AI tutor, textbook image reader, voice questions,
quiz generator, study planner, picture generator, and dashboards for students, teachers and administrators.

- Folder: `Education/`  ·  Django project: `myproject`  ·  App: `myapp`
- Runs locally with SQLite. Production guide for PostgreSQL, Gunicorn and Nginx is below.

## 1. Quick start (5 minutes)

```bash
cd Education
./run_dev.sh            # Linux / macOS: makes a venv, installs, migrates, seeds demo data, starts the server
# Windows: run_dev.bat
```

Manual steps:

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with the demo accounts (password for all: `LearnMate#2026`):

| Username | Role |
|---|---|
| `admin` | Administrator |
| `teacher` | Teacher (owns "Grade 9 Science") |
| `asha`, `karthik` | Students (enrolled, with quiz results and a study plan) |

The seed quiz is hand-written sample content, not AI output. Change these passwords before any real use.

> The pages load Bootstrap, Bootstrap Icons, Chart.js and the Inter font from public CDNs, so the browser needs internet access.

## 2. What works without any AI credentials

Login, roles, dashboards, classes, enrollment, assignments, materials, **study planner** (rule-based scheduler),
manual quiz building, quiz taking with server-side scoring, analytics, notifications, search, admin tools.

## 3. What needs AI credentials

| Feature | Needs | If missing |
|---|---|---|
| AI tutor chat | Text model (Muse Spark, or a local server) | Clear "not configured" message, retry button |
| Textbook image explanation | Image-reading model (Muse Wonder) **and** a text model | Upload is kept, marked Failed with the reason |
| Diagram regions | SAM 3.1 (optional) | Skipped silently, explanation still works |
| Voice questions | Muse Voice Transcribe | Message shown, text box always available |
| AI quiz generation | Text model | Message shown, nothing saved |
| Picture generator | Muse Image | Message shown |

### Configuring the Meta models (read this)

I could not verify Meta's endpoint URLs, model identifiers or request schemas from inside this build, and the brief
says not to invent them. So **nothing is hard-coded as fact**:

1. Put the values from your official Meta documentation into `.env`: `META_API_BASE_URL`, `META_API_KEY`, and for each
   model `*_MODEL` (identifier) and `*_PATH` (endpoint path). A feature counts as configured only when all four are set.
2. Open `myapp/services/adapters.py`. Each adapter has `build_payload` / `build_request` and `parse_response`.
   The defaults use the common chat-completions JSON shape (`messages` in, `choices[0].message.content` out),
   a `{"data":[{"b64_json":...}]}` shape for images, `{"text": ...}` for transcription, and
   `{"segments":[{"label","box":[x,y,w,h in %]}]}` for SAM. **If the official schema differs, change only those methods.**
3. Check the Configuration page (admin) to see which services report "Configured".
4. Before promising Tamil or any audio format to users, confirm support in the model documentation.

Open-weight models (Muse Spark Open, Muse Glimmer) can run on your own server behind an OpenAI-compatible endpoint
(vLLM, llama.cpp, Ollama). Set `TEXT_PROVIDER=local`, `LOCAL_MODEL_BASE_URL`, `LOCAL_MODEL_NAME`. Check each model's licence first.

Every adapter: reads secrets from the environment, applies a timeout and bounded retries, handles 429/5xx, validates the
reply shape, and writes **metadata only** (service, model, latency, sizes, error code) to `AIRequestLog`.
Prompts, answers, audio and API keys are never logged.

## 4. Project layout

```
Education/
├── manage.py  requirements.txt  .env.example  run_dev.sh  run_dev.bat
├── deploy/                 gunicorn.conf.py, learnmate.service, nginx.conf
├── myproject/              settings.py, urls.py, wsgi.py
└── myapp/                  (single app, as requested; grouped by feature inside)
    ├── models.py           all 25 models: Profile, Subject, Course, Enrollment, Topic, LearningMaterial, Assignment,
    │                       Conversation, Message, SavedNote, UploadedImage, ExtractedContent, Quiz, Question,
    │                       QuizAttempt, QuizAnswer, StudyPlan, StudyTask, LearningActivity, GeneratedVisual,
    │                       Notification, AIRequestLog ...
    ├── services/           adapters.py (Muse* + SAM31 + local), base.py (HTTP/retry/logging), quiz.py, planner.py,
    │                       analytics.py, safety.py (prompt-injection + upload checks), ratelimit.py, access.py
    ├── views/              core, tutor (DRF API), textbook, voice, visuals, quizzes, planner, courses (student+teacher),
    │                       admin_panel, dashboards
    ├── templates/myapp/    base shell + one template per page
    ├── static/myapp/       css/app.css (design system), js/app.js
    ├── management/commands seed_demo, purge_old_data, send_reminders
    └── tests/              69 tests
```

The brief listed eleven module names (accounts, quizzes, ai_tutor ...). Because you asked for one app called `myapp`,
those modules live as files and folders inside it instead. Splitting them into separate Django apps later is mechanical.

## 5. Security and privacy summary

- Roles (student / teacher / admin) enforced on every view and API via `services/access.py`; students only reach their own
  records; teachers only reach classes they own. Teachers see quiz results and plan progress, never AI chats or notes.
- CSRF on all forms and APIs (session auth), secure cookie and HTTPS settings when `DJANGO_DEBUG=False`.
- Uploads: size limits, real image decoding (not just extension), audio type allow-list, material extension allow-list.
- Audio is held in memory for transcription and never written to disk or the database.
- Uploaded files are not served from a public media path. They go through `/media-private/<kind>/<id>/` with ownership checks.
- Quiz scores are computed on the server. Correct answers and explanations are not sent to the browser during a quiz.
- Prompt-injection defence: uploaded text and image-extracted text are fenced in `<untrusted_material>` tags, the system prompt
  says to treat them as data, and the fence cannot be closed by the content.
- AI features are opt-in per user; under-18 users also need guardian consent (Profile page).
- Rate limits per user per hour for each expensive operation (`RATE_*` in `.env`). Uses the cache, so use Redis
  (`REDIS_URL`) when running several Gunicorn workers for exact shared limits.
- Retention: `python manage.py purge_old_data` removes old AI logs and read notifications.
- Admin pages never show keys; the Configuration page only says Configured / Not configured.

## 6. Tests

```bash
python manage.py test myapp
```

Covers registration and login, role permissions, data isolation, CSRF, upload validation, adapter success, timeout, retry,
429, bad response and missing credentials (with mocked HTTP), tutor and quiz flows, server-side scoring, cheating attempts,
timer, study-plan create/edit/reschedule, analytics, rate limiting, and the management commands.
Responsive layout was built with Bootstrap breakpoints but is **not covered by automated tests**: check it in a browser.

## 7. Production deployment (Ubuntu, Gunicorn, Nginx, PostgreSQL)

```bash
sudo apt install python3-venv nginx postgresql libpq-dev
sudo -u postgres psql -c "CREATE USER learnmate WITH PASSWORD 'change-me';"
sudo -u postgres psql -c "CREATE DATABASE learnmate OWNER learnmate;"

sudo useradd -r -m -d /srv/learnmate learnmate
# copy the project to /srv/learnmate/Education, then:
sudo -u learnmate python3 -m venv /srv/learnmate/venv
sudo -u learnmate /srv/learnmate/venv/bin/pip install -r /srv/learnmate/Education/requirements.txt
```

Create `/srv/learnmate/Education/.env` (copy `.env.example`) and set at least:

```
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<long random string>
DJANGO_ALLOWED_HOSTS=learn.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://learn.example.com
POSTGRES_DB=learnmate
POSTGRES_USER=learnmate
POSTGRES_PASSWORD=change-me
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend   # plus EMAIL_HOST etc.
```

```bash
cd /srv/learnmate/Education
sudo -u learnmate ../venv/bin/python manage.py migrate
sudo -u learnmate ../venv/bin/python manage.py collectstatic --noinput
sudo -u learnmate ../venv/bin/python manage.py createsuperuser
sudo -u learnmate ../venv/bin/python manage.py check --deploy

sudo cp deploy/learnmate.service /etc/systemd/system/
sudo systemctl enable --now learnmate

sudo cp deploy/nginx.conf /etc/nginx/sites-available/learnmate   # edit server_name
sudo ln -s /etc/nginx/sites-available/learnmate /etc/nginx/sites-enabled/
sudo certbot --nginx -d learn.example.com                         # HTTPS certificate
sudo nginx -t && sudo systemctl reload nginx
```

Cron (as the `learnmate` user):

```
0 7 * * *  cd /srv/learnmate/Education && ../venv/bin/python manage.py send_reminders
30 3 * * * cd /srv/learnmate/Education && ../venv/bin/python manage.py purge_old_data
```

Do not run `seed_demo` in production. Back up the database and `media/` regularly.

## 8. Design notes

The interface follows the two references you gave (Taste Skill and Impeccable): one clear action per area, flat panels
with hairline dividers instead of cards inside cards, a single key-figure strip instead of four identical stat cards,
no side-stripe borders, no gradient washes, no icon tiles, sentence-case plain labels, visible form labels, and empty states
that tell the person what to do next. Colors and the Inter font follow your brief (indigo `#4338CA`, teal `#0D9488`).
Teal is used only for progress and success.

## 9. Known limits

- Meta model schemas are placeholders until you align them with the official docs (section 3).
- Textbook OCR relies on the image-reading model; SAM only segments regions.
- Quiz and tutor quality depends on the model you connect; AI content is labelled as AI-generated in the interface.
- Short-answer grading is exact match after lowercasing and removing punctuation, so spelling variants count as wrong.
- Tamil answers depend on the connected model's Tamil ability; the UI font supports Tamil.
- Teacher self-signup is off by default (`TEACHER_SELF_SIGNUP=False`); admins assign the teacher role.

# LearnMateAi
88acbd55a6460268e1f1ad23f521d75d76db6fa4
