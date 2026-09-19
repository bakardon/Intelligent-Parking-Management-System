from src.database import Database


def main():
    db = Database()

    print("Connecting to PostgreSQL...")
    db.initialize()
    print("Database connection successful.")

    db.save_occupancy(
        capacity=10,
        occupied=4,
        available=6,
    )

    print("Test occupancy record saved.")

    history = db.get_history(limit=5)

    print("\nRecent occupancy records:")

    for record in history:
        print(record)

    print("\nDATABASE TEST PASSED")


if __name__ == "__main__":
    main()