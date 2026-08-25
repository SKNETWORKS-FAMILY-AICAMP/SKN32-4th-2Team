from django import forms
from django.core.exceptions import ValidationError
import re
from .models import User

USER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{4,20}$')


class LoginForm(forms.Form):
    user_id = forms.CharField(max_length=20, label='아이디')
    passwd = forms.CharField(widget=forms.PasswordInput, label='비밀번호')


class SignupForm(forms.Form):
    user_id = forms.CharField(max_length=20, label='아이디')
    passwd = forms.CharField(widget=forms.PasswordInput, label='비밀번호')
    passwd_confirm = forms.CharField(widget=forms.PasswordInput, label='비밀번호 확인')
    name = forms.CharField(max_length=50, label='이름')
    department = forms.CharField(max_length=100, label='부서')

    def clean_user_id(self):
        user_id = self.cleaned_data.get('user_id')
        if not USER_ID_PATTERN.match(user_id):
            raise ValidationError('아이디는 영문/숫자 4~20자로 입력해주세요.')
        if User.objects.filter(username=user_id, is_deleted=False).exists():
            raise ValidationError('이미 사용 중인 아이디입니다.')
        return user_id

    def clean_passwd(self):
        passwd = self.cleaned_data.get('passwd')
        if len(passwd) < 8:
            raise ValidationError('비밀번호는 8자 이상이어야 합니다.')
        return passwd

    def clean(self):
        cleaned_data = super().clean()
        passwd = cleaned_data.get('passwd')
        passwd_confirm = cleaned_data.get('passwd_confirm')
        if passwd and passwd_confirm and passwd != passwd_confirm:
            raise ValidationError('비밀번호가 일치하지 않습니다.')
        return cleaned_data


class UserCreateForm(forms.Form):
    user_id = forms.CharField(max_length=20, label='아이디')
    passwd = forms.CharField(widget=forms.PasswordInput, label='비밀번호')
    passwd_confirm = forms.CharField(widget=forms.PasswordInput, label='비밀번호 확인')
    name = forms.CharField(max_length=50, label='이름')
    department = forms.CharField(max_length=100, label='부서')
    is_admin = forms.BooleanField(required=False, label='관리자 권한')
    is_disabled = forms.BooleanField(required=False, label='비활성화')

    def clean_user_id(self):
        user_id = self.cleaned_data.get('user_id')
        if not USER_ID_PATTERN.match(user_id):
            raise ValidationError('아이디는 영문/숫자 4~20자로 입력해주세요.')
        if User.objects.filter(username=user_id, is_deleted=False).exists():
            raise ValidationError('이미 사용 중인 아이디입니다.')
        return user_id

    def clean_passwd(self):
        passwd = self.cleaned_data.get('passwd')
        if len(passwd) < 8:
            raise ValidationError('비밀번호는 8자 이상이어야 합니다.')
        return passwd

    def clean(self):
        cleaned_data = super().clean()
        passwd = cleaned_data.get('passwd')
        passwd_confirm = cleaned_data.get('passwd_confirm')
        if passwd and passwd_confirm and passwd != passwd_confirm:
            raise ValidationError('비밀번호가 일치하지 않습니다.')
        return cleaned_data


class UserUpdateForm(forms.Form):
    name = forms.CharField(max_length=50, required=False, label='이름')
    department = forms.CharField(max_length=100, required=False, label='부서')
    passwd = forms.CharField(widget=forms.PasswordInput, required=False, label='비밀번호')
    is_admin = forms.BooleanField(required=False, label='관리자 권한')
    is_disabled = forms.BooleanField(required=False, label='비활성화')

    def clean_passwd(self):
        passwd = self.cleaned_data.get('passwd')
        if passwd and len(passwd) < 8:
            raise ValidationError('비밀번호는 8자 이상이어야 합니다.')
        return passwd
