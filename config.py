import os
from dotenv import load_dotenv
INPUT_FILE = "data/input.xlsx"
UNMERGED_FILE="data/unmerged.xlsx"
PREPROCESSED_FILE = "data/preprocessed.xlsx"
OUTPUT_FILE = "data/output.xlsx"

GEMINI_MODEL = "gemini-3.5-flash-lite"
load_dotenv()  # reads .env into environment variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# Max number of raw values sent to Gemini in a single API call.
GEMINI_BATCH_SIZE = 200

MIN_CONFIDENCE_THRESHOLD = 0.7
FUZZY_MATCH_THRESHOLD = 80           # Minimum score to accept a match
FUZZY_HIGH_CONFIDENCE_THRESHOLD = 95  # Score at/above which we trust completely (no logging)


# Uses environment variables if available, otherwise defaults to the string provided
SQL_SERVER = os.getenv("SQL_SERVER", "SHARAF7") 
SQL_DATABASE = "VehicleMasterDB"
SQL_DRIVER = "ODBC Driver 17 for SQL Server"
# Trusted_Connection=yes tells pyodbc to use your Windows Login
SQL_TRUSTED_CONNECTION = "yes"
