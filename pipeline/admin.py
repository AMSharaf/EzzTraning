from django.contrib import admin

from .models import ProcessingJob


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("id", "report_date", "status", "row_count", "filtered_row_count", "created_at")
    list_filter = ("status",)
    readonly_fields = ("created_at", "started_at", "finished_at")
