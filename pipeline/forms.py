from django import forms
from .models import ProcessingJob


class UploadForm(forms.ModelForm):
    class Meta:
        model = ProcessingJob
        fields = ["uploaded_file", "report_date", "filter_private"]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "uploaded_file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "filter_private": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "uploaded_file": "Excel file (.xlsx)",
            "report_date": "Report date",
            "filter_private": "Only include Private license type in the filtered / SQL Server output",
        }

    def clean_uploaded_file(self):
        f = self.cleaned_data["uploaded_file"]
        if not f.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
            raise forms.ValidationError("Please upload an Excel file (.xlsx/.xls/.xlsm).")
        return f
