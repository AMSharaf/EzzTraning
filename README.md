# Vehicle Data Pipeline — Web App

A Django front-end for your existing pipeline (`Database`, `Matcher`,
`GeminiService`, `Enricher`, `ExcelProcessor`, `ExcelHandler`, `BatchResolver`).
Upload an Excel file, pick a report date, and the app runs the same steps
your standalone script did — then lets you download the results.

## What this does NOT change

`pipeline/services.py` calls your modules with the exact same arguments as
your original script:

```
ExcelHandler.unmerge_and_fill(input_file, unmerged_file)
processor.process(..., skip_rows=3, target_columns=[1,2,3,4],
                   new_headers=["Governorate","License Type","Brand","Model"],
                   extra_columns=[9], new_extra_headers=["Count"], ...)
processor.persist_to_database(dataframe=processor.last_filtered_df, ...)
db.save()
```

**One fix included:** year/month passed to `persist_to_database()` are now
derived automatically from the `report_date` you pick in the form, instead
of needing to be kept in sync by hand (that was flagged as a footgun in
your original script's comments).

## 1. Drop in your existing code

Copy into the project root (next to `manage.py`):

- your `modules/` package (`database.py`, `matcher.py`, `gemini_service.py`,
  `enricher.py`, `excel_processor.py`, `excel_handler.py`, `batch_resolver.py`)
- your `config.py`
- your `data/master_data.json` and `data/low_confidence.json` (or let the
  app create them fresh — check what your `Database`/`Matcher` classes do
  if the files don't exist yet)

If `config.py` defines its own paths/env vars (Gemini API key, SQL Server
connection string, etc.), leave it as-is — `pipeline/services.py` doesn't
touch those, it only imports your modules and calls them.

## 2. Install & run

```bash
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
# + install whatever modules/ needs (google-generativeai, pyodbc, etc.)

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` to upload a file, and
`http://127.0.0.1:8000/jobs/` to see job history.

## How it works

- **Upload form** (`/`) → creates a `ProcessingJob` row (uploaded file +
  report date), kicks off `pipeline.services.run_pipeline()` in a
  background thread, redirects to the job's status page.
- **Job status page** (`/jobs/<id>/`) → polls `/jobs/<id>/status/` every 3s
  and reloads once the job finishes, then shows download links for the
  full output file and the filtered file (the one actually pushed to
  `Fact_Vehicles`), plus row counts.
- **`pipeline/services.run_pipeline`** → does the real work: unmerge →
  `processor.process()` → `processor.persist_to_database()` → `db.save()`,
  exactly like your script, then attaches the resulting files to the job
  and marks it done/failed.

## Going to production

The built-in `threading.Thread` background runner is fine for a single
dev server or low-traffic internal tool, but it has real limits:

- jobs are lost if the process restarts mid-run
- no retry, no concurrency limits, no queue if many people upload at once
- doesn't scale across multiple app server processes/machines

For anything beyond a small internal tool, swap `views.upload_view`'s
`threading.Thread(...)` call for a **Celery** task (`pipeline/tasks.py`)
backed by Redis or RabbitMQ, and run `celery -A vehicle_pipeline worker`
alongside `runserver`/gunicorn. The `run_pipeline(job_id)` function is
already written to be call-by-id, so it drops into a Celery task with
almost no changes — just decorate it with `@shared_task` and swap the
`threading.Thread` call in the view for `run_pipeline.delay(job.pk)`.

Also, before deploying anywhere reachable from the internet:
- set `DJANGO_SECRET_KEY` and `DJANGO_DEBUG=0` as environment variables
- set `DJANGO_ALLOWED_HOSTS` to your real domain
- put uploaded files/media somewhere durable (not local disk) if you're
  running more than one app server
- add authentication in front of the upload form (currently open to
  anyone who can reach the URL) — Django's built-in auth + `@login_required`
  on the views is the quickest way

## Project layout

```
vehicle_pipeline_project/
├── manage.py
├── requirements.txt
├── vehicle_pipeline/        # Django project settings/urls
├── pipeline/                # the app: models, views, templates, services.py
│   ├── models.py            # ProcessingJob
│   ├── forms.py             # UploadForm (file + date)
│   ├── services.py          # <- runs your existing pipeline
│   ├── views.py             # upload / job list / job detail / status JSON
│   └── templates/pipeline/  # upload.html, job_list.html, job_detail.html
├── modules/                 # <- put your existing pipeline modules here
├── data/                    # master_data.json, low_confidence.json
└── media/                   # uploaded files + generated outputs (gitignored)
```
