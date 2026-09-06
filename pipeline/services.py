"""
Service layer that runs your EXISTING pipeline for a single uploaded job.

This mirrors your original standalone script line-for-line:

    db = Database("data/master_data.json")
    gemini = GeminiService()
    matcher = Matcher(database=db, gemini_service=gemini, low_confidence_file=...)
    enricher = Enricher(gemini_service=gemini, database=db)
    batch_resolver = BatchResolver(matcher=matcher, enricher=enricher)
    processor = ExcelProcessor(batch_resolver)
    ExcelHandler.unmerge_and_fill(INPUT_FILE, UNMERGED_FILE)
    result = processor.process(...)
    processor.persist_to_database(dataframe=processor.last_filtered_df, ...)
    db.save()

The only behavioral change: year/month for persist_to_database() are now
derived automatically from the report_date the user picks in the web form,
instead of having to be kept in sync by hand.
"""

import logging
import os
import traceback
from datetime import datetime

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# These imports assume you've copied your existing `modules/` package and
# `config.py` into the project root (next to manage.py), unchanged.
import config
from modules.database import Database
from modules.matcher import Matcher
from modules.gemini_service import GeminiService
from modules.enricher import Enricher
from modules.excel_processor import ExcelProcessor
from modules.excel_handler import ExcelHandler
from modules.batch_resolver import BatchResolver


def _job_workdir(job):
    workdir = os.path.join(settings.MEDIA_ROOT, "jobs", str(job.pk))
    os.makedirs(workdir, exist_ok=True)
    return workdir


def _dated_filename(base_path, report_date):
    """
    Takes a base path from config.py (e.g. "data/unmerged2.xlsx") and a
    report_date, and returns a filename stamped with that date in
    zero-padded YYYY-MM-DD order, e.g. "unmerged2-2025-04-20.xlsx".

    YYYY-MM-DD (not day-month-year) so files sort correctly by name in
    a file browser / `ls` / Explorer - alphabetical order then matches
    chronological order. Only the filename is used - the folder from
    config.py is ignored since each job gets its own folder under
    media/jobs/<id>/ instead.
    """
    base = os.path.basename(base_path)
    name, ext = os.path.splitext(base)
    date_str = report_date.strftime("%Y-%m-%d")
    return f"{name}-{date_str}{ext}"


def run_pipeline(job_id):
    """
    Runs the full pipeline for the ProcessingJob with the given id.
    Designed to be called from a background thread (see views.upload_view),
    so it re-fetches the job fresh and saves progress as it goes.
    """
    # Imported here to avoid app-registry issues when called from a thread
    from .models import ProcessingJob

    job = ProcessingJob.objects.get(pk=job_id)
    job.status = ProcessingJob.STATUS_PROCESSING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    try:
        input_file = job.uploaded_file.path
        workdir = _job_workdir(job)

        # File names are stamped with the report date, using the base
        # names configured in config.py (UNMERGED_FILE, OUTPUT_FILE,
        # PREPROCESSED_FILE) - e.g. "unmerged2-2025-04-20.xlsx". Each job
        # still gets its own folder (media/jobs/<id>/) so concurrent jobs
        # never overwrite each other even if the date is the same.
        unmerged_file = os.path.join(
            workdir, _dated_filename(config.UNMERGED_FILE, job.report_date)
        )
        output_file = os.path.join(
            workdir, _dated_filename(config.OUTPUT_FILE, job.report_date)
        )
        filtered_file = os.path.join(
            workdir, _dated_filename(config.PREPROCESSED_FILE, job.report_date)
        )

        report_date_str = job.report_date.strftime("%Y-%m-%d")

        # ---- exact same wiring as your original script -----------------
        db = Database(settings.MASTER_DATA_PATH)
        gemini = GeminiService()

        matcher = Matcher(
            database=db,
            gemini_service=gemini,
            low_confidence_file=settings.LOW_CONFIDENCE_PATH,
        )

        enricher = Enricher(
            gemini_service=gemini,
            database=db,
        )

        batch_resolver = BatchResolver(
            matcher=matcher,
            enricher=enricher,
        )

        processor = ExcelProcessor(batch_resolver)

        ExcelHandler.unmerge_and_fill(input_file, unmerged_file)

        result = processor.process(
            input_file=unmerged_file,
            output_file=output_file,
            skip_rows=3,
            target_columns=[1, 2, 3, 4],
            new_headers=["Governorate", "License Type", "Brand", "Model"],
            filtered_output_file=filtered_file,
            extra_columns=[9],
            new_extra_headers=["Count"],
            report_date=report_date_str,
            filter_private=job.filter_private,
        )

        # IMPORTANT (kept from your original comment): use
        # processor.last_filtered_df - nulls/non-private rows already
        # dropped - NOT `result`, which is the full unfiltered dataset and
        # can contain rows with missing brand_id/model_id that would fail
        # the SQL insert.
        processor.persist_to_database(
            dataframe=processor.last_filtered_df,
            source_file=unmerged_file,
            year=job.report_date.year,
            month=job.report_date.month,
            extra_columns=["Count"],
        )

        # Sync any newly discovered master entities (brands/models/license
        # types/governorates) to SQL Server.
        db.save()
        # ------------------------------------------------------------------

        from django.core.files import File

        if os.path.exists(output_file):
            with open(output_file, "rb") as fh:
                job.output_file.save(os.path.basename(output_file), File(fh), save=False)
        if os.path.exists(filtered_file):
            with open(filtered_file, "rb") as fh:
                job.filtered_file.save(os.path.basename(filtered_file), File(fh), save=False)

        job.row_count = len(result) if result is not None and hasattr(result, "__len__") else None
        job.filtered_row_count = (
            len(processor.last_filtered_df)
            if getattr(processor, "last_filtered_df", None) is not None
            else None
        )
        job.status = ProcessingJob.STATUS_DONE
        job.finished_at = timezone.now()
        job.save()

    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline failed for job %s", job_id)
        job.status = ProcessingJob.STATUS_FAILED
        job.error_message = f"{exc}\n\n{traceback.format_exc()}"
        job.finished_at = timezone.now()
        job.save()