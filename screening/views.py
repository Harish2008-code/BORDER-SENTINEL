from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import EmailVerification, ExpiredDocument, ScreeningRecord, WatchlistEntry
from .pipeline import run_screening, store_upload

DOC_TYPES = [c[0] for c in ScreeningRecord.DOC_TYPES]


def dashboard(request):
    qs = ScreeningRecord.objects.all()
    stats = {
        "total": qs.count(),
        "levels": {r["risk_level"]: r["n"] for r in
                   qs.values("risk_level").annotate(n=Count("id"))},
        "types": {r["doc_type"]: r["n"] for r in
                  qs.values("doc_type").annotate(n=Count("id"))},
        "flagged": qs.filter(status="FLAGGED").count(),
        "watchlist": WatchlistEntry.objects.count(),
        "blacklist": ExpiredDocument.objects.count(),
    }
    recent_ms = [r.processing_ms for r in qs[:200]]
    stats["avg_ms"] = round(sum(recent_ms) / len(recent_ms)) if recent_ms else 0
    recent = qs[:8]
    return render(request, "screening/dashboard.html",
                  {"stats": stats, "recent": recent})


def upload(request):
    if request.method == "POST":
        doc = request.FILES.get("document")
        if not doc:
            messages.error(request, "A document image is required.")
            return redirect("screening:upload")
        live = request.FILES.get("live_photo") or None
        hint = request.POST.get("doc_type") or None
        doc_rel = store_upload(doc, "documents")
        live_path = request.POST.get("live_photo_path", "").strip()
        if live:
            live_rel = store_upload(live, "live")
        elif live_path:
            live_rel = live_path
        else:
            live_rel = None
        try:
            base_url = f"{request.scheme}://{request.get_host()}"
            result = run_screening(doc_rel, live_rel,
                                   doc_type_hint=hint or None,
                                   base_url=base_url)
        except Exception as exc:
            messages.error(request, f"Screening failed: {exc}")
            return redirect("screening:upload")
        return redirect("screening:record", pk=result["record_id"])
    return render(request, "screening/upload.html", {"doc_types": DOC_TYPES})


def record_detail(request, pk):
    record = get_object_or_404(ScreeningRecord, pk=pk)
    if request.method == "POST":
        record.status = request.POST.get("status", record.status)
        record.review_note = request.POST.get("review_note", record.review_note)
        record.save()
        record.append_audit("status_change", record.status)
        messages.success(request, f"Record #{pk} updated to {record.status}.")
        return redirect("screening:record", pk=pk)

    # Email verification status
    email_verification = None
    try:
        ev = record.email_verifications.latest("created_at")
        from django.utils import timezone
        if ev.status == "PENDING" and timezone.now() > ev.expires_at:
            ev.status = "EXPIRED"
            ev.save(update_fields=["status"])
        email_verification = ev
    except EmailVerification.DoesNotExist:
        pass

    # Parse face_json for multi-comparison display
    face_json = record.face_json or {}
    face_comparisons = {}
    if "doc_vs_live" in face_json:
        face_comparisons["doc_vs_live"] = face_json["doc_vs_live"]
        face_comparisons["doc_vs_db"] = face_json.get("doc_vs_db")
        face_comparisons["live_vs_db"] = face_json.get("live_vs_db")
    elif face_json.get("similarity") is not None or face_json.get("matched") is not None:
        # Legacy format: single face result = doc_vs_live
        face_comparisons["doc_vs_live"] = face_json
    else:
        face_comparisons = face_json

    return render(request, "screening/record_detail.html", {
        "record": record,
        "chain_ok": record.verify_audit_chain(),
        "audit": record.audit_events.all(),
        "email_verification": email_verification,
        "face_comparisons": face_comparisons,
    })


def records_list(request):
    qs = ScreeningRecord.objects.all()
    q = request.GET.get("q", "").strip()
    level = request.GET.get("level", "").strip()
    dtype = request.GET.get("type", "").strip()
    if q:
        qs = qs.filter(Q(holder_name__icontains=q) | Q(doc_number__icontains=q))
    if level:
        qs = qs.filter(risk_level=level)
    if dtype:
        qs = qs.filter(doc_type=dtype)
    return render(request, "screening/records.html", {
        "records": qs[:100], "q": q, "level": level, "dtype": dtype,
        "doc_types": DOC_TYPES, "levels": ["LOW", "MEDIUM", "HIGH"],
    })


