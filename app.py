"""StockWise - Inventory Optimization System (Streamlit frontend).

Run:  streamlit run app.py
All searching, sorting, hashing and heap work is done by the C engine
(backend/libstockwise) through c_bridge.py. SQLite (database.py) stores data.
"""
import random
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

import database as db
from c_bridge import Engine, StockWiseError, load_library

st.set_page_config(page_title="StockWise", page_icon="📦", layout="wide")

PAGES = ["Dashboard", "Product Management", "Search and Sorting", "Restocking Recommendations",
         "Inventory Transactions", "DSA Algorithm Laboratory", "About and Complexity Analysis"]

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


# ---------------------------------------------------------------- helpers
@st.cache_resource
def get_connection():
    conn = db.connect()
    db.init_db(conn)
    return conn


def flash(message):
    """Show a success message after st.rerun()."""
    st.session_state["flash"] = message
    st.rerun()


def stock_status(p):
    if p["quantity"] == 0:
        return "Out of stock"
    return "Low stock" if p["quantity"] <= p["min_stock"] else "OK"


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
        st.info("No products to show.")
        return
    st.dataframe(to_frame(products), hide_index=True, height=height,
                 column_config={"Price": st.column_config.NumberColumn(format="$%.2f"),
                                "Value": st.column_config.NumberColumn(format="$%.2f")})


def product_label(p):
    return f"{p['id']} - {p['name']}"


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
    with st.form(key, clear_on_submit=id_editable):
        c1, c2, c3 = st.columns(3)
        pid = c1.number_input("Product ID", min_value=1, step=1, value=defaults["id"],
                              disabled=not id_editable)
        name = c2.text_input("Name", value=defaults["name"], max_chars=63)
        category = c3.text_input("Category", value=defaults["category"], max_chars=31)
        c1, c2, c3 = st.columns(3)
        price = c1.number_input("Price ($)", min_value=0.0, step=0.5, format="%.2f",
                                value=float(defaults["price"]))
        quantity = c2.number_input("Quantity", min_value=0, step=1, value=defaults["quantity"],
                                   disabled=not id_editable,
                                   help=None if id_editable else
                                   "Change stock on the Inventory Transactions page.")
        min_stock = c3.number_input("Minimum stock", min_value=0, step=1,
                                    value=defaults["min_stock"])
        c1, c2, c3 = st.columns(3)
        demand = c1.number_input("Estimated demand (units/month)", min_value=0, step=1,
                                 value=defaults["demand"] or 0)
        demand_unknown = c2.checkbox("Demand unknown", value=defaults["demand"] is None)
        importance = c3.select_slider("Importance", options=["Unknown", 1, 2, 3, 4, 5],
                                      value=defaults["importance"] or "Unknown")
        if not st.form_submit_button("Save product", type="primary"):
            return None
    return {"id": int(pid), "name": name, "category": category, "price": float(price),
            "quantity": int(quantity), "min_stock": int(min_stock),
            "demand": None if demand_unknown else int(demand),
            "importance": None if importance == "Unknown" else int(importance)}


def search_box(engine, key):
    """Search by numeric id (C hash table) or by name (C linear search)."""
    query = st.text_input("Search by product ID or name", key=key,
                          placeholder="e.g. 1042 or cable").strip()
    if not query:
        return None
    if query.isdigit():
        r = engine.hash_search(int(query))
        st.caption(f"Hash table lookup in C: {r['comparisons']} comparison(s)")
        return [r["product"]] if r["found"] else []
    r = engine.search_name(query)
    st.caption(f"Linear name search in C: {r['comparisons']} comparison(s)")
    return r["products"]


