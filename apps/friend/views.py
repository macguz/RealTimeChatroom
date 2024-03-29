from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect

from account.models import Account
from friend.models import FriendRequest, FriendList


# 展示friend列表视图
def friend_list_view(request, *args, **kwargs):
    context = {}
    user = request.user
    if user.is_authenticated:
        # user_id是写在路由中的参数，以kwargs形式传递
        user_id = kwargs.get("user_id")
        if user_id:
            try:
                this_user = Account.objects.get(pk=user_id)
            except Account.DoesNotExist:
                return HttpResponse("That user does not exist.")
            else:
                context['this_user'] = this_user
            try:
                friend_list = FriendList.objects.get(user=this_user)
            except FriendList.DoesNotExist:
                return HttpResponse(f"Could not find a friends list for {this_user.username}")

            # 如果当前登录用户不是被查看用户，并且不是被查看用户的朋友，你没有权限观看他的好友列表
            if user != this_user and user not in friend_list.friends.all():
                return HttpResponse("You must be friends to view their friends list.")

            friends = []  # [(account1, True)..] 当前用户与被查看用户的朋友也是朋友，True
            auth_user_friend_list = FriendList.objects.get(user=user)
            for friend in friend_list.friends.all():
                friends.append((friend, auth_user_friend_list.is_mutual_friend(friend)))
            context['friends'] = friends
        else:
            return HttpResponse("You must be friends to view their friends.")
        return render(request, "friend/friend_list.html", context)


def friend_requests_view(request, *args, **kwargs):
    """ 展示他人发送的好友请求 """
    context = {}
    user = request.user
    if user.is_authenticated:
        user_id = kwargs.get("user_id")
        account = Account.objects.get(pk=user_id)
        if account == user:
            friend_requests = FriendRequest.objects.filter(receiver=account, is_active=True)
            context['friend_requests'] = friend_requests
        else:
            return HttpResponse("You can't view another user's friend requests")
    else:
        redirect("login")
    return render(request, "friend/friend_requests.html", context)


def send_friend_request(request):
    """ 使用ajax，发送好友请求 """
    user = request.user
    payload = {}
    if request.method == "POST" and user.is_authenticated:
        user_id = request.POST.get("receiver_user_id")
        if user_id:
            receiver = Account.objects.get(pk=user_id)
            try:
                # Get any friend requests (active and not-active)
                friend_requests = FriendRequest.objects.filter(sender=user, receiver=receiver)
                # find if any of them are active
                try:
                    for request in friend_requests:
                        if request.is_active:
                            raise Exception("You already sent them a friend request.")
                    # 如果没有有效的好友请求，重新创建，发送请求
                    friend_request = FriendRequest(sender=user, receiver=receiver)
                    friend_request.save()
                    payload['response'] = 'Friend request sent.'
                except Exception as e:
                    payload['response'] = str(e)
            except FriendRequest.DoesNotExist:
                #  没有好友请求，则创建
                friend_request = FriendRequest(sender=user, receiver=receiver)
                friend_request.save()
                payload['response'] = "Friend request sent."

            if payload['response'] is None:
                payload['response'] = "Something went wrong."
        else:
            payload['response'] = "Unable to sent a friend request."
    else:
        payload['response'] = "You must be authenticated to send a friend request."

    return JsonResponse(payload)


# 使用ajax，同意好友请求
def accept_friend_request(request, *args, **kwargs):
    user = request.user
    # ajax请求，让服务器返回一个字典
    payload = {}
    if request.method == "GET" and user.is_authenticated:
        friend_request_id = kwargs.get("friend_request_id")
        if friend_request_id:
            friend_request = FriendRequest.objects.get(pk=friend_request_id)
            # confirm it
            if friend_request.receiver == user:
                if friend_request:
                    friend_request.accept()
                    payload["response"] = "Friend request accepted."
                else:
                    payload["response"] = "Something went wrong."
            else:
                payload['response'] = "This is not your request to accept."
        else:
            payload['response'] = "Unable to accept that friend request."
    else:
        payload['response'] = "You must be authenticated to accept a friend request."

    return JsonResponse(payload)


# 使用ajax，删除好友
def remove_friend(request, *args, **kwargs):
    user = request.user
    payload = {}
    if request.method == "POST" and user.is_authenticated:
        user_id = request.POST.get("receiver_user_id")
        if user_id:
            try:
                removee = Account.objects.get(pk=user_id)
                # our friend_list
                friend_list = FriendList.objects.get(user=user)
                friend_list.unfriend(removee)
                payload['response'] = "Successfully removed that friend."
            except Exception as e:
                payload['response'] = f"Something went wrong: {str(e)}"
        else:
            payload['response'] = "There was an error. unable to remove that friend."
    else:
        payload['response'] = "You must be authenticated to remove a friend."

    return JsonResponse(payload)


def decline_friend_request(request, *args, **kwargs):
    """ 处理ajax，拒绝好友请求 """
    user = request.user
    payload = {}
    if request.method == "GET" and user.is_authenticated:
        friend_request_id = kwargs.get("friend_request_id")
        if friend_request_id:
            friend_request = FriendRequest.objects.get(pk=friend_request_id)
            # confirm it
            if friend_request.receiver == user:
                if friend_request:
                    # found the request, decline it
                    friend_request.decline()
                    payload['response'] = "Friend request declined."
                else:
                    payload['response'] = "Something went wrong."
            else:
                payload['response'] = "This is not your friend request to decline."
        else:
            payload['response'] = "Unable to decline that friend request."
    else:
        payload['response'] = 'You must be authenticated to decline a friend request.'

    return JsonResponse(payload)


def cancel_friend_request(request, *args, **kwargs):
    """ 使用ajax，取消自己发送的好友请求 """
    user = request.user
    payload = {}
    if request.method == "POST" and user.is_authenticated:
        user_id = request.POST.get("receiver_user_id")
        if user_id:
            receiver = Account.objects.get(pk=user_id)
            try:
                friend_requests = FriendRequest.objects.filter(sender=user, receiver=receiver, is_active=True)
            except Exception as e:
                payload['response'] = "Nothing to cancel. Friend request does not exist."
            # There should only ever be a single active friend request at any given time.
            # Cancel them all just in case.
            if len(friend_requests) > 1:
                for request in friend_requests:
                    request.cancel()
                payload['response'] = "Friend request cancelled."
            else:
                # found the request. Now cancel it.
                friend_requests.first().cancel()
                payload['response'] = "Friend request cancelled."
        else:
            payload['response'] = "Unable to cancel that friend request."
    else:
        payload['response'] = "You must be authenticated to cancel a friend request."

    return JsonResponse(payload)

