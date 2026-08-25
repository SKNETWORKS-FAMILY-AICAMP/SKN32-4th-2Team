from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from collections import Counter
from datetime import date, datetime, time, timedelta
from .models import User
from chat.models import Chat, Chatroom

DEFAULT_TREND_DAYS = 14
STATS_WINDOW_DAYS = 14
FAQ_TOP_N = 10
CATEGORY_OTHER = "기타"


def is_admin(user):
    return user.is_authenticated and user.is_admin


def _window_start(days=STATS_WINDOW_DAYS):
    start_date = date.today() - timedelta(days=days - 1)
    return datetime.combine(start_date, time.min)


def get_category_ratio():
    chats = Chat.objects.filter(speaker='user', created_at__gte=_window_start())
    topics = [chat.topic or CATEGORY_OTHER for chat in chats]
    
    counter = Counter(topics)
    total = sum(counter.values()) or 1
    
    return [
        {
            "category": category,
            "count": count,
            "percent": round(count / total * 100, 1),
        }
        for category, count in counter.most_common()
    ]


def get_user_question_summary():
    from django.db.models import Q
    
    chats = Chat.objects.filter(
        speaker='user', 
        created_at__gte=_window_start()
    ).select_related('chatroom__user')
    
    rows = [(chat.chatroom.user.name, chat.chat_id) for chat in chats]
    
    counter = Counter(name for name, _ in rows)
    total_questions = len(rows)
    active_users = len(counter)
    avg_per_user = round(total_questions / active_users, 1) if active_users else 0
    top_name, top_count = counter.most_common(1)[0] if counter else ("-", 0)
    
    return {
        "total_questions": total_questions,
        "active_users": active_users,
        "avg_per_user": avg_per_user,
        "top_user_name": top_name,
        "top_user_count": top_count,
    }


def get_daily_trend(days=DEFAULT_TREND_DAYS):
    start_date = date.today() - timedelta(days=days - 1)
    
    chats = Chat.objects.filter(
        speaker='user', 
        created_at__gte=_window_start(days)
    )
    
    counter = Counter(chat.created_at.date() for chat in chats if chat.created_at)
    
    return [
        {
            "date": (start_date + timedelta(days=i)).strftime("%m-%d"),
            "count": counter.get(start_date + timedelta(days=i), 0),
        }
        for i in range(days)
    ]


def get_faq_top10():
    chats = Chat.objects.filter(
        speaker='user', 
        created_at__gte=_window_start()
    )
    
    counter = Counter()
    topic_by_message = {}
    
    for chat in chats:
        key = chat.message.strip()
        if not key:
            continue
        counter[key] += 1
        topic_by_message.setdefault(key, chat.topic or CATEGORY_OTHER)
    
    return [
        {
            "rank": i + 1,
            "message": message,
            "category": topic_by_message.get(message, CATEGORY_OTHER),
            "count": count,
        }
        for i, (message, count) in enumerate(counter.most_common(FAQ_TOP_N))
    ]


@login_required
@user_passes_test(is_admin, login_url='/login')
def stats_page(request):
    return render(request, 'admin/stats.html', {'user': request.user, 'active': 'admin_stats'})


@login_required
@user_passes_test(is_admin, login_url='/login')
@require_http_methods(["GET"])
def stats_summary_api(request):
    return JsonResponse({
        "category_ratio": get_category_ratio(),
        "user_summary": get_user_question_summary(),
        "daily_trend": get_daily_trend(),
        "faq_top10": get_faq_top10(),
    })