def watchlist(request):
    if request.method == "POST":
        action = request.POST.get("action", "add")
        if action == "add":
            WatchlistEntry.objects.create(
                full_name=request.POST.get("full_name", "").upper(),
                doc_type=request.POST.get("doc_type", ""),
                doc_number=request.POST.get("doc_number", "").upper(),
                nationality=request.POST.get("nationality", "").upper(),
                reason=request.POST.get("reason", ""),
                photo=request.FILES.get("photo") or None,
            )
            messages.success(request, "Watchlist entry added.")
        elif action == "delete":
            WatchlistEntry.objects.filter(pk=request.POST.get("entry_id")).delete()
            messages.success(request, "Watchlist entry removed.")
        return redirect("screening:watchlist")
    return render(request, "screening/watchlist.html", {
        "entries": WatchlistEntry.objects.all(),
        "blacklist": ExpiredDocument.objects.all(),
    })


@require_POST
def blacklist_add(request):
    obj, created = ExpiredDocument.objects.get_or_create(
        doc_number=request.POST.get("doc_number", "").upper(),
        defaults={"reason": request.POST.get("reason", ""),
                  "doc_type": request.POST.get("doc_type", "passport")})
    photo = request.FILES.get("photo")
    if photo:
        obj.photo = photo
        obj.save(update_fields=["photo"])
    messages.success(request, "Document blacklisted.")
    return redirect("screening:watchlist")


@require_POST
def blacklist_delete(request):
    ExpiredDocument.objects.filter(pk=request.POST.get("entry_id")).delete()
    messages.success(request, "Blacklist entry removed.")
    return redirect("screening:watchlist")


# --------------------------------------------------------------------------
# Email verification response endpoints (token-based, no auth needed)
# --------------------------------------------------------------------------

def email_verify_response(request, token, action):
    """Handle approve/reject clicks from verification emails."""
    from . import email_verify

    if action not in ("approve", "reject"):
        return HttpResponse("Invalid action.", status=400)

    result = email_verify.process_response(token, action)

    if result["success"]:
        status_label = "APPROVED" if action == "approve" else "REJECTED"
        html = f"""<!DOCTYPE html>
<html><head><title>BorderSentinel — Verification {status_label}</title>
<style>
body {{ font-family: system-ui, sans-serif; display: flex; justify-content: center;
       align-items: center; min-height: 100vh; margin: 0;
       background: {'#e8f5e9' if action == 'approve' else '#ffebee'}; }}
.card {{ background: #fff; border-radius: 12px; padding: 3rem; text-align: center;
         box-shadow: 0 4px 24px rgba(0,0,0,0.1); max-width: 480px; }}
h1 {{ color: {'#2e7d32' if action == 'approve' else '#c62828'}; }}
</style></head><body>
<div class="card">
  <h1>{'✅' if action == 'approve' else '❌'} Verification {status_label}</h1>
  <p>Your identity verification has been <strong>{action}d</strong>.</p>
  <p>You may close this window.</p>
</div></body></html>"""
    else:
        html = f"""<!DOCTYPE html>
<html><head><title>BorderSentinel — Verification Error</title>
<style>
body {{ font-family: system-ui, sans-serif; display: flex; justify-content: center;
       align-items: center; min-height: 100vh; margin: 0; background: #fff3e0; }}
.card {{ background: #fff; border-radius: 12px; padding: 3rem; text-align: center;
         box-shadow: 0 4px 24px rgba(0,0,0,0.1); max-width: 480px; }}
h1 {{ color: #e65100; }}
</style></head><body>
<div class="card">
  <h1>⚠️ Verification Error</h1>
  <p>{result['detail']}</p>
</div></body></html>"""

    return HttpResponse(html)


def email_verify_status_api(request, pk):
    """AJAX endpoint: returns current email verification status as JSON."""
    import json
    record = get_object_or_404(ScreeningRecord, pk=pk)
    from . import email_verify
    status = email_verify.check_verification_status(record)
    return HttpResponse(json.dumps(status), content_type="application/json")
