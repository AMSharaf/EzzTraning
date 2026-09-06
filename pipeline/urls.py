from django.urls import path

from . import views

urlpatterns = [
    path("", views.upload_view, name="upload"),
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<int:pk>/status/", views.job_status, name="job_status"),
]
