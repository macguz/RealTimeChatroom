from django.urls import path
from friend.views import (
    send_friend_request,
    friend_requests_view,
    accept_friend_request,
    remove_friend,
)

app_name = "friend"

urlpatterns = [
    path('friend_request/', send_friend_request, name="friend-request"),
    path('friend_request/<user_id>/', friend_requests_view, name="friend-requests"),
    path('friend_request_accept/<friend_request_id>/', accept_friend_request, name="friend-request-accept"),
    path('friend_remove/', remove_friend, name="remove-friend"),
]