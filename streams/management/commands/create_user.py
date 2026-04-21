from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os


class Command(BaseCommand):
    help = "Create User from ENV"

    def handle(self, *args, **kwargs):
        require_login = os.getenv('REQUIRE_LOGIN', 'True').lower() in ['true', '1', 'yes']
        if not require_login:
            self.stdout.write(self.style.WARNING("Login is disabled via REQUIRE_LOGIN. No user will be created."))
            return

        # Prefer current env names, keep legacy WEB_* for backward compatibility.
        username = os.getenv("USERNAME") or os.getenv("WEB_USERNAME") or "admin"
        password = os.getenv("PASSWORD") or os.getenv("WEB_PASSWORD") or "password"

        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email="", password=password)
            self.stdout.write(self.style.SUCCESS(f"User '{username}' was created."))
        else:
            # Keep login credentials in sync on redeploy when username already exists.
            user = User.objects.get(username=username)
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"User '{username}' password updated from environment."))
