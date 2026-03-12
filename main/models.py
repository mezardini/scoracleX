from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.auth.hashers import make_password


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email,  password, **extra_fields):

        values = [email, ]
        field_value_map = dict(zip(self.model.REQUIRED_FIELDS, values))

        for field_name, value in field_value_map.items():
            if not value:
                raise ValueError('The {} value must be set'.format(field_name))

        email = self.normalize_email(email)

        user = self.model(
            email=email,

            **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_user(self, email,  password, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email,  password, **extra_fields)

    def create_superuser(self, email,  password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email,  password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(max_length=255, unique=True)
    credit = models.IntegerField(default=3, null=True)
    username = models.CharField(max_length=50, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'
    # REQUIRED_FIELDS = ['username']

    objects = UserManager()

    def __str__(self):
        return f'{self.email}'

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
    fixture_id = models.CharField(max_length=40, unique=True, primary_key=True)

    def __str__(self):
        return f"{self.home_team} {self.home_team_score} vs {self.away_team_score} {self.away_team} on {self.date.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        indexes = [
            models.Index(fields=['home_team', 'away_team', 'league']),
        ]
