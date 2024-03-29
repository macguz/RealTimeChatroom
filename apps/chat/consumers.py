import json


from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.paginator import Paginator
from django.utils import timezone

from account.utils import LazyAccountEncoder
from chat.exceptions import ClientError
from chat.models import PrivateChatroom, ChatroomMessage
from chat.utils import calculate_timestamp, LazyChatroomMessageEncoder
from friend.models import FriendList
from chat.constants import MSG_TYPE_MESSAGE, MSG_TYPE_ENTER, MSG_TYPE_LEAVE, DEFAULT_ROOM_CHAT_MESSAGE_PAGE_SIZE


class ChatConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        """
        WebSocket连接时调用
        """
        print("ChatConsumer: connect: " + str(self.scope["user"]))

        await self.accept()

        self.room_id = None

    async def receive_json(self, content):
        """
        接收前端发来的消息，并按照command进行处理
        """
        print("ChatConsumer: receive_json")
        command = content.get("command", None)
        try:
            if command == "join":
                await self.join_room(content['room_id'])
            elif command == "leave":
                await self.leave_room(content["room_id"])
            elif command == "send":
                if len(content["message"].lstrip()) == 0:
                    raise ClientError(422, "无法发送空白消息.")
                await self.send_room(content["room_id"], content["message"])
            elif command == "get_room_chat_messages":
                await self.display_progress_bar(True)
                room = await get_room_or_error(content['room_id'], self.scope['user'])
                payload = await get_room_chat_messages(room, content['page_number'])
                if payload is not None:
                    payload = json.loads(payload)
                    await self.send_messages_payload(payload['messages'], payload['new_page_number'])
                else:
                    raise ClientError(204, "Database error")
                await self.display_progress_bar(False)
            elif command == "get_user_info":
                await self.display_progress_bar(True)
                room = await get_room_or_error(content['room_id'], self.scope["user"])
                payload = get_user_info(room, self.scope["user"])
                if payload is not None:
                    payload = json.loads(payload)
                    await self.send_user_info_payload(payload['user_info'])
                else:
                    raise ClientError('INVALID_ROOM', "获取资料错误.")
                await self.display_progress_bar(False)
        except ClientError as e:
            await self.display_progress_bar(False)
            await self.handle_client_error(e)

    async def disconnect(self, code):
        """
        关闭WebSocket连接
        """
        print("ChatConsumer: disconnect")
        try:
            if self.room_id is not None:
                await self.leave_room(self.room_id)
        except Exception as e:
            print("EXCEPTION: " + str(e))
            pass

    # 几个处理命令的辅助函数
    async def join_room(self, room_id):
        """
        join 命令.
        """
        print("ChatConsumer: join_room: " + str(room_id))
        try:
            room = await get_room_or_error(room_id, self.scope["user"])
        except ClientError as e:
            return await self.handle_client_error(e)

        # 存储当前room_id
        self.room_id = room.id

        # 将用户加入组中
        await self.channel_layer.group_add(
            room.group_name,
            self.channel_name,
        )

        # Instruct their client to finish opening the room
        await self.send_json({
            "join": str(room.id),
        })

        # 组内发送消息，当前用户进入聊天
        if self.scope["user"].is_authenticated:
            # Notify the group that someone joined
            await self.channel_layer.group_send(
                room.group_name,
                {
                    "type": "chat.join",  # chat_join()
                    "room_id": room_id,
                    "profile_image": self.scope["user"].profile_image.url,
                    "username": self.scope["user"].username,
                    "user_id": self.scope["user"].id,
                }
            )

    async def leave_room(self, room_id):
        """
        Called by receive_json when someone sent a leave command.
        """
        # The logged-in user is in our scope thanks to the authentication ASGI middleware
        print("ChatConsumer: leave_room")
        room = await get_room_or_error(room_id, self.scope["user"])

        # Notify the group that someone left
        await self.channel_layer.group_send(
            room.group_name,
            {
                "type": "chat.leave",  # chat_leave
                "room_id": room_id,
                "profile_image": self.scope["user"].profile_image.url,
                "username": self.scope["user"].username,
                "user_id": self.scope["user"].id,
            }
        )

        # Remove that we're in the room
        self.room_id = None

        # Remove them from the group so they no longer get room messages
        await self.channel_layer.group_discard(
            room.group_name,
            self.channel_name,
        )
        # Instruct their client to finish closing the room
        await self.send_json({
            "leave": str(room.id),
        })

    async def send_room(self, room_id, message):
        """
        Called by receive_json when someone sends a message to a room.
        """
        print("ChatConsumer: send_room")
        # Check they are in this room
        if self.room_id is not None:
            if str(room_id) != str(self.room_id):
                raise ClientError("ROOM_ACCESS_DENIED", "Room access denied")
        else:
            raise ClientError("ROOM_ACCESS_DENIED", "Room access denied")

        # 获取聊天会话
        room = await get_room_or_error(room_id, self.scope["user"])

        await create_room_chat_message(room, self.scope["user"], message)

        await self.channel_layer.group_send(
            room.group_name,
            {
                "type": "chat.message",
                "profile_image": self.scope["user"].profile_image.url,
                "username": self.scope["user"].username,
                "user_id": self.scope["user"].id,
                "message": message,
            }
        )

    # 几个发送消息的工具函数
    async def chat_join(self, event):
        """
        Called when someone has joined our chat.
        """
        # Send a message down to the client
        print("ChatConsumer: chat_join: " + str(self.scope["user"].id))
        if event["username"]:
            await self.send_json(
                {
                    "msg_type": MSG_TYPE_ENTER,
                    "room_id": event["room_id"],
                    "profile_image": event["profile_image"],
                    "username": event["username"],
                    "user_id": event["user_id"],
                    "message": event["username"] + " 进入聊天",
                },
            )

    async def chat_leave(self, event):
        """
        Called when someone has left our chat.
        """
        # Send a message down to the client
        print("ChatConsumer: chat_leave")
        if event["username"]:
            await self.send_json(
                {
                    "msg_type": MSG_TYPE_LEAVE,
                    "room": event["room_id"],
                    "profile_image": event["profile_image"],
                    "username": event["username"],
                    "user_id": event["user_id"],
                    "message": event["username"] + " 离开聊天",
                },
            )

    async def chat_message(self, event):
        """
        Called when someone has messaged our chat.
        """
        # Send a message down to the client
        print("ChatConsumer: chat_message")
        timestamp = calculate_timestamp(timezone.now())

        await self.send_json(
            {
                "msg_type": MSG_TYPE_MESSAGE,
                "username": event["username"],
                "user_id": event["user_id"],
                "profile_image": event["profile_image"],
                "message": event["message"],
                "natural_timestamp": timestamp,
            },
        )

    async def handle_client_error(self, e):
        """
        Called when a ClientError is raised.
        Sends error data to UI.
        """
        errorData = {}
        errorData['error'] = e.code
        if e.message:
            errorData['message'] = e.message
            await self.send_json(errorData)
        return

    async def send_messages_payload(self, messages, new_page_number):
        """
        Send a payload of messages to the ui
        """
        print("ChatConsumer: send_messages_payload. ")
        await self.send_json({
            "messages_payload": "messages_payload",
            "messages": messages,
            "new_page_number": new_page_number,
        })

    async def send_user_info_payload(self, user_info):
        """
        Send a payload of user information to the ui
        """
        print("ChatConsumer: send_user_info_payload. ")
        await self.send_json({
            "user_info": user_info,
        })

    async def display_progress_bar(self, is_displayed):
        """
        1. is_displayed = True
            - Display the progress bar on UI
        2. is_displayed = False
            - Hide the progress bar on UI
        """
        print("DISPLAY PROGRESS BAR: " + str(is_displayed))
        await self.send_json({
            "display_progress_bar": is_displayed
        })


