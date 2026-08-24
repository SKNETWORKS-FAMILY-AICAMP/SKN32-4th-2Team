from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chat, Chatroom, User

DEFAULT_TREND_DAYS = 14
STATS_WINDOW_DAYS = 14
FAQ_TOP_N = 10
CATEGORY_OTHER = "기타"


def _window_start(days: int = STATS_WINDOW_DAYS) -> datetime:
    start_date = date.today() - timedelta(days=days - 1)
    return datetime.combine(start_date, time.min)


def get_category_ratio(db: Session) -> list[dict]:
    stmt = select(Chat.topic).where(Chat.speaker == "user", Chat.created_at >= _window_start())
    topics = db.scalars(stmt).all()

    counter = Counter(topic or CATEGORY_OTHER for topic in topics)
    total = sum(counter.values()) or 1

    return [
        {
            "category": category,
            "count": count,
            "percent": round(count / total * 100, 1),
        }
        for category, count in counter.most_common()
    ]


def get_user_question_summary(db: Session) -> dict:
    stmt = (
        select(User.name, Chat.chat_id)
        .select_from(User)
        .join(Chatroom, Chatroom.user_id == User.user_id)
        .join(Chat, Chat.chatroom_id == Chatroom.chatroom_id)
        .where(Chat.speaker == "user", Chat.created_at >= _window_start())
    )
    rows = db.execute(stmt).all()

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


def get_daily_trend(db: Session, days: int = DEFAULT_TREND_DAYS) -> list[dict]:
    start_date = date.today() - timedelta(days=days - 1)

    stmt = select(Chat.created_at).where(Chat.speaker == "user", Chat.created_at >= _window_start(days))
    rows = db.scalars(stmt).all()

    counter = Counter(created_at.date() for created_at in rows if created_at)

    return [
        {
            "date": (start_date + timedelta(days=i)).strftime("%m-%d"),
            "count": counter.get(start_date + timedelta(days=i), 0),
        }
        for i in range(days)
    ]


def get_faq_top10(db: Session) -> list[dict]:
    stmt = select(Chat.message, Chat.topic).where(Chat.speaker == "user", Chat.created_at >= _window_start())
    rows = db.execute(stmt).all()

    counter: Counter = Counter()
    topic_by_message: dict[str, str] = {}

    for message, topic in rows:
        key = message.strip()
        if not key:
            continue
        counter[key] += 1
        topic_by_message.setdefault(key, topic or CATEGORY_OTHER)

    return [
        {
            "rank": i + 1,
            "message": message,
            "category": topic_by_message.get(message, CATEGORY_OTHER),
            "count": count,
        }
        for i, (message, count) in enumerate(counter.most_common(FAQ_TOP_N))
    ]
