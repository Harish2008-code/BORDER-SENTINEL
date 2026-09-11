"""Seeds security databases and generates the synthetic demo corpus."""
from django.conf import settings
from django.core.management.base import BaseCommand

from screening import synthetic
from screening.models import ExpiredDocument, ScreeningRecord, WatchlistEntry


class Command(BaseCommand):
    help = "Seed watchlist/blacklist entries and generate demo documents"

    def handle(self, *args, **options):
        # demo runs upload the same holders repeatedly; stale screening
        # records would trip the duplicate_identity rule on every fresh demo
        deleted, _ = ScreeningRecord.objects.all().delete()
        if deleted:
            self.stdout.write(f"Cleared {deleted} previous screening records")
        WatchlistEntry.objects.get_or_create(
            full_name="VIKRAM SINGH",
            defaults=dict(doc_number="S7777777", nationality="IND",
                          reason="Interpol red notice - document fraud syndicate"))
        ExpiredDocument.objects.get_or_create(
            doc_number="B4444444",
            defaults=dict(reason="Reported lost / stolen"))
        out = settings.DEMO_ASSETS_DIR / "generated"
        paths = synthetic.generate_demo_docs(str(out))
        self.stdout.write(self.style.SUCCESS(
            f"Seeded databases and wrote {len(paths)} demo documents to {out}"))
        for k, v in paths.items():
            self.stdout.write(f"  - {k}: {v}")
        self.stdout.write("Live-capture photos for face verification:")
        self.stdout.write(f"  - match:   {settings.DEMO_ASSETS_DIR / 'subject_a_live_capture.jpg'}")
        self.stdout.write(f"  - imposter:{settings.DEMO_ASSETS_DIR / 'subject_b_passport_photo.jpg'}")
