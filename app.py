"""StockWise - Inventory Optimization System (Streamlit frontend).

Run:  streamlit run app.py
All searching, sorting, hashing and heap work is done by the C engine
(backend/libstockwise) through c_bridge.py. SQLite (database.py) stores data.
Theme: .streamlit/config.toml. Artwork: assets/*.svg. Icons: Material Symbols.
"""
import os
import random
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

import database as db
from c_bridge import Engine, StockWiseError, load_library

st.set_page_config(page_title="StockWise", page_icon=":material/inventory_2:", layout="wide")

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO, MARK, HERO, EMPTY, ARCHITECTURE = (os.path.join(ASSETS, f) for f in (
    "logo.svg", "mark.svg", "hero.svg", "empty.svg", "architecture.svg"))

# Chart palette: validated categorical slots 1-3 (blue, orange, aqua) + neutral chrome.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, MUTED, GRID, AXIS = "#14171f", "#52525b", "#898781", "#e1e0d9", "#c3c2b7"
# Plotly Express picks trace colors at creation time, so set them here, not per layout.
px.defaults.template = "plotly_white"
px.defaults.color_discrete_sequence = [BLUE, ORANGE, AQUA]

COMPLEXITY = pd.DataFrame([
    ("Linear search", "O(1)", "O(n)", "O(n)", "O(1)", "Works on unsorted data"),
    ("Binary search", "O(1)", "O(log n)", "O(log n)", "O(1)", "Needs data sorted by id"),
    ("Hash table lookup", "O(1)", "O(1)", "O(n)", "O(n + m)", "Separate chaining, m buckets"),
    ("Merge Sort", "O(n log n)", "O(n log n)", "O(n log n)", "O(n)", "Stable, divide & conquer"),
    ("Insertion Sort", "O(n)", "O(n²)", "O(n²)", "O(1)", "Stable, fast on nearly sorted data"),
    ("Heap insert", "O(1)", "O(log n)", "O(log n)", "O(1)", "Sift up"),
    ("Heap extract-max", "O(log n)", "O(log n)", "O(log n)", "O(1)", "Sift down"),
    ("Restock ranking", "O(n log n)", "O(n log n)", "O(n log n)", "O(n)", "n pushes + n pops"),
], columns=["Algorithm", "Best", "Average", "Worst", "Space", "Notes"])

PSEUDOCODE = {
    "Linear search": """for i = 0 to n-1:
    comparisons += 1
    if A[i].id == target: return i
return NOT_FOUND""",
    "Binary search": """low = 0, high = n-1            # A sorted by id
while low <= high:
    mid = low + (high - low) / 2
    comparisons += 1
    if A[mid].id == target: return mid
    if A[mid].id < target: low = mid + 1
    else: high = mid - 1
return NOT_FOUND""",
    "Hash table (separate chaining)": """hash(k) = k mod m
insert(k, v):
    b = hash(k)
    if k already in chain[b]: return DUPLICATE
    new node -> head of chain[b]
find(k):
    for node in chain[hash(k)]:
        comparisons += 1
        if node.key == k: return node.value
    return NOT_FOUND""",
    "Merge Sort": """merge_sort(A, lo, hi):
    if hi - lo < 2: return
    mid = (lo + hi) / 2
    merge_sort(A, lo, mid); merge_sort(A, mid, hi)
    merge(A, lo, mid, hi)        # take from left on ties -> stable
merge: repeatedly copy the smaller head of the two runs into tmp,
       then copy tmp back into A[lo..hi)""",
    "Insertion Sort": """for i = 1 to n-1:
    current = A[i]; j = i - 1
    while j >= 0 and A[j] > current:   # strict > keeps it stable
        A[j+1] = A[j]; j -= 1
    A[j+1] = current""",
    "Max-Heap priority queue": """push(x):  A[size] = x; i = size; size += 1
          while i > 0 and A[i] > A[parent(i)]: swap; i = parent(i)
pop():    top = A[0]; A[0] = A[size-1]; size -= 1
          sift down: swap with the larger child until heap property holds
          return top
parent(i) = (i-1)/2, left(i) = 2i+1, right(i) = 2i+2""",
}

STATUS_BADGE = {"Out of stock": ":red-badge[:material/error: Out of stock]",
                "Low stock": ":orange-badge[:material/warning: Low stock]",
                "In stock": ":green-badge[:material/check_circle: In stock]"}


# ---------------------------------------------------------------- helpers
@st.cache_resource
def get_connection():
    conn = db.connect()
    db.init_db(conn)
    return conn


