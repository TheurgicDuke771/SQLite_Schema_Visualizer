import os
from graphviz import Digraph
from snowflake.connector import connect
from flask import Flask, render_template, request, send_file, redirect, url_for


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Snowflake connection parameters
SNOWFLAKE_CONFIG = {
    "user": "your_username",
    "password": "your_password",
    "account": "your_account_identifier",
    "warehouse": "your_warehouse",
}


def create_snowflake_connection():
    """Create a connection to Snowflake."""
    return connect(**SNOWFLAKE_CONFIG)


def infer_relationships(cursor, tables, schema):
    """
    Infer relationships between tables based on column names, metadata, and naming conventions.

    Args:
        cursor: Snowflake cursor object.
        tables (list): List of table names.
        schema (str): Schema name to inspect.

    Returns:
        list: List of tuples representing inferred relationships (table, referenced_table, column).
    """
    relationships = []

    # Fetch all columns for tables in the specified schema
    cursor.execute(
        f"""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = '{schema}'
    """
    )
    columns = cursor.fetchall()

    # Create a dictionary of tables and their columns
    table_columns = {}
    for table, column in columns:
        if table not in table_columns:
            table_columns[table] = []
        table_columns[table].append(column)

    # Identify dimension and fact tables
    dim_tables = [table for table in tables if table.endswith("_dim")]
    fact_tables = [table for table in tables if table.endswith("_fact")]

    # Infer relationships based on column names and naming conventions
    for table in tables:
        for column in table_columns.get(table, []):
            # Heuristic 1: Columns ending with '_ID', '_num', or '_number' often reference another table
            if column.endswith("_ID") or column.endswith("_num") or column.endswith("_number"):
                # Remove suffix to infer referenced table
                if column.endswith("_ID"):
                    referenced_table = column[:-3]  # Remove '_ID'
                elif column.endswith("_num"):
                    referenced_table = column[:-4]  # Remove '_num'
                elif column.endswith("_number"):
                    referenced_table = column[:-7]  # Remove '_number'

                # Check if the referenced table exists
                if referenced_table in tables:
                    relationships.append((table, referenced_table, column))
                # Check if the referenced table has a corresponding _dim table
                elif f"{referenced_table}_dim" in tables:
                    relationships.append((table, f"{referenced_table}_dim", column))

            # Heuristic 2: Columns with names like 'TABLE_NAME_ID' reference 'TABLE_NAME'
            elif "_ID" in column or "_num" in column or "_number" in column:
                if "_ID" in column:
                    referenced_table = column.split("_ID")[0]
                elif "_num" in column:
                    referenced_table = column.split("_num")[0]
                elif "_number" in column:
                    referenced_table = column.split("_number")[0]

                if referenced_table in tables:
                    relationships.append((table, referenced_table, column))
                # Check if the referenced table has a corresponding _dim table
                elif f"{referenced_table}_dim" in tables:
                    relationships.append((table, f"{referenced_table}_dim", column))

            # Heuristic 3: Columns with names matching another table's primary key
            elif column in tables:
                referenced_table = column
                if referenced_table in tables:
                    relationships.append((table, referenced_table, column))
                # Check if the referenced table has a corresponding _dim table
                elif f"{referenced_table}_dim" in tables:
                    relationships.append((table, f"{referenced_table}_dim", column))

    return relationships


def create_schema_graph(database, schema, show_columns=False):
    """
    Generate a schema graph using Graphviz for a specified database and schema.

    Args:
        database (str): Database name.
        schema (str): Schema name.
        show_columns (bool): Whether to include column details in the graph.

    Returns:
        str: Path to the generated image file.
    """
    # Initialize Graphviz directed graph
    dot = Digraph(comment=f"{database}.{schema} Schema")
    dot.attr(rankdir="LR", splines="ortho")
    dot.attr("node", shape="rectangle", style="filled", fillcolor="lightgrey")

    # Connect to Snowflake
    conn = create_snowflake_connection()
    cursor = conn.cursor()

    try:
        # Use the specified database and schema
        cursor.execute(f"USE DATABASE {database}")
        cursor.execute(f"USE SCHEMA {schema}")

        # Fetch all tables and views in the specified schema
        cursor.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = '{schema}'
        """
        )
        tables = [row[0] for row in cursor.fetchall()]

        # Add nodes for all tables/views
        for table in tables:
            if show_columns:
                # Fetch column details
                cursor.execute(
                    f"""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = '{schema}' AND table_name = '{table}'
                """
                )
                columns = cursor.fetchall()
                columns_str = "\n".join(
                    f"{col[0]}: {col[1]}{' (nullable)' if col[2] == 'YES' else ''}" for col in columns
                )
                dot.node(table, f"{table}\n\n{columns_str}")
            else:
                dot.node(table)

        # Infer relationships between tables
        relationships = infer_relationships(cursor, tables, schema)
        for table, referenced_table, column in relationships:
            dot.edge(
                table,
                referenced_table,
                label=column,
                fontsize="10",
                color="#666666",
                arrowhead="crow",
                arrowtail="dot",
                dir="both",
            )

    finally:
        cursor.close()
        conn.close()

    # Render and save the graph
    output_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{database}_{schema}_schema")
    dot.render(output_path, format="png", cleanup=True)
    return f"{output_path}.png"


@app.route("/", methods=["GET", "POST"])
def index():
    """Main route for generating the schema graph."""
    if request.method == "POST":
        database = request.form.get("database")
        schema = request.form.get("schema")
        show_columns = "show_columns" in request.form

        if not database or not schema:
            return redirect(request.url)

        image_path = create_schema_graph(database, schema, show_columns)
        return redirect(url_for("results", filename=os.path.basename(image_path)))

    return render_template("index.html")


@app.route("/results")
def results():
    """Route to display the generated schema graph."""
    filename = request.args.get("filename")
    if not filename:
        return redirect(url_for("index"))
    return render_template("results.html", image_url=url_for("uploaded_file", filename=filename))


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_file(os.path.join(app.config["UPLOAD_FOLDER"], filename))


if __name__ == "__main__":
    app.run(debug=True)
