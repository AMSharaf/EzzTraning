import time
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors

from config import GEMINI_MODEL


class GeminiService:
    def __init__(self, client: Optional[genai.Client] = None):
        self.client = client or genai.Client()

    # ============================================================
    # Gemini API Plumbing
    # ============================================================

    def _generate_content(self, prompt: str, response_schema: dict) -> Optional[Dict[str, Any]]:
        max_retries = 3

        for attempt in range(max_retries):
            try:
                print(f"   [API Request] Calling Gemini ({GEMINI_MODEL})...")

                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": response_schema,
                    },
                )

                print("   [API Success] Received response from Gemini.")
                return response.parsed

            except errors.ServerError as e:
                print(
                    f"   Gemini server error "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )

                if attempt == max_retries - 1:
                    return None

                time.sleep(2**attempt)

            except Exception as e:
                print(f"   Gemini API error: {e}")
                return None

        return None

    @staticmethod
    def _align_batch_results(response: Optional[dict], expected_count: int) -> list:
        aligned = [None] * expected_count

        if not response or not isinstance(response, dict):
            return aligned

        for item in response.get("results", []):
            if isinstance(item, dict):
                index = item.get("index")
                if isinstance(index, int) and 0 <= index < expected_count:
                    aligned[index] = item

        return aligned

    def _run_batch(
        self, prompt: str, extra_properties: dict, expected_count: int
    ) -> list:
        """
        Shared plumbing for numbered batch -> per-item result calls.

        Builds the response schema around the fields required by the
        specific operation, calls Gemini, and aligns results back to
        the original input order.
        """
        if expected_count == 0:
            return []

        response = self._generate_content(
            prompt=prompt,
            response_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                **extra_properties,
                                "confidence": {"type": "number"},
                            },
                            "required": [
                                "index",
                                *extra_properties.keys(),
                                "confidence",
                            ],
                        },
                    }
                },
                "required": ["results"],
            },
        )

        return self._align_batch_results(response, expected_count)

    # ============================================================
    # Generic Entity Methods
    # ============================================================

    def match_entities_batch(
        self, entity_name: str, raw_values: list, existing_entities: list
    ) -> list:
        if not raw_values:
            return []

        print(
            f"\n🔹 [AI Matching] Matching batch of "
            f"{len(raw_values)} '{entity_name}' items against "
            f"{len(existing_entities)} existing entities..."
        )

        numbered_values = "\n".join(
            f"{i}: {val}" for i, val in enumerate(raw_values)
        )

        prompt = f"""
You are a data cleaning assistant.

We have a numbered list of raw {entity_name} names from an Excel file.

Raw values:
{numbered_values}

Existing entities:
{existing_entities}

For EACH raw value, determine whether it refers to one of the
existing entities.

Rules:

- Match ONLY to an entity from the existing list.
- Do not invent a new entity.
- Ignore differences in:
  - language
  - capitalization
  - spacing
  - punctuation
  - obvious spelling mistakes
  - obvious Arabic/English representation differences
- When a match exists, return the matched canonical_name
  EXACTLY as it appears in the existing list.
- Never create a new spelling or variation of an existing entity.
- If there is no confident match, return matched=false.
- Return exactly one result per raw value.
- Preserve the original index.
- confidence must be strictly between 0.7 and 1.0 ONLY for high-confidence, clear matches. If uncertain, use a confidence below 0.7 or set matched=false.

IMPORTANT:

Correctness is more important than forcing a match.

When uncertain:
matched=false
"""

        return self._run_batch(
            prompt,
            {
                "matched": {"type": "boolean"},
                "canonical_name": {"type": "string"},
            },
            len(raw_values),
        )

    def identify_entities_batch(
        self, entity_name: str, raw_values: list
    ) -> list:
        if not raw_values:
            return []

        print(
            f"\n🔹 [AI Identification] Identifying batch of "
            f"{len(raw_values)} unresolved '{entity_name}' items..."
        )

        numbered_values = "\n".join(
            f"{i}: {val}" for i, val in enumerate(raw_values)
        )

        prompt = f"""
You are a data cleaning assistant.

We have a numbered list of raw {entity_name} names from an Excel file.
Inputs may be:

- Arabic
- English
- transliterated
- misspelled
- badly formatted

Raw values:
{numbered_values}

For EACH raw value, identify the standard/canonical {entity_name}
it represents.

Rules:

- Output canonical_name in standard English.
- Correct obvious spelling mistakes.
- Correct Arabic/English equivalents when the meaning is clear.
- Normalize obvious formatting differences.
- If a raw value is an Excel summary row such as:
  "Total"
  "Grand Total"
  "الإجمالي العام"
  or another section/header row,
  return identified=false.
- If the value is invalid, incomplete, or ambiguous,
  return identified=false.
- Never invent an entity merely because the value looks plausible.
- Return exactly one result per raw value.
- Preserve the original index.
- confidence must be strictly between 0.7 and 1.0 ONLY for high-confidence, clear identifications. If uncertain, use a confidence below 0.7 or set identified=false.

IMPORTANT:

It is better to return identified=false than to make a
confident-looking wrong identification.
"""

        return self._run_batch(
            prompt,
            {
                "identified": {"type": "boolean"},
                "canonical_name": {"type": "string"},
            },
            len(raw_values),
        )

    # ============================================================
    # Cross-Brand Model Matching
    # ============================================================

    def match_models_cross_brand_batch(self, items: list) -> list:
        if not items:
            return []

        print(
            f"\n🔹 [AI Cross-Brand Matching] Matching batch of "
            f"{len(items)} models across different brands..."
        )

        formatted_items = []

        for i, item in enumerate(items):
            brand = item.get("brand_name", "")
            raw_model = item.get("raw_model", "")
            existing = item.get("existing_models", [])
            formatted_items.append(
                f"{i}: "
                f"Brand: '{brand}' | "
                f"Raw Model: '{raw_model}' | "
                f"Known Models: {existing}"
            )

        numbered_list = "\n".join(formatted_items)

        prompt = f"""
You are an expert automotive data cleaning assistant.

Below is a numbered list of raw vehicle models together with their
brand and Known Models for that specific brand.

Items:
{numbered_list}

For EACH item, determine whether Raw Model refers to one of the
Known Models for that exact brand.

============================================================
GENERAL MATCHING RULES
============================================================

- Match ONLY to a model inside Known Models.
- Never invent a canonical model during this matching phase.
- Ignore:
  - capitalization
  - spacing
  - punctuation
  - obvious spelling mistakes
  - Arabic/English differences
  - common transliteration differences
- Allow known shorthand names to match the full canonical model.
- Allow known generation/chassis aliases.
- Allow removable engine modifiers.
- Allow removable trim modifiers.
- Allow removable drivetrain modifiers.
- When a match exists, return canonical_name EXACTLY as it appears
  in Known Models.
- Never add the brand name to canonical_name.
- Never remove a word that is genuinely part of the model identity.
- If there is no confident match, return matched=false.

============================================================
BRAND-AS-MODEL GUARD (CRITICAL)
============================================================
If the Raw Model text is actually a standalone manufacturer or brand name 
(whether in English or Arabic, e.g., "Renault", "Toyota", "BMW", "رينيو", "تويوتا"), 
you must immediately return matched=false. Never turn a brand name into a model.

============================================================
ALPHANUMERIC & CHASSIS CODE GUARD (CRITICAL)
============================================================
Do NOT collapse unique alphanumeric chassis/engine codes (such as "c210", "w123", "e200") 
into general class lines (like "C-Class" or "E-Class"). If the raw input is a specific 
alphanumeric code like "c210", it must ONLY match an exact equivalent in Known Models. 
Otherwise, return matched=false.

============================================================
NUMERIC / MODEL PREFIX RULE
============================================================

A raw numeric value can be an incomplete model-family prefix.

When Raw Model consists only of a number:

DO NOT automatically treat the number as a complete model.

FIRST check Known Models.

CASE 1:
Exactly ONE Known Model is a valid completion of the number.

Then match it.

Example:

Brand: BMW
Raw Model: "320"
Known Models: ["320i"]

Result:
matched=true
canonical_name="320i"

Example:

Brand: BMW
Raw Model: "325"
Known Models: ["325i"]

Result:
matched=true
canonical_name="325i"

CASE 2:
MORE THAN ONE Known Model is a valid completion.

Then the raw value is ambiguous.

Return:

matched=false

Example:

Brand: BMW
Raw Model: "320"
Known Models: ["320i", "320d"]

Result:
matched=false

Do NOT return:
"320"

Example:

Brand: BMW
Raw Model: "325"
Known Models: ["325i", "325d", "325xi"]

Result:
matched=false

CASE 3:
NO Known Models.

Do NOT invent a completion.

Return:

matched=false

Example:

Brand: BMW
Raw Model: "320"
Known Models: []

Result:
matched=false

IMPORTANT:

The absence of Known Models does NOT mean the number itself
is a valid model.

============================================================
WORD FORM VS DIGIT FORM (MG EXCEPTION)
============================================================

If Known Models contains a numeric model and Raw Model is its
spelled-out word form, they may represent the same model.
This is fully valid for brands like MG where "1" or "One" is a complete model.

Example:

Brand: MG
Raw Model: "One"
Known Models: ["1"]

Result:
matched=true
canonical_name="1"

Also:

"MG One"
"MG1"
"MG 1"

may match:
"1"

Only do this when they genuinely represent the same model. Do NOT treat MG "1" or "One" as an incomplete number.

============================================================
RANGE ROVER SAFETY RULE
============================================================

These are distinct models and are atomic. They cannot be broken down:

- Range Rover
- Range Rover Sport
- Range Rover Velar
- Range Rover Evoque

Never collapse a specific model (like "Range Rover Sport") into the generic "Range Rover". 
Never strip the "Range Rover" prefix and leave just "Sport".

Examples:

Raw:
"Range Rover Sport Autobiography"

Known:
[ "Range Rover Sport"]

Result:
matched=true
canonical_name="Range Rover Sport"

Raw:
"RR Sport HSE"

Known:
[ "Range Rover Sport"]

Result:
matched=true
canonical_name="Range Rover Sport"

Raw:
"Velar"

Known:
[ "Range Rover Velar"]

Result:
matched=true
canonical_name="Range Rover Velar"

Raw:
"Evoque"

Known:
["Range Rover Evoque"]

Result:
matched=true
canonical_name="Range Rover Evoque"

If a specific sub-model word is present, do not remove it.

============================================================
FINAL RULE & CONFIDENCE CALIBRATION
============================================================

A false match is worse than an unresolved value. Never guess.

When evidence is insufficient:

matched=false

Return exactly one result per input.
Preserve the original index.
confidence must be strictly between 0.7 and 1.0 ONLY for high-confidence, verified matches. If stretching or guessing, set matched=false.
"""

        return self._run_batch(
            prompt,
            {
                "matched": {"type": "boolean"},
                "canonical_name": {"type": "string"},
            },
            len(items),
        )

    # ============================================================
    # Cross-Brand Model Identification
    # ============================================================

    def identify_models_cross_brand_batch(self, items: list) -> list:
        if not items:
            return []

        print(
            f"\n🔹 [AI Cross-Brand Identification] Generating "
            f"canonical English names for batch of {len(items)} models..."
        )

        formatted_items = []

        for i, item in enumerate(items):
            brand = item.get("brand_name", "")
            raw_model = item.get("raw_model", "")
            existing = item.get("existing_models") or []

            if existing:
                known_str = f"Known Models: {existing}"
            else:
                known_str = (
                    "Known Models: "
                    "(none recorded yet for this brand)"
                )

            formatted_items.append(
                f"{i}: "
                f"Brand: '{brand}' | "
                f"Raw Model: '{raw_model}' | "
                f"{known_str}"
            )

        numbered_list = "\n".join(formatted_items)

        prompt = f"""
You are an expert automotive data cleansing assistant.

You have strong knowledge of real-world vehicle manufacturers,
their model lineups, Arabic automotive terminology, Arabic
transliterations, common misspellings, shorthand names, and
vehicle naming conventions.

Below is a numbered list of raw vehicle model strings paired with:

- Brand
- Raw Model
- Known Models for that brand, when available

Inputs may be:

- Arabic
- English
- Arabic transliteration
- mixed Arabic/English
- misspelled
- badly spaced
- abbreviated
- partially written
- written with Arabic digits
- written with English digits
- written with a brand prefix
- written using common automotive shorthand

Items:
{numbered_list}

Your task is to identify the REAL marketed vehicle model represented
by each Raw Model.

Correctness is more important than coverage.

============================================================
0. CORE PRINCIPLE - NEVER INVENT OR OVER-GENERALIZE
============================================================

Do NOT force every raw value into a vehicle model.
STRICTLY FORBIDDEN: Do not transform technical or chassis codes like "c210", "w123", or "e200" into commercial luxury lines like "C-Class" or "C200". Keep them literal or return identified=false.

A wrong identified=true result is worse than:

identified=false

Only return identified=true when there is enough evidence that the
raw value refers to ONE specific real-world marketed vehicle model.

If the evidence is insufficient, incomplete, ambiguous, or can
reasonably refer to multiple models:

identified=false

============================================================
BRAND-AS-MODEL GUARD (CRITICAL)
============================================================
If the Raw Model text is actually a standalone manufacturer or brand name 
(whether in English or Arabic, e.g., "Renault", "Toyota", "BMW", "رينيو", "تويوتا"), 
you must immediately return identified=false. A brand name data leakage into the model column must never be converted into a model like "ren5".

============================================================
1. CHECK KNOWN MODELS FIRST
============================================================

When Known Models are provided:

FIRST determine whether Raw Model clearly refers to one of them.

Allow:

- spelling differences
- capitalization differences
- spacing differences
- punctuation differences
- Arabic/English equivalents
- transliteration differences
- common shorthand
- generation/chassis aliases
- removable engine modifiers
- removable trim modifiers
- removable drivetrain modifiers

If exactly one Known Model clearly matches, return that model's
canonical_name EXACTLY as it appears in Known Models.

Do NOT:

- invent a new spelling
- add the brand name
- create a stylistic variation
- replace one Known Model with another
- invent a missing variant

============================================================
2. ARABIC / TRANSLITERATION HANDLING & PHONETIC LETTERS
============================================================

Understand common Arabic automotive representations.

Examples:

"بي ام دبليو" -> BMW
"بى ام دبليو" -> BMW
"مرسيدس" -> Mercedes-Benz
"رانج روفر" -> Range Rover
"رنج روفر" -> Range Rover
"فيلار" -> Velar
"سبورت" -> Sport
"اكس ٥" -> X5
"اكس فايف" -> X5

PHONETIC ARABIC LETTERS:
When Arabic text uses letters like "دي" (D), "اس" (S), "سي" (C), or "اي" (E), treat them as engineering/fuel suffixes or code letters (e.g., "دي 220" or "220 دي" means "220d" or Diesel variant, NOT an S-Class).

Arabic and English digits are equivalent:

٠ -> 0
١ -> 1
٢ -> 2
٣ -> 3
٤ -> 4
٥ -> 5
٦ -> 6
٧ -> 7
٨ -> 8
٩ -> 9

Correct obvious Arabic spelling/transliteration errors when
the intended model is clear.

Do NOT use transliteration to invent a model.

============================================================
3. GOLDEN RULE - NEVER GUESS
============================================================

Never infer a missing model variant without sufficient evidence.

Do NOT invent:

- engine suffixes
- fuel suffixes
- drivetrain suffixes
- trim levels
- generations
- performance packages
- missing model-family names

When a raw value is incomplete and there is not enough evidence
to resolve it to one model:

identified=false

============================================================
4. NUMERIC / MODEL PREFIX RULE & MISSING SUFFIX GENERALIZATION
============================================================

THIS RULE IS CRITICAL.

A Raw Model consisting only of a number may be:

- a complete standalone model
- a model-family prefix
- an engine designation
- an engine size
- a series designation
- a trim designation
- a power designation
- an incomplete vehicle designation

Therefore:

NEVER automatically return the bare number as canonical_name unless it's a known standalone numerical model.

GENERALIZED MISSING SUFFIX RULE:
For European or alphanumeric models (such as BMW series numbers like 316, 520, etc.) where the base commercial model universally includes an engine/fuel suffix letter (like 'i' for petrol), if the raw input is a bare 3-digit number and no conflicting evidence exists, default to the standard gasoline variant (e.g., "316" -> "316i", "520" -> "520i").
A numeric prefix completion rule must ONLY apply to tight technical, engine, or series suffixes (such as adding an engine letter like 'i', 'd', 'h', or a numeric series extension like '320' -> '320i').

It must NEVER bridge across independent lexical words or expand a short standalone number into a completely different multi-word model name.

GENERAL RESTRICTIONS:
- DO NOT expand a bare number or short prefix into a model name that contains a distinct independent word or separate noun component (e.g., do not map "4" to "4Runner", "3" to "300C", or "5" to "500X"). 
- Prefix completion is strictly reserved for tight alphanumeric code variations, never compound word formations.
- If a raw input is a bare number (e.g., "4"), it can ONLY match a multi-word model if that exact multi-word model is already a direct, exact textual match in the Known Models list. Never manufacture the second half of a compound name via prefix guessing.
------------------------------------------------------------
CASE 1: EXACTLY ONE KNOWN MODEL COMPLETION
------------------------------------------------------------

If the raw number is an established prefix of EXACTLY ONE Known
Model, return that Known Model.

Example:

Brand: BMW
Raw Model: "320"
Known Models: ["320i"]

Result:

identified=true
canonical_name="320i"

Another example:

Brand: BMW
Raw Model: "325"
Known Models: ["325i"]

Result:

identified=true
canonical_name="325i"

------------------------------------------------------------
CASE 2: MULTIPLE KNOWN MODEL COMPLETIONS
------------------------------------------------------------

If the raw number can refer to MORE THAN ONE Known Model:

identified=false

Example:

Brand: BMW
Raw Model: "320"
Known Models: ["320i", "320d"]

Result:

identified=false

Do NOT return:
canonical_name="320"

------------------------------------------------------------
CASE 3: NO KNOWN MODELS
------------------------------------------------------------

If Known Models is empty, evaluate using standard market naming conventions (applying default suffix injection where standard for the brand).

============================================================
4b. EXCEPTION TO THE MISSING-SUFFIX RULE - GENUINE STANDALONE NUMERIC MODELS (MG CRITICAL FIX)
============================================================

The missing-suffix caution above applies to brands where a bare number
is normally an INCOMPLETE technical code (BMW, Mercedes-Benz engine/series
numbers). It does NOT apply to brands that genuinely market a vehicle
under a bare number or short numeric name as its complete, official name.

Known examples (not exhaustive - use real-world knowledge):
MG "1", MG "3", MG "5", MG "6" | Renault "5" | Fiat "500"

For these brands, a bare number IS a complete standalone model by
default - do not require it to have Known Models present first, and do
NOT treat it as needing a suffix. Return identified=true with high
confidence. 

THIS ALSO APPLIES TO SPELLED OUT WORDS: MG "One", "MG1", and "MG 1" MUST cleanly resolve to canonical_name = "1". Do not treat them as incomplete.
============================================================
5. BARE NUMERIC VALUES - IMPORTANT SAFETY CHECK
============================================================

Before treating ANY bare number as a model, determine whether it is
really the complete official marketed model name for that manufacturer.

If the number is normally used as:

- engine designation
- series number
- power designation
- trim
- family prefix
- incomplete model identifier

then apply standard completion or return false if ambiguous.

============================================================
6. VALID STANDALONE NUMERIC MODELS & PLURAL/TYPO STRIPPING
============================================================

Some manufacturers genuinely market a vehicle under a standalone
numeric model name.

Examples:

Renault + "5" -> "5"
Fiat + "500" -> "500"
MG + "1" -> "1"
ROX + "01s" -> Strip trailing 's' or 'S' plural/typo suffixes -> "01".

============================================================
7. ESTABLISHED NUMERIC SHORTHANDS & WORD FORM VS DIGIT FORM
============================================================

Word Form to Digit Generalization:
If a model is marketed universally as a digit, convert spelled-out number words (like "One", "Five") to digits when they represent the same model identity (e.g., MG "One" -> "1", Renault "Five" -> "5").

Tesla + "3" -> "Model 3"

============================================================
8. BRAND PREFIX RULE
============================================================

canonical_name represents the MODEL, not the manufacturer.

Remove redundant manufacturer prefixes.

Examples:

"MG 4" -> "4"
"BMW X5" -> "X5"
"Toyota Corolla" -> "Corolla"

However, do NOT remove words that are genuinely part of the
marketed model name.

============================================================
9. GENERAL RULE: ISOLATED TRIMS, ENGINE CODES & SUB-MODELS (CRITICAL)
============================================================

Distinguish structural sub-models from equipment trims.

- ISOLATED TRIMS ARE INVALID: If the raw input consists ENTIRELY of a trim level, feature description, package name, engine code, or power designation with NO base model name attached (e.g., inputs like "Autobiography", "Vogue", "P440e", "HSE", "SE", "SVR", or Arabic "اوتوبيجرافي"), you MUST return identified=false. Never default or fall back an isolated trim or code to a generic parent brand or root name like "Range Rover".
- TRIMS MUST BE REMOVED WHEN ATTACHED: When a trim accompanies a valid sub-model (e.g., "Range Rover Sport Autobiography"), strip the trim completely to leave the base sub-model.
- SUB-MODELS MUST KEEP THEIR PARENT PREFIX: Sub-models that rely on the parent line identity must never be separated or stripped down to a lone word. ALL sub-models under Land Rover must retain the full prefix. Your only allowed outputs for these are: "Range Rover", "Range Rover Sport", "Range Rover Velar", and "Range Rover Evoque". Never output "Sport", "Velar", or "Evoque" alone. AND NEVER collapse "Range Rover Sport", "Velar", or "Evoque" down to just "Range Rover".

============================================================
10. GENERATION / CHASSIS / PLATFORM
============================================================

Generation codes, chassis codes, and platform codes generally
should NOT become separate canonical models when they refer to
different generations of the same marketed vehicle.

Examples:
"Elantra HD" -> "Elantra"
"Accent RB" -> "Accent"

============================================================
11. ENGINE / TRIM / DRIVETRAIN
============================================================

canonical_name normally represents the base marketed model.
Remove modifiers (e.g., "BMW X5 xDrive40i" -> "X5").

============================================================
12. INVALID DATA
============================================================

Return identified=false for Excel total rows, headers, prices, dates, years, and garbage text.

============================================================
13. FINAL DECISION RULE & CONFIDENCE CALIBRATION
============================================================

For EACH input:
- Return exactly ONE result.
- Preserve the original index.
- If identified=true: canonical_name MUST be the correct BASE MARKETED MODEL.
- If identified=false: do NOT pretend to know the model.
- confidence must be strictly between 0.7 and 1.0 ONLY for high-confidence, clear identifications. If you are guessing or stretching, output a confidence below 0.7 (or set identified=false). Correctness > coverage.
"""

        return self._run_batch(
            prompt,
            {
                "identified": {"type": "boolean"},
                "canonical_name": {"type": "string"},
            },
            len(items),
        )
 # ============================================================
    # Enrichment: Brand Attributes
    # ============================================================

    def enrich_brands_batch(self, brand_names: list) -> list:
        if not brand_names:
            return []

        print(
            f"\n🔹 [AI Enrichment] Looking up country of origin "
            f"for {len(brand_names)} brand(s)..."
        )

        numbered_values = "\n".join(
            f"{i}: {name}" for i, name in enumerate(brand_names)
        )

        prompt = f"""
You are an automotive data assistant.

For EACH of the following vehicle brand names, identify the country
where the brand originates as it is commonly known and marketed in
Egypt and the Middle East.

Brands:
{numbered_values}

Rules:

- Return the country name in standard English.
- Base the country on the brand's perceived market identity,
  not necessarily the current corporate holding company.

Examples:

MG -> China
Jaguar -> United Kingdom
Land Rover -> United Kingdom
Opel -> Germany
Volvo -> Sweden

- If you are not confident, return identified=false.
- Return exactly one result per brand.
- Preserve the original index.
- confidence must be strictly between 0.7 and 1.0 for confident identifications, otherwise below 0.7 or identified=false.
"""

        return self._run_batch(
            prompt,
            {
                "identified": {"type": "boolean"},
                "country": {"type": "string"},
            },
            len(brand_names),
        )
    # ============================================================
    # Enrichment: Model Attributes
    # ============================================================
    def enrich_brands_batch(self, brand_names: list) -> list:
        if not brand_names:
            return []

        print(
            f"\n🔹 [AI Enrichment] Looking up country of origin "
            f"for {len(brand_names)} brand(s)..."
        )

        numbered_values = "\n".join(
            f"{i}: {name}" for i, name in enumerate(brand_names)
        )

        prompt = f"""
    You are an automotive data assistant specializing in the Egyptian
    and Middle Eastern automotive markets.

    For EACH vehicle brand below, identify the country of origin of the
    BRAND itself.

    Important:
    - Use the brand's commonly recognized origin/market identity.
    - Do NOT use the current parent company's headquarters if different.
    - Do NOT use the country where the vehicle is manufactured unless
    that is also the brand's origin.
    - Return the country name in standard English.

    Examples:
    MG -> China
    Jaguar -> United Kingdom
    Land Rover -> United Kingdom
    Opel -> Germany
    Volvo -> Sweden
    Toyota -> Japan
    Hyundai -> South Korea
    BMW -> Germany
    Mercedes-Benz -> Germany
    Ford -> United States

    If you are not sufficiently confident:
    - identified = false
    - country = ""
    - confidence < 0.70

    Return exactly ONE result for every input item.
    Preserve the original index.
    Do not return explanations.
    Do not return additional fields.

    Brands:
    {numbered_values}
    """

        return self._run_batch(
            prompt,
            {
                "identified": {"type": "boolean"},
                "country": {"type": "string"},
                "confidence": {"type": "number"},
            },
            len(brand_names),
        )


    # ============================================================
    # Enrichment: Model Attributes
    # ============================================================

    def enrich_models_batch(self, items: list) -> list:
        if not items:
            return []

        # De-duplicate by brand+model so identical items (e.g. the same
        # "Hyundai Elantra" row appearing 5 times) are only sent to the
        # model once, instead of paying to classify the same thing
        # repeatedly in one batch.
        unique_map = {}                          # (brand, model) -> index in unique_items
        unique_items = []                        # de-duplicated list actually sent to the API
        index_to_unique = [None] * len(items)    # original index -> position in unique_items

        for i, item in enumerate(items):
            key = (
                item.get("brand_name", "").strip().lower(),
                item.get("model_name", "").strip().lower(),
            )
            if key not in unique_map:
                unique_map[key] = len(unique_items)
                unique_items.append(item)
            index_to_unique[i] = unique_map[key]

        print(
            f"\n🔹 [AI Enrichment] Identifying and classifying "
            f"{len(unique_items)} unique model(s) "
            f"({len(items) - len(unique_items)} duplicate(s) skipped) "
            f"out of {len(items)} received..."
        )

        numbered_items = "\n".join(
            f"{i}: Brand: '{item.get('brand_name', '')}' | "
            f"Model: '{item.get('model_name', '')}'"
            for i, item in enumerate(unique_items)
        )

        prompt = f"""
        You are an automotive data expert specializing in the Egyptian
        automotive market.

        Your task has TWO stages for EACH input:

        STAGE 1:
        Identify and normalize the vehicle BRAND + MODEL.

        STAGE 2:
        Determine the most representative POWERTRAIN for that exact
        vehicle model in the Egyptian market during approximately 2022–2027.


        ============================================================
        ALLOWED POWERTRAIN VALUES
        ============================================================

        The motor_type MUST be exactly ONE of:

        Petrol
        Diesel
        Electric
        Hybrid
        CNG
        REEV


        ============================================================
        STAGE 1 — MODEL IDENTIFICATION AND NORMALIZATION
        ============================================================

        The input model name may NOT be the official model name.

        It may contain:

        - numbers instead of words
        - abbreviations
        - missing spaces
        - extra spaces
        - missing hyphens
        - different capitalization
        - dealer naming
        - importer naming
        - Egyptian-market naming
        - common spelling variations
        - transliteration or simplified names

        You MUST normalize obvious naming variations BEFORE deciding
        whether the model is identifiable.

        IMPORTANT:

        Do NOT reject a model just because the supplied model name
        does not exactly match the official model spelling.

        Examples:

        MG 1 -> MG ONE
        MG One -> MG ONE
        MG-1 -> MG ONE
        MG ONE -> MG ONE

        Nissan X Trail -> NISSAN X-TRAIL
        Nissan Xtrail -> NISSAN X-TRAIL
        Nissan X-Trail -> NISSAN X-TRAIL

        Toyota Land Cruiser Prado -> LAND CRUISER PRADO
        Mercedes GLC -> GLC

        The normalization must consider BOTH the brand and model.

        For example:

        MG + 1

        should be interpreted as:

        MG + ONE

        when that is the clearly identifiable vehicle model.

        Do NOT invent a completely different model.

        Only return identified=false when the BRAND + MODEL combination
        remains genuinely ambiguous after normalization.


        ============================================================
        IMPORTANT: MODEL NAME ≠ POWERTRAIN
        ============================================================

        Do NOT determine the motor type from the model name alone.

        First identify the exact vehicle model.

        Then determine its powertrain.

        For example:

        MG 1
        -> normalize to MG ONE
        -> identify MG ONE
        -> determine Egyptian-market powertrain
        -> classify as Petrol

        Do NOT assume that "1" means a 1.0L engine.

        Do NOT assume that a model name containing "e", "EV", "E",
        "Hybrid", etc. automatically determines the powertrain unless
        the actual vehicle configuration confirms it.


        ============================================================
        EGYPTIAN MARKET PRIORITY
        ============================================================

        The target market is EGYPT.

        The target period is approximately 2022–2027.

        Egyptian-market configurations have priority over global
        configurations.

        Use international information only when it helps identify the
        exact vehicle or when the configuration is genuinely relevant
        to vehicles commonly sold/imported in Egypt.

        Do NOT classify a vehicle based only on a powertrain that exists
        in another country.


        ============================================================
        POWERTRAIN DEFINITIONS
        ============================================================

        Petrol:
        A conventional gasoline/petrol internal-combustion vehicle.

        Diesel:
        A conventional diesel internal-combustion vehicle.

        Electric:
        A fully battery-electric vehicle (BEV) with NO combustion
        engine used as part of the vehicle propulsion system.

        Hybrid:
        A vehicle combining a combustion engine with electric propulsion
        or electric motor assistance.

        Hybrid includes:

        - HEV
        - PHEV
        - Mild Hybrid
        - e-POWER-type systems where a combustion engine generates
        electricity for an electrically driven vehicle

        CNG:
        A vehicle primarily powered by compressed natural gas.

        REEV:
        A genuine range-extended electric vehicle where electric
        propulsion is primary and the combustion engine primarily acts
        as a range extender.


        ============================================================
        POWERTRAIN DECISION RULES
        ============================================================

        1. Determine the exact normalized model first.

        2. Determine which powertrain is representative of that exact
        model in Egypt during approximately 2022–2027.

        3. If multiple configurations exist, select the mainstream or
        commonly sold Egyptian-market configuration.

        4. Do NOT select a rare international configuration.

        5. Do NOT use an old-generation engine merely because an older
        version of the model had it.

        6. Do NOT use another model from the same brand as evidence.


        ============================================================
        DIESEL RULE
        ============================================================

        Be especially careful with Diesel.

        DO NOT classify a model as Diesel merely because:

        - a diesel version exists internationally
        - an older generation had a diesel engine
        - Europe sells a diesel version
        - the manufacturer offers diesel globally
        - another model from the same manufacturer uses diesel
        - a commercial version uses diesel

        Classify as Diesel ONLY when there is strong evidence that
        Diesel is a representative/common configuration of THAT EXACT
        MODEL in the Egyptian market during approximately 2022–2027.

        If the Egyptian-market vehicle is primarily Petrol, classify it
        as Petrol even if a Diesel version exists internationally.


        ============================================================
        PETROL RULE
        ============================================================

        If the exact model is primarily sold or commonly represented
        in Egypt as a conventional petrol vehicle, classify it as:

        Petrol

        unless there is strong evidence that another powertrain is the
        representative Egyptian configuration.


        ============================================================
        HYBRID RULE
        ============================================================

        Classify as Hybrid when the relevant Egyptian-market vehicle
        uses both:

        - a combustion engine
        AND
        - an electric propulsion/motor system.

        This includes:

        HEV
        PHEV
        Mild Hybrid
        e-POWER

        IMPORTANT:

        A PHEV is Hybrid, NOT Electric.

        A mild-hybrid is Hybrid.

        A Nissan e-POWER vehicle is Hybrid, NOT Electric, because it
        still contains a combustion engine.

        Do NOT classify an e-POWER vehicle as Electric simply because
        the wheels are driven by an electric motor.


        ============================================================
        ELECTRIC RULE
        ============================================================

        Classify as Electric ONLY when the exact vehicle is a BEV.

        The vehicle must have:

        - battery-electric propulsion
        - NO combustion engine used as part of the vehicle system

        Do NOT classify a Hybrid, PHEV, mild-hybrid, or e-POWER vehicle
        as Electric.


        ============================================================
        REEV RULE
        ============================================================

        Use REEV only for a genuine range-extended electric architecture.

        Do NOT use REEV for:

        - normal hybrids
        - HEVs
        - PHEVs
        - mild hybrids
        - Nissan e-POWER


        ============================================================
        CNG RULE
        ============================================================

        Use CNG only when CNG is genuinely a primary powertrain for
        the exact model and is relevant to the Egyptian market.


        ============================================================
        AMBIGUOUS MODELS
        ============================================================

        If the model name has a clear and commonly recognized
        normalization, normalize it.

        Do NOT return false simply because:

        "MG 1"

        is written differently from:

        "MG ONE"

        However, if even after normalization you cannot determine
        which exact vehicle model is intended, return:

        identified = false
        normalized_model = ""
        motor_type = ""
        confidence < 0.80


        ============================================================
        CONFIDENCE
        ============================================================

        confidence represents confidence in:

        1. Brand identification
        2. Model normalization
        3. Exact model identification
        4. Egyptian-market relevance
        5. Representative powertrain
        6. Target period 2022–2027

        Use:

        0.90–1.00
        Strong confidence.

        0.80–0.89
        Reasonably confident.

        Below 0.80
        Do not force a classification.


        ============================================================
        OUTPUT
        ============================================================

        Return EXACTLY ONE result for EACH input item.

        Preserve the original index.

        Never skip an item.

        Never reorder items.

        Every result MUST contain exactly these fields:

        identified
        normalized_model
        motor_type
        confidence

        If identified=true:

        normalized_model = normalized official/common model name
        motor_type = one allowed value
        confidence >= 0.80

        If identified=false:

        normalized_model = ""
        motor_type = ""
        confidence < 0.80

        Do NOT return explanations.

        Do NOT return additional fields.


        ============================================================
        EXAMPLES
        ============================================================

        Input:

        Brand: MG
        Model: 1

        Expected reasoning:

        MG 1 -> MG ONE -> identify MG ONE -> determine Egyptian
        powertrain -> Petrol

        Output:

        identified = true
        normalized_model = "ONE"
        motor_type = "Petrol"


        Input:

        Brand: Nissan
        Model: X-Trail e-POWER

        Expected:

        identified = true
        normalized_model = "X-TRAIL E-POWER"
        motor_type = "Hybrid"


        Input:

        Brand: Nissan
        Model: X Trail

        Expected:

        identified = true
        normalized_model = "X-TRAIL"
        motor_type = appropriate Egyptian-market configuration


        Input:

        Brand: Toyota
        Model: Corolla

        Do NOT choose Diesel merely because a diesel Corolla existed
        in another market or generation.

        Determine the representative Egyptian-market configuration.


        ============================================================
        ITEMS
        ============================================================

        {numbered_items}
        """

        unique_results = self._run_batch(
            prompt,
            {
                "identified": {"type": "boolean"},
                "normalized_model": {"type": "string"},
                "motor_type": {"type": "string"},
                "confidence": {"type": "number"},
            },
            len(unique_items),
        )

        # Expand the de-duplicated results back out to match the original
        # `items` list, one result per original index, duplicates included.
        return [unique_results[index_to_unique[i]] for i in range(len(items))]