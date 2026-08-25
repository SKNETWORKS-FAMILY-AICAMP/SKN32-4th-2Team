from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
import bcrypt


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username field must be set')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_admin', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=20, primary_key=True, db_column='user_id')
    name = models.CharField(max_length=50, null=False)
    department = models.CharField(max_length=100, null=False)
    is_admin = models.BooleanField(default=False, null=False)
    is_disabled = models.BooleanField(default=False, null=False)
    is_deleted = models.BooleanField(default=False, null=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=False)
    updated_at = models.DateTimeField(auto_now=True, null=False)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['name', 'department']

    class Meta:
        db_table = 'user'

    def set_password(self, raw_password):
        """Override to use bcrypt instead of Django's default"""
        self.password = bcrypt.hashpw(raw_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, raw_password):
        """Override to use bcrypt instead of Django's default"""
        return bcrypt.checkpw(raw_password.encode('utf-8'), self.password.encode('utf-8'))

    @property
    def is_staff(self):
        return self.is_admin

    @property
    def is_active(self):
        return not self.is_disabled and not self.is_deleted


class UserLoginHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id')
    created_at = models.DateTimeField(auto_now_add=True, null=False)

    class Meta:
        db_table = 'user_login_history'
