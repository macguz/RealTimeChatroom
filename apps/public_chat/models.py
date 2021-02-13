from django.db import models
from django.conf import settings


class PublicChatroom(models.Model):
    title = models.CharField(max_length=255, unique=True, blank=False)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, help_text="聊天室中的用户")

    def __str__(self):
        return self.title

    def connect_user(self, user):
        """
        如果用户被加入到users list，返回True
        """
        is_user_added = False
        if not user in self.users.all():
            self.users.add(user)
            self.save()
            is_user_added = True
        elif user in self.users.all():
            is_user_added = True
        return is_user_added

    def disconnect_user(self, user):
        """
        删除
        """
        is_user_removed = False
        if user in self.users.all():
            self.users.remove(user)
            self.save()
            is_user_removed = True

        return is_user_removed

    @property
    def group_name(self):
        """
        Returns the channels group name that sockets should subscribe
         to and get sent messages as they are generated
        Returns
        -------

        """
        return f"PublicChatRoom-{self.id}"