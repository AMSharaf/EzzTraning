from config import GEMINI_BATCH_SIZE

class BatchResolver:
    def __init__(self, matcher, enricher=None, batch_size: int = GEMINI_BATCH_SIZE):
        self.matcher = matcher
        self.enricher = enricher
        self.batch_size = batch_size
        self.brand_cache = {}
        self.model_cache = {}
        self.license_cache = {}
        self.governorate_cache = {}

    def _get_unique_list(self, raw_values):
        return list(dict.fromkeys(
            str(val).strip() for val in raw_values 
            if val is not None and str(val).strip() and str(val).strip().lower() != "nan"
        ))

    def resolve_brands(self, raw_brands):
        results = {}
        unique_brands = self._get_unique_list(raw_brands)
        to_resolve = []

        for raw_brand in unique_brands:
            cache_key = raw_brand.lower()
            if cache_key in self.brand_cache:
                results[raw_brand] = self.brand_cache[cache_key]
            else:
                to_resolve.append(raw_brand)

        if to_resolve:
            resolved = self.matcher.resolve_brands_batch(raw_brands=to_resolve, batch_size=self.batch_size)
            for raw_brand, brand in resolved.items():
                self.brand_cache[raw_brand.lower()] = brand
                results[raw_brand] = brand

        if self.enricher:
            self.enricher.enrich_brands([b for b in results.values() if b], batch_size=self.batch_size)

        return results

    def resolve_models(self, rows):
        results = {}
        to_resolve_rows = []
        seen = set()

        for row in rows:
            brand = row["brand"]
            if not brand: continue
            raw_model = str(row["raw_model"]).strip()
            if not raw_model or raw_model.lower() == "nan": continue

            cache_key = (brand["id"], raw_model.lower())
            if cache_key in self.model_cache:
                results[(brand["id"], raw_model)] = self.model_cache[cache_key]
                continue
            if cache_key in seen:
                continue

            seen.add(cache_key)
            to_resolve_rows.append({"brand": brand, "raw_model": raw_model})

        if to_resolve_rows:
            resolved = self.matcher.resolve_models_batch(rows=to_resolve_rows, batch_size=self.batch_size)
            for (brand_id, raw_model), model in resolved.items():
                self.model_cache[(brand_id, raw_model.lower())] = model
                results[(brand_id, raw_model)] = model

        if self.enricher:
            self.enricher.enrich_models([m for m in results.values() if m], batch_size=self.batch_size)

        return results

    def resolve_license_types(self, raw_licenses):
        results = {}
        unique_licenses = self._get_unique_list(raw_licenses)
        to_resolve = []

        for raw_lic in unique_licenses:
            cache_key = raw_lic.lower()
            if cache_key in self.license_cache:
                results[raw_lic] = self.license_cache[cache_key]
            else:
                to_resolve.append(raw_lic)

        if to_resolve:
            resolved = self.matcher.resolve_generic_batch(
                entity_type="license_type",
                entity_desc="vehicle license type",
                raw_values=to_resolve,
                batch_size=self.batch_size
            )
            for raw_lic, entity in resolved.items():
                self.license_cache[raw_lic.lower()] = entity
                results[raw_lic] = entity

        return results

    def resolve_governorates(self, raw_governorates):
        results = {}
        unique_govs = self._get_unique_list(raw_governorates)
        to_resolve = []

        for raw_gov in unique_govs:
            cache_key = raw_gov.lower()
            if cache_key in self.governorate_cache:
                results[raw_gov] = self.governorate_cache[cache_key]
            else:
                to_resolve.append(raw_gov)

        if to_resolve:
            resolved = self.matcher.resolve_generic_batch(
                entity_type="governorate_city",
                entity_desc="governorate or city",
                raw_values=to_resolve,
                batch_size=self.batch_size
            )
            for raw_gov, entity in resolved.items():
                self.governorate_cache[raw_gov.lower()] = entity
                results[raw_gov] = entity

        return results
