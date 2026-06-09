from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from ..models import EmailVerificationCode, PasswordResetCode, PlayerProfile
from .email_service import EmailService
from .exceptions import ServiceError

User = get_user_model()


class AuthService:
    """Encapsulate account authentication workflows.

    Views should only translate HTTP requests/responses. This service owns the
    business rules for registration, email verification, login, logout, and
    password reset.
    """

    MIN_PASSWORD_LENGTH = 8

    def __init__(self, email_service=None):
        self.email_service = email_service or EmailService()

    def register(self, data):
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        password_confirm = str(data.get('password_confirm', ''))
        email = str(data.get('email', '')).strip().lower()
        nickname = str(data.get('nickname', '')).strip() or username

        self._validate_registration_input(username, password, password_confirm, email)
        self._ensure_unique_account(username, email)

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_active=False,
            )
            PlayerProfile.objects.create(user=user, nickname=nickname)
            self.email_service.create_verification_code(user)

        return user

    def verify_email(self, data):
        email = str(data.get('email', '')).strip().lower()
        code = str(data.get('code', '')).strip()
        if not email or not code:
            raise ServiceError('email and code are required.')

        verification = (
            EmailVerificationCode.objects
            .select_related('user')
            .filter(email__iexact=email, code=code, verified_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        if verification is None:
            raise ServiceError('verification code is invalid.', status=404, code='invalid_code')
        if verification.is_expired:
            raise ServiceError('verification code is expired.', code='expired_code')

        user = verification.user
        user.email = verification.email
        user.is_active = True
        verification.verified_at = timezone.now()

        with transaction.atomic():
            user.save(update_fields=['email', 'is_active'])
            verification.save(update_fields=['verified_at'])

        return user

    def resend_verification(self, data):
        email = str(data.get('email', '')).strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is None:
            raise ServiceError('pending user not found.', status=404, code='pending_user_not_found')

        self.email_service.create_verification_code(user)
        return user

    def request_password_reset(self, data):
        email = str(data.get('email', '')).strip().lower()
        if not email:
            raise ServiceError('email is required.')

        self._validate_email_format(email)

        # Preserve the original security behavior: do not reveal whether the
        # address exists. Only send a reset email when a verified account exists.
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            self.email_service.create_password_reset_code(user)
        return user

    def reset_password(self, data):
        email = str(data.get('email', '')).strip().lower()
        token = str(data.get('token', '')).strip()
        new_password = str(data.get('new_password', ''))
        new_password_confirm = str(data.get('new_password_confirm', ''))

        if not email or not token or not new_password or not new_password_confirm:
            raise ServiceError('email, token, new_password, and new_password_confirm are required.')
        if len(new_password) < self.MIN_PASSWORD_LENGTH:
            raise ServiceError('new_password must be at least 8 characters.')
        if new_password != new_password_confirm:
            raise ServiceError('passwords do not match.', code='password_mismatch')

        reset_code = (
            PasswordResetCode.objects
            .select_related('user')
            .filter(email__iexact=email, token=token, used_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        if reset_code is None:
            raise ServiceError('password reset link is invalid.', status=404, code='invalid_token')
        if reset_code.is_expired:
            raise ServiceError('password reset link is expired.', code='expired_token')

        user = reset_code.user
        user.set_password(new_password)
        reset_code.used_at = timezone.now()

        with transaction.atomic():
            user.save(update_fields=['password'])
            reset_code.delete()

        return user

    def login(self, request, data):
        identifier = str(data.get('username', data.get('email', ''))).strip()
        password = str(data.get('password', ''))
        if not identifier or not password:
            raise ServiceError('username/email and password are required.')

        user = User.objects.filter(email__iexact=identifier).first()
        if user is None:
            user = User.objects.filter(username=identifier).first()

        username = user.username if user else identifier
        authenticated_user = authenticate(request, username=username, password=password)
        if authenticated_user is None:
            raise ServiceError('login failed.', status=401, code='invalid_credentials')
        if not authenticated_user.is_active:
            raise ServiceError('email is not verified.', status=403, code='email_not_verified')

        login(request, authenticated_user)
        return authenticated_user

    def logout(self, request, cleanup_callback=None):
        cleaned_rooms = []
        if request.user.is_authenticated and cleanup_callback is not None:
            cleaned_rooms = cleanup_callback(request.user)
        logout(request)
        return cleaned_rooms

    def _validate_registration_input(self, username, password, password_confirm, email):
        if not username or not password or not password_confirm or not email:
            raise ServiceError('username, password, password_confirm, and email are required.')
        if len(password) < self.MIN_PASSWORD_LENGTH:
            raise ServiceError('password must be at least 8 characters.')
        if password != password_confirm:
            raise ServiceError('passwords do not match.', code='password_mismatch')
        self._validate_email_format(email)

    def _validate_email_format(self, email):
        try:
            validate_email(email)
        except ValidationError:
            raise ServiceError('email format is invalid.')

    def _ensure_unique_account(self, username, email):
        if User.objects.filter(username=username).exists():
            raise ServiceError('username already exists.', code='username_exists')
        if User.objects.filter(email__iexact=email).exists():
            raise ServiceError('email already exists.', code='email_exists')
