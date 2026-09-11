"""Persistence layer: screening records, watchlists and the audit chain."""
from __future__ import annotations

import hashlib
import json

from django.db import models
from django.utils import timezone


class WatchlistEntry(models.Model):
    DOC_TYPES = [
        ("passport", "Passport"),
        ("visa", "Visa"),
        ("id_card", "National ID / Aadhaar"),
        ("driving_license", "Driving Licence"),
        ("permit", "Permit"),
        ("other", "Other"),
    ]
    full_name = models.CharField(max_length=120)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES,
                                blank=True, default="")
    doc_number = models.CharField(max_length=30, blank=True)
    nationality = models.CharField(max_length=3, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    photo = models.FileField(upload_to="watchlist/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.doc_number or 'no-doc'})"


class ExpiredDocument(models.Model):
    """Blacklisted / reported-lost / expired travel documents database."""
    DOC_TYPES = [
        ("passport", "Passport"),
        ("visa", "Visa"),
        ("id_card", "National ID / Aadhaar"),
        ("driving_license", "Driving Licence"),
        ("permit", "Permit"),
        ("other", "Other"),
    ]
    doc_number = models.CharField(max_length=30, unique=True)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES,
                                default="passport")
    reason = models.CharField(max_length=255, blank=True)
    photo = models.FileField(upload_to="blacklist/", null=True, blank=True)
    reported_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.doc_number


class ScreeningRecord(models.Model):
    DOC_TYPES = [
        ("passport", "Passport"),
        ("visa", "Visa"),
        ("id_card", "National ID"),
        ("driving_license", "Driving Licence"),
        ("permit", "Permit"),
    ]
    LEVELS = [("LOW", "LOW"), ("MEDIUM", "MEDIUM"), ("HIGH", "HIGH")]
    STATUSES = [
        ("NEW", "New"), ("REVIEWED", "Reviewed"),
        ("CLEARED", "Cleared"), ("FLAGGED", "Flagged"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES)
    original = models.FileField(upload_to="documents/")
    live_photo = models.FileField(upload_to="live/", null=True, blank=True)

    holder_name = models.CharField(max_length=160, blank=True, default="")
    doc_number = models.CharField(max_length=30, blank=True, default="", db_index=True)

    risk_score = models.IntegerField(default=0)
    risk_level = models.CharField(max_length=8, choices=LEVELS, default="LOW")
    recommendation = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUSES, default="NEW")
    review_note = models.TextField(blank=True, default="")

    ocr_confidence = models.FloatField(null=True, blank=True)
    processing_ms = models.IntegerField(default=0)

    fields_json = models.JSONField(default=dict, blank=True)
    checks_json = models.JSONField(default=list, blank=True)
    tamper_json = models.JSONField(default=dict, blank=True)
    face_json = models.JSONField(default=dict, blank=True)
    scoring_json = models.JSONField(default=dict, blank=True)
    annotated = models.CharField(max_length=255, blank=True, default="")

    integrity_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.doc_number or self.doc_type} [{self.risk_level}]"

    # -- audit trail -------------------------------------------------------
    def append_audit(self, action: str, detail: str = ""):
        prev = AuditEvent.objects.filter(record=self).order_by("-seq").first()
        prev_hash = prev.hash if prev else "0" * 64
        payload = json.dumps(
            {"seq": (prev.seq + 1) if prev else 1, "record": self.pk,
             "action": action, "detail": detail, "prev": prev_hash},
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return AuditEvent.objects.create(
            record=self, seq=(prev.seq + 1) if prev else 1,
            action=action, detail=detail, prev_hash=prev_hash, hash=digest,
        )

    def verify_audit_chain(self) -> bool:
        events = list(AuditEvent.objects.filter(record=self).order_by("seq"))
        prev = "0" * 64
        for e in events:
            payload = json.dumps(
                {"seq": e.seq, "record": self.pk, "action": e.action,
                 "detail": e.detail, "prev": prev}, sort_keys=True)
            if hashlib.sha256(payload.encode()).hexdigest() != e.hash:
                return False
            if e.prev_hash != prev:
                return False
            prev = e.hash
        return True


class AuditEvent(models.Model):
    record = models.ForeignKey(ScreeningRecord, on_delete=models.CASCADE,
                               related_name="audit_events")
    seq = models.IntegerField()
    action = models.CharField(max_length=60)
    detail = models.TextField(blank=True, default="")
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["record", "seq"]


class EmailVerification(models.Model):
    """Tracks passport email verification requests and responses."""
    STATUSES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
    ]

    screening_record = models.ForeignKey(
        ScreeningRecord, on_delete=models.CASCADE,
        related_name="email_verifications",
    )
    email = models.EmailField()
    token = models.CharField(max_length=128, unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="PENDING")
    sent = models.BooleanField(default=False)
    detail = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"EmailVerify #{self.pk} [{self.status}] → {self.email}"
