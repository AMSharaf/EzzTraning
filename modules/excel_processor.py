import pandas as pd
import json
import os

from sqlalchemy import text
from modules.db_sync import get_sql_engine

class ExcelProcessor:
    def __init__(self, batch_resolver):
        self.batch_resolver = batch_resolver
        self.last_filtered_df = None

    def _log_unique_json(self, new_records_list, json_file_path):
        if not new_records_list:
            return
        os.makedirs(os.path.dirname(json_file_path), exist_ok=True)
        df_new = pd.DataFrame(new_records_list)

        if os.path.exists(json_file_path):
            try:
                df_existing = pd.read_json(json_file_path)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            except Exception:
                df_combined = df_new
        else:
            df_combined = df_new

        df_combined = df_combined.drop_duplicates()
        df_combined.to_json(json_file_path, orient="records", indent=4, force_ascii=False)

    def process(
            self, input_file, output_file, skip_rows, target_columns,
              new_headers, report_date, filtered_output_file=None,
              extra_columns=None, new_extra_headers=None,
              filter_private=True
        ):
            df = pd.read_excel(input_file, skiprows=skip_rows)
            
            # Parse report_date and extract separate Year and Month columns
            parsed_date = pd.to_datetime(report_date)
            df['Reporting_Date'] = parsed_date
            df['Year'] = parsed_date.year
            df['Month'] = parsed_date.month
            
            resolved_targets = [df.columns[col] if isinstance(col, int) else col for col in target_columns]

            resolved_extras = []
            final_extra_headers = []
            if extra_columns:
                for col in extra_columns:
                    resolved_extras.append(df.columns[col] if isinstance(col, int) else col)
                
                if new_extra_headers and len(new_extra_headers) == len(extra_columns):
                    final_extra_headers = new_extra_headers
                else:
                    final_extra_headers = resolved_extras

            rename_dict = dict(zip(resolved_targets, new_headers))
            if extra_columns:
                rename_dict.update(dict(zip(resolved_extras, final_extra_headers)))
            
            df = df.rename(columns=rename_dict)

            # Ensure Reporting_Date, Year, and Month are kept along with headers and extra columns
            columns_to_keep = new_headers.copy() + final_extra_headers
            for col in ['Reporting_Date', 'Year', 'Month']:
                if col not in columns_to_keep:
                    columns_to_keep.append(col)
                
            df_processed = df[columns_to_keep].copy()

            if "Model" in df_processed.columns:
                df_processed = df_processed.dropna(subset=["Model"])
                model_str = df_processed["Model"].astype(str).str.strip()
                df_processed = df_processed[(model_str != "") & (model_str.str.lower() != "nan")]

            df_processed = self._resolve_columns(df_processed)

            unmatched_records = []
            id_cols_present = [c for c in ("brand_id", "model_id") if c in df_processed.columns]
            if id_cols_present:
                for _, row in df_processed.iterrows():
                    if any(pd.isna(row.get(c)) for c in id_cols_present):
                        unmatched_records.append({
                            "Brand": str(row.get("Brand")),
                            "Model": str(row.get("Model")),
                            "License Type": str(row.get("License Type")),
                            "Governorate": str(row.get("Governorate")),
                            "Reason": "Unmatched or low-confidence mapping"
                        })

            if unmatched_records:
                self._log_unique_json(unmatched_records, "data/low_confidence_review.json")
                print(f"⚠️ Logged unique unmapped records to 'data/low_confidence_review.json'")

            if final_extra_headers:
                main_cols = [c for c in df_processed.columns if c not in final_extra_headers] + final_extra_headers
                df_processed = df_processed[main_cols]

            df_processed.to_excel(output_file, index=False)
            print(f"✓ Saved full dataset with all details to {output_file}")

            if not filtered_output_file:
                filtered_output_file = str(output_file).replace(".xlsx", "_filtered_private.xlsx")
            
            df_filtered = df_processed.copy()

            essential_cols = [c for c in ["brand_id", "model_id", "license_type_id", "governorate_id"] if c in df_filtered.columns]
            if essential_cols:
                df_filtered = df_filtered.dropna(subset=essential_cols)

            # Filter for Private license type (optional - controlled by filter_private)
            if filter_private and "license_type_canonical_name" in df_filtered.columns:
                is_private = df_filtered["license_type_canonical_name"].astype(str).str.lower().isin(["private", "ملاكي"])
                df_filtered = df_filtered[is_private]

            # Filter for rows that have a valid value in the 'Count' column
            count_col = next((c for c in df_filtered.columns if c.lower() == 'count'), None)
            if count_col:
                df_filtered = df_filtered.dropna(subset=[count_col])

            meta_cols = [c for c in ["model_motor_type", "brand_country"] if c in df_filtered.columns]
            if meta_cols:
                missing_meta_mask = df_filtered[meta_cols].isna().any(axis=1)
                df_missing = df_filtered[missing_meta_mask]
                
                if not df_missing.empty:
                    missing_json_file = str(filtered_output_file).replace(".xlsx", "_missing_metadata.json")
                    missing_records = []
                    for _, row in df_missing.iterrows():
                        brand_name = row.get("brand_canonical_name", "Unknown")
                        model_name = row.get("model_canonical_name", "Unknown")
                        if pd.isna(row.get("brand_country")):
                            missing_records.append({"brand": brand_name, "model": model_name, "missing": "brand_country"})
                        if pd.isna(row.get("model_motor_type")):
                            missing_records.append({"brand": brand_name, "model": model_name, "missing": "model_motor_type"})
                    if missing_records:
                        self._log_unique_json(missing_records, missing_json_file)
                        print(f"⚠️ Logged unique metadata errors to '{missing_json_file}'")
                
                df_filtered = df_filtered.dropna(subset=meta_cols)
            self.last_filtered_df = df_filtered
            # Filter for Private license type (optional - controlled by filter_private)
            if filter_private and "license_type_canonical_name" in df_filtered.columns:
                is_private = df_filtered["license_type_canonical_name"].astype(str).str.lower().isin(["private", "ملاكي"])
                df_filtered = df_filtered[is_private]
            # Drop old raw attributes and ID columns from the filtered output
            cols_to_drop = [
                'brand_id', 'model_id', 'license_type_id', 'governorate_id',
                'Brand', 'Model', 'License Type', 'Governorate'
            ]
            df_filtered = df_filtered.drop(columns=[c for c in cols_to_drop if c in df_filtered.columns], errors='ignore')

            # Store the filtered dataframe instance for explicit persistence calls

            df_filtered.to_excel(filtered_output_file, index=False)
            print(f"✓ Saved clean/filtered dataset to {filtered_output_file}")

            return df_processed

    def persist_to_database(self, dataframe, source_file, year, month, extra_columns=None):
        """
        Pushes the filtered dataset and its associated extra attributes to SQL Server.
        """
        if dataframe is None or dataframe.empty:
            print("⚠️ DataFrame is empty. Nothing to persist to database.")
            return

        report_date = f"{year}-{month:02d}-01"

        extra_headers = extra_columns or []
        if not extra_headers:
            extra_headers = [c for c in dataframe.columns if c not in [
                'brand_id', 'model_id', 'license_type_id', 'governorate_id',
                'Brand', 'Model', 'License Type', 'Governorate',
                'brand', 'model_canonical_name', 'license_type_canonical_name', 'governorate_canonical_name',
                'brand_country', 'model_motor_type'
            ]]

        count_col = next((c for c in dataframe.columns if c.lower() == 'count'), None)
        if not count_col:
            print("⚠️ No 'Count' column found. Nothing to persist to database.")
            return

        # Guarantee all four ID columns exist. If the source file didn't have
        # a given field at all (e.g. no License Type column), fill it with
        # None so it's inserted as NULL, instead of KeyError-ing later.
        id_col_map = {
            'brand_id': 'Brand_ID',
            'model_id': 'Model_ID',
            'license_type_id': 'LicenseType_ID',
            'governorate_id': 'Governorate_ID',
        }

        fact_df = pd.DataFrame(index=dataframe.index)
        for raw_col, renamed_col in id_col_map.items():
            fact_df[renamed_col] = dataframe[raw_col] if raw_col in dataframe.columns else None

        fact_df['Vehicle_Count'] = dataframe[count_col]
        fact_df['Reporting_Date'] = pd.to_datetime(report_date)

        present_extras = [c for c in extra_headers if c in dataframe.columns]
        for col in present_extras:
            fact_df[col] = dataframe[col]

        try:
            self._push_fact_table(fact_df, extra_columns=present_extras)
            print(f"✓ Successfully uploaded monthly batch updates to SQL Server for {report_date}.")
        except Exception as e:
            print(f"❌ Failed to upload updates to SQL Server: {e}")
    def _push_fact_table(self, fact_df: pd.DataFrame, extra_columns: list):
        engine = get_sql_engine()
        print(f"Pushing {len(fact_df)} records to SQL Server Fact_Vehicles...")

        with engine.begin() as connection:
            for _, row in fact_df.iterrows():
                result = connection.execute(text("""
                    INSERT INTO Fact_Vehicles (Brand_ID, Model_ID, LicenseType_ID, Governorate_ID, Vehicle_Count, Reporting_Date)
                    OUTPUT INSERTED.Fact_ID
                    VALUES (:brand_id, :model_id, :license_type_id, :governorate_id, :vehicle_count, :reporting_date)
                """), {
                    "brand_id": row["Brand_ID"],
                    "model_id": row["Model_ID"],
                    "license_type_id": row["LicenseType_ID"],
                    "governorate_id": row["Governorate_ID"],
                    "vehicle_count": row["Vehicle_Count"],
                    "reporting_date": row["Reporting_Date"],
                })
                fact_id = result.scalar()

                for column in extra_columns:
                    value = row.get(column)
                    if pd.isna(value):
                        continue
                    connection.execute(text("""
                        INSERT INTO Fact_Vehicles_Extra_Attributes (Fact_ID, Attribute_Name, Attribute_Value)
                        VALUES (:fact_id, :attribute_name, :attribute_value)
                    """), {"fact_id": fact_id, "attribute_name": column, "attribute_value": str(value)})

    def _resolve_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        has_brand = "Brand" in df.columns
        has_model = "Model" in df.columns
        has_license = "License Type" in df.columns
        has_governorate = "Governorate" in df.columns

        brand_results = {}
        model_results = {}
        license_results = {}
        governorate_results = {}

        if has_brand:
            brand_results = self.batch_resolver.resolve_brands(df["Brand"].tolist())

        if has_brand and has_model:
            model_rows = []
            for _, row in df.iterrows():
                raw_brand = self._clean(row.get("Brand"))
                raw_model = self._clean(row.get("Model"))
                brand = brand_results.get(raw_brand)
                if brand:
                    model_rows.append({"brand": brand, "raw_model": raw_model})
            model_results = self.batch_resolver.resolve_models(model_rows)

        if has_license:
            license_results = self.batch_resolver.resolve_license_types(df["License Type"].tolist())

        if has_governorate:
            governorate_results = self.batch_resolver.resolve_governorates(df["Governorate"].tolist())

        brand_ids, brand_names, brand_countries = [], [], []
        model_ids, model_names, motor_types = [], [], []
        license_ids, license_names = [], []
        governorate_ids, governorate_names = [], []

        for _, row in df.iterrows():
            brand = brand_results.get(self._clean(row.get("Brand"))) if has_brand else None
            model = model_results.get((brand["id"], self._clean(row.get("Model")))) if (has_brand and has_model and brand) else None
            license_entity = license_results.get(self._clean(row.get("License Type"))) if has_license else None
            governorate_entity = governorate_results.get(self._clean(row.get("Governorate"))) if has_governorate else None

            brand_ids.append(brand["id"] if brand else None)
            brand_names.append(brand["canonical_name"] if brand else None)
            brand_countries.append(brand.get("country") if brand else None)

            model_ids.append(model["id"] if model else None)
            model_names.append(model["canonical_name"] if model else None)
            motor_types.append(model.get("motor_type") if model else None)

            license_ids.append(license_entity["id"] if license_entity else None)
            license_names.append(license_entity["canonical_name"] if license_entity else None)

            governorate_ids.append(governorate_entity["id"] if governorate_entity else None)
            governorate_names.append(governorate_entity["canonical_name"] if governorate_entity else None)

        if has_brand:
            df["brand_id"] = brand_ids
            df["brand_canonical_name"] = brand_names
            df["brand_country"] = brand_countries

        if has_brand and has_model:
            df["model_id"] = model_ids
            df["model_canonical_name"] = model_names
            df["model_motor_type"] = motor_types

        if has_license:
            df["license_type_id"] = license_ids
            df["license_type_canonical_name"] = license_names

        if has_governorate:
            df["governorate_id"] = governorate_ids
            df["governorate_canonical_name"] = governorate_names

        return df

    @staticmethod
    def _clean(value) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and pd.isna(value):
            return ""
        text = str(value).strip()
        return "" if text.lower() == "nan" else text
