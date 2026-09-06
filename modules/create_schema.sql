
use VehicleMasterDB
CREATE TABLE Dim_Brand (
    Brand_ID        VARCHAR(10)   NOT NULL PRIMARY KEY,
    Canonical_Name  NVARCHAR(200) NOT NULL,
    Normalized_Name NVARCHAR(200) NOT NULL,
    Country         NVARCHAR(100) NULL
);

CREATE TABLE Dim_Brand_Alias (
    Alias_ID   INT IDENTITY(1,1) PRIMARY KEY,
    Brand_ID   VARCHAR(10)   NOT NULL FOREIGN KEY REFERENCES Dim_Brand(Brand_ID),
    Alias      NVARCHAR(200) NOT NULL,
    CONSTRAINT UQ_Brand_Alias UNIQUE (Brand_ID, Alias)
);

CREATE TABLE Dim_Model (
    Model_ID        VARCHAR(10)   NOT NULL PRIMARY KEY,
    Brand_ID        VARCHAR(10)   NOT NULL FOREIGN KEY REFERENCES Dim_Brand(Brand_ID),
    Canonical_Name  NVARCHAR(200) NOT NULL,
    Normalized_Name NVARCHAR(200) NOT NULL,
    Motor_Type      NVARCHAR(50)  NULL
);

CREATE TABLE Dim_Model_Alias (
    Alias_ID   INT IDENTITY(1,1) PRIMARY KEY,
    Model_ID   VARCHAR(10)   NOT NULL FOREIGN KEY REFERENCES Dim_Model(Model_ID),
    Alias      NVARCHAR(200) NOT NULL,
    CONSTRAINT UQ_Model_Alias UNIQUE (Model_ID, Alias)
);

CREATE TABLE Dim_LicenseType (
    LicenseType_ID  VARCHAR(10)   NOT NULL PRIMARY KEY,
    Canonical_Name  NVARCHAR(200) NOT NULL,
    Normalized_Name NVARCHAR(200) NOT NULL
);

CREATE TABLE Dim_LicenseType_Alias (
    Alias_ID       INT IDENTITY(1,1) PRIMARY KEY,
    LicenseType_ID VARCHAR(10)   NOT NULL FOREIGN KEY REFERENCES Dim_LicenseType(LicenseType_ID),
    Alias          NVARCHAR(200) NOT NULL,
    CONSTRAINT UQ_LicenseType_Alias UNIQUE (LicenseType_ID, Alias)
);

CREATE TABLE Dim_Governorate (
    Governorate_ID  VARCHAR(10)   NOT NULL PRIMARY KEY,
    Canonical_Name  NVARCHAR(200) NOT NULL,
    Normalized_Name NVARCHAR(200) NOT NULL
);

CREATE TABLE Dim_Governorate_Alias (
    Alias_ID       INT IDENTITY(1,1) PRIMARY KEY,
    Governorate_ID VARCHAR(10)   NOT NULL FOREIGN KEY REFERENCES Dim_Governorate(Governorate_ID),
    Alias          NVARCHAR(200) NOT NULL,
    CONSTRAINT UQ_Governorate_Alias UNIQUE (Governorate_ID, Alias)
);

-- Atomic ID counters, one row per entity type. UPDATE ... OUTPUT makes
-- allocating the next ID a single atomic statement, so two processes
-- running at the same time can never be handed the same ID (the old
-- JSON "_metadata" counters could not guarantee that).
CREATE TABLE Dim_Counters (
    EntityType VARCHAR(50) NOT NULL PRIMARY KEY,
    NextValue  INT NOT NULL
);

INSERT INTO Dim_Counters (EntityType, NextValue) VALUES
    ('brand', 1),
    ('model', 1),
    ('license_type', 1),
    ('governorate_city', 1);



