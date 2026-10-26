"""StockWise - Inventory Optimization System (Streamlit frontend).

Run:  streamlit run app.py
Every search, sort, hash, tree, trie, heap, graph, queue and DP operation runs
in the C engine (backend/libstockwise) through c_bridge.py. SQLite
(database.py) stores data. Theme: .streamlit/config.toml. Artwork: assets/.
"""
import math
import os
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

import streamlit as st

st.set_page_config(page_title="StockWise", page_icon=":material/inventory_2:", layout="wide")

# Oldest versions the app is tested with; see requirements.txt.
MIN_PYTHON, MIN_PACKAGES = (3, 11), {"streamlit": (1, 66), "plotly": (6, 0), "pandas": (2, 2)}


def check_environment():
    """Return a human-readable list of environment problems (empty if all is well)."""
    problems = []
    if sys.version_info < MIN_PYTHON:
        problems.append("Python %d.%d or newer is required; this is %d.%d."
                        % (MIN_PYTHON + sys.version_info[:2]))
    for name, minimum in MIN_PACKAGES.items():
        try:
            have = tuple(int(x) for x in version(name).split(".")[:2])
        except PackageNotFoundError:
            problems.append(f"`{name}` is not installed.")
            continue
        except ValueError:  # unusual version string such as a dev build: trust it
            continue
        if have < minimum:
            problems.append(f"`{name}` {version(name)} is too old; {'.'.join(map(str, minimum))} "
                            "or newer is required.")
    return problems


_problems = check_environment()
if _problems:
    st.error("StockWise cannot start yet:\n\n" + "\n".join(f"- {p}" for p in _problems)
             + "\n\nIn the project folder run: `python -m pip install -r requirements.txt` "
             "and start the app with `python -m streamlit run app.py`.",
             icon=":material/error:")
    st.stop()

import pandas as pd  # noqa: E402  (imported after the environment check above)
import plotly.express as px  # noqa: E402

import database as db  # noqa: E402
from c_bridge import (STABLE_ALGORITHMS, Engine, StockWiseError, fifo_lots,  # noqa: E402
                      knapsack, knapsack_greedy, load_library, shortest_path)
from core import (COMPLEXITY_COLUMNS, COMPLEXITY_ROWS, PSEUDOCODE,  # noqa: E402
                  generate_products, run_edge_cases)

COMPLEXITY = pd.DataFrame(COMPLEXITY_ROWS, columns=COMPLEXITY_COLUMNS)

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO, MARK, HERO, EMPTY, ARCHITECTURE = (os.path.join(ASSETS, f) for f in (
    "logo.svg", "mark.svg", "hero.svg", "empty.svg", "architecture.svg"))

# Chart palette: validated categorical slots 1-3 (blue, orange, aqua) + neutral chrome.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, MUTED, GRID, AXIS = "#14171f", "#52525b", "#898781", "#e1e0d9", "#c3c2b7"
# Plotly Express picks trace colors at creation time, so set them here, not per layout.
px.defaults.template = "plotly_white"
px.defaults.color_discrete_sequence = [BLUE, ORANGE, AQUA]

ALGO_NAMES = {"merge": "Merge Sort", "insertion": "Insertion Sort", "quick": "Quick Sort",
              "heap": "Heap Sort"}
ALGO_COMPLEXITY = {"merge": "O(n log n)", "insertion": "O(n²)", "quick": "O(n log n)",
                   "heap": "O(n log n)"}


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


def category_image(category):
    path = os.path.join(ASSETS, "categories", category.strip().lower().replace(" ", "-") + ".svg")
    return path if os.path.exists(path) else os.path.join(ASSETS, "categories", "other.svg")


def price_ceiling(products):
    """Upper end of a price slider: highest price rounded up, at least $1 so the
    slider always has min < max (it fails when every price is 0)."""
    return float(max(1, math.ceil(max((p["price"] for p in products), default=0))))


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


