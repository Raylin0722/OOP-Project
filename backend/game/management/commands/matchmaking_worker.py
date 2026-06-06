import time

from django.core.management.base import BaseCommand
from django.db import OperationalError, close_old_connections

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
        parser.add_argument(
            '--max-drain',
            default=20,
            type=int,
            help='Maximum number of rooms to create in one scan.',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        once = options['once']
        self.max_drain = options['max_drain']
        self.stdout.write(self.style.SUCCESS('Matchmaking worker started.'))

        while True:
            close_old_connections()

            try:
                processed = self.process_once()
            except OperationalError as exc:
                self.stderr.write(self.style.WARNING(
                    f'Matchmaking worker database busy: {exc}'
                ))
                processed = 0
                time.sleep(0.5)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f'Matchmaking worker error: {exc}'
                ))
                processed = 0
            finally:
                close_old_connections()

            if once:
                self.stdout.write(f'Matchmaking worker processed {processed} match(es).')
                return

            time.sleep(interval)

    def process_once(self):
        processed = 0

        for _ in range(self.max_drain):
            ticket = (
                MatchmakingTicket.objects
                .select_related('user')
                .filter(status=MatchmakingTicket.Status.WAITING)
                .order_by('created_at', 'id')
                .first()
            )

            if ticket is None:
                return processed

            self.stdout.write(
                f'[matchmaking-worker] processing ticket id={ticket.id} '
                f'user={ticket.user_id} score={ticket.score}'
            )

            room = _try_complete_matchmaking(ticket.user)

            if room is None:
                self.stdout.write('[matchmaking-worker] no match yet')
                return processed

            processed += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'[matchmaking-worker] matched room={room.code}'
                )
            )

        return processed
