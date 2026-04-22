from django.db import models


class Configuration(models.Model):
    language = models.CharField(max_length=10, default='en')

    def __str__(self):
        return f"Config({self.language})"


class PushRoute(models.Model):
    publisher = models.CharField(max_length=255, unique=True)
    source_player_key = models.CharField(max_length=255, blank=True, default='')
    destination_url = models.CharField(max_length=1024, blank=True, default='')
    enabled = models.BooleanField(default=False)
    runner_state = models.CharField(max_length=32, default='stopped')
    last_error = models.TextField(blank=True, default='')
    relay_bitrate_kbps = models.FloatField(default=0)
    relay_uptime_seconds = models.IntegerField(default=0)
    retry_in_seconds = models.IntegerField(default=0)
    last_exit_code = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    runner_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"PushRoute({self.publisher}, enabled={self.enabled})"


class PushControlToken(models.Model):
    publisher = models.CharField(max_length=255, db_index=True)
    label = models.CharField(max_length=120, blank=True, default='')
    token_hash = models.CharField(max_length=64, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"PushControlToken({self.publisher}, active={self.active})"


class StreamMeta(models.Model):
    publisher = models.CharField(max_length=255, unique=True)
    sort_order = models.IntegerField(default=0)
    group_name = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"StreamMeta({self.publisher}, group={self.group_name or 'default'}, order={self.sort_order})"
