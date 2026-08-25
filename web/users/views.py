import time
import re
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from .models import User, UserLoginHistory
from .forms import LoginForm, SignupForm, UserCreateForm, UserUpdateForm

USER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{4,20}$')


def post_login_redirect_url(is_admin):
    """로그인 직후(또는 이미 로그인된 상태로 /login에 온 경우) 보낼 목적지.
    관리자는 챗봇을 쓰지 않으므로 통계 화면으로, 일반 유저는 채팅 화면으로 보낸다."""
    return '/admin/stats' if is_admin else '/chat'


def login_page(request):
    user = request.user if request.user.is_authenticated else None
    if user:
        return redirect(post_login_redirect_url(user.is_admin))
    
    error = request.GET.get('expired') and '세션이 만료되었습니다. 다시 로그인해주세요.' or None
    return render(request, 'login.html', {'error': error})


@require_http_methods(["POST"])
def login_submit(request):
    form = LoginForm(request.POST)
    if not form.is_valid():
        return render(request, 'login.html', {'error': '아이디 또는 비밀번호가 올바르지 않습니다.'})
    
    username = form.cleaned_data['user_id']  # form field is still user_id for compatibility
    passwd = form.cleaned_data['passwd']
    
    try:
        user = User.objects.get(username=username, is_deleted=False)
    except User.DoesNotExist:
        return render(request, 'login.html', {'error': '아이디 또는 비밀번호가 올바르지 않습니다.'})
    
    if user.is_disabled:
        return render(request, 'login.html', {'error': '비활성화된 계정입니다. 관리자에게 문의하세요.'})
    
    if not user.check_password(passwd):
        return render(request, 'login.html', {'error': '아이디 또는 비밀번호가 올바르지 않습니다.'})
    
    # Login the user
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)
    
    # Record login history
    UserLoginHistory.objects.create(user=user)
    
    return redirect(post_login_redirect_url(user.is_admin))


@require_http_methods(["GET"])
def check_user_id(request):
    user_id = request.GET.get('user_id', '')
    if not USER_ID_PATTERN.match(user_id):
        return JsonResponse({'available': False, 'detail': '아이디는 영문/숫자 4~20자로 입력해주세요.'}, status=400)
    
    exists = User.objects.filter(username=user_id, is_deleted=False).exists()
    if exists:
        return JsonResponse({'available': False, 'detail': '이미 사용 중인 아이디입니다.'})
    
    return JsonResponse({'available': True, 'detail': '사용 가능한 아이디입니다.'})


@require_http_methods(["POST"])
def signup_submit(request):
    form = SignupForm(request.POST)
    if not form.is_valid():
        errors = form.errors.get_json_data()
        first_error = list(errors.values())[0][0]['message'] if errors else '회원가입에 실패했습니다.'
        return JsonResponse({'detail': first_error}, status=400)
    
    user = User.objects.create_user(
        username=form.cleaned_data['user_id'],  # form field is still user_id for compatibility
        password=form.cleaned_data['passwd'],
        name=form.cleaned_data['name'],
        department=form.cleaned_data['department'],
        is_admin=False,
        is_disabled=False,
    )
    
    return JsonResponse({'detail': '회원가입이 완료되었습니다. 로그인해주세요.'}, status=201)


@require_http_methods(["POST"])
def logout_submit(request):
    logout(request)
    return redirect('/login')
