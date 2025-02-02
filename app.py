import os
from typing import Optional
from graphviz import Digraph
from sqlalchemy import create_engine, inspect
from flask import Flask, render_template, request, send_file, redirect, url_for, Response


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["ALLOWED_EXTENSIONS"] = {"db", "sqlite", "sqlite3"}

# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def allowed_file(filename: str) -> bool:
    """Check if the uploaded file has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]


def create_schema_graph(database_path: str, show_columns: bool = False) -> str:
    """
    Generate a schema graph using Graphviz.

    Args:
        database_path (str): Path to the SQLite database file.
        show_columns (bool): Whether to include column details in the graph.

    Returns:
        str: Path to the generated image file.
    """
    # Create database engine and inspector
    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)

    # Initialize Graphviz directed graph
    dot = Digraph(comment="Database Schema")
    dot.attr(rankdir="LR", splines="ortho")
    dot.attr("node", shape="rectangle", style="filled", fillcolor="lightgrey")

    # Add nodes for all tables
    tables = inspector.get_table_names()
    for table in tables:
        if show_columns:
            columns = inspector.get_columns(table)
            columns_str = "\n".join(
                f"{col['name']}: {col['type']}" f"{' (PK)' if col['primary_key'] else ''}" for col in columns
            )
            dot.node(table, f"{table}\n\n{columns_str}")
        else:
            dot.node(table)

    # Add edges for foreign key relationships
    for table in tables:
        for fk in inspector.get_foreign_keys(table):
            target_table = fk["referred_table"]
            constraint_cols = [f"{fk['constrained_columns']} → {fk['referred_columns']}"]
            dot.edge(
                table,
                target_table,
                label="\n".join(constraint_cols),
                fontsize="10",
                color="#0000FF",
                arrowhead="crow",
                arrowtail="dot",
                dir="both",
            )

    # Render and save the graph
    output_path = os.path.join(app.config["UPLOAD_FOLDER"], "schema")
    dot.render(output_path, format="png", cleanup=True)
    return f"{output_path}.png"


@app.route("/", methods=["GET", "POST"])
def index() -> Response:
    """Main route for uploading the database file."""
    if request.method == "POST":
        # Check if a file was uploaded
        if "file" not in request.files:
            return redirect(request.url)

        file = request.files["file"]
        if file.filename == "":
            return redirect(request.url)

        if file and allowed_file(file.filename):
            # Save the uploaded file
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)

            # Generate the schema graph
            show_columns = "show_columns" in request.form
            image_path = create_schema_graph(filepath, show_columns)

            # Redirect to the results page
            return redirect(url_for("results", filename=os.path.basename(image_path)))

    return render_template("index.html")


@app.route("/results")
def results() -> Response:
    """Route to display the generated schema graph."""
    filename: Optional[str] = request.args.get("filename")
    if not filename:
        return redirect(url_for("index"))

    return render_template("results.html", image_url=url_for("uploaded_file", filename=filename))


@app.route("/uploads/<filename>")
def uploaded_file(filename: str) -> Response:
    """Serve uploaded files."""
    return send_file(os.path.join(app.config["UPLOAD_FOLDER"], filename))


if __name__ == "__main__":
    app.run(debug=True)
