import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from game.models import MatchmakingTicket
from game.views import _try_complete_matchmaking


class Command(BaseCommand):
    help = 'Runs the matchmaking queue worker.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            default=1.0,
            type=float,
            help='Seconds between matchmaking scans.',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run one scan and exit.',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        once = options['once']
        self.stdout.write(self.style.SUCCESS('Matchmaking worker started.'))

        while True:
            close_old_connections()
            processed = self.process_once()
            close_old_connections()

            if once:
                self.stdout.write(f'Matchmaking worker processed {processed} scan(s).')
                return

            time.sleep(interval)

    def process_once(self):
        ticket = (
            MatchmakingTicket.objects
            .select_related('user', 'source_room')
            .filter(status=MatchmakingTicket.Status.WAITING)
            .order_by('created_at', 'id')
            .first()
        )
        if ticket is None:
            return 0

        self.stdout.write(
            f'[matchmaking-worker] processing ticket '
            f'id={ticket.id} '
            f'user={ticket.user_id} '
            f'score={ticket.score} '
            f'source_room={ticket.source_room.code if ticket.source_room_id else None}'
        )

        room = _try_complete_matchmaking(ticket.user)

        if room is None:
            self.stdout.write(
                f'[matchmaking-worker] no match yet '
                f'ticket_id={ticket.id} '
                f'user={ticket.user_id} '
                f'source_room={ticket.source_room.code if ticket.source_room_id else None}'
            )
            return 0
        self.stdout.write(
            self.style.SUCCESS(
                f'[matchmaking-worker] matched '
                f'room={room.code} '
                f'room_id={room.room_id}'
            )
        )
        return 1
