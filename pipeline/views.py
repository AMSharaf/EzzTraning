import threading

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import UploadForm
from .models import ProcessingJob
from .services import run_pipeline


def upload_view(request):
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            job = form.save(commit=False)
            job.status = ProcessingJob.STATUS_QUEUED
            job.save()

            # Run the (potentially slow, Gemini-calling) pipeline in a
            # background thread so the upload request returns immediately.
            # For production, swap this for Celery + a real broker (see
            # README) so jobs survive a server restart / run on a worker.
            thread = threading.Thread(target=run_pipeline, args=(job.pk,), daemon=True)
            thread.start()

            return redirect("job_detail", pk=job.pk)
    else:
        form = UploadForm()

    return render(request, "pipeline/upload.html", {"form": form})


def job_list(request):
    jobs = ProcessingJob.objects.all()
    return render(request, "pipeline/job_list.html", {"jobs": jobs})


def job_detail(request, pk):
    job = get_object_or_404(ProcessingJob, pk=pk)
    return render(request, "pipeline/job_detail.html", {"job": job})


def job_status(request, pk):
    """JSON endpoint polled by job_detail.html to auto-refresh progress."""
    job = get_object_or_404(ProcessingJob, pk=pk)
    return JsonResponse(
        {
            "status": job.status,
            "error_message": job.error_message,
            "row_count": job.row_count,
            "filtered_row_count": job.filtered_row_count,
            "has_output": bool(job.output_file),
            "has_filtered": bool(job.filtered_file),
        }
    )