# ---------------------------------------------------------------- pages
def page_dashboard(conn, products, engine):
    st.title("📊 Dashboard")
    total_units = sum(p["quantity"] for p in products)
    total_value = sum(p["price"] * p["quantity"] for p in products)
    out = sum(p["quantity"] == 0 for p in products)
    low = sum(0 < p["quantity"] <= p["min_stock"] for p in products)
    c = st.columns(5)
    c[0].metric("Total products", len(products))
    c[1].metric("Units in stock", f"{total_units:,}")
    c[2].metric("Inventory value", f"${total_value:,.2f}")
    c[3].metric("Low stock", low)
    c[4].metric("Out of stock", out)
    if not products:
        st.info("No products yet. Add some on the Product Management page.")
        return

    left, right = st.columns(2)
    df = to_frame(products)
    by_cat = df.groupby("Category", as_index=False)["Value"].sum().sort_values("Value")
    left.subheader("Inventory value by category")
    left.plotly_chart(px.bar(by_cat, x="Value", y="Category", orientation="h",
                             labels={"Value": "Value ($)"}), key="cat")

    top = engine.sort("value", "merge", descending=True)
    right.subheader("Highest-value products")
    top_df = to_frame(top["products"][:10]).iloc[::-1]
    right.plotly_chart(px.bar(top_df, x="Value", y="Name", orientation="h",
                              labels={"Value": "Value ($)", "Name": ""}), key="top")
    right.caption(f"Ranked by C Merge Sort: {top['comparisons']} comparisons.")

    st.subheader("Recent stock transactions")
    recent = db.list_transactions(conn, limit=10)
    if recent:
        st.dataframe(pd.DataFrame(recent), hide_index=True)
    else:
        st.info("No transactions yet.")


def page_products(conn, products, engine):
    st.title("🗂️ Product Management")
    view, add, edit, delete = st.tabs(["View & search", "Add", "Edit", "Delete"])

    with view:
        found = search_box(engine, "pm_search")
        shown = products if found is None else found
        cats = sorted({p["category"] for p in products})
        chosen = st.multiselect("Filter by category", cats)
        if chosen:
            shown = [p for p in shown if p["category"] in chosen]
        show_products(shown)

    with add:
        next_id = max((p["id"] for p in products), default=1000) + 1
        new = product_form("add_form", {"id": next_id, "name": "", "category": "",
                                        "price": 0.0, "quantity": 0, "min_stock": 10,
                                        "demand": None, "importance": 3}, True)
        if new is not None:
            try:
                db.add_product(conn, new)
                flash(f"Added product {new['id']} - {new['name'].strip()}.")
            except ValueError as exc:
                st.error(f"Could not add product: {exc}")

    if not products:
        edit.info("No products to edit.")
        delete.info("No products to delete.")
        return

    with edit:
        p = pick_product(st, "Product to edit", products, key="edit_pick")
        st.caption("Quantity is changed through stock transactions so every change "
                   "has a history record.")
        changes = product_form(f"edit_form_{p['id']}", p, False)
        if changes is not None:
            try:
                db.update_product(conn, p["id"], changes)
                flash(f"Updated product {p['id']}.")
            except ValueError as exc:
                st.error(f"Could not update product: {exc}")

    with delete:
        p = pick_product(st, "Product to delete", products, key="delete_pick")
        st.warning(f"Deleting **{p['name']}** also removes its transaction history. "
                   "This cannot be undone.")
        sure = st.checkbox("Yes, I want to delete this product", key=f"sure_{p['id']}")
        if st.button("Delete product", type="primary", disabled=not sure):
            db.delete_product(conn, p["id"])
            flash(f"Deleted product {p['id']} - {p['name']}.")


def page_search_sort(products, engine):
    st.title("🔎 Search and Sorting")
    st.subheader("Search")
    c1, c2 = st.columns([1, 2])
    method = c1.radio("Algorithm", ["Hash table", "Binary search", "Linear search",
                                    "Linear search by name"])
    with c2:
        if method == "Linear search by name":
            text = st.text_input("Product name contains", placeholder="e.g. cable")
            if text.strip():
                r = engine.search_name(text)
                st.metric("Comparisons", r["comparisons"])
                show_products(r["products"])
        else:
            pid = st.number_input("Product ID", min_value=1, step=1, value=1042)
            fn = {"Hash table": engine.hash_search, "Binary search": engine.binary_search,
                  "Linear search": engine.linear_search}[method]
            r = fn(int(pid))
            st.metric("Comparisons", r["comparisons"])
            if r["found"]:
                show_products([r["product"]])
            else:
                st.warning(f"Product {int(pid)} not found.")
    st.caption("Binary search runs on an id-sorted index that the C engine builds with "
               "Merge Sort; the stored product order is by name.")

    st.divider()
    st.subheader("Sort")
    c1, c2, c3 = st.columns(3)
    key = c1.selectbox("Sort by", ["name", "price", "quantity", "value"])
    algorithm = c2.selectbox("Algorithm", ["merge", "insertion"],
                             format_func=lambda a: f"{a.title()} Sort")
    descending = c3.radio("Order", ["Ascending", "Descending"], horizontal=True) == "Descending"
    r = engine.sort(key, algorithm, descending)
    c = st.columns(3)
    c[0].metric("Comparisons", f"{r['comparisons']:,}")
    c[1].metric("Element moves", f"{r['moves']:,}")
    c[2].metric("Time complexity", "O(n log n)" if algorithm == "merge" else "O(n²) / best O(n)")
    show_products(r["products"])


