from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate embeddings for companies (sync or async via Celery)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--async',
            action='store_true',
            dest='run_async',
            help='Dispatch as Celery task instead of running synchronously',
        )
        parser.add_argument(
            '--projections-only',
            action='store_true',
            help='Only compute UMAP projections and HDBSCAN clusters',
        )

    def handle(self, *args, **options):
        if options['run_async']:
            if options['projections_only']:
                from core.tasks import compute_projections_task
                result = compute_projections_task.delay()
                self.stdout.write(f'Dispatched projections task: {result.id}')
            else:
                from core.tasks import full_pipeline_task
                result = full_pipeline_task.delay()
                self.stdout.write(f'Dispatched full pipeline task: {result.id}')
        else:
            if options['projections_only']:
                from core.tasks import compute_projections_task
                result = compute_projections_task()
                self.stdout.write(self.style.SUCCESS(f'Projections: {result}'))
            else:
                from core.tasks import full_pipeline_task
                result = full_pipeline_task()
                self.stdout.write(self.style.SUCCESS(f'Pipeline: {result}'))
