from config import MIN_CONFIDENCE_THRESHOLD


class Enricher:
    """
    Backfills descriptive attributes onto already-resolved entities:
    - brand  -> country of origin
    - model  -> motor/engine type

    This runs as a separate pass *after* matching/identification, so it
    never blocks or slows down core brand/model resolution, and it can
    be re-run safely at any time to fill in gaps for entities that were
    created before this feature existed (it only calls Gemini for
    entities missing the field, so already-enriched ones are free).
    """

    def __init__(self, gemini_service, database):
        self.gemini_service = gemini_service
        self.database = database

    @staticmethod
    def _chunks(values: list, size: int):
        for start in range(0, len(values), size):
            yield values[start:start + size]

    def enrich_brands(self, brands: list, batch_size: int = 100):
        """
        brands: list of brand entity dicts. Duplicates are fine - they're
        deduped by id. Only brands missing 'country' hit the API.
        """

        unique_brands = {}
        for brand in brands:
            if brand and not brand.get("country"):
                unique_brands[brand["id"]] = brand

        if not unique_brands:
            return

        targets = list(unique_brands.values())

        for chunk in self._chunks(targets, batch_size):

            names = [brand["canonical_name"] for brand in chunk]
            results = self.gemini_service.enrich_brands_batch(names)

            for brand, result in zip(chunk, results):
                if (
                    result
                    and result.get("identified")
                    and result.get("confidence", 1.0) >= MIN_CONFIDENCE_THRESHOLD
                ):
                    self.database.update_entity_fields(
                        entity_type="brand",
                        entity_id=brand["id"],
                        fields={"country": result["country"]},
                        save_immediately=False
                    )

        self.database.save()

    def enrich_models(self, models: list, batch_size: int = 100):
        """
        models: list of model entity dicts. Duplicates are fine - they're
        deduped by id. Only models missing 'motor_type' hit the API.
        Each model must carry a valid brand_id so we can look up the
        brand name for context.
        """

        unique_models = {}
        for model in models:
            if model and not model.get("motor_type"):
                unique_models[model["id"]] = model

        if not unique_models:
            return

        targets = list(unique_models.values())

        for chunk in self._chunks(targets, batch_size):

            items = []
            for model in chunk:
                brand = self.database.data["brand"].get(model.get("brand_id"))
                items.append({
                    "brand_name": brand["canonical_name"] if brand else "",
                    "model_name": model["canonical_name"]
                })

            results = self.gemini_service.enrich_models_batch(items)

            for model, result in zip(chunk, results):
                if (
                    result
                    and result.get("identified")
                    and result.get("confidence", 1.0) >= MIN_CONFIDENCE_THRESHOLD
                ):
                    self.database.update_entity_fields(
                        entity_type="model",
                        entity_id=model["id"],
                        fields={"motor_type": result["motor_type"]},
                        save_immediately=False
                    )

        self.database.save()
