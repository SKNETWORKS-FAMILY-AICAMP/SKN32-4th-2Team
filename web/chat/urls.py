from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_page, name='chat_page'),
    path('<str:chatroom_id>', views.chat_page, name='chat_page_with_id'),
    path('api/rooms', views.list_rooms_api, name='list_rooms_api'),
    path('api/rooms/create', views.create_room_api, name='create_room_api'),
    path('api/rooms/<str:chatroom_id>/messages', views.get_messages_api, name='get_messages_api'),
    path('api/rooms/<str:chatroom_id>/messages/send', views.send_message_api, name='send_message_api'),
    path('api/rooms/<str:chatroom_id>/delete', views.delete_room_api, name='delete_room_api'),
]
