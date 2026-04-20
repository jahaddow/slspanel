from django.core.management.base import BaseCommand
from streams.models import Configuration


class Command(BaseCommand):
    help = "Initial configuration or update from ENV"

    def handle(self, *args, **kwargs):
        conf, _created = Configuration.objects.get_or_create(id=1)
        conf.language = "en"
        conf.save()
        self.stdout.write(self.style.SUCCESS("Config set language to en"))
