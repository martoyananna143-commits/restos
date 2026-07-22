#!/usr/bin/env python3
"""Script to create initial migration."""

import subprocess
import sys


def main():
    """Create initial migration."""
    try:
        print("Creating initial migration...")

        result = subprocess.run([
            "alembic", "revision", "--autogenerate", "-m", "Initial migration"
        ], check=True, capture_output=True, text=True)

        print("Migration created successfully!")
        print(result.stdout)

        print("Applying migration...")

        result = subprocess.run([
            "alembic", "upgrade", "head"
        ], check=True, capture_output=True, text=True)

        print("Migration applied successfully!")
        print(result.stdout)

        print("Database setup completed!")

    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: alembic not found. Make sure it's installed:")
        print("poetry install")
        sys.exit(1)


if __name__ == "__main__":
    main()
