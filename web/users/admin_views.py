from django.shortcuts import render
from django.http import JsonResponse, QueryDict
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from .models import User, UserLoginHistory
from .forms import UserCreateForm, UserUpdateForm
import bcrypt


def is_admin(user):
    return user.is_authenticated and user.is_admin


@login_required
@user_passes_test(is_admin, login_url='/login')
def users_page(request):
    return render(request, 'admin/users.html', {'user': request.user, 'active': 'admin_users'})


@login_required
@user_passes_test(is_admin, login_url='/login')
@require_http_methods(["GET"])
def list_users_api(request):
    name = request.GET.get('name')
    department = request.GET.get('department')
    is_disabled = request.GET.get('is_disabled')
    is_admin = request.GET.get('is_admin')
    page = int(request.GET.get('page', 1))
    size = int(request.GET.get('size', 20))
    
    page = max(page, 1)
    size = min(max(size, 1), 100)
    
    queryset = User.objects.filter(is_deleted=False)
    
    if name:
        queryset = queryset.filter(name__icontains=name)
    
    if department:
        queryset = queryset.filter(department=department)
    
    if is_disabled is not None:
        queryset = queryset.filter(is_disabled=is_disabled == 'true')
    
    if is_admin is not None:
        queryset = queryset.filter(is_admin=is_admin == 'true')
    
    total = queryset.count()
    users = queryset.order_by('-created_at')[(page - 1) * size:page * size]
    
    return JsonResponse({
        'items': [
            {
                'id': user.username,  # Changed from user_id to username
                'name': user.name,
                'department': user.department,
                'is_disabled': user.is_disabled,
                'is_admin': user.is_admin,
                'created_at': user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else '',
            }
            for user in users
        ],
        'page': page,
        'size': size,
        'total': total,
        'total_pages': (total + size - 1) // size if total else 1,
    })


@login_required
@user_passes_test(is_admin, login_url='/login')
@require_http_methods(["POST"])
def create_user_api(request):
    form = UserCreateForm(request.POST)
    if not form.is_valid():
        errors = form.errors.get_json_data()
        first_error = list(errors.values())[0][0]['message'] if errors else '사용자 추가에 실패했습니다.'
        return JsonResponse({'detail': first_error}, status=400)
    
    user = User.objects.create_user(
        username=form.cleaned_data['user_id'],  # form field is still user_id for compatibility
        password=form.cleaned_data['passwd'],
        name=form.cleaned_data['name'],
        department=form.cleaned_data['department'],
        is_admin=form.cleaned_data.get('is_admin', False),
        is_disabled=form.cleaned_data.get('is_disabled', False),
    )
    
    return JsonResponse({'detail': '사용자가 추가되었습니다.'}, status=201)


@login_required
@user_passes_test(is_admin, login_url='/login')
@require_http_methods(["PATCH"])
def update_user_api(request, user_id):
    # Django는 PATCH 본문을 request.POST로 파싱하지 않는다. 프론트가 보내는
    # application/x-www-form-urlencoded 본문을 명시적으로 읽어야 한다.
    data = QueryDict(request.body, encoding=request.encoding or "utf-8")

    if user_id == request.user.username:
        is_admin = data.get('is_admin')
        is_disabled = data.get('is_disabled')
        if is_admin == 'false' or is_disabled == 'true':
            return JsonResponse({'detail': '본인 계정의 관리자 권한은 해제할 수 없습니다.' if is_admin == 'false' else '본인 계정은 비활성화할 수 없습니다.'}, status=400)
    
    try:
        user = User.objects.get(username=user_id, is_deleted=False)
    except User.DoesNotExist:
        return JsonResponse({'detail': '사용자를 찾을 수 없습니다.'}, status=404)
    
    form = UserUpdateForm(data)
    if not form.is_valid():
        errors = form.errors.get_json_data()
        first_error = list(errors.values())[0][0]['message'] if errors else '수정에 실패했습니다.'
        return JsonResponse({'detail': first_error}, status=400)
    
    if form.cleaned_data.get('name'):
        user.name = form.cleaned_data['name']
    
    if form.cleaned_data.get('department'):
        user.department = form.cleaned_data['department']
    
    if form.cleaned_data.get('passwd'):
        user.set_password(form.cleaned_data['passwd'])
    
    if 'is_admin' in data:
        user.is_admin = form.cleaned_data['is_admin']
    
    if 'is_disabled' in data:
        user.is_disabled = form.cleaned_data['is_disabled']
    
    user.save()
    
    return JsonResponse({'detail': '수정되었습니다.'}, status=200)


@login_required
@user_passes_test(is_admin, login_url='/login')
@require_http_methods(["DELETE"])
def delete_user_api(request, user_id):
    if user_id == request.user.username:
        return JsonResponse({'detail': '본인 계정은 삭제할 수 없습니다.'}, status=400)
    
    try:
        user = User.objects.get(username=user_id, is_deleted=False)
    except User.DoesNotExist:
        return JsonResponse({'detail': '사용자를 찾을 수 없습니다.'}, status=404)
    
    from django.utils import timezone
    user.is_deleted = True
    user.deleted_at = timezone.now()
    user.save()
    
    return JsonResponse({'detail': '계정이 삭제되었습니다.'}, status=200)