def page_restock(conn, engine):
    st.title("🚚 Restocking Recommendations")
    with st.expander("How the priority score is calculated", expanded=False):
        st.latex(r"\text{Priority} = 100 \times (0.5\,S + 0.3\,D + 0.2\,I)")
        st.markdown(
            "- **S, shortage** = (min stock − quantity) / min stock, clamped to 0..1 "
            "(min stock 0: 1 if out of stock, else 0)\n"
            "- **D, demand** = demand / highest demand in the inventory\n"
            "- **I, importance** = (importance − 1) / 4 for importance 1..5\n"
            "- Missing demand or importance uses a neutral **0.5**.\n"
            "- Only products **at or below** their minimum stock are listed.\n"
            "- **Suggested quantity** = min stock + one month of demand − quantity "
            "(2 × min stock − quantity if demand is unknown), at least 1.\n"
            "- Every candidate is pushed into a C **Max-Heap** and extracted in order.")
    result = engine.restock_ranking()
    ranking = result["ranking"]
    if not ranking:
        st.success("All products are above their minimum stock. Nothing to restock.")
        return
    st.caption(f"Max-Heap: {len(ranking)} items, {result['comparisons']} comparisons, "
               f"{result['swaps']} swaps.")
    rows = [{"Rank": i + 1, "ID": p["id"], "Name": p["name"], "Stock": p["quantity"],
             "Min stock": p["min_stock"], "Priority": p["score"],
             "Reason": "; ".join(p["reasons"]), "Suggested qty": p["suggested_qty"]}
            for i, p in enumerate(ranking)]
    st.dataframe(pd.DataFrame(rows), hide_index=True,
                 column_config={"Priority": st.column_config.ProgressColumn(
                     min_value=0, max_value=100, format="%.1f")})

    parts = pd.DataFrame([{"Name": p["name"], "Shortage": 50 * p["shortage_score"],
                           "Demand": 30 * p["demand_score"],
                           "Importance": 20 * p["importance_score"]} for p in ranking[:15]])
    st.subheader("Score breakdown (top 15)")
    st.plotly_chart(px.bar(parts.iloc[::-1], y="Name", x=["Shortage", "Demand", "Importance"],
                           orientation="h", labels={"value": "Points", "Name": "",
                                                    "variable": "Component"}), key="breakdown")

    st.subheader("Restock now")
    with st.form("restock_form"):
        p = pick_product(st, "Product", ranking,
                         extra=lambda p: f" (suggested {p['suggested_qty']})")
        qty = st.number_input("Quantity received (0 = use suggested)", min_value=0, step=1)
        if st.form_submit_button("Record delivery", type="primary"):
            amount = int(qty) or p["suggested_qty"]
            balance = db.record_transaction(conn, p["id"], "IN", amount, "Restock")
            flash(f"Added {amount} units to {p['name']} (now {balance}).")


