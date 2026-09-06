import json
import os

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from modules.normalizer import Normalizer
from config import (
    MIN_CONFIDENCE_THRESHOLD,
    FUZZY_MATCH_THRESHOLD,
    FUZZY_HIGH_CONFIDENCE_THRESHOLD
)

SHORT_VALUE_MAX_LENGTH = 6
SHORT_VALUE_MAX_EDIT_DISTANCE = 1


def _simple_normalize(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _strip_brand_prefix(name: str, brand_name: str) -> str:
    n = _simple_normalize(name)
    b = _simple_normalize(brand_name) if brand_name else ""
    if b and n.startswith(b):
        n = n[len(b):].strip()
    return n


# Deliberately narrow, fixed dictionary - NOT fuzzy/partial matching.
# Mirrors the same safe design already used in merge_duplicates.py's
# number_word_to_digit(). Only fires when the ENTIRE remaining text
# (after stripping a brand prefix, if present) is exactly one of these
# words, so it can never corrupt a real model name that merely contains
# one of these words as part of something longer.
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10",
}


def _normalize_number_word(raw_model: str, brand_name: str = None) -> str:
    """
    Converts a spelled-out number word - optionally with a brand prefix,
    e.g. "MG One" or "One" - into its digit form ("1"), applied to the
    RAW value before it ever reaches caching/DB-lookup/AI matching.

    Why this exists: previously this conversion only happened inside the
    AI prompt (gemini_service.py, WORD FORM VS DIGIT FORM rule), and an
    LLM call is not 100% deterministic - it would sometimes return "One"
    and sometimes "1" for the exact same raw input across different
    calls, silently creating duplicate model entities (see
    DUPLICATE_MODEL_FINDINGS.md, MG "One"/"1" pair). Normalizing the raw
    text deterministically before resolution removes that ambiguity at
    the source, so identical input always produces identical output
    regardless of what the AI happens to return.
    """
    stripped = (
        _strip_brand_prefix(raw_model, brand_name)
        if brand_name else _simple_normalize(raw_model)
    )
    if stripped in _NUMBER_WORDS:
        return _NUMBER_WORDS[stripped]
    return raw_model


def _same_model_deterministic(name_a: str, name_b: str, brand_name: str) -> bool:
    """
    True when name_a and name_b are almost certainly the same real model
    once brand-prefix differences are removed.
    
    Word-to-digit conversion logic has been completely removed to prevent
    corrupting proper vehicle names like 'MG One' into '1'.
    """
    a_norm = _simple_normalize(name_a)
    b_norm = _simple_normalize(name_b)
    if a_norm == b_norm:
        return True

    a_strip = _strip_brand_prefix(name_a, brand_name)
    b_strip = _strip_brand_prefix(name_b, brand_name)

    if a_strip and a_strip == b_norm:
        return True
    if b_strip and b_strip == a_norm:
        return True

    return False


def _find_unique_numeric_completion(bare_number: str, candidate_names: list) -> str | None:
    """
    Handles the "BMW 528 vs 528i" shape specifically: a bare numeric
    canonical_name (528) that is really just the incomplete engine/
    trim code for an already-known lettered model (528i).

    IMPORTANT SAFETY CHECK: the remainder after the bare number must be
    a short, letter-only engine/trim code (e.g. "i", "d", "h", "li"),
    NOT a whole separate word. Without this check, "4" would also count
    as a "completion" of "4Runner" (since "R" isn't a digit either),
    silently reusing a completely unrelated model - this exact bug is
    what let MG "4" resolve to Toyota's "4Runner". This mirrors the
    AI prompt's own restriction in gemini_service.py: "Prefix completion
    is strictly reserved for tight alphanumeric code variations, never
    compound word formations."
    """
    bare = _simple_normalize(bare_number)
    if not bare.isdigit():
        return None

    MAX_SUFFIX_LENGTH = 3

    completions = []
    for name in candidate_names:
        n = _simple_normalize(name)
        if n == bare or not n.startswith(bare):
            continue

        remainder = n[len(bare):]

        # Must be a tight alphabetic engine/trim code, never a separate
        # word (e.g. "runner", "series") and never containing a space
        # (which would signal a genuinely different, longer model name).
        if remainder.isalpha() and len(remainder) <= MAX_SUFFIX_LENGTH:
            completions.append(name)

    unique = list(dict.fromkeys(completions))
    if len(unique) == 1:
        return unique[0]
    return None


