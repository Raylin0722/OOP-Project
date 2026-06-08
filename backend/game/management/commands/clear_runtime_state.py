from django.core.management.base import BaseCommand
from django.db import transaction

from game.models import MatchmakingTicket, Room


class Command(BaseCommand):
    help = 'Clear runtime-only game state such as rooms and matchmaking tickets.'

    def handle(self, *args, **options):
        with transaction.atomic():
            ticket_count = MatchmakingTicket.objects.count()
            room_count = Room.objects.count()

            MatchmakingTicket.objects.all().delete()
            Room.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                f'Cleared runtime state: {ticket_count} matchmaking ticket(s), '
                f'{room_count} room(s).'
            )
        )
