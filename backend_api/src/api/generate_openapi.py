import json
import os

# Importing app from main does not initialize the DB because engine creation is deferred
# until startup and get_engine() call. This is safe for schema generation.
from src.api.main import app

# Get the OpenAPI schema
openapi_schema = app.openapi()

# Write to file
output_dir = "interfaces"
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "openapi.json")

with open(output_path, "w") as f:
    json.dump(openapi_schema, f, indent=2)
