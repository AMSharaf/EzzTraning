import json
from pathlib import Path
from modules.normalizer import Normalizer
from modules.db_sync import sync_master_database

class Database:
    def __init__(self, database_file: str | Path, _preloaded_data=None):
        self.database_file = Path(database_file)
        if _preloaded_data is not None:
            self.data = _preloaded_data
        else:
            self.data = self.load()

    def empty_database(self):
        return {
            "_metadata": {
                "next_brand_id": 1,
                "next_model_id": 1,
                "next_license_type_id": 1,
                "next_governorate_city_id": 1
            },
            "brand": {},
            "model": {},
            "license_type": {},
            "governorate_city": {}
        }

    def load(self):
        if not self.database_file.exists():
            return self.empty_database()
        with open(self.database_file, "r", encoding="utf-8") as file:
            return json.load(file)

    def save(self):
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.database_file, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=4)
        
        # Automatically sync master data dimensions to SQL Server on every save
        try:
            sync_master_database(self)
        except Exception as e:
            print(f"⚠️ Warning: Failed to sync master data to SQL Server: {e}")

    def next_id(self, entity_type: str, save_immediately: bool = True) -> str:
        prefixes = {
            "brand": "BR",
            "model": "MD",
            "license_type": "LT",
            "governorate_city": "LOC"
        }
        counters = {
            "brand": "next_brand_id",
            "model": "next_model_id",
            "license_type": "next_license_type_id",
            "governorate_city": "next_governorate_city_id"
        }
        prefix = prefixes[entity_type]
        counter_key = counters[entity_type]
        current_number = self.data["_metadata"][counter_key]
        new_id = f"{prefix}{current_number:05d}"
        self.data["_metadata"][counter_key] += 1
        if save_immediately:
            self.save()
        return new_id

    def create_entity(self, entity_type: str, canonical_name: str, brand_id: str = None, save_immediately: bool = True):
        entity_id = self.next_id(entity_type, save_immediately=False)
        normalized_name = Normalizer.normalize_text(canonical_name)
        entity = {
            "id": entity_id,
            "canonical_name": canonical_name,
            "normalized_name": normalized_name,
            "aliases": [normalized_name],
            "mappings": []
        }
        if entity_type == "model":
            entity["brand_id"] = brand_id
        self.data[entity_type][entity_id] = entity
        if save_immediately:
            self.save()
        return entity

    def find_by_alias(self, entity_type: str, alias: str, brand_id: str = None):
        alias = Normalizer.normalize_text(alias)
        for entity in self.data[entity_type].values():
            if entity_type == "model" and entity["brand_id"] != brand_id:
                continue
            if alias in entity["aliases"]:
                return entity
        return None

    def find_by_canonical_name(self, entity_type, canonical_name):
        normalized = Normalizer.normalize_text(canonical_name)
        for entity in self.data[entity_type].values():
            if entity["normalized_name"] == normalized:
                return entity
        return None

    def find_by_canonical_name_and_brand(self, canonical_name: str, brand_id: str):
        # NOTE: this used to compare raw canonical_name strings exactly,
        # which meant any whitespace/case drift in what Gemini returned
        # (e.g. "1" vs " 1" vs "1 ") caused this lookup to miss an
        # already-existing model and silently create a duplicate entity.
        # Comparing normalized_name (as find_by_canonical_name already
        # does for brand/license_type/governorate_city) makes this
        # lookup robust the same way.
        normalized = Normalizer.normalize_text(canonical_name)
        for model in self.data["model"].values():
            if model.get("normalized_name") == normalized and model["brand_id"] == brand_id:
                return model
        return None

    def find_by_brand_id(self, entity_type: str, brand_id: str):
        entities = []
        for entity in self.data[entity_type].values():
            if entity.get("brand_id") == brand_id:
                entities.append(entity)
        return entities

    def add_alias(self, entity_type: str, entity_id: str, alias: str, save_immediately: bool = True):
        alias = Normalizer.normalize_text(alias)
        entity = self.data[entity_type][entity_id]
        if alias not in entity["aliases"]:
            entity["aliases"].append(alias)
            if save_immediately:
                self.save()

    def update_entity_fields(
        self,
        entity_type: str,
        entity_id: str,
        fields: dict,
        save_immediately: bool = True
    ):
        entity = self.data[entity_type][entity_id]
        entity.update(fields)
        if save_immediately:
            self.save()

    def get_all_entities(self, entity_type: str, brand_id: str = None):
        entities = list(self.data[entity_type].values())
        if entity_type != "model":
            return entities
        return [entity for entity in entities if entity["brand_id"] == brand_id]