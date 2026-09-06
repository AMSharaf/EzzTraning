import urllib.parse

from sqlalchemy import create_engine, text

from config import SQL_SERVER, SQL_DATABASE, SQL_DRIVER, SQL_TRUSTED_CONNECTION


def get_sql_engine():
    """Creates a SQLAlchemy engine using Windows Authentication."""
    params = urllib.parse.quote_plus(
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"Trusted_Connection={SQL_TRUSTED_CONNECTION}"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")


def _sync_aliases(connection, entities, alias_table, id_column):
    """
    Sync aliases stored in the JSON master database into the
    corresponding SQL Server alias table.

    The SQL alias tables have a UNIQUE constraint on (entity_id, alias),
    so MERGE makes the operation idempotent.
    """
    alias_sql = text(f"""
        MERGE INTO {alias_table} AS target
        USING (
            VALUES (:entity_id, :alias)
        ) AS source ({id_column}, Alias)
        ON target.{id_column} = source.{id_column}
           AND target.Alias = source.Alias

        WHEN NOT MATCHED THEN
            INSERT ({id_column}, Alias)
            VALUES (source.{id_column}, source.Alias);
    """)

    for entity in entities:
        entity_id = entity["id"]

        for alias in entity.get("aliases", []):
            if alias is None:
                continue

            alias = str(alias).strip()

            if not alias:
                continue

            connection.execute(
                alias_sql,
                {
                    "entity_id": entity_id,
                    "alias": alias,
                },
            )


def sync_master_database(database_obj):
    """
    Pulls master data from the Database instance and safely syncs it
    to SQL Server Dimension and Alias tables using SQL Server MERGE
    (Upsert) logic.

    Source of truth:
        database_obj.data

    Synced entities:
        - Brands + Brand aliases
        - Models + Model aliases
        - License types + License type aliases
        - Governorates + Governorate aliases
    """
    engine = get_sql_engine()

    with engine.begin() as connection:

        # ============================================================
        # 1. Sync Brands
        # ============================================================
        for b in database_obj.data["brand"].values():
            connection.execute(
                text("""
                    MERGE INTO Dim_Brand AS target
                    USING (
                        VALUES (:id, :name, :norm_name, :country)
                    ) AS source
                        (Brand_ID, Canonical_Name, Normalized_Name, Country)
                    ON target.Brand_ID = source.Brand_ID

                    WHEN MATCHED THEN
                        UPDATE SET
                            Canonical_Name = source.Canonical_Name,
                            Normalized_Name = source.Normalized_Name,
                            Country = source.Country

                    WHEN NOT MATCHED THEN
                        INSERT (
                            Brand_ID,
                            Canonical_Name,
                            Normalized_Name,
                            Country
                        )
                        VALUES (
                            source.Brand_ID,
                            source.Canonical_Name,
                            source.Normalized_Name,
                            source.Country
                        );
                """),
                {
                    "id": b["id"],
                    "name": b["canonical_name"],
                    "norm_name": b.get("normalized_name", ""),
                    "country": b.get("country"),
                },
            )

        # Brand aliases
        _sync_aliases(
            connection,
            database_obj.data["brand"].values(),
            "Dim_Brand_Alias",
            "Brand_ID",
        )

        # ============================================================
        # 2. Sync Models
        # ============================================================
        for m in database_obj.data["model"].values():
            connection.execute(
                text("""
                    MERGE INTO Dim_Model AS target
                    USING (
                        VALUES (
                            :id,
                            :brand_id,
                            :name,
                            :norm_name,
                            :motor_type
                        )
                    ) AS source (
                        Model_ID,
                        Brand_ID,
                        Canonical_Name,
                        Normalized_Name,
                        Motor_Type
                    )
                    ON target.Model_ID = source.Model_ID

                    WHEN MATCHED THEN
                        UPDATE SET
                            Brand_ID = source.Brand_ID,
                            Canonical_Name = source.Canonical_Name,
                            Normalized_Name = source.Normalized_Name,
                            Motor_Type = source.Motor_Type

                    WHEN NOT MATCHED THEN
                        INSERT (
                            Model_ID,
                            Brand_ID,
                            Canonical_Name,
                            Normalized_Name,
                            Motor_Type
                        )
                        VALUES (
                            source.Model_ID,
                            source.Brand_ID,
                            source.Canonical_Name,
                            source.Normalized_Name,
                            source.Motor_Type
                        );
                """),
                {
                    "id": m["id"],
                    "brand_id": m["brand_id"],
                    "name": m["canonical_name"],
                    "norm_name": m.get("normalized_name", ""),
                    "motor_type": m.get("motor_type"),
                },
            )

        # Model aliases
        _sync_aliases(
            connection,
            database_obj.data["model"].values(),
            "Dim_Model_Alias",
            "Model_ID",
        )

        # ============================================================
        # 3. Sync License Types
        # ============================================================
        for lt in database_obj.data["license_type"].values():
            connection.execute(
                text("""
                    MERGE INTO Dim_LicenseType AS target
                    USING (
                        VALUES (:id, :name, :norm_name)
                    ) AS source (
                        LicenseType_ID,
                        Canonical_Name,
                        Normalized_Name
                    )
                    ON target.LicenseType_ID = source.LicenseType_ID

                    WHEN MATCHED THEN
                        UPDATE SET
                            Canonical_Name = source.Canonical_Name,
                            Normalized_Name = source.Normalized_Name

                    WHEN NOT MATCHED THEN
                        INSERT (
                            LicenseType_ID,
                            Canonical_Name,
                            Normalized_Name
                        )
                        VALUES (
                            source.LicenseType_ID,
                            source.Canonical_Name,
                            source.Normalized_Name
                        );
                """),
                {
                    "id": lt["id"],
                    "name": lt["canonical_name"],
                    "norm_name": lt.get("normalized_name", ""),
                },
            )

        # License type aliases
        _sync_aliases(
            connection,
            database_obj.data["license_type"].values(),
            "Dim_LicenseType_Alias",
            "LicenseType_ID",
        )

        # ============================================================
        # 4. Sync Governorates
        # ============================================================
        for g in database_obj.data["governorate_city"].values():
            connection.execute(
                text("""
                    MERGE INTO Dim_Governorate AS target
                    USING (
                        VALUES (:id, :name, :norm_name)
                    ) AS source (
                        Governorate_ID,
                        Canonical_Name,
                        Normalized_Name
                    )
                    ON target.Governorate_ID = source.Governorate_ID

                    WHEN MATCHED THEN
                        UPDATE SET
                            Canonical_Name = source.Canonical_Name,
                            Normalized_Name = source.Normalized_Name

                    WHEN NOT MATCHED THEN
                        INSERT (
                            Governorate_ID,
                            Canonical_Name,
                            Normalized_Name
                        )
                        VALUES (
                            source.Governorate_ID,
                            source.Canonical_Name,
                            source.Normalized_Name
                        );
                """),
                {
                    "id": g["id"],
                    "name": g["canonical_name"],
                    "norm_name": g.get("normalized_name", ""),
                },
            )

        # Governorate aliases
        _sync_aliases(
            connection,
            database_obj.data["governorate_city"].values(),
            "Dim_Governorate_Alias",
            "Governorate_ID",
        )

    print(
        "✓ Master database entities and aliases successfully synced "
        "to SQL Server dimensions via Upsert."
    )