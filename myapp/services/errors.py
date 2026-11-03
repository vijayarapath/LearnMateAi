class AIError(Exception):
    """Base class for AI integration errors. `message` is safe to show to users."""
    code = "ai_error"
    retryable = False

    def __init__(self, message="The AI service could not complete this request.", code=None, retryable=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class AINotConfigured(AIError):
    code = "not_configured"

    def __init__(self, what="This AI feature"):
        super().__init__(f"{what} is not configured yet. Ask an administrator to add the model credentials in the .env file.")


class AIRateLimited(AIError):
    code = "rate_limited"
    retryable = True


class AITimeout(AIError):
    code = "timeout"
    retryable = True


class AIBadResponse(AIError):
    code = "bad_response"
    retryable = True


class ConsentRequired(AIError):
    code = "consent_required"

    def __init__(self):
        super().__init__("Turn on AI features in your profile before using this tool. Minors also need guardian consent.")
