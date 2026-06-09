import random
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from ..models import EmailVerificationCode, PasswordResetCode


class EmailService:
    """Handle account-related email code creation and delivery.

    This service keeps email-specific behavior out of views.py so the view layer
    can focus on HTTP request/response handling.
    """

    VERIFICATION_CODE_EXPIRE_MINUTES = 15
    PASSWORD_RESET_EXPIRE_MINUTES = 15
    PASSWORD_RESET_TOKEN_BYTES = 48

    def create_verification_code(self, user):
        """Create and email a 6-digit verification code for a newly registered user."""
        code = self._generate_numeric_code()
        verification = EmailVerificationCode.objects.create(
            user=user,
            email=user.email,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=self.VERIFICATION_CODE_EXPIRE_MINUTES),
        )
        self._send_verification_code_email(user.email, code)
        return verification

    def create_password_reset_code(self, user):
        """Create and email a one-time password reset token for an active user."""
        token = self._generate_reset_token()
        reset_link = self._build_password_reset_link(user.email, token)

        # Preserve the original behavior: email is attempted before old reset
        # tokens are cleared and the new token is stored.
        self._send_password_reset_email(user.email, reset_link)

        PasswordResetCode.objects.filter(
            user=user,
            used_at__isnull=True,
        ).delete()
        reset_code = PasswordResetCode.objects.create(
            user=user,
            email=user.email,
            token=token,
            expires_at=timezone.now() + timedelta(minutes=self.PASSWORD_RESET_EXPIRE_MINUTES),
        )
        return reset_code

    def _generate_numeric_code(self):
        return f'{random.SystemRandom().randint(0, 999999):06d}'

    def _generate_reset_token(self):
        return secrets.token_urlsafe(self.PASSWORD_RESET_TOKEN_BYTES)

    def _build_password_reset_link(self, email, token):
        query_string = urlencode({
            'reset_email': email,
            'reset_token': token,
        })
        frontend_base_url = settings.FRONTEND_BASE_URL.rstrip('/')
        return f'{frontend_base_url}/auth?{query_string}'

    def _send_verification_code_email(self, email, code):
        send_mail(
            subject='Email verification code',
            message=f'Your verification code is {code}. It expires in 15 minutes.',
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )

    def _send_password_reset_email(self, email, reset_link):
        send_mail(
            subject='Password reset link',
            message=(
                'Use this link to reset your password. '
                'It expires in 15 minutes and can only be used once.\n\n'
                f'{reset_link}'
            ),
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )
