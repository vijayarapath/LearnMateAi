"""Shared HTTP plumbing for every Meta model adapter.

IMPORTANT: Meta's endpoint paths and request schemas are NOT hard-coded as facts here.
Base URL, model names and paths come from environment variables. Each adapter's
`build_*` / `parse_*` method holds the request and response mapping in ONE place so you
can align it with the official documentation for your account.
"""
import logging
import time

import requests
from django.conf import settings

from myapp.models import AIRequestLog
from .errors import AIBadResponse, AINotConfigured, AIRateLimited, AITimeout, AIError

log = logging.getLogger("myapp.ai")


class BaseAdapter:
    service_name = "base"
    config_key = "spark"
    label = "This AI feature"

    # ---- config
    @property
    def cfg(self):
        return settings.META_AI

    @property
    def model_cfg(self):
        return self.cfg["MODELS"].get(self.config_key, {})

    @property
    def model_name(self):
        return self.model_cfg.get("model", "")

    def is_configured(self):
        return bool(self.cfg["BASE_URL"] and self.cfg["API_KEY"] and self.model_cfg.get("model") and self.model_cfg.get("path"))

    def require_configured(self):
        if not self.is_configured():
            raise AINotConfigured(self.label)

    # ---- transport
    def _url(self):
        return self.cfg["BASE_URL"].rstrip("/") + "/" + self.model_cfg["path"].lstrip("/")

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg['API_KEY']}"}

    def _post(self, user=None, input_chars=0, **kwargs):
        """POST with timeout, bounded retries and metadata-only logging. Returns parsed JSON."""
        self.require_configured()
        started = time.monotonic()
        attempts = max(1, int(self.cfg["MAX_RETRIES"]) + 1)
        last_error = None
        for attempt in range(attempts):
            try:
                resp = requests.post(self._url(), headers=self._headers(), timeout=self.cfg["TIMEOUT"], **kwargs)
                if resp.status_code == 429:
                    wait = _retry_after(resp)
                    last_error = AIRateLimited("The AI service is busy right now. Wait a moment and try again.")
                    if attempt < attempts - 1 and wait <= 5:
                        time.sleep(wait)
                        continue
                    raise last_error
                if resp.status_code in (401, 403):
                    raise AIError("The AI provider rejected the credentials. Ask an administrator to check the API key.", code="auth_failed")
                if resp.status_code >= 500:
                    last_error = AIBadResponse("The AI service had a problem. Try again in a moment.")
                    if attempt < attempts - 1:
                        time.sleep(0.5 * (2 ** attempt))
                        continue
                    raise last_error
                if resp.status_code >= 400:
                    try:
                        err_data = resp.json()
                        err_detail = err_data.get("error", {}).get("message") or str(err_data)
                    except Exception:
                        err_detail = resp.text
                    log.error("AI HTTP %s error: %s", resp.status_code, err_detail)
                    msg = f"The AI service did not accept this request: {err_detail[:120]}" if err_detail else "The AI service did not accept this request."
                    raise AIError(msg, code=f"http_{resp.status_code}")
                try:
                    data = resp.json()
                except ValueError:
                    raise AIBadResponse("The AI service returned an unreadable response.")
                self._log(user, True, started, input_chars, 0)
                return data
            except requests.Timeout:
                last_error = AITimeout("The AI service took too long to answer. Try again.")
                if attempt < attempts - 1:
                    continue
            except requests.ConnectionError:
                last_error = AIError("Could not reach the AI service. Check the connection and try again.", code="connection", retryable=True)
                if attempt < attempts - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
            except AIError as exc:
                self._log(user, False, started, input_chars, 0, exc.code)
                raise
        err = last_error or AIError()
        self._log(user, False, started, input_chars, 0, err.code)
        raise err

    def _log(self, user, ok, started, in_chars, out_chars, code=""):
        latency = int((time.monotonic() - started) * 1000)
        log.info("ai_request service=%s ok=%s code=%s latency_ms=%s", self.service_name, ok, code, latency)
        try:
            AIRequestLog.objects.create(
                user=user if getattr(user, "pk", None) else None, service=self.service_name,
                model_name=self.model_name[:80], ok=ok, error_code=code, latency_ms=latency,
                input_chars=in_chars, output_chars=out_chars,
            )
        except Exception:  # logging must never break a request
            log.exception("could not write AIRequestLog")

    def record_output(self, user, out_chars):
        """Adapters call this after parsing so usage stats include output size."""
        latest = AIRequestLog.objects.filter(service=self.service_name, user=user if getattr(user, "pk", None) else None).first()
        if latest and not latest.output_chars:
            latest.output_chars = out_chars
            latest.save(update_fields=["output_chars"])


def _retry_after(resp):
    try:
        return float(resp.headers.get("Retry-After", "1"))
    except ValueError:
        return 1.0