class Matcher:
    def __init__(
        self,
        database,
        gemini_service,
        low_confidence_file="low_confidence.json"
    ):
        self.database = database
        self.gemini_service = gemini_service
        self.low_confidence_file = low_confidence_file
        self.unresolved_log = []

    # ============================================================
    # Logging
    # ============================================================

    def _log_low_confidence(
        self,
        entity_type: str,
        raw_value: str,
        reason: str,
        extra_info: dict = None
    ):
        entry = {
            "entity_type": entity_type,
            "raw_value": raw_value,
            "reason": reason
        }

        if extra_info:
            entry.update(extra_info)

        self.unresolved_log.append(entry)

    def _save_low_confidence_log(self):
        if not self.unresolved_log:
            return

        existing_data = []

        if os.path.exists(self.low_confidence_file):
            try:
                with open(
                    self.low_confidence_file,
                    "r",
                    encoding="utf-8"
                ) as f:
                    existing_data = json.load(f)

                if not isinstance(existing_data, list):
                    existing_data = []

            except (json.JSONDecodeError, IOError):
                existing_data = []

        existing_data.extend(self.unresolved_log)

        with open(
            self.low_confidence_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                existing_data,
                f,
                ensure_ascii=False,
                indent=4
            )

        print(
            f"⚠️ Logged {len(self.unresolved_log)} "
            f"unmapped/low-confidence items to "
            f"'{self.low_confidence_file}'."
        )

        self.unresolved_log = []

    # ============================================================
    # Basic Helpers
    # ============================================================

    @staticmethod
    def _is_numeric_model_value(value: str) -> bool:
        normalized = Normalizer.normalize_text(value)
        return bool(normalized) and normalized.isdigit()

    @staticmethod
    def _chunks(values: list, size: int):
        if size <= 0:
            raise ValueError("Batch size must be greater than zero.")

        for start in range(0, len(values), size):
            yield values[start:start + size]

    @staticmethod
    def _normalize_for_comparison(value: str) -> str:
        return Normalizer.normalize_text(str(value))

    # ============================================================
    # Local Exact Matching
    # ============================================================

    def exact_match(
        self,
        entity_type: str,
        raw_value: str,
        brand_id=None
    ):
        normalized_value = self._normalize_for_comparison(raw_value)

        for entity in self.database.data[entity_type].values():
            if entity.get("normalized_name") != normalized_value:
                continue

            if (
                entity_type == "model"
                and entity.get("brand_id") != brand_id
            ):
                continue

            return entity

        return None

    # ============================================================
    # Fuzzy Matching
    # ============================================================

    def _fuzzy_match(
        self,
        entity_type: str,
        raw_value: str,
        threshold: int = FUZZY_MATCH_THRESHOLD,
        brand_id=None
    ):
        normalized_value = self._normalize_for_comparison(raw_value)

        if (
            entity_type == "model"
            and self._is_numeric_model_value(normalized_value)
        ):
            return None, 0

        best_entity = None
        best_score = 0

        for entity in self.database.get_all_entities(
            entity_type,
            brand_id
        ):
            for alias in entity.get("aliases", []):
                normalized_alias = self._normalize_for_comparison(alias)

                score = fuzz.ratio(
                    normalized_value,
                    normalized_alias
                )

                if score > best_score:
                    best_score = score
                    best_entity = entity

        if best_entity and best_score >= threshold:
            return best_entity, best_score

        return None, best_score

    # ============================================================
    # Short Edit-Distance Matching
    # ============================================================

    def _short_value_typo_match(
        self,
        entity_type: str,
        raw_value: str,
        brand_id=None
    ):
        normalized_value = self._normalize_for_comparison(raw_value)

        if len(normalized_value) > SHORT_VALUE_MAX_LENGTH:
            return None

        if (
            entity_type == "model"
            and self._is_numeric_model_value(normalized_value)
        ):
            return None

        best_distance = None
        best_entity_ids = set()
        best_entity = None

        for entity in self.database.get_all_entities(
            entity_type,
            brand_id
        ):
            for alias in entity.get("aliases", []):
                normalized_alias = self._normalize_for_comparison(alias)

                if len(normalized_alias) > SHORT_VALUE_MAX_LENGTH:
                    continue

                distance = Levenshtein.distance(
                    normalized_value,
                    normalized_alias
                )

                if distance > SHORT_VALUE_MAX_EDIT_DISTANCE:
                    continue

                if (
                    best_distance is None
                    or distance < best_distance
                ):
                    best_distance = distance
                    best_entity = entity
                    best_entity_ids = {entity["id"]}

                elif distance == best_distance:
                    best_entity_ids.add(entity["id"])

        if best_entity is None:
            return None

        if len(best_entity_ids) != 1:
            return None

        return best_entity

    # ============================================================
    # Existing Entity Resolution
    # ============================================================

    def _resolve_existing(
        self,
        entity_type: str,
        raw_value: str,
        brand_id: str = None,
        save_immediately: bool = True
    ):
        if raw_value is None:
            return None

        raw_value = str(raw_value).strip()

        if not raw_value:
            return None

        entity = self.exact_match(
            entity_type,
            raw_value,
            brand_id
        )

        if entity:
            return entity

        numeric_model_value = (
            entity_type == "model"
            and self._is_numeric_model_value(raw_value)
        )

        if not numeric_model_value:
            entity = self._short_value_typo_match(
                entity_type,
                raw_value,
                brand_id=brand_id
            )

            if entity:
                self._log_low_confidence(
                    entity_type=entity_type,
                    raw_value=raw_value,
                    reason=(
                        "Accepted via short-value edit-distance "
                        "match (likely typo)"
                    ),
                    extra_info={
                        "matched_entity_id": entity["id"],
                        "matched_canonical_name": entity["canonical_name"]
                    }
                )

                self.database.add_alias(
                    entity_type,
                    entity["id"],
                    raw_value,
                    save_immediately=save_immediately
                )

                return entity

        if not numeric_model_value:
            entity, score = self._fuzzy_match(
                entity_type,
                raw_value,
                brand_id=brand_id
            )

            if entity:
                if score < FUZZY_HIGH_CONFIDENCE_THRESHOLD:
                    self._log_low_confidence(
                        entity_type=entity_type,
                        raw_value=raw_value,
                        reason=(
                            f"Accepted via medium-confidence "
                            f"fuzzy match ({score}%)"
                        ),
                        extra_info={
                            "matched_entity_id": entity["id"],
                            "matched_canonical_name": entity["canonical_name"],
                            "fuzzy_score": score
                        }
                    )

                self.database.add_alias(
                    entity_type,
                    entity["id"],
                    raw_value,
                    save_immediately=save_immediately
                )

                return entity

        return None

    # ============================================================
    # Generic Entity Batch Resolution
    # ============================================================

    def resolve_generic_batch(
        self,
        entity_type: str,
        entity_desc: str,
        raw_values: list,
        batch_size: int = 100
    ) -> dict:
        results = {}
        unresolved = []

        print(
            f"\n--- Processing {len(raw_values)} "
            f"'{entity_desc}' items ---"
        )

        print(
            "⚡ Phase 1: Checking local DB "
            "(Exact & Fuzzy match)..."
        )

        for raw_val in raw_values:
            if raw_val is None:
                continue

            raw_val = str(raw_val).strip()

            if not raw_val:
                continue

            entity = self._resolve_existing(
                entity_type,
                raw_val,
                save_immediately=False
            )

            if entity:
                results[raw_val] = entity
            else:
                unresolved.append(raw_val)

        print(
            f"✓ Local match completed: "
            f"{len(results)} resolved, "
            f"{len(unresolved)} unresolved."
        )

        if not unresolved:
            self.database.save()
            self._save_low_confidence_log()
            return results

        existing_entities = self.database.get_all_entities(
            entity_type
        )

        entity_names = [
            ent["canonical_name"]
            for ent in existing_entities
        ]

        still_unresolved = []

        if entity_names:
            print(
                f"⚡ Phase 2: AI Matching unresolved "
                f"{entity_desc} entries against existing DB entries..."
            )

            for chunk in self._chunks(
                unresolved,
                batch_size
            ):
                match_results = (
                    self.gemini_service.match_entities_batch(
                        entity_name=entity_desc,
                        raw_values=chunk,
                        existing_entities=entity_names
                    )
                )

                for raw_val, result in zip(
                    chunk,
                    match_results
                ):
                    if (
                        result
                        and result.get("matched")
                        and result.get("confidence", 1.0)
                        >= MIN_CONFIDENCE_THRESHOLD
                    ):
                        canonical_name = result.get(
                            "canonical_name"
                        )

                        if canonical_name:
                            entity = (
                                self.database
                                .find_by_canonical_name(
                                    entity_type,
                                    canonical_name
                                )
                            )

                            if entity:
                                self.database.add_alias(
                                    entity_type,
                                    entity["id"],
                                    raw_val,
                                    save_immediately=False
                                )

                                results[raw_val] = entity
                                continue

                    still_unresolved.append(raw_val)
        else:
            still_unresolved = unresolved

        created_this_run = {}

        if still_unresolved:
            print(
                f"⚡ Phase 3: AI Identification for remaining "
                f"{len(still_unresolved)} unmapped entries..."
            )

            for chunk in self._chunks(
                still_unresolved,
                batch_size
            ):
                identify_results = (
                    self.gemini_service.identify_entities_batch(
                        entity_name=entity_desc,
                        raw_values=chunk
                    )
                )

                for raw_val, result in zip(
                    chunk,
                    identify_results
                ):
                    if (
                        result
                        and result.get("identified")
                        and result.get("confidence", 1.0)
                        >= MIN_CONFIDENCE_THRESHOLD
                    ):
                        canonical_name = result.get(
                            "canonical_name"
                        )

                        if not canonical_name:
                            self._log_low_confidence(
                                entity_type=entity_type,
                                raw_value=raw_val,
                                reason=(
                                    "AI identified the entity but "
                                    "returned an empty canonical name"
                                ),
                                extra_info={
                                    "ai_response": result
                                }
                            )

                            results[raw_val] = None
                            continue

                        dedup_key = self._normalize_for_comparison(
                            canonical_name
                        )

                        entity = (
                            created_this_run.get(dedup_key)
                            or self.database.find_by_canonical_name(
                                entity_type,
                                canonical_name
                            )
                        )

                        if not entity:
                            entity = self.database.create_entity(
                                entity_type,
                                canonical_name,
                                save_immediately=False
                            )

                            created_this_run[dedup_key] = entity

                        self.database.add_alias(
                            entity_type,
                            entity["id"],
                            raw_val,
                            save_immediately=False
                        )

                        results[raw_val] = entity

                    else:
                        self._log_low_confidence(
                            entity_type=entity_type,
                            raw_value=raw_val,
                            reason=(
                                "Unidentified or low confidence by AI"
                            ),
                            extra_info={
                                "ai_response": result
                            }
                        )

                        results[raw_val] = None

        self.database.save()
        self._save_low_confidence_log()

        print(
            f"✓ All '{entity_desc}' items processed "
            f"and database updated."
        )

        return results

    # ============================================================
    # Brand Resolution
    # ============================================================

    def resolve_brands_batch(
        self,
        raw_brands: list,
        batch_size: int = 100
    ) -> dict:
        return self.resolve_generic_batch(
            "brand",
            "brand",
            raw_brands,
            batch_size
        )

    # ============================================================
    # Model Resolution
    # ============================================================

    def resolve_models_batch(
        self,
        rows: list,
        batch_size: int = 100
    ) -> dict:
        results = {}

        unique_model_requests = []
        seen_keys = set()

        for row in rows:
            brand = row.get("brand")

            if not brand:
                continue

            raw_model_original = str(
                row.get("raw_model", "")
            ).strip()

            if (
                not raw_model_original
                or raw_model_original.lower() == "nan"
            ):
                continue

            # Deterministically fold spelled-out number words ("One",
            # "MG One") to their digit form ("1") for MATCHING purposes
            # only - see _normalize_number_word() docstring for why.
            #
            # IMPORTANT: the dict key returned to the caller must stay
            # keyed on raw_model_original, NOT the normalized value.
            # batch_resolver.py / excel_processor.py look up results by
            # the exact raw text that came out of the Excel file (e.g.
            # "One"); if the key were normalized to "1" instead, any row
            # whose raw text was literally "One" would fail that lookup,
            # get treated as unmatched, and silently vanish from the
            # final output. Normalization must only affect WHICH entity
            # gets resolved/created, never the key the result is stored
            # under.
            raw_model = _normalize_number_word(
                raw_model_original,
                brand.get("canonical_name")
            )

            key = (
                brand["id"],
                raw_model_original
            )

            if key not in seen_keys:
                seen_keys.add(key)

                unique_model_requests.append(
                    {
                        "brand": brand,
                        "raw_model": raw_model,
                        "key": key
                    }
                )

        print(
            f"\n--- Processing "
            f"{len(unique_model_requests)} Unique Model Requests "
            f"(Cross-Brand) ---"
        )

        print(
            "⚡ Phase 1: Checking local DB for models..."
        )

        unresolved_items = []

        for req in unique_model_requests:
            brand_id = req["brand"]["id"]
            raw_model = req["raw_model"]

            entity = self._resolve_existing(
                "model",
                raw_model,
                brand_id=brand_id,
                save_immediately=False
            )

            if entity:
                results[req["key"]] = entity
            else:
                unresolved_items.append(req)

        print(
            f"✓ Local match completed: "
            f"{len(results)} resolved, "
            f"{len(unresolved_items)} unresolved."
        )

        if not unresolved_items:
            self.database.save()
            self._save_low_confidence_log()
            return results

        still_unresolved = []
        match_payloads = []

        for req in unresolved_items:
            brand = req["brand"]

            existing_models = (
                self.database.find_by_brand_id(
                    "model",
                    brand["id"]
                )
            )

            model_names = [
                model["canonical_name"]
                for model in existing_models
            ]

            if model_names:
                match_payloads.append(
                    {
                        "brand_id": brand["id"],
                        "brand_name": brand["canonical_name"],
                        "raw_model": req["raw_model"],
                        "existing_models": model_names,
                        "key": req["key"]
                    }
                )
            else:
                still_unresolved.append(req)

        if match_payloads:
            print(
                f"⚡ Phase 2: AI Matching "
                f"{len(match_payloads)} models across brands "
                f"against known database models..."
            )

            for chunk in self._chunks(
                match_payloads,
                batch_size
            ):
                match_results = (
                    self.gemini_service
                    .match_models_cross_brand_batch(chunk)
                )

                for payload, result in zip(
                    chunk,
                    match_results
                ):
                    if not (
                        result
                        and result.get("matched")
                        and result.get("confidence", 1.0)
                        >= MIN_CONFIDENCE_THRESHOLD
                    ):
                        still_unresolved.append(
                            {
                                "brand": {
                                    "id": payload["brand_id"],
                                    "canonical_name": payload["brand_name"]
                                },
                                "raw_model": payload["raw_model"],
                                "key": payload["key"]
                            }
                        )
                        continue

                    canonical_name = result.get(
                        "canonical_name"
                    )

                    if not canonical_name:
                        still_unresolved.append(
                            {
                                "brand": {
                                    "id": payload["brand_id"],
                                    "canonical_name": payload["brand_name"]
                                },
                                "raw_model": payload["raw_model"],
                                "key": payload["key"]
                            }
                        )
                        continue

                    entity = (
                        self.database
                        .find_by_canonical_name_and_brand(
                            canonical_name=canonical_name,
                            brand_id=payload["brand_id"]
                        )
                    )

                    if entity:
                        self.database.add_alias(
                            "model",
                            entity["id"],
                            payload["raw_model"],
                            save_immediately=False
                        )

                        results[payload["key"]] = entity
                        continue

                    still_unresolved.append(
                        {
                            "brand": {
                                "id": payload["brand_id"],
                                "canonical_name": payload["brand_name"]
                            },
                            "raw_model": payload["raw_model"],
                            "key": payload["key"]
                        }
                    )

        if still_unresolved:
            print(
                f"⚡ Phase 3: AI Cross-Brand Identification "
                f"for {len(still_unresolved)} unmapped models..."
            )

            identify_payloads = []

            for req in still_unresolved:
                brand_id = req["brand"]["id"]

                existing_models = (
                    self.database.find_by_brand_id(
                        "model",
                        brand_id
                    )
                )

                identify_payloads.append(
                    {
                        "brand_id": brand_id,
                        "brand_name": req["brand"]["canonical_name"],
                        "raw_model": req["raw_model"],
                        "existing_models": [
                            model["canonical_name"]
                            for model in existing_models
                        ],
                        "key": req["key"]
                    }
                )

            created_this_run = {}

            for chunk in self._chunks(
                identify_payloads,
                batch_size
            ):
                identify_results = (
                    self.gemini_service
                    .identify_models_cross_brand_batch(
                        chunk
                    )
                )

                for payload, result in zip(
                    chunk,
                    identify_results
                ):
                    if not (
                        result
                        and result.get("identified")
                        and result.get("confidence", 1.0)
                        >= MIN_CONFIDENCE_THRESHOLD
                    ):
                        self._log_low_confidence(
                            entity_type="model",
                            raw_value=payload["raw_model"],
                            reason=(
                                "Model unidentified or "
                                "low confidence by AI"
                            ),
                            extra_info={
                                "brand_id": payload["brand_id"],
                                "brand_name": payload["brand_name"],
                                "ai_response": result
                            }
                        )

                        results[payload["key"]] = None
                        continue

                    canonical_name = (
                        result.get("canonical_name")
                        or ""
                    ).strip()

                    if not canonical_name:
                        self._log_low_confidence(
                            entity_type="model",
                            raw_value=payload["raw_model"],
                            reason=(
                                "AI identified the model but returned "
                                "an empty canonical name"
                            ),
                            extra_info={
                                "brand_id": payload["brand_id"],
                                "brand_name": payload["brand_name"],
                                "ai_response": result
                            }
                        )

                        results[payload["key"]] = None
                        continue

                    brand_id = payload["brand_id"]

                    entity = (
                        self.database
                        .find_by_canonical_name_and_brand(
                            canonical_name=canonical_name,
                            brand_id=brand_id
                        )
                    )

                    if entity:
                        self.database.add_alias(
                            "model",
                            entity["id"],
                            payload["raw_model"],
                            save_immediately=False
                        )

                        results[payload["key"]] = entity
                        continue

                    dedup_key = (
                        brand_id,
                        self._normalize_for_comparison(
                            canonical_name
                        )
                    )

                    entity = created_this_run.get(
                        dedup_key
                    )

                    if entity:
                        self.database.add_alias(
                            "model",
                            entity["id"],
                            payload["raw_model"],
                            save_immediately=False
                        )

                        results[payload["key"]] = entity
                        continue

                    brand_name = payload["brand_name"]

                    candidate_entities = list(created_this_run.values()) + (
                        self.database.find_by_brand_id("model", brand_id)
                    )

                    matched_existing = None
                    for candidate in candidate_entities:
                        if candidate.get("brand_id") not in (brand_id, None):
                            continue
                        if _same_model_deterministic(
                            canonical_name,
                            candidate["canonical_name"],
                            brand_name
                        ):
                            matched_existing = candidate
                            break

                    if matched_existing:
                        self._log_low_confidence(
                            entity_type="model",
                            raw_value=payload["raw_model"],
                            reason=(
                                "Deterministic duplicate guard: AI's "
                                f"canonical_name '{canonical_name}' looked "
                                "like a brand-prefix variant of "
                                f"existing model '{matched_existing['canonical_name']}' "
                                "- reused the existing entity instead of "
                                "creating a new one. Verify this is correct."
                            ),
                            extra_info={
                                "brand_id": brand_id,
                                "brand_name": brand_name,
                                "matched_entity_id": matched_existing["id"]
                            }
                        )

                        self.database.add_alias(
                            "model",
                            matched_existing["id"],
                            payload["raw_model"],
                            save_immediately=False
                        )

                        results[payload["key"]] = matched_existing
                        continue

                    completion = _find_unique_numeric_completion(
                        canonical_name,
                        [c["canonical_name"] for c in candidate_entities]
                    )

                    if completion:
                        completion_entity = next(
                            c for c in candidate_entities
                            if c["canonical_name"] == completion
                        )

                        self._log_low_confidence(
                            entity_type="model",
                            raw_value=payload["raw_model"],
                            reason=(
                                "Bare-numeric-completion guard: AI's "
                                f"canonical_name '{canonical_name}' is a "
                                "bare number that is a prefix of exactly "
                                f"one existing model, '{completion}' - "
                                "reused that entity instead of creating "
                                "an incomplete standalone numeric model. "
                                "Verify this is correct."
                            ),
                            extra_info={
                                "brand_id": brand_id,
                                "brand_name": brand_name,
                                "matched_entity_id": completion_entity["id"]
                            }
                        )

                        self.database.add_alias(
                            "model",
                            completion_entity["id"],
                            payload["raw_model"],
                            save_immediately=False
                        )

                        results[payload["key"]] = completion_entity
                        continue

                    if self._is_numeric_model_value(payload["raw_model"]) and (
                        self._normalize_for_comparison(canonical_name)
                        == self._normalize_for_comparison(payload["raw_model"])
                    ):
                        self._log_low_confidence(
                            entity_type="model",
                            raw_value=payload["raw_model"],
                            reason=(
                                "AI created a NEW model using the bare "
                                "numeric value unchanged - verify this "
                                "isn't an incomplete engine/trim prefix "
                                "(e.g. BMW '325' instead of '325i')"
                            ),
                            extra_info={
                                "brand_id": payload["brand_id"],
                                "brand_name": payload["brand_name"],
                                "ai_response": result
                            }
                        )

                    entity = self.database.create_entity(
                        "model",
                        canonical_name,
                        brand_id=brand_id,
                        save_immediately=False
                    )

                    created_this_run[dedup_key] = entity

                    self.database.add_alias(
                        "model",
                        entity["id"],
                        payload["raw_model"],
                        save_immediately=False
                    )

                    results[payload["key"]] = entity

        self.database.save()
        self._save_low_confidence_log()

        print(
            "\n✓ Cross-brand model resolution complete."
        )

        return results

    # ============================================================
    # Individual Entity Resolution
    # ============================================================

    def resolve_license_type(self, raw_license_type: str):
        return self._resolve_existing(
            "license_type",
            raw_license_type
        )

    def resolve_governorate(self, raw_governorate: str):
        return self._resolve_existing(
            "governorate_city",
            raw_governorate
        )