"""SQLite helpers for reusing missing positive record IDs."""

_ID_TABLES = {
    "memories",
    "messages",
    "feedback",
    "learnings",
    "outcomes",
    "workflows",
}


def insert_with_lowest_free_id(conn, table: str, columns: tuple[str, ...], values: tuple):
    """Insert a row at the table's lowest unused positive ID."""
    if table not in _ID_TABLES or not columns or any(not column.isidentifier() for column in columns):
        raise ValueError("invalid ID table or columns")
    if len(columns) != len(values):
        raise ValueError("column and value counts differ")

    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    record_id = 1
    # ponytail: O(n) ordered ID scan; replace with a gap query if these tables reach millions of rows.
    for (existing_id,) in conn.execute(f'SELECT id FROM "{table}" ORDER BY id'):
        if existing_id < record_id:
            continue
        if existing_id > record_id:
            break
        record_id += 1

    column_sql = ", ".join(("id", *columns))
    placeholders = ", ".join("?" for _ in range(len(values) + 1))
    return conn.execute(
        f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
        (record_id, *values),
    )
