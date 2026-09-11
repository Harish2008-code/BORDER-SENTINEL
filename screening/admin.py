from django.contrib import admin

from .models import AuditEvent, ExpiredDocument, ScreeningRecord, WatchlistEntry


@admin.register(ScreeningRecord)
class ScreeningRecordAdmin(admin.ModelAdmin):
    list_display = ("pk", "created_at", "doc_type", "holder_name", "doc_number",
                    "risk_score", "risk_level", "status")
    list_filter = ("risk_level", "doc_type", "status")
    search_fields = ("holder_name", "doc_number")
    readonly_fields = ("fields_json", "checks_json", "tamper_json", "face_json",
                       "scoring_json", "integrity_hash")


admin.site.register(WatchlistEntry)
admin.site.register(ExpiredDocument)
admin.site.register(AuditEvent)