def product_grid(products, limit=48):
    """Product cards, four per row, with category artwork and a stock gauge."""
    if not products:
        empty_state("No products match.")
        return
    shown = products[:limit]
    for start in range(0, len(shown), 4):
        cols = st.columns(4)
        for col, p in zip(cols, shown[start:start + 4]):
            with col.container(border=True):
                img, text = st.columns([1, 3], vertical_alignment="center")
                img.image(category_image(p["category"]), width=52)
                text.markdown(f"**{p['name']}**  \n:gray[{p['category']} · #{p['id']}]")
                target = max(2 * p["min_stock"], 1)
                st.progress(min(p["quantity"] / target, 1.0),
                            text=f"{p['quantity']} in stock · minimum {p['min_stock']}")
                st.markdown(f"{STATUS_BADGE[stock_status(p)]} &nbsp; **${p['price']:.2f}**")
    if len(products) > limit:
        st.caption(f"Showing {limit} of {len(products)} products. Switch to Table to see all.")


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


def to_epoch(timestamp):
    return int(datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").timestamp())


def stock_lots(conn, product_id):
    """Replay a product's history through the C FIFO queue."""
    rows = sorted(db.list_transactions(conn, product_id), key=lambda t: (t["created_at"], t["id"]))
    moves = [(t["quantity"] if t["type"] == "IN" else -t["quantity"], to_epoch(t["created_at"]))
             for t in rows]
    result = fifo_lots(moves)
    now = datetime.now().timestamp()
    for lot in result["lots"]:
        lot["age_days"] = int((now - lot["received"]) // 86400)
    return result


def stock_history(conn):
    """Total units on hand per day, and units in/out per day, for the last 30 days."""
    tx = pd.DataFrame(db.list_transactions(conn))
    if tx.empty:
        return None, None
    tx["day"] = pd.to_datetime(tx["created_at"]).dt.normalize()
    tx["signed"] = tx["quantity"].where(tx["type"] == "IN", -tx["quantity"])
    days = pd.date_range(tx["day"].min(), pd.Timestamp.now().normalize())
    level = tx.groupby("day")["signed"].sum().reindex(days, fill_value=0).cumsum()
    moves = (tx.pivot_table(index="day", columns="type", values="quantity", aggfunc="sum")
             .reindex(index=days, columns=["IN", "OUT"]).fillna(0))
    return level.iloc[-30:], moves.iloc[-30:]


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
    """ID -> C hash table. Text -> C trie prefix search, falling back to C
    linear substring search when no word starts with the text."""
    query = st.text_input("Search", key=key, icon=":material/search:",
                          placeholder="Search by product ID or name, e.g. 1042 or cab",
                          label_visibility="collapsed").strip()
    if not query:
        return None
    if query.isdigit():
        r = engine.hash_search(int(query))
        st.caption(f":material/tag: Hash table lookup in C · {r['comparisons']} comparison(s)")
        return [r["product"]] if r["found"] else []
    r = engine.prefix_search(query)
    if r["products"]:
        st.caption(f":material/account_tree: Trie prefix search in C · "
                   f"{r['nodes_visited']} trie nodes visited")
        return r["products"]
    r = engine.search_name(query)
    st.caption(f":material/manage_search: No word starts with that, so C linear substring "
               f"search ran · {r['comparisons']} comparison(s)")
    return r["products"]


# ---------------------------------------------------------------- pages
def page_dashboard(conn, products, engine):
    st.image(HERO, width="stretch")
    total_units = sum(p["quantity"] for p in products)
    total_value = sum(p["price"] * p["quantity"] for p in products)
    out = sum(p["quantity"] == 0 for p in products)
    low = sum(0 < p["quantity"] <= p["min_stock"] for p in products)
    level, moves = stock_history(conn)

    c = st.columns(5)
    c[0].metric("Products", len(products), border=True, icon=":material/inventory_2:")
    if level is not None:
        c[1].metric("Units in stock", f"{total_units:,}", border=True,
                    icon=":material/package_2:",
                    delta=f"{int(level.iloc[-1] - level.iloc[0]):+,} in 30 days",
                    delta_color="off", chart_data=level.tolist(), chart_type="area")
    else:
        c[1].metric("Units in stock", f"{total_units:,}", border=True,
                    icon=":material/package_2:")
    c[2].metric("Inventory value", f"${total_value:,.0f}", border=True,
                icon=":material/payments:", help=f"${total_value:,.2f} exactly")
    c[3].metric("Low stock", low, border=True, icon=":material/warning:",
                help="Above zero but at or below minimum stock")
    c[4].metric("Out of stock", out, border=True, icon=":material/error:")
    if not products:
        empty_state("No products yet. Add your first one on the Products page.")
        return

    left, right = st.columns([3, 2])
    with left.container(border=True):
        card_title("Stock movement, last 30 days")
        if moves is None:
            st.caption("No transactions yet.")
        else:
            df = moves.rename(columns={"IN": "Stock in", "OUT": "Stock out"})
            fig = px.bar(df, x=df.index, y=["Stock in", "Stock out"], barmode="group")
            fig.update_traces(hovertemplate="%{x|%d %b}<br>%{fullData.name}: %{y:,} units"
                                            "<extra></extra>")
            fig.update_xaxes(title=None, showgrid=False, tickformat="%d %b")
            fig.update_yaxes(title="Units")
            chart(fig, "movement", height=300, legend=True, bargap=0.25)
    with right.container(border=True):
        card_title("Needs attention")
        ranking = engine.restock_ranking()["ranking"][:5]
        if not ranking:
            st.caption("Every product is above its minimum stock.")
        for p in ranking:
            img, text, badge = st.columns([1, 4, 3], vertical_alignment="center")
            img.image(category_image(p["category"]), width=36)
            text.markdown(f"**{p['name']}**  \n:gray[{p['quantity']} of {p['min_stock']} min · "
                          f"priority {p['score']:.0f}]")
            badge.markdown(STATUS_BADGE[stock_status(p)])

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

    with st.container(border=True):
        card_title("Recent transactions")
        show_transactions(db.list_transactions(conn, limit=8))


def page_products(conn, products, engine):
    header("Products", "Search uses the C hash table (ID) and trie (name prefix). The price "
                       "filter is a range query on a C AVL tree.")
    view, add, edit, delete = st.tabs([":material/grid_view: Catalog",
                                       ":material/add_circle: Add product",
                                       ":material/edit: Edit", ":material/delete: Delete"])

    with view:
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            found = search_box(engine, "pm_search")
        cats = sorted({p["category"] for p in products})
        chosen = c2.multiselect("Category", cats, placeholder="All categories",
                                label_visibility="collapsed")
        layout = c3.segmented_control("View", [":material/grid_view: Grid",
                                               ":material/table_rows: Table"],
                                      default=":material/grid_view: Grid",
                                      label_visibility="collapsed")
        top_price = price_ceiling(products)
        low, high = st.slider("Price range", 0.0, top_price, (0.0, top_price),
                              step=0.5, format="$%.2f")
        shown = products if found is None else found
        if (low, high) != (0.0, top_price):
            r = engine.price_range(low, high)
            in_range = {p["id"] for p in r["products"]}
            # Without a search, show the AVL in-order result (ascending price).
            shown = r["products"] if found is None else [p for p in found if p["id"] in in_range]
            st.caption(f":material/account_tree: AVL range query in C · {r['nodes_visited']} of "
                       f"{engine.count} tree nodes visited")
        if chosen:
            shown = [p for p in shown if p["category"] in chosen]
        st.caption(f"{len(shown)} of {len(products)} products")
        if layout and "Table" in layout:
            show_products(shown)
        else:
            product_grid(shown)

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
                                        "Trie prefix", "Linear substring", "AVL price range"],
                          captions=["O(1) average, by ID", "O(log n), id-sorted index",
                                    "O(n), by ID", "O(P + k), by name prefix",
                                    "O(n), name contains text", "O(log n + k), by price"])
        with c2:
            if method in ("Trie prefix", "Linear substring"):
                text = st.text_input("Name prefix" if method == "Trie prefix" else
                                     "Name contains", value="ca", icon=":material/search:")
                if text.strip():
                    if method == "Trie prefix":
                        r = engine.prefix_search(text)
                        work, label = r["nodes_visited"], "Trie nodes visited"
                    else:
                        r = engine.search_name(text)
                        work, label = r["comparisons"], "Comparisons"
                    st.metric(label, work, border=True, icon=":material/compare_arrows:")
                    show_products(r["products"])
            elif method == "AVL price range":
                top = price_ceiling(products)
                low, high = st.slider("Price range", 0.0, top, (min(2.0, top / 4), min(8.0, top)),
                                      step=0.5, format="$%.2f")
                r = engine.price_range(low, high)
                st.metric("Tree nodes visited", f"{r['nodes_visited']} of {engine.count}",
                          border=True, icon=":material/account_tree:")
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

    with st.container(border=True):
        card_title("Sort")
        c1, c2, c3 = st.columns(3)
        key = c1.selectbox("Sort by", ["name", "price", "quantity", "value"],
                           format_func=str.title)
        algorithm = c2.selectbox("Algorithm", list(ALGO_NAMES), format_func=ALGO_NAMES.get)
        descending = c3.segmented_control("Order", ["Ascending", "Descending"],
                                          default="Ascending") == "Descending"
        r = engine.sort(key, algorithm, descending)
        c = st.columns(4)
        c[0].metric("Comparisons", f"{r['comparisons']:,}", border=True,
                    icon=":material/compare_arrows:")
        c[1].metric("Element moves", f"{r['moves']:,}", border=True, icon=":material/swap_vert:")
        c[2].metric("Time complexity", ALGO_COMPLEXITY[algorithm], border=True,
                    icon=":material/timer:")
        c[3].metric("Stable", "Yes" if algorithm in STABLE_ALGORITHMS else "No", border=True,
                    icon=":material/balance:", help="A stable sort keeps equal keys in their "
                                                    "original order.")
        show_products(r["products"])


