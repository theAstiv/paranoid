"""Reset the Paranoid database to a clean demo-ready state.

Usage:
  python scripts/demo_reset.py                  # interactive confirmation
  python scripts/demo_reset.py --yes             # skip confirmation
  python scripts/demo_reset.py --db data/demo.db # custom DB path

Creates:
  - Fresh database with all migrations applied
  - All 16 seed pattern collections loaded
  - Admin user (admin / paranoid-demo)
  - Demo user (analyst / paranoid-demo)
  - Demo project "Payment Gateway API" with both users
  - Demo project "RAG Chatbot Platform" with admin only
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


DEMO_ADMIN_PASSWORD = "paranoid-demo"
DEMO_ANALYST_PASSWORD = "paranoid-demo"

DEMO_PROJECTS = [
    {
        "name": "Payment Gateway API",
        "description": (
            "STRIDE threat model for a payment gateway handling UPI, card, "
            "and net-banking transactions. Includes PCI-DSS scoped trust "
            "boundaries and third-party acquirer integrations."
        ),
    },
    {
        "name": "RAG Chatbot Platform",
        "description": (
            "MAESTRO threat model for an internal RAG-based chatbot that "
            "indexes company documentation and answers employee queries. "
            "Uses Ollama for local inference and ChromaDB for vector storage."
        ),
    },
]


async def reset(db_path: str) -> None:
    db_file = Path(db_path)

    # Remove existing database
    if db_file.exists():
        print(f"  Removing existing database: {db_file}")
        db_file.unlink()
        # Also remove WAL and SHM files if present
        for suffix in (".db-wal", ".db-shm"):
            wal = db_file.with_suffix(suffix)
            if wal.exists():
                wal.unlink()

    # Ensure parent directory exists
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Override DB_PATH before importing backend modules
    os.environ["DB_PATH"] = str(db_file)

    from backend.auth.passwords import hash_password
    from backend.config import settings
    from backend.db.connection import db
    from backend.db.crud_auth import create_user
    from backend.db.crud_projects import add_member, create_project
    from backend.db.seed import load_all_seeds

    # Force settings to use our path
    settings.db_path = str(db_file)

    # Initialize fresh database (creates schema via migrations)
    print("  Initializing database schema...")
    await db.initialize(str(db_file))

    # Load all seed patterns
    print("  Loading seed patterns (362 patterns across 16 files)...")
    counts = await load_all_seeds(force=True)
    total = counts.get("total", sum(v for k, v in counts.items() if k != "total"))
    print(f"  Loaded {total} seed patterns from {len(counts) - 1} collections")

    # Create admin user
    print("  Creating admin user (admin / paranoid-demo)...")
    admin = await create_user(
        username="admin",
        email="admin@paranoid.local",
        password_hash=hash_password(DEMO_ADMIN_PASSWORD),
        display_name="Administrator",
        is_admin=True,
    )

    # Create demo analyst user
    print("  Creating analyst user (analyst / paranoid-demo)...")
    analyst = await create_user(
        username="analyst",
        email="analyst@paranoid.local",
        password_hash=hash_password(DEMO_ANALYST_PASSWORD),
        display_name="Security Analyst",
        is_admin=False,
    )

    # Create demo projects
    for proj in DEMO_PROJECTS:
        print(f"  Creating project: {proj['name']}...")
        project = await create_project(
            name=proj["name"],
            created_by=admin["id"],
            description=proj["description"],
        )
        # Add analyst as editor to the first project
        if proj["name"] == "Payment Gateway API":
            await add_member(project["id"], analyst["id"], "editor")
            print(f"    Added analyst as editor")

    # Close connection
    await db.close()

    print()
    print("  Demo environment ready!")
    print()
    print("  Credentials:")
    print(f"    Admin:   admin / {DEMO_ADMIN_PASSWORD}")
    print(f"    Analyst: analyst / {DEMO_ANALYST_PASSWORD}")
    print()
    print("  Projects:")
    for proj in DEMO_PROJECTS:
        print(f"    - {proj['name']}")
    print()
    print(f"  Database: {db_file.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="Reset Paranoid to a clean demo state"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--db",
        default="./data/paranoid.db",
        help="Database file path (default: ./data/paranoid.db)",
    )
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  PARANOID — Demo Reset")
    print("=" * 60)
    print()
    print(f"  This will DELETE the database at: {args.db}")
    print("  and recreate it with demo data.")
    print()

    if not args.yes:
        confirm = input("  Continue? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("  Aborted.")
            sys.exit(0)

    print()
    asyncio.run(reset(args.db))


if __name__ == "__main__":
    main()
