from django.urls import path

from . import api, camera, views

app_name = "screening"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("screen/", views.upload, name="upload"),
    path("records/", views.records_list, name="records"),
    path("record/<int:pk>/", views.record_detail, name="record"),
    path("watchlist/", views.watchlist, name="watchlist"),
    path("watchlist/blacklist/add/", views.blacklist_add, name="blacklist_add"),
    path("watchlist/blacklist/del/", views.blacklist_delete,
         name="blacklist_delete"),

    # Camera endpoints
    path("camera/stream/", camera.camera_stream, name="camera_stream"),
    path("camera/snapshot/", camera.camera_snapshot, name="camera_snapshot"),
    path("camera/capture/", camera.camera_capture, name="camera_capture"),

    # Email verification endpoints
    path("screen/email-verify/<str:token>/<str:action>/",
         views.email_verify_response, name="email_verify_response"),
    path("api/email-status/<int:pk>/",
         views.email_verify_status_api, name="email_verify_status"),

    # API
    path("api/health/", api.health, name="api_health"),
    path("api/screen/", api.screen, name="api_screen"),
    path("api/records/", api.record_list, name="api_records"),
    path("api/records/<int:pk>/", api.record_detail, name="api_record"),
    path("api/watchlist/", api.watchlist_api, name="api_watchlist"),
]
