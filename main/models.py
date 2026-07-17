from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The email value must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(max_length=255, unique=True)
    username = models.CharField(max_length=50, blank=True, null=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    credit = models.IntegerField(default=3, null=True)
    auth_provider = models.CharField(max_length=50, default='email')
    google_id = models.CharField(
        max_length=255, blank=True, null=True, unique=True)
    avatar_url = models.URLField(blank=True)
    email_verified = models.BooleanField(default=False)
    signup_ip = models.GenericIPAddressField(blank=True, null=True)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return f'{self.email}'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

# Create your models here.


class Fixture(models.Model):
    home_team = models.CharField(max_length=100)
    home_team_score = models.IntegerField()
    away_team = models.CharField(max_length=100)
    away_team_score = models.IntegerField()
    league = models.CharField(max_length=100)
    date = models.DateTimeField()
    predicted_scorelines = models.TextField()
    over_3_goals_probability = models.FloatField()
    over_2_goals_probability = models.FloatField()
    home_win_probability = models.FloatField(null=True, blank=True)
    away_win_probability = models.FloatField(null=True, blank=True)
    draw_probability = models.FloatField(null=True, blank=True)
    fixture_id = models.CharField(max_length=40, unique=True, primary_key=True)

    def __str__(self):
        return f"{self.home_team} {self.home_team_score} vs {self.away_team_score} {self.away_team} on {self.date.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        indexes = [
            models.Index(fields=['home_team', 'away_team', 'league']),
        ]
