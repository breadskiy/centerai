"""Assign records created before accounts to a known local workspace owner."""

import argparse

from sqlalchemy import select, update

from .auth import normalize_email
from .db import Account, Project, Session
from .migrate import upgrade


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Email of the registered owner")
    args = parser.parse_args()
    upgrade()
    with Session.begin() as db:
        owner = db.scalar(
            select(Account).where(Account.email == normalize_email(args.email))
        )
        if owner is None:
            parser.error("Register this account first.")
        updated = db.execute(
            update(Project).where(Project.owner_id.is_(None)).values(owner_id=owner.id)
        )
        print(f"Assigned {updated.rowcount} existing workspace records.")


if __name__ == "__main__":
    main()