@database_sync_to_async
def get_room_or_error(room_id, user):
    """
    获取聊天会话
    """
    try:
        room = PrivateChatroom.objects.get(pk=room_id)
    except PrivateChatroom.DoesNotExist:
        raise ClientError("INVALID_ROOM", "Invalid room.")

    # Is this user allowed in the room? (must be user1 or user2)
    if user != room.user1 and user != room.user2:
        raise ClientError("ACCESS_DENIED", "You do not have permission to join this room.")

    # Are the users in this room friends?
    friend_list = FriendList.objects.get(user=user).friends.all()
    if room.user1 not in friend_list:
        if room.user2 not in friend_list:
            raise ClientError("You must be friends to chat.")
    return room


def get_user_info(room, user):
    """
    获取聊天对象的消息
    """
    try:
        # Determine who is who
        other_user = room.user1
        if other_user == user:
            other_user = room.user2

        payload = {}
        s = LazyAccountEncoder()
        # convert to list for serializer and select first entry (there will be only 1)
        payload['user_info'] = s.serialize([other_user])[0]
        return json.dumps(payload)
    except ClientError as e:
        print("ClientError: " + str(e))

    return None


@database_sync_to_async
def create_room_chat_message(room, user, message):
    return ChatroomMessage.objects.create(user=user, room=room, content=message)


@database_sync_to_async
def get_room_chat_messages(room, page_number):
    try:
        qs = ChatroomMessage.objects.by_room(room)
        p = Paginator(qs, DEFAULT_ROOM_CHAT_MESSAGE_PAGE_SIZE)

        payload = {}

        new_page_number = int(page_number)
        if new_page_number <= p.num_pages:
            new_page_number = new_page_number + 1
            s = LazyChatroomMessageEncoder()
            payload['messages'] = s.serialize(p.page(page_number).object_list)
        else:
            payload['messages'] = "None"
        payload['new_page_number'] = new_page_number
        return json.dumps(payload)
    except Exception as e:
        print("EXCEPTION: " + str(e))
        return None