from django.db import models


class Configuration(models.Model):
    language = models.CharField(max_length=10, default='en')

    def __str__(self):
        return f"Config({self.language})"


class PushRoute(models.Model):
    publisher = models.CharField(max_length=255, unique=True)
    destination_url = models.CharField(max_length=1024, blank=True, default='')
    enabled = models.BooleanField(default=False)
    runner_state = models.CharField(max_length=32, default='stopped')
    last_error = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    runner_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"PushRoute({self.publisher}, enabled={self.enabled})"
