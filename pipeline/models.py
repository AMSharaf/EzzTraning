from django.db import models


class ProcessingJob(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    uploaded_file = models.FileField(upload_to="uploads/%Y/%m/")
    report_date = models.DateField(
        help_text="Same date you'd pass as report_date to processor.process(). "
        "Year/month for persist_to_database() are derived from this automatically."
    )
    filter_private = models.BooleanField(
        default=True,
        help_text="If checked, the filtered output / SQL Server push only "
        "includes rows where License Type resolves to Private. Uncheck to "
        "keep all license types in the filtered output.",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    error_message = models.TextField(blank=True, null=True)

    output_file = models.FileField(upload_to="outputs/", blank=True, null=True)
    filtered_file = models.FileField(upload_to="filtered/", blank=True, null=True)
    row_count = models.IntegerField(blank=True, null=True)
    filtered_row_count = models.IntegerField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Job #{self.pk} ({self.report_date}) - {self.status}"