def page_transactions(conn, products):
    st.title("🔁 Inventory Transactions")
    if not products:
        st.info("Add a product first.")
        return
    with st.form("tx_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        p = pick_product(c1, "Product", products, extra=lambda p: f" (stock {p['quantity']})")
        kind = c2.radio("Type", ["Add stock (IN)", "Reduce stock (OUT)"])
        qty = c3.number_input("Quantity", min_value=1, step=1)
        note = st.text_input("Note (optional)", max_chars=200)
        if st.form_submit_button("Record transaction", type="primary"):
            tx_type = "IN" if kind.startswith("Add") else "OUT"
            try:
                balance = db.record_transaction(conn, p["id"], tx_type, int(qty), note)
                flash(f"{tx_type} {int(qty)} × {p['name']}. New balance: {balance}.")
            except ValueError as exc:
                st.error(f"Transaction rejected: {exc}")

    st.subheader("Transaction history")
    by_id = {p["id"]: p for p in products}
    choice = st.selectbox("Show", [None] + list(by_id), format_func=lambda i: "All products"
                          if i is None else product_label(by_id[i]))
    history = db.list_transactions(conn, product_id=choice)
    if history:
        st.dataframe(pd.DataFrame(history), hide_index=True)
    else:
        st.info("No transactions recorded.")


def run_edge_cases():
    """Execute real edge-case calls against the C engine and a scratch database."""
    cases = []

    def case(name, expected, fn):
        try:
            actual = fn()
        except (ValueError, StockWiseError) as exc:
            actual = f"Error: {exc}"
        cases.append({"Case": name, "Expected": expected, "Actual": str(actual),
                      "Pass": "✅" if str(actual).startswith(expected) else "❌"})

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
    lines = ["digraph { node [shape=box, style=rounded];"]
    for i, p in enumerate(heap[:31]):
        lines.append(f'n{i} [label="{p["id"]}\\n{p["score"]:.1f}"];')
        if i > 0:
            lines.append(f"n{(i - 1) // 2} -> n{i};")
    return "\n".join(lines + ["}"])


def page_lab(products):
    st.title("🧪 DSA Algorithm Laboratory")
    c1, c2, c3, c4 = st.columns(4)
    source = c1.radio("Data", ["Real inventory", "Generated sample"])
    n = c2.number_input("Sample size", 0, 5000, 200, step=50, disabled=source != "Generated sample")
    seed = c3.number_input("Random seed", 0, 10_000, 42, disabled=source != "Generated sample")
    buckets = c4.number_input("Hash buckets (0 = auto)", 0, 100_000, 0)
    data = products if source == "Real inventory" else generate_products(int(n), int(seed))

    with Engine(data, bucket_count=int(buckets)) as eng:
        tabs = st.tabs(["Search", "Sorting", "Hash table", "Max-Heap", "Edge cases",
                        "Pseudocode & complexity"])
        with tabs[0]:
            default = data[len(data) // 2]["id"] if data else 1
            pid = st.number_input("Target product ID (try a missing one too)", 1, 2**31 - 1,
                                  default)
            rows = []
            for name, fn, cx in [("Linear search", eng.linear_search, "O(n)"),
                                 ("Binary search", eng.binary_search, "O(log n)"),
                                 ("Hash table", eng.hash_search, "O(1) average")]:
                r = fn(int(pid))
                rows.append({"Algorithm": name, "Found": "Yes" if r["found"] else "No",
                             "Product": r["product"]["name"] if r["found"] else "-",
                             "Comparisons": r["comparisons"], "Complexity": cx})
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True)
            st.plotly_chart(px.bar(df, x="Algorithm", y="Comparisons", text="Comparisons"),
                            key="search_cmp")

        with tabs[1]:
            key = st.selectbox("Key", ["price", "name", "quantity", "value"], key="lab_key")
            rows = []
            for a in ("merge", "insertion"):
                r = eng.sort(key, a)
                rows.append({"Algorithm": f"{a.title()} Sort", "Comparisons": r["comparisons"],
                             "Moves": r["moves"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            same = eng.sort(key, "merge")["products"] == eng.sort(key, "insertion")["products"]
            st.caption(f"Both algorithms produced the same order: {'yes' if same else 'NO'}")
            if data:
                show_products(eng.sort(key, "merge")["products"][:50], height=250)

            st.subheader("Scaling experiment (random data)")
            sizes = [50, 100, 200, 400, 800, 1600]
            exp = []
            for size in sizes:
                with Engine(generate_products(size, size)) as e2:
                    for a in ("merge", "insertion"):
                        exp.append({"n": size, "Algorithm": f"{a.title()} Sort",
                                    "Comparisons": e2.sort("price", a)["comparisons"]})
            st.plotly_chart(px.line(pd.DataFrame(exp), x="n", y="Comparisons",
                                    color="Algorithm", markers=True), key="scaling")

        with tabs[2]:
            hs = eng.hash_stats()
            c = st.columns(5)
            c[0].metric("Buckets (m)", hs["bucket_count"])
            c[1].metric("Items (n)", hs["item_count"])
            c[2].metric("Load factor", f"{hs['load_factor']:.2f}")
            c[3].metric("Collisions", hs["collisions"])
            c[4].metric("Longest chain", hs["longest_chain"])
            st.caption("hash(id) = id mod m. A collision is an item stored in a bucket "
                       "that already had one. Set a small bucket count to force collisions.")
            chains = hs["chain_lengths"][:300]
            st.plotly_chart(px.bar(x=list(range(len(chains))), y=chains,
                                   labels={"x": "Bucket", "y": "Chain length"}), key="chains")

        with tabs[3]:
            r = eng.restock_ranking()
            if not r["ranking"]:
                st.info("No product is at or below its minimum stock.")
            else:
                st.caption(f"{len(r['ranking'])} candidates · {r['comparisons']} comparisons · "
                           f"{r['swaps']} swaps")
                left, right = st.columns(2)
                left.markdown("**Heap array after all pushes** (level order)")
                left.dataframe(pd.DataFrame([{"Index": i, "Parent": (i - 1) // 2 if i else None,
                                              "ID": p["id"], "Score": p["score"]}
                                             for i, p in enumerate(r["heap_array"])]),
                               hide_index=True)
                right.markdown("**Extraction order** (repeated extract-max)")
                right.dataframe(pd.DataFrame([{"Rank": i + 1, "ID": p["id"],
                                               "Name": p["name"], "Score": p["score"]}
                                              for i, p in enumerate(r["ranking"])]),
                                hide_index=True)
                st.markdown("**Heap as a tree** (first 31 nodes: id / score)")
                st.graphviz_chart(heap_dot(r["heap_array"]))

    with tabs[4]:
        st.dataframe(run_edge_cases(), hide_index=True)

    with tabs[5]:
        st.dataframe(COMPLEXITY, hide_index=True)
        for name, code in PSEUDOCODE.items():
            with st.expander(name):
                st.code(code, language="text")


def page_about():
    st.title("ℹ️ About and Complexity Analysis")
    st.markdown("""
**StockWise** is an inventory optimization system built for a Data Structures and
Algorithms course. The interface is Python (Streamlit); every search, sort, hash and
heap operation runs in a C11 shared library loaded with `ctypes`.

```
 Streamlit UI (app.py)
        │  product dicts / results
        ▼
 c_bridge.py  ── ctypes structs ──►  libstockwise (C)
        ▲                              ├─ search.c       linear + binary search
        │                              ├─ hash_table.c   separate chaining
 database.py ◄──► stockwise.db         ├─ sorting.c      merge + insertion sort
   (SQLite: source of truth)           ├─ max_heap.c     priority queue
                                       └─ inventory_engine.c  public API
```

**Flow:** SQLite → `list_products()` → `Engine(products)` copies the records into C,
builds the hash index and an id-sorted index → the UI calls search/sort/restock →
C returns indices and operation counts → Python maps them back to products.
The engine is rebuilt on every page load, so it can never be stale after an update.
""")
    st.subheader("Complexity")
    st.dataframe(COMPLEXITY, hide_index=True)
    st.subheader("Restock priority formula")
    st.latex(r"\text{Priority} = 100 \times (0.5\,S + 0.3\,D + 0.2\,I)")
    st.markdown("S = shortage, D = normalized demand, I = normalized importance, "
                "each 0..1; missing values use 0.5.")


# ---------------------------------------------------------------- main
def main():
    try:
        load_library()
    except StockWiseError as exc:
        st.error(f"{exc}\n\nSee README.md → *Build the C library*.")
        st.stop()

    conn = get_connection()
    st.sidebar.title("📦 StockWise")
    st.sidebar.caption("Inventory Optimization with C-powered DSA")
    page = st.sidebar.radio("Navigate", PAGES, label_visibility="collapsed")
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    products = db.list_products(conn)
    st.sidebar.divider()
    st.sidebar.caption(f"{len(products)} products loaded into the C engine")

    # Rebuilt each rerun from SQLite, so C indexes always match the database.
    # ponytail: O(n log n) rebuild per page load; cache by a DB version if n gets huge.
    with Engine(products) as engine:
        if page == PAGES[0]:
            page_dashboard(conn, products, engine)
        elif page == PAGES[1]:
            page_products(conn, products, engine)
        elif page == PAGES[2]:
            page_search_sort(products, engine)
        elif page == PAGES[3]:
            page_restock(conn, engine)
        elif page == PAGES[4]:
            page_transactions(conn, products)
        elif page == PAGES[5]:
            page_lab(products)
        else:
            page_about()


main()
