from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PlayerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='player_profile',
    )
    nickname = models.CharField(max_length=50)
    total_score = models.IntegerField(default=0)
    win_rate = models.FloatField(default=0.0)

    class Meta:
        db_table = 'player_profile'

    def __str__(self):
        return self.nickname


class Room(models.Model):
    class Status(models.IntegerChoices):
        WAITING = 0, 'Waiting'
        PLAYING = 1, 'Playing'
        FULL = 2, 'Full'

    room_id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=6, unique=True)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hosted_rooms',
    )
    status = models.IntegerField(choices=Status.choices, default=Status.WAITING)
    is_public = models.BooleanField(default=False)
    last_visibility_changed_at = models.DateTimeField(null=True, blank=True)
    room_password = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'room'

    def __str__(self):
        return f'Room {self.code}'


class RoomMember(models.Model):
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='members',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='room_memberships',
        null=True,
        blank=True,
    )
    is_ai = models.BooleanField(default=False)
    ai_name = models.CharField(max_length=50, blank=True)
    is_ready = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'room_member'
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'user'],
                name='unique_room_member',
            ),
        ]
        ordering = ['joined_at', 'id']

    def __str__(self):
        return f'{self.user or self.ai_name} in {self.room}'


class MatchmakingTicket(models.Model):
    class Status(models.IntegerChoices):
        WAITING = 0, 'Waiting'
        MATCHED = 1, 'Matched'
        CANCELLED = 2, 'Cancelled'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='matchmaking_ticket',
    )
    score = models.IntegerField(default=0)
    status = models.IntegerField(choices=Status.choices, default=Status.WAITING)
    matched_room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        related_name='matchmaking_tickets',
        null=True,
        blank=True,
    )
    source_room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='source_matchmaking_tickets',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'matchmaking_ticket'
        indexes = [
            models.Index(fields=['status', 'score', 'created_at']),
            models.Index(fields=['status', 'source_room', 'created_at']),
        ]

    def __str__(self):
        return f'{self.user} matchmaking ({self.get_status_display()})'


class MatchRecord(models.Model):
    match_id = models.BigAutoField(primary_key=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'match_record'

    def __str__(self):
        return f'Match {self.match_id}'


class MatchParticipant(models.Model):
    match = models.ForeignKey(
        MatchRecord,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='match_participations',
    )
    player_rank = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
    )
    score_change = models.IntegerField(default=0)

    class Meta:
        db_table = 'match_participant'
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'user'],
                name='unique_match_participant',
            ),
            models.UniqueConstraint(
                fields=['match', 'player_rank'],
                name='unique_match_player_rank',
            ),
        ]

    def __str__(self):
        return f'{self.user} in {self.match}'


class EmailVerificationCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='email_verification_codes',
    )
    email = models.EmailField()
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'email_verification_code'
        indexes = [
            models.Index(fields=['email', 'code']),
        ]

    @property
    def is_verified(self):
        return self.verified_at is not None

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f'{self.email} ({self.code})'


class PasswordResetCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='password_reset_codes',
    )
    email = models.EmailField()
    token = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'password_reset_code'
        indexes = [
            models.Index(fields=['email', 'token']),
        ]

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return self.email