def budget_planner(conn, ranking, costs):
    """0/1 knapsack (C dynamic programming) vs greedy, with a one-click order."""
    card_title("Budget planner")
    st.caption("Not enough money to restock everything? Pick the set of restocks with the "
               "highest total priority that fits the budget. Dynamic programming finds the "
               "best set; the greedy shortcut (best priority per dollar first) is compared.")
    total = sum(costs)
    budget = st.slider("Budget", 0, max(total, 1), max(total // 2, min(total, 1)),
                       step=max(total // 100, 1), format="$%d")
    values = [p["score"] for p in ranking]
    try:
        dp = knapsack(costs, values, budget)
        greedy = knapsack_greedy(costs, values, budget)
    except (ValueError, StockWiseError) as exc:
        st.error(str(exc), icon=":material/error:")
        return
    dp_cost = sum(costs[i] for i in dp["chosen"])
    m = st.columns(4)
    m[0].metric("DP priority covered", f"{dp['value']:.1f}", border=True,
                icon=":material/grid_on:",
                delta=f"{dp['value'] - greedy['value']:+.1f} vs greedy", delta_color="normal")
    m[1].metric("Greedy priority covered", f"{greedy['value']:.1f}", border=True,
                icon=":material/bolt:")
    m[2].metric("DP plan cost", f"${dp_cost:,}", border=True, icon=":material/payments:",
                help=f"${budget - dp_cost:,} of the budget left over")
    m[3].metric("DP cells evaluated", f"{dp['cells']:,}", border=True,
                icon=":material/table:", help="n × (budget + 1) at most")
    dp_set, greedy_set = set(dp["chosen"]), set(greedy["chosen"])
    plan = pd.DataFrame([{"Product": p["name"], "Cost": costs[i], "Priority": p["score"],
                          "Priority per $": p["score"] / costs[i] if costs[i] else None,
                          "DP plan": "Selected" if i in dp_set else "",
                          "Greedy plan": "Selected" if i in greedy_set else ""}
                         for i, p in enumerate(ranking)])
    st.dataframe(plan, hide_index=True, column_config={
        "Cost": st.column_config.NumberColumn(format="$%d"),
        "Priority per $": st.column_config.NumberColumn(format="%.3f")})
    if st.button("Order the DP plan", type="primary", icon=":material/shopping_cart:",
                 disabled=not dp["chosen"]):
        for i in dp["chosen"]:
            db.record_transaction(conn, ranking[i]["id"], "IN", ranking[i]["suggested_qty"],
                                  "Budget plan delivery")
        flash(f"Recorded {len(dp['chosen'])} deliveries costing ${dp_cost:,}")


def page_restock(conn, engine):
    header("Restocking", "Products at or below minimum stock, ranked by a C Max-Heap. The "
                         "budget planner solves a 0/1 knapsack with dynamic programming.")
    result = engine.restock_ranking()
    ranking = result["ranking"]
    if not ranking:
        empty_state("Every product is above its minimum stock. Nothing to restock.")
        return

    costs = [math.ceil(p["suggested_qty"] * p["price"]) for p in ranking]
    c = st.columns(4)
    c[0].metric("Products to restock", len(ranking), border=True,
                icon=":material/local_shipping:")
    c[1].metric("Out of stock", sum(p["quantity"] == 0 for p in ranking), border=True,
                icon=":material/error:")
    c[2].metric("Cost to restock all", f"${sum(costs):,}", border=True,
                icon=":material/shopping_cart:",
                help=f"{sum(p['suggested_qty'] for p in ranking):,} units in total")
    c[3].metric("Heap operations", f"{result['comparisons'] + result['swaps']}", border=True,
                icon=":material/account_tree:",
                help=f"{result['comparisons']} comparisons, {result['swaps']} swaps")

    with st.container(border=True):
        card_title("Priority ranking")
        rows = [{"Rank": i + 1, "Product": p["name"], "Stock": p["quantity"],
                 "Min stock": p["min_stock"], "Priority": p["score"],
                 "Reason": "; ".join(p["reasons"]), "Suggested qty": p["suggested_qty"],
                 "Cost": costs[i]}
                for i, p in enumerate(ranking)]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     column_config={"Priority": st.column_config.ProgressColumn(
                         min_value=0, max_value=100, format="%.1f", color=BLUE),
                         "Cost": st.column_config.NumberColumn(format="$%d")})
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

    with st.container(border=True):
        budget_planner(conn, ranking, costs)

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
    header("Transactions", "Stock in and stock out are saved atomically with their history. "
                           "Stock lots are tracked first-in, first-out with a C circular queue.")
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

    by_id = {p["id"]: p for p in products}
    choice = st.selectbox("Show history for", [None] + list(by_id),
                          format_func=lambda i: "All products" if i is None
                          else product_label(by_id[i]))
    left, right = st.columns([3, 2])
    with left.container(border=True):
        card_title("History")
        show_transactions(db.list_transactions(conn, product_id=choice))

    with right.container(border=True):
        if choice is None:
            card_title("Oldest stock")
            st.caption("Age of the oldest units still on the shelf, per product, from FIFO lots.")
            aging = []
            for p in products:
                lots = stock_lots(conn, p["id"])["lots"]
                if lots:
                    aging.append({"Product": p["name"], "Oldest lot (days)": lots[0]["age_days"],
                                  "Lots": len(lots)})
            aging.sort(key=lambda r: -r["Oldest lot (days)"])
            if aging:
                st.dataframe(pd.DataFrame(aging[:10]), hide_index=True)
            else:
                st.caption("No stock on hand.")
        else:
            card_title("Stock lots (FIFO queue)")
            r = stock_lots(conn, choice)
            lots = r["lots"]
            if not lots:
                empty_state("No units on hand, so the queue is empty.")
            else:
                m = st.columns(2)
                m[0].metric("Lots on hand", len(lots), border=True, icon=":material/layers:")
                m[1].metric("Oldest stock", f"{lots[0]['age_days']} days", border=True,
                            icon=":material/schedule:")
                df = pd.DataFrame([{"Received": datetime.fromtimestamp(l["received"]),
                                    "Units": l["quantity"], "Age (days)": l["age_days"]}
                                   for l in lots])
                fig = px.bar(df, x="Received", y="Units")
                fig.update_traces(hovertemplate="%{x|%d %b %Y}<br>%{y} units<extra></extra>")
                fig.update_xaxes(title=None, showgrid=False)
                fig.update_yaxes(title=None)
                chart(fig, "lots", height=200)
                st.dataframe(df, hide_index=True, column_config={
                    "Received": st.column_config.DatetimeColumn(format="D MMM YYYY")})
                st.caption(f"{r['queue_operations']} enqueue/dequeue operations. Sales take "
                           "units from the oldest lot first.")


def route_dot(path, distances):
    """Graphviz map of the delivery network with the chosen route highlighted."""
    on_route = set(zip(path, path[1:])) | set(zip(path[1:], path))
    lines = ['graph { layout=neato; bgcolor="transparent"; splines=true;',
             'node [shape=box, style="rounded,filled", fontname="Inter", fontsize=11, '
             'fillcolor="#ffffff", color="#c3c2b7", fontcolor="#14171f", penwidth=1.2, '
             'margin="0.15,0.08"];',
             'edge [fontname="Inter", fontsize=10, fontcolor="#52525b", color="#c3c2b7"];']
    for i, (name, x, y) in enumerate(db.LOCATIONS):
        style = ''
        if path and i in (path[0], path[-1]):
            style = ', fillcolor="#2a78d6", color="#2a78d6", fontcolor="#ffffff"'
        elif i in path:
            style = ', fillcolor="#e6f0fc", color="#2a78d6"'
        km = "" if distances[i] is None else f"\\n{distances[i]} km"
        lines.append(f'n{i} [label="{name}{km}", pos="{x * 1.3},{y * 1.1}!"{style}];')
    for a, b, w in db.ROUTES:
        hot = (a, b) in on_route
        attrs = 'color="#2a78d6", penwidth=3, fontcolor="#1c5cab"' if hot else 'penwidth=1.2'
        lines.append(f'n{a} -- n{b} [label="{w}", {attrs}];')
    return "\n".join(lines + ["}"])


def page_routes():
    header("Delivery routes", "Shortest delivery routes between the warehouse and branches, "
                              "found with Dijkstra's algorithm in C.")
    names = [loc[0] for loc in db.LOCATIONS]
    c1, c2 = st.columns(2)
    source = c1.selectbox("From", range(len(names)), format_func=names.__getitem__)
    target = c2.selectbox("To", range(len(names)), format_func=names.__getitem__,
                          index=len(names) - 1)
    r = shortest_path(len(names), db.ROUTES, source, target)
    path, dist = r["path"], r["distances"]

    m = st.columns(4)
    m[0].metric("Distance", "Unreachable" if not path else f"{dist[target]} km", border=True,
                icon=":material/route:")
    m[1].metric("Stops on the way", max(len(path) - 2, 0), border=True,
                icon=":material/location_on:")
    m[2].metric("Edges relaxed", r["relaxations"], border=True, icon=":material/call_split:")
    m[3].metric("Heap comparisons", r["comparisons"], border=True,
                icon=":material/account_tree:")
    if path:
        st.markdown(" :gray[:material/arrow_forward:] ".join(
            f":blue-badge[{names[i]}]" for i in path))

    left, right = st.columns([3, 2])
    with left.container(border=True):
        card_title("Network")
        st.caption("Road distances in km. Each node shows its shortest distance from the start.")
        st.graphviz_chart(route_dot(path, dist))
    with right.container(border=True):
        card_title(f"Distances from {names[source]}")
        table = pd.DataFrame([{"Location": names[i], "Distance (km)": d}
                              for i, d in enumerate(dist) if i != source])
        st.dataframe(table.sort_values("Distance (km)"), hide_index=True)
        st.caption("Dijkstra settles the closest unsettled location each round, so one run "
                   "gives the shortest distance to every location.")


def tree_dot(nodes, label, max_depth=5):
    """Graphviz drawing of a binary tree given as positions with left/right children."""
    lines = ['digraph { bgcolor="transparent"; nodesep=0.2; ranksep=0.35;',
             'node [shape=box, style="rounded,filled", fillcolor="#eef4fc", color="#86b6ef", '
             'fontname="Inter", fontsize=11, fontcolor="#14171f", penwidth=1.2];',
             'edge [color="#c3c2b7", arrowsize=0.6];']
    stack = [(0, 0)] if nodes else []
    while stack:  # pre-order; Graphviz draws children in the order edges appear
        i, depth = stack.pop()
        root = ', fillcolor="#2a78d6", color="#2a78d6", fontcolor="#ffffff"' if i == 0 else ""
        lines.append(f'n{i} [label="{label(nodes[i])}"{root}];')
        kids = [c for c in (nodes[i]["left"], nodes[i]["right"])
                if c >= 0 and depth + 1 < max_depth]
        lines += [f"n{i} -> n{c};" for c in kids]  # left edge first, so left child is drawn left
        stack += [(c, depth + 1) for c in reversed(kids)]
    return "\n".join(lines + ["}"])


def heap_tree(heap):
    """Heap array -> the node format tree_dot draws (children at 2i+1, 2i+2)."""
    n = len(heap)
    return [{"p": p, "left": 2 * i + 1 if 2 * i + 1 < n else -1,
             "right": 2 * i + 2 if 2 * i + 2 < n else -1} for i, p in enumerate(heap)]


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

    tabs = st.tabs([":material/search: Search", ":material/sort: Sorting",
                    ":material/tag: Hash table", ":material/account_tree: Max-Heap",
                    ":material/park: AVL tree", ":material/spellcheck: Trie",
                    ":material/grid_on: Knapsack DP", ":material/rule: Edge cases",
                    ":material/code: Pseudocode"])
    with Engine(data, bucket_count=int(buckets)) as eng:
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
            rows, orders = [], {}
            for a in ALGO_NAMES:
                r = eng.sort(key, a)
                orders[a] = [p[key] for p in r["products"]]
                rows.append({"Algorithm": ALGO_NAMES[a], "Comparisons": r["comparisons"],
                             "Moves": r["moves"], "Stable": "Yes" if a in STABLE_ALGORITHMS
                             else "No", "Time": ALGO_COMPLEXITY[a]})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            same = all(o == orders["merge"] for o in orders.values())
            st.caption(":material/check_circle: All four algorithms produced the same key order"
                       if same else ":material/error: The key orders differ")

            card_title("Scaling experiment")
            st.caption("Comparisons needed to sort random data by price as n grows "
                       "(logarithmic axis).")
            exp = []
            for size in [50, 100, 200, 400, 800, 1600]:
                with Engine(generate_products(size, size)) as e2:
                    for a in ALGO_NAMES:
                        exp.append({"n": size, "Algorithm": ALGO_NAMES[a],
                                    "Comparisons": e2.sort("price", a)["comparisons"]})
            exp = pd.DataFrame(exp)
            fig = px.line(exp, x="n", y="Comparisons", color="Algorithm", markers=True, log_y=True,
                          color_discrete_sequence=[BLUE, ORANGE, AQUA, "#eda100"])
            fig.update_traces(line_width=2, marker_size=8,
                              hovertemplate="n = %{x}<br>%{y:,} comparisons<extra></extra>")
            ends = exp[exp["n"] == exp["n"].max()].sort_values("Comparisons", ascending=False)
            shift, prev = 0, None
            for _, row in ends.iterrows():  # direct labels at line ends, nudged apart
                y = math.log10(row["Comparisons"])
                shift = shift - 15 if prev is not None and prev - y < 0.15 else 0
                prev = y
                fig.add_annotation(x=row["n"], y=y, text=row["Algorithm"], showarrow=False,
                                   xanchor="left", xshift=8, yshift=shift,
                                   font=dict(color=INK, size=12))
            fig.update_xaxes(title="Number of products (n)", range=[0, 2050])
            fig.update_yaxes(title=None)
            chart(fig, "scaling", height=360, legend=True)

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
                    st.caption("Labelled id / score. The root is the most urgent product.")
                    st.graphviz_chart(tree_dot(heap_tree(r["heap_array"]),
                                               lambda t: f'{t["p"]["id"]}\\n{t["p"]["score"]:.1f}'))
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
            stats = eng.index_stats()
            ideal = math.ceil(math.log2(eng.count + 1)) if eng.count else 0
            c = st.columns(4)
            c[0].metric("Nodes", stats["avl_nodes"], border=True)
            c[1].metric("Height", stats["avl_height"], border=True,
                        help="A single node has height 1")
            c[2].metric("Best possible height", ideal, border=True, help="⌈log₂(n + 1)⌉")
            c[3].metric("Rotations while building", stats["avl_rotations"], border=True)
            if data:
                top = price_ceiling(data)
                low, high = st.slider("Range query", 0.0, top,
                                      (top * 0.2, top * 0.4), step=0.5, format="$%.2f",
                                      key="lab_range")
                r = eng.price_range(low, high)
                st.caption(f"{len(r['products'])} products in range · {r['nodes_visited']} of "
                           f"{eng.count} nodes visited (linear search would check all "
                           f"{eng.count})")
                with st.container(border=True):
                    card_title("Tree, top 5 levels")
                    st.caption("Keyed by price. Left subtree cheaper, right subtree dearer.")
                    st.graphviz_chart(tree_dot(eng.avl_nodes(),
                                               lambda t: f'${t["product"]["price"]:.2f}'))

        with tabs[5]:
            stats = eng.index_stats()
            c = st.columns(3)
            c[0].metric("Trie nodes", f"{stats['trie_nodes']:,}", border=True)
            c[1].metric("Keys inserted", f"{stats['trie_keys']:,}", border=True,
                        help="One key per word start of every name")
            c[2].metric("Products", eng.count, border=True)
            prefix = st.text_input("Prefix", value="s", key="lab_prefix",
                                   icon=":material/keyboard:")
            if prefix.strip() and data:
                trie = eng.prefix_search(prefix)
                linear = eng.search_name(prefix)
                cmp = pd.DataFrame([
                    {"Method": "Trie prefix", "Work": trie["nodes_visited"],
                     "Matches": len(trie["products"])},
                    {"Method": "Linear substring", "Work": linear["comparisons"],
                     "Matches": len(linear["products"])}])
                left, right = st.columns([2, 3])
                left.dataframe(cmp, hide_index=True)
                left.caption("Trie work counts nodes visited; linear work counts names checked. "
                             "Substring search also matches text inside words.")
                right.dataframe(pd.DataFrame([{"Suggestion": p["name"], "ID": p["id"]}
                                              for p in trie["products"][:20]]), hide_index=True)

        with tabs[6]:
            st.caption("Edit the items and budget. Each cell dp[i][w] is the best priority "
                       "using the first i items with budget w.")
            items = st.data_editor(
                pd.DataFrame({"Item": ["Cables", "Rice", "Soap", "Juice"],
                              "Cost": [1, 3, 4, 5], "Priority": [1.0, 4.0, 5.0, 7.0]}),
                hide_index=True, num_rows="dynamic", key="ks_items",
                column_config={"Cost": st.column_config.NumberColumn(min_value=0, max_value=20,
                                                                     step=1),
                               "Priority": st.column_config.NumberColumn(min_value=0.0)})
            items = items.dropna()
            budget = st.slider("Budget", 0, 20, 7, key="ks_budget")
            try:
                costs = [int(c) for c in items["Cost"]]
                values = [float(v) for v in items["Priority"]]
                dp = knapsack(costs, values, budget, with_table=True)
                greedy = knapsack_greedy(costs, values, budget)
            except (ValueError, StockWiseError) as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                names = list(items["Item"].astype(str))
                c = st.columns(3)
                c[0].metric("DP best priority", f"{dp['value']:.1f}", border=True)
                c[1].metric("Greedy priority", f"{greedy['value']:.1f}", border=True,
                            delta=f"{greedy['value'] - dp['value']:+.1f} vs DP")
                c[2].metric("Cells evaluated", dp["cells"], border=True)
                st.markdown("**DP picks:** " + (", ".join(names[i] for i in dp["chosen"])
                                                or "nothing") +
                            " &nbsp; **Greedy picks:** " +
                            (", ".join(names[i] for i in greedy["chosen"]) or "nothing"))
                table = pd.DataFrame(dp["table"], index=["(none)"] + names)
                fig = px.imshow(table, text_auto=".0f", aspect="auto",
                                color_continuous_scale=["#f2f4f7", "#9ec5f4", "#2a78d6",
                                                        "#104281"],
                                labels=dict(x="Budget w", y="", color="Best"))
                fig.update_traces(hovertemplate="first %{y}, budget %{x}<br>best %{z:.1f}"
                                                "<extra></extra>")
                fig.update_xaxes(side="top", dtick=1, showgrid=False)
                fig.update_yaxes(showgrid=False)
                fig.update_layout(coloraxis_showscale=False)
                chart(fig, "dp_table", height=80 + 44 * len(table))

    with tabs[7]:
        cases = pd.DataFrame(run_edge_cases())
        passed = int((cases["Result"] == "Passed").sum())
        st.caption(f"{passed} of {len(cases)} checks passed. These run live against the C "
                   "engine and a scratch database.")
        st.dataframe(cases, hide_index=True)

    with tabs[8]:
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
            "copies the records into C, which builds a hash index, an id-sorted index, an AVL "
            "tree by price and a trie of name prefixes. The planning algorithms (knapsack, "
            "Dijkstra, FIFO queue) are stateless C functions that work on arrays Python passes "
            "in.")
    left, right = st.columns([3, 2])
    with left.container(border=True):
        card_title("Complexity")
        st.dataframe(COMPLEXITY, hide_index=True)
    with right.container(border=True):
        card_title("Where each concept is used")
        st.markdown(
            "- **Hash table**: product lookup by ID\n"
            "- **Binary / linear search**: ID search comparison\n"
            "- **Trie**: name autocomplete\n"
            "- **AVL tree**: price range filter\n"
            "- **Merge, Insertion, Quick, Heap Sort**: sorted views\n"
            "- **Max-Heap**: restock priority queue\n"
            "- **0/1 Knapsack (DP)**: budget restock plan\n"
            "- **Graph + Dijkstra**: delivery routes\n"
            "- **Circular queue**: FIFO stock lots and stock age")
        st.latex(r"\text{Priority} = 100 \times (0.5\,S + 0.3\,D + 0.2\,I)")


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
                page(page_routes, "Delivery routes", "route", "routes"),
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
