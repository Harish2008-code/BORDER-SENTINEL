"""JSON API for integration with checkpoint kiosks / case systems."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import faces
from .models import ExpiredDocument, ScreeningRecord, WatchlistEntry
from .pipeline import run_screening, store_upload


def _record_payload(r: ScreeningRecord):
    return {
        "id": r.pk,
        "created_at": r.created_at.isoformat(),
        "doc_type": r.doc_type,
        "holder_name": r.holder_name,
        "doc_number": r.doc_number,
        "risk_score": r.risk_score,
        "risk_level": r.risk_level,
        "recommendation": r.recommendation,
        "status": r.status,
        "ocr_confidence": r.ocr_confidence,
        "processing_ms": r.processing_ms,
        "fields": r.fields_json.get("values", {}),
        "failed_checks": [c for c in r.checks_json if not c.get("passed")],
        "tamper_score": r.tamper_json.get("score"),
        "face": r.face_json,
        "scoring": r.scoring_json,
    }


@api_view(["GET"])
def health(request):
    return Response({
        "status": "ok",
        "face_backend": faces.backend_name(),
        "records": ScreeningRecord.objects.count(),
    })


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def screen(request):
    doc = request.FILES.get("document")
    if not doc:
        return Response({"error": "multipart 'document' image required"},
                        status=status.HTTP_400_BAD_REQUEST)
    live = request.FILES.get("live_photo")
    doc_rel = store_upload(doc, "documents")
    live_rel = store_upload(live, "live") if live else None
    try:
        result = run_screening(doc_rel, live_rel,
                               doc_type_hint=request.data.get("doc_type") or None)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    payload = _record_payload(ScreeningRecord.objects.get(pk=result["record_id"]))
    payload["modules"] = {
        "ocr_fields": result["extraction"]["values"],
        "mrz": result["mrz"],
        "validation": result["checks"],
        "tamper_detectors": result["tamper"]["detectors"],
        "face_verification": result["face"],
    }
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def record_list(request):
    qs = ScreeningRecord.objects.all()[:100]
    level = request.GET.get("level")
    if level:
        qs = qs.filter(risk_level=level)
    return Response([_record_payload(r) for r in qs])


@api_view(["GET"])
def record_detail(request, pk):
    try:
        r = ScreeningRecord.objects.get(pk=pk)
    except ScreeningRecord.DoesNotExist:
        return Response({"error": "not found"}, status=404)
    payload = _record_payload(r)
    payload["audit_trail"] = [
        {"seq": e.seq, "action": e.action, "detail": e.detail,
         "hash": e.hash[:16], "at": e.at.isoformat()}
        for e in r.audit_events.all()
    ]
    payload["audit_chain_valid"] = r.verify_audit_chain()
    return Response(payload)


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def watchlist_api(request):
    if request.method == "POST":
        entry = WatchlistEntry.objects.create(
            full_name=str(request.data.get("full_name", "")).upper(),
            doc_number=str(request.data.get("doc_number", "")).upper(),
            nationality=str(request.data.get("nationality", "")).upper(),
            reason=str(request.data.get("reason", "")),
        )
        return Response({"id": entry.pk}, status=status.HTTP_201_CREATED)
    return Response({
        "watchlist": [
            {"id": w.pk, "full_name": w.full_name, "doc_number": w.doc_number,
             "reason": w.reason}
            for w in WatchlistEntry.objects.all()],
        "blacklist": [
            {"id": b.pk, "doc_number": b.doc_number, "reason": b.reason}
            for b in ExpiredDocument.objects.all()],
    })