def flash(message):
    """Show a confirmation toast after st.rerun()."""
    st.session_state["flash"] = message
    st.rerun()


def header(title, subtitle):
    st.title(title, anchor=False)
    st.caption(subtitle)


def card_title(text):
    st.subheader(text, anchor=False)


def empty_state(message):
    st.image(EMPTY, width=160)
    st.caption(message)


def chart(fig, key, height=320, legend=False, bargap=0.35):
    """Render a Plotly figure with the shared StockWise chart styling."""
    fig.update_layout(
        height=height, showlegend=legend, bargap=bargap, barcornerradius=4,
        margin=dict(l=0, r=12, t=40 if legend else 8, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=13, color=INK_2),
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", title_text=""),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=GRID, font=dict(color=INK)))
    for axis in (fig.update_xaxes, fig.update_yaxes):
        axis(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont_color=INK_2,
             title_font_color=INK_2, automargin=True)
    st.plotly_chart(fig, key=key, theme=None, config={"displayModeBar": False})


def stock_status(p):
    if p["quantity"] == 0:
        return "Out of stock"
    return "Low stock" if p["quantity"] <= p["min_stock"] else "In stock"


def to_frame(products):
    df = pd.DataFrame(products, columns=list(db.PRODUCT_FIELDS))
    df["value"] = (df["price"] * df["quantity"]).round(2)
    df["status"] = [stock_status(p) for p in products]
    return df.rename(columns={"id": "ID", "name": "Name", "category": "Category",
                              "price": "Price", "quantity": "Qty", "min_stock": "Min stock",
                              "demand": "Demand", "importance": "Importance",
                              "value": "Value", "status": "Status"})


def show_products(products, height="auto"):
    if not products:
        empty_state("No products match.")
        return
    st.dataframe(to_frame(products), hide_index=True, height=height,
                 column_config={"Price": st.column_config.NumberColumn(format="$%.2f"),
                                "Value": st.column_config.NumberColumn(format="$%.2f"),
                                "Importance": st.column_config.NumberColumn(format="%d / 5")})


def show_transactions(rows):
    if not rows:
        empty_state("No transactions recorded yet.")
        return
    df = pd.DataFrame(rows).rename(columns={
        "id": "Tx", "created_at": "Time", "product_id": "Product ID", "product_name": "Product",
        "type": "Type", "quantity": "Quantity", "balance_after": "Balance", "note": "Note"})
    df["Type"] = df["Type"].map({"IN": "Stock in", "OUT": "Stock out"})
    st.dataframe(df, hide_index=True)


def product_label(p):
    return f"{p['id']} · {p['name']}"


def pick_product(container, label, products, key=None, extra=lambda p: ""):
    """Selectbox keyed by product id, so the choice survives data changes."""
    by_id = {p["id"]: p for p in products}
    pid = container.selectbox(label, list(by_id), key=key,
                              format_func=lambda i: product_label(by_id[i]) + extra(by_id[i]))
    return by_id[pid]


def generate_products(n, seed):
    """Random but valid inventory for the lab (ids are shuffled, not sorted)."""
    rng = random.Random(seed)
    words = ["Steel", "Blue", "Organic", "Mini", "Pro", "Eco", "Classic", "Smart", "Ultra"]
    things = ["Bolt", "Lamp", "Tea", "Cable", "Notebook", "Soap", "Juice", "Fan", "Mug"]
    cats = ["Electronics", "Grocery", "Stationery", "Cleaning", "Beverages"]
    ids = rng.sample(range(1, max(n * 10, 10)), n)
    return [{"id": i, "name": f"{rng.choice(words)} {rng.choice(things)} {k}",
             "category": rng.choice(cats), "price": round(rng.uniform(0.5, 120), 2),
             "quantity": rng.randint(0, 150), "min_stock": rng.randint(5, 60),
             "demand": None if rng.random() < 0.05 else rng.randint(0, 100),
             "importance": None if rng.random() < 0.05 else rng.randint(1, 5)}
            for k, i in enumerate(ids)]


def product_form(key, defaults, id_editable):
    """Shared add/edit form. Returns a product dict when submitted, else None."""
    with st.form(key, clear_on_submit=id_editable, border=True):
        st.markdown("**Details**")
        c1, c2, c3 = st.columns(3)
        pid = c1.number_input("Product ID", min_value=1, step=1, value=defaults["id"],
                              disabled=not id_editable)
        name = c2.text_input("Name", value=defaults["name"], max_chars=63,
                             placeholder="e.g. USB-C Charging Cable")
        category = c3.text_input("Category", value=defaults["category"], max_chars=31,
                                 placeholder="e.g. Electronics")
        st.markdown("**Stock and pricing**")
        c1, c2, c3 = st.columns(3)
        price = c1.number_input("Price ($)", min_value=0.0, step=0.5, format="%.2f",
                                value=float(defaults["price"]))
        quantity = c2.number_input("Quantity", min_value=0, step=1, value=defaults["quantity"],
                                   disabled=not id_editable,
                                   help=None if id_editable else
                                   "Change stock on the Transactions page.")
        min_stock = c3.number_input("Minimum stock", min_value=0, step=1,
                                    value=defaults["min_stock"])
        st.markdown("**Planning inputs**")
        c1, c2, c3 = st.columns(3)
        demand = c1.number_input("Estimated demand (units/month)", min_value=0, step=1,
                                 value=defaults["demand"] or 0)
        demand_unknown = c2.checkbox("Demand unknown", value=defaults["demand"] is None)
        importance = c3.select_slider("Importance", options=["Unknown", 1, 2, 3, 4, 5],
                                      value=defaults["importance"] or "Unknown")
        if not st.form_submit_button("Save product", type="primary", icon=":material/save:"):
            return None
    return {"id": int(pid), "name": name, "category": category, "price": float(price),
            "quantity": int(quantity), "min_stock": int(min_stock),
            "demand": None if demand_unknown else int(demand),
            "importance": None if importance == "Unknown" else int(importance)}


def search_box(engine, key):
    """Search by numeric id (C hash table) or by name (C linear search)."""
    query = st.text_input("Search", key=key, icon=":material/search:",
                          placeholder="Search by product ID or name, e.g. 1042 or cable",
                          label_visibility="collapsed").strip()
    if not query:
        return None
    if query.isdigit():
        r = engine.hash_search(int(query))
        st.caption(f":material/tag: Hash table lookup in C · {r['comparisons']} comparison(s)")
        return [r["product"]] if r["found"] else []
    r = engine.search_name(query)
    st.caption(f":material/manage_search: Linear name search in C · "
               f"{r['comparisons']} comparison(s)")
    return r["products"]


# ---------------------------------------------------------------- pages
def page_dashboard(conn, products, engine):
    st.image(HERO, width="stretch")
    total_units = sum(p["quantity"] for p in products)
    total_value = sum(p["price"] * p["quantity"] for p in products)
    out = sum(p["quantity"] == 0 for p in products)
    low = sum(0 < p["quantity"] <= p["min_stock"] for p in products)
    c = st.columns(5)
    c[0].metric("Products", len(products), border=True, icon=":material/inventory_2:")
    c[1].metric("Units in stock", f"{total_units:,}", border=True, icon=":material/package_2:")
    c[2].metric("Inventory value", f"${total_value:,.0f}", border=True,
                icon=":material/payments:", help=f"${total_value:,.2f} exactly")
    c[3].metric("Low stock", low, border=True, icon=":material/warning:",
                help="Above zero but at or below minimum stock")
    c[4].metric("Out of stock", out, border=True, icon=":material/error:")
    if not products:
        empty_state("No products yet. Add your first one on the Products page.")
        return

    left, right = st.columns(2)
    with left.container(border=True):
        card_title("Inventory value by category")
        by_cat = to_frame(products).groupby("Category", as_index=False)["Value"].sum()
        fig = px.bar(by_cat.sort_values("Value"), x="Value", y="Category", orientation="h")
        fig.update_traces(hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>")
        fig.update_xaxes(title=None, tickprefix="$")
        fig.update_yaxes(title=None, showgrid=False)
        chart(fig, "cat")

    top = engine.sort("value", "merge", descending=True)
    with right.container(border=True):
        card_title("Highest-value products")
        top_df = to_frame(top["products"][:8]).iloc[::-1]
        fig = px.bar(top_df, x="Value", y="Name", orientation="h")
        fig.update_traces(hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>")
        fig.update_xaxes(title=None, tickprefix="$")
        fig.update_yaxes(title=None, showgrid=False)
        chart(fig, "top")
        st.caption(f"Ranked by C Merge Sort · {top['comparisons']} comparisons")

    left, right = st.columns([2, 3])
    with left.container(border=True):
        card_title("Needs attention")
        ranking = engine.restock_ranking()["ranking"][:5]
        if not ranking:
            st.caption("Every product is above its minimum stock.")
        for p in ranking:
            a, b = st.columns([3, 2], vertical_alignment="center")
            a.markdown(f"**{p['name']}**  \n:gray[{p['quantity']} of {p['min_stock']} min · "
                       f"priority {p['score']:.0f}]")
            b.markdown(STATUS_BADGE[stock_status(p)])
    with right.container(border=True):
        card_title("Recent transactions")
        show_transactions(db.list_transactions(conn, limit=6))


def page_products(conn, products, engine):
    header("Products", "Manage the product catalog. Search runs on the C hash table "
                       "(by ID) or C linear search (by name).")
    view, add, edit, delete = st.tabs([":material/table_view: Catalog",
                                       ":material/add_circle: Add product",
                                       ":material/edit: Edit", ":material/delete: Delete"])

    with view:
        c1, c2 = st.columns([3, 2])
        with c1:
            found = search_box(engine, "pm_search")
        cats = sorted({p["category"] for p in products})
        chosen = c2.multiselect("Category", cats, placeholder="All categories",
                                label_visibility="collapsed")
        shown = products if found is None else found
        if chosen:
            shown = [p for p in shown if p["category"] in chosen]
        st.caption(f"{len(shown)} of {len(products)} products")
        show_products(shown)

    with add:
        next_id = max((p["id"] for p in products), default=1000) + 1
        new = product_form("add_form", {"id": next_id, "name": "", "category": "",
                                        "price": 0.0, "quantity": 0, "min_stock": 10,
                                        "demand": None, "importance": 3}, True)
        if new is not None:
            try:
                db.add_product(conn, new)
                flash(f"Added product {new['id']} · {new['name'].strip()}")
            except ValueError as exc:
                st.error(f"Could not add product: {exc}", icon=":material/error:")

    if not products:
        with edit:
            empty_state("No products to edit.")
        with delete:
            empty_state("No products to delete.")
        return

    with edit:
        p = pick_product(st, "Product to edit", products, key="edit_pick")
        st.caption(":material/info: Quantity changes go through Transactions so every change "
                   "has a history record.")
        changes = product_form(f"edit_form_{p['id']}", p, False)
        if changes is not None:
            try:
                db.update_product(conn, p["id"], changes)
                flash(f"Updated product {p['id']}")
            except ValueError as exc:
                st.error(f"Could not update product: {exc}", icon=":material/error:")

    with delete:
        p = pick_product(st, "Product to delete", products, key="delete_pick")
        with st.container(border=True):
            st.markdown(f"**Delete {p['name']}?**")
            st.caption("This also removes the product's transaction history. "
                       "It cannot be undone.")
            sure = st.checkbox("I understand, delete this product", key=f"sure_{p['id']}")
            if st.button("Delete product", type="primary", disabled=not sure,
                         icon=":material/delete:"):
                db.delete_product(conn, p["id"])
                flash(f"Deleted product {p['id']} · {p['name']}")


def page_search_sort(products, engine):
    header("Search and sorting", "Run the C search and sort algorithms on the live catalog "
                                 "and compare the work each one does.")
    with st.container(border=True):
        card_title("Search")
        c1, c2 = st.columns([1, 2], gap="large")
        method = c1.radio("Algorithm", ["Hash table", "Binary search", "Linear search",
                                        "Linear search by name"],
                          captions=["O(1) average", "O(log n), id-sorted index", "O(n)",
                                    "O(n), substring match"])
        with c2:
            if method == "Linear search by name":
                text = st.text_input("Product name contains", placeholder="e.g. cable",
                                     icon=":material/search:")
                if text.strip():
                    r = engine.search_name(text)
                    st.metric("Comparisons", r["comparisons"], border=True,
                              icon=":material/compare_arrows:")
                    show_products(r["products"])
            else:
                pid = st.number_input("Product ID", min_value=1, step=1, value=1042)
                fn = {"Hash table": engine.hash_search, "Binary search": engine.binary_search,
                      "Linear search": engine.linear_search}[method]
                r = fn(int(pid))
                st.metric("Comparisons", r["comparisons"], border=True,
                          icon=":material/compare_arrows:")
                if r["found"]:
                    show_products([r["product"]])
                else:
                    st.warning(f"Product {int(pid)} was not found.", icon=":material/search_off:")
        st.caption("Binary search runs on an id-sorted index that the C engine builds with "
                   "Merge Sort; products are stored in name order.")

    with st.container(border=True):
        card_title("Sort")
        c1, c2, c3 = st.columns(3)
        key = c1.selectbox("Sort by", ["name", "price", "quantity", "value"],
                           format_func=str.title)
        algorithm = c2.selectbox("Algorithm", ["merge", "insertion"],
                                 format_func=lambda a: f"{a.title()} Sort")
        descending = c3.segmented_control("Order", ["Ascending", "Descending"],
                                          default="Ascending") == "Descending"
        r = engine.sort(key, algorithm, descending)
        c = st.columns(3)
        c[0].metric("Comparisons", f"{r['comparisons']:,}", border=True,
                    icon=":material/compare_arrows:")
        c[1].metric("Element moves", f"{r['moves']:,}", border=True,
                    icon=":material/swap_vert:")
        c[2].metric("Time complexity", "O(n log n)" if algorithm == "merge" else "O(n²)",
                    border=True, icon=":material/timer:",
                    help=None if algorithm == "merge" else "Best case O(n) on sorted input")
        show_products(r["products"])


def page_restock(conn, engine):
    header("Restocking", "Products at or below minimum stock, ranked by a C Max-Heap "
                         "priority queue.")
    result = engine.restock_ranking()
    ranking = result["ranking"]
    if not ranking:
        empty_state("Every product is above its minimum stock. Nothing to restock.")
        return

    c = st.columns(4)
    c[0].metric("Products to restock", len(ranking), border=True,
                icon=":material/local_shipping:")
    c[1].metric("Out of stock", sum(p["quantity"] == 0 for p in ranking), border=True,
                icon=":material/error:")
    c[2].metric("Units to order", f"{sum(p['suggested_qty'] for p in ranking):,}",
                border=True, icon=":material/shopping_cart:")
    c[3].metric("Heap operations", f"{result['comparisons'] + result['swaps']}", border=True,
                icon=":material/account_tree:",
                help=f"{result['comparisons']} comparisons, {result['swaps']} swaps")

    with st.container(border=True):
        card_title("Priority ranking")
        rows = [{"Rank": i + 1, "ID": p["id"], "Name": p["name"], "Stock": p["quantity"],
                 "Min stock": p["min_stock"], "Priority": p["score"],
                 "Reason": "; ".join(p["reasons"]), "Suggested qty": p["suggested_qty"]}
                for i, p in enumerate(ranking)]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     column_config={"Priority": st.column_config.ProgressColumn(
                         min_value=0, max_value=100, format="%.1f", color=BLUE)})
        with st.expander("How the priority score is calculated", icon=":material/function:"):
            st.latex(r"\text{Priority} = 100 \times (0.5\,S + 0.3\,D + 0.2\,I)")
            st.markdown(
                "- **S, shortage** = (min stock − quantity) / min stock, clamped to 0..1 "
                "(min stock 0: 1 if out of stock, else 0)\n"
                "- **D, demand** = demand / highest demand in the inventory\n"
                "- **I, importance** = (importance − 1) / 4 for importance 1..5\n"
                "- Missing demand or importance uses a neutral **0.5**.\n"
                "- **Suggested quantity** = min stock + one month of demand − quantity "
                "(2 × min stock − quantity if demand is unknown), at least 1.")

    left, right = st.columns([3, 2])
    with left.container(border=True):
        card_title("Score breakdown")
        parts = pd.DataFrame([{"Name": p["name"], "Shortage": 50 * p["shortage_score"],
                               "Demand": 30 * p["demand_score"],
                               "Importance": 20 * p["importance_score"]}
                              for p in ranking[:10]])
        fig = px.bar(parts.iloc[::-1], y="Name", x=["Shortage", "Demand", "Importance"],
                     orientation="h")
        fig.update_traces(marker_line_color="#ffffff", marker_line_width=2,
                          hovertemplate="%{y}<br>%{fullData.name}: %{x:.1f} pts<extra></extra>")
        fig.update_xaxes(title="Priority points", range=[0, 100])
        fig.update_yaxes(title=None, showgrid=False)
        chart(fig, "breakdown", height=380, legend=True)

    with right.container(border=True):
        card_title("Record a delivery")
        with st.form("restock_form", border=False):
            p = pick_product(st, "Product", ranking,
                             extra=lambda p: f" · suggested {p['suggested_qty']}")
            qty = st.number_input("Quantity received", min_value=0, step=1,
                                  help="Leave at 0 to use the suggested quantity.")
            if st.form_submit_button("Record delivery", type="primary",
                                     icon=":material/local_shipping:"):
                amount = int(qty) or p["suggested_qty"]
                balance = db.record_transaction(conn, p["id"], "IN", amount, "Restock")
                flash(f"Added {amount} units to {p['name']} · now {balance}")


def page_transactions(conn, products):
    header("Transactions", "Stock in and stock out are saved atomically with their history, "
                           "and stock can never go negative.")
    if not products:
        empty_state("Add a product first.")
        return
    with st.form("tx_form", clear_on_submit=True):
        card_title("New transaction")
        c1, c2, c3 = st.columns([2, 1, 1])
        p = pick_product(c1, "Product", products, extra=lambda p: f" · stock {p['quantity']}")
        kind = c2.radio("Type", ["Add stock (IN)", "Reduce stock (OUT)"])
        qty = c3.number_input("Quantity", min_value=1, step=1)
        note = st.text_input("Note (optional)", max_chars=200,
                             placeholder="e.g. Supplier delivery, customer order")
        if st.form_submit_button("Record transaction", type="primary",
                                 icon=":material/sync_alt:"):
            tx_type = "IN" if kind.startswith("Add") else "OUT"
            try:
                balance = db.record_transaction(conn, p["id"], tx_type, int(qty), note)
                flash(f"{'Added' if tx_type == 'IN' else 'Removed'} {int(qty)} × "
                      f"{p['name']} · balance {balance}")
            except ValueError as exc:
                st.error(f"Transaction rejected: {exc}", icon=":material/block:")

    with st.container(border=True):
        card_title("History")
        by_id = {p["id"]: p for p in products}
        choice = st.selectbox("Show", [None] + list(by_id), format_func=lambda i: "All products"
                              if i is None else product_label(by_id[i]))
        show_transactions(db.list_transactions(conn, product_id=choice))


def run_edge_cases():
    """Execute real edge-case calls against the C engine and a scratch database."""
    cases = []

    def case(name, expected, fn):
        try:
            actual = fn()
        except (ValueError, StockWiseError) as exc:
            actual = f"Error: {exc}"
        cases.append({"Case": name, "Expected": expected, "Actual": str(actual),
                      "Result": "Passed" if str(actual).startswith(expected) else "Failed"})

    sample = generate_products(5, 1)
    with Engine([]) as empty, Engine(sample) as eng:
        case("Hash search on empty array", "not found",
             lambda: "found" if empty.hash_search(1)["found"] else "not found")
        case("Binary search on empty array", "not found",
             lambda: "found" if empty.binary_search(1)["found"] else "not found")
        case("Sort empty array", "[]", lambda: empty.sort("name")["products"])
        case("Restock on empty array", "[]", lambda: empty.restock_ranking()["ranking"])
        case("Missing product id (all 3 searches)", "not found",
             lambda: "found" if any(f(10**7)["found"] for f in
                                    (eng.linear_search, eng.binary_search, eng.hash_search))
             else "not found")
        case("Empty name query", "Error", lambda: eng.search_name(""))
    case("Duplicate product ids", "Error", lambda: Engine([sample[0], sample[0]]))
    case("Negative price", "Error", lambda: Engine([{**sample[0], "price": -5}]))
    case("Negative quantity", "Error", lambda: Engine([{**sample[0], "quantity": -1}]))

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn, seed=False)
    db.add_product(conn, {**sample[0], "quantity": 3})
    case("Remove more stock than available", "Error",
         lambda: db.record_transaction(conn, sample[0]["id"], "OUT", 4))
    case("Stock unchanged after rejected removal", "3",
         lambda: db.get_product(conn, sample[0]["id"])["quantity"])
    conn.close()
    return pd.DataFrame(cases)


def heap_dot(heap):
    lines = ['digraph { bgcolor="transparent"; nodesep=0.25; ranksep=0.35;',
             'node [shape=box, style="rounded,filled", fillcolor="#eef4fc", color="#86b6ef", '
             'fontname="Inter", fontsize=11, fontcolor="#14171f", penwidth=1.2];',
             'edge [color="#c3c2b7", arrowsize=0.6];']
    for i, p in enumerate(heap[:31]):
        root = ', fillcolor="#2a78d6", color="#2a78d6", fontcolor="#ffffff"' if i == 0 else ""
        lines.append(f'n{i} [label="{p["id"]}\\n{p["score"]:.1f}"{root}];')
        if i > 0:
            lines.append(f"n{(i - 1) // 2} -> n{i};")
    return "\n".join(lines + ["}"])


def page_lab(products):
    header("DSA laboratory", "Experiment with the C data structures on real or generated "
                             "inventory data.")
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        source = c1.segmented_control("Data", ["Real inventory", "Generated"],
                                      default="Real inventory")
        generated = source == "Generated"
        n = c2.number_input("Sample size", 0, 5000, 200, step=50, disabled=not generated)
        seed = c3.number_input("Random seed", 0, 10_000, 42, disabled=not generated)
        buckets = c4.number_input("Hash buckets (0 = auto)", 0, 100_000, 0)
    data = generate_products(int(n), int(seed)) if generated else products

    with Engine(data, bucket_count=int(buckets)) as eng:
        tabs = st.tabs([":material/search: Search", ":material/sort: Sorting",
                        ":material/tag: Hash table", ":material/account_tree: Max-Heap",
                        ":material/rule: Edge cases", ":material/code: Pseudocode"])
        with tabs[0]:
            default = data[len(data) // 2]["id"] if data else 1
            pid = st.number_input("Target product ID (try a missing one too)", 1, 2**31 - 1,
                                  default)
            rows = []
            for name, fn, cx in [("Linear search", eng.linear_search, "O(n)"),
                                 ("Binary search", eng.binary_search, "O(log n)"),
                                 ("Hash table", eng.hash_search, "O(1) average")]:
                r = fn(int(pid))
                rows.append({"Algorithm": name, "Result": "Found" if r["found"] else "Not found",
                             "Product": r["product"]["name"] if r["found"] else "-",
                             "Comparisons": r["comparisons"], "Complexity": cx})
            df = pd.DataFrame(rows)
            left, right = st.columns([3, 2])
            left.dataframe(df, hide_index=True)
            with right:
                fig = px.bar(df, x="Algorithm", y="Comparisons", text="Comparisons")
                fig.update_traces(textposition="outside", textfont_color=INK, cliponaxis=False,
                                  hovertemplate="%{x}<br>%{y} comparisons<extra></extra>")
                fig.update_xaxes(title=None, showgrid=False)
                fig.update_yaxes(title=None)
                chart(fig, "search_cmp", height=260)

        with tabs[1]:
            key = st.selectbox("Sort key", ["price", "name", "quantity", "value"], key="lab_key",
                               format_func=str.title)
            rows = []
            for a in ("merge", "insertion"):
                r = eng.sort(key, a)
                rows.append({"Algorithm": f"{a.title()} Sort", "Comparisons": r["comparisons"],
                             "Moves": r["moves"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            same = eng.sort(key, "merge")["products"] == eng.sort(key, "insertion")["products"]
            st.caption((":material/check_circle: Both algorithms produced the same order"
                        if same else ":material/error: The two orders differ"))
            if data:
                show_products(eng.sort(key, "merge")["products"][:50], height=250)

            card_title("Scaling experiment")
            st.caption("Comparisons needed to sort random data by price as n grows.")
            exp = []
            for size in [50, 100, 200, 400, 800, 1600]:
                with Engine(generate_products(size, size)) as e2:
                    for a in ("merge", "insertion"):
                        exp.append({"n": size, "Algorithm": f"{a.title()} Sort",
                                    "Comparisons": e2.sort("price", a)["comparisons"]})
            exp = pd.DataFrame(exp)
            fig = px.line(exp, x="n", y="Comparisons", color="Algorithm", markers=True)
            fig.update_traces(line_width=2, marker_size=8,
                              hovertemplate="n = %{x}<br>%{y:,} comparisons<extra></extra>")
            for name, g in exp.groupby("Algorithm"):  # direct labels at line ends
                fig.add_annotation(x=g["n"].iloc[-1], y=g["Comparisons"].iloc[-1], text=name,
                                   showarrow=False, xanchor="right", yanchor="bottom",
                                   yshift=8, font=dict(color=INK, size=12))
            fig.update_xaxes(title="Number of products (n)")
            fig.update_yaxes(title=None)
            chart(fig, "scaling", height=340, legend=True)

        with tabs[2]:
            hs = eng.hash_stats()
            c = st.columns(5)
            c[0].metric("Buckets (m)", hs["bucket_count"], border=True)
            c[1].metric("Items (n)", hs["item_count"], border=True)
            c[2].metric("Load factor", f"{hs['load_factor']:.2f}", border=True)
            c[3].metric("Collisions", hs["collisions"], border=True)
            c[4].metric("Longest chain", hs["longest_chain"], border=True)
            st.caption("hash(id) = id mod m. A collision is an item stored in a bucket that "
                       "already had one. Set a small bucket count to force collisions.")
            chains = hs["chain_lengths"][:300]
            fig = px.bar(x=list(range(len(chains))), y=chains)
            fig.update_traces(hovertemplate="Bucket %{x}<br>%{y} item(s)<extra></extra>")
            fig.update_xaxes(title="Bucket", showgrid=False)
            fig.update_yaxes(title="Chain length")
            chart(fig, "chains", height=280, bargap=0.15)

        with tabs[3]:
            r = eng.restock_ranking()
            if not r["ranking"]:
                empty_state("No product is at or below its minimum stock.")
            else:
                st.caption(f"{len(r['ranking'])} candidates · {r['comparisons']} comparisons · "
                           f"{r['swaps']} swaps")
                with st.container(border=True):
                    card_title("Heap as a tree")
                    st.caption("First 31 nodes, labelled id / score. The root is the most "
                               "urgent product.")
                    st.graphviz_chart(heap_dot(r["heap_array"]))
                left, right = st.columns(2)
                with left.container(border=True):
                    card_title("Heap array")
                    st.caption("Level order, after all pushes")
                    st.dataframe(pd.DataFrame([{"Index": i,
                                                "Parent": (i - 1) // 2 if i else None,
                                                "ID": p["id"], "Score": p["score"]}
                                               for i, p in enumerate(r["heap_array"])]),
                                 hide_index=True)
                with right.container(border=True):
                    card_title("Extraction order")
                    st.caption("Repeated extract-max")
                    st.dataframe(pd.DataFrame([{"Rank": i + 1, "ID": p["id"],
                                                "Name": p["name"], "Score": p["score"]}
                                               for i, p in enumerate(r["ranking"])]),
                                 hide_index=True)

    with tabs[4]:
        cases = run_edge_cases()
        passed = int((cases["Result"] == "Passed").sum())
        st.caption(f"{passed} of {len(cases)} checks passed. These run live against the C "
                   "engine and a scratch database.")
        st.dataframe(cases, hide_index=True)

    with tabs[5]:
        st.dataframe(COMPLEXITY, hide_index=True)
        for name, code in PSEUDOCODE.items():
            with st.expander(name, icon=":material/code:"):
                st.code(code, language="text")


def page_about():
    header("About", "How StockWise is built and what each algorithm costs.")
    with st.container(border=True):
        card_title("Architecture")
        st.image(ARCHITECTURE, width="stretch")
        st.markdown(
            "SQLite is the single source of truth. On every page load, `Engine(products)` "
            "copies the records into C, which builds the hash index and an id-sorted index. "
            "The UI calls search, sort and restock functions; C returns indices and operation "
            "counts, and Python maps them back to products.")
    left, right = st.columns([3, 2])
    with left.container(border=True):
        card_title("Complexity")
        st.dataframe(COMPLEXITY, hide_index=True)
    with right.container(border=True):
        card_title("Restock priority formula")
        st.latex(r"\text{Priority} = 100 \times (0.5\,S + 0.3\,D + 0.2\,I)")
        st.markdown("S = shortage, D = normalized demand, I = normalized importance, each "
                    "scaled 0 to 1. Missing values use a neutral 0.5.")


# ---------------------------------------------------------------- main
def main():
    st.logo(LOGO, size="large", icon_image=MARK)
    try:
        load_library()
    except StockWiseError as exc:
        st.error(f"{exc}\n\nSee README.md, section Setup.", icon=":material/error:")
        st.stop()

    conn = get_connection()
    if "flash" in st.session_state:
        st.toast(st.session_state.pop("flash"), icon=":material/check_circle:")
    products = db.list_products(conn)

    # Rebuilt each rerun from SQLite, so C indexes always match the database.
    # ponytail: O(n log n) rebuild per page load; cache by a DB version if n gets huge.
    with Engine(products) as engine:
        def page(fn, title, icon, path, default=False):
            return st.Page(fn, title=title, icon=f":material/{icon}:", url_path=path,
                           default=default)

        nav = st.navigation({
            "Overview": [page(lambda: page_dashboard(conn, products, engine), "Dashboard",
                              "space_dashboard", "dashboard", default=True)],
            "Inventory": [
                page(lambda: page_products(conn, products, engine), "Products",
                     "inventory_2", "products"),
                page(lambda: page_transactions(conn, products), "Transactions",
                     "sync_alt", "transactions"),
                page(lambda: page_restock(conn, engine), "Restocking",
                     "local_shipping", "restocking"),
            ],
            "Algorithms": [
                page(lambda: page_search_sort(products, engine), "Search and sorting",
                     "manage_search", "search-sort"),
                page(lambda: page_lab(products), "DSA laboratory", "science", "lab"),
                page(page_about, "About", "info", "about"),
            ],
        })
        st.sidebar.caption(f":material/memory: {len(products)} products indexed by the "
                           "C engine")
        nav.run()


main()
