"""Aplicativo Streamlit para registrar e acompanhar gastos pessoais."""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import streamlit as st


APP_TITLE = "Meu Controle de Gastos"
CATEGORIES = (
    "Alimentação",
    "Casa",
    "Contas",
    "Educação",
    "Lazer",
    "Saúde",
    "Transporte",
    "Outros",
)
DATABASE_PATH = Path(__file__).with_name("gastos.db")


def money(cents: int) -> str:
    """Formata centavos como moeda brasileira."""
    whole, fraction = divmod(abs(cents), 100)
    whole_text = f"{whole:,}".replace(",", ".")
    sign = "-" if cents < 0 else ""
    return f"{sign}R$ {whole_text},{fraction:02d}"


def parse_amount(value: str) -> int:
    """Converte valores em formato brasileiro ou decimal para centavos."""
    amount_text = value.strip().replace("R$", "").replace(" ", "")
    if "," in amount_text:
        amount_text = amount_text.replace(".", "").replace(",", ".")
    amount = Decimal(amount_text)
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise InvalidOperation
    return int(amount * 100)


class ExpenseStore:
    """Persistência SQLite para os lançamentos."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                expense_date TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                payment_method TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.connection.commit()

    def list_expenses(
        self, month: str = "", category: str = "", search: str = ""
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        values: list[str] = []
        if month:
            clauses.append("substr(expense_date, 1, 7) = ?")
            values.append(month)
        if category and category != "Todas":
            clauses.append("category = ?")
            values.append(category)
        if search.strip():
            clauses.append("(description LIKE ? OR payment_method LIKE ?)")
            term = f"%{search.strip()}%"
            values.extend((term, term))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return list(
            self.connection.execute(
                f"SELECT * FROM expenses {where} ORDER BY expense_date DESC, id DESC",
                values,
            )
        )

    def add(
        self, description: str, category: str, expense_date: str, cents: int, payment: str
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO expenses (description, category, expense_date, amount_cents, payment_method)
            VALUES (?, ?, ?, ?, ?)
            """,
            (description, category, expense_date, cents, payment),
        )
        self.connection.commit()

    def update(
        self,
        expense_id: int,
        description: str,
        category: str,
        expense_date: str,
        cents: int,
        payment: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE expenses
            SET description = ?, category = ?, expense_date = ?, amount_cents = ?, payment_method = ?
            WHERE id = ?
            """,
            (description, category, expense_date, cents, payment, expense_id),
        )
        self.connection.commit()

    def delete(self, expense_id: int) -> None:
        self.connection.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def render_app(store: ExpenseStore) -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="💰",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .stApp { background: #f4f7f5; }
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e3eae6;
            padding: 18px 20px;
            border-radius: 12px;
        }
        [data-testid="stMetricLabel"] { color: #718078; }
        [data-testid="stMetricValue"] { color: #172b24; }
        h1, h2, h3 { color: #172b24; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    today = date.today()
    all_rows = store.list_expenses()
    month_rows = store.list_expenses(month=today.strftime("%Y-%m"))

    st.title(APP_TITLE)
    st.caption("Organize suas despesas e acompanhe para onde seu dinheiro vai.")

    metric_month, metric_total, metric_count = st.columns(3)
    metric_month.metric(
        "Gastos neste mês", money(sum(row["amount_cents"] for row in month_rows))
    )
    metric_total.metric(
        "Total registrado", money(sum(row["amount_cents"] for row in all_rows))
    )
    metric_count.metric("Lançamentos neste mês", len(month_rows))

    with st.sidebar:
        st.header("Novo lançamento")
        with st.form("add_expense_form", clear_on_submit=True):
            description = st.text_input(
                "Descrição", placeholder="Ex.: compra no mercado", key="new_description"
            )
            amount_text = st.text_input(
                "Valor (R$)", placeholder="Ex.: 45,90", key="new_amount"
            )
            expense_date = st.date_input(
                "Data", value=today, format="DD/MM/YYYY", key="new_date"
            )
            category = st.selectbox("Categoria", CATEGORIES, key="new_category")
            payment = st.text_input(
                "Forma de pagamento (opcional)",
                placeholder="Ex.: cartão",
                key="new_payment",
            )
            submitted = st.form_submit_button(
                "Adicionar gasto", type="primary", use_container_width=True
            )

        if submitted:
            if not description.strip():
                st.error("Informe uma descrição para o gasto.")
            else:
                try:
                    cents = parse_amount(amount_text)
                    store.add(
                        description.strip(),
                        category,
                        expense_date.isoformat(),
                        cents,
                        payment.strip(),
                    )
                except (InvalidOperation, ValueError):
                    st.error(
                        "Informe um valor maior que zero, com até duas casas decimais."
                    )
                except sqlite3.Error as error:
                    st.error(f"Não foi possível salvar o lançamento: {error}")
                else:
                    st.success("Gasto adicionado.")
                    st.rerun()

        st.divider()
        st.caption(f"Dados salvos localmente em `{DATABASE_PATH.name}`.")

    st.subheader("Lançamentos")
    distinct_months = sorted(
        {row["expense_date"][:7] for row in all_rows} | {today.strftime("%Y-%m")},
        reverse=True,
    )
    month_options = ["Todos", *distinct_months]
    filter_col1, filter_col2, filter_col3 = st.columns((1, 1, 2))
    selected_month = filter_col1.selectbox(
        "Mês", month_options, index=month_options.index(today.strftime("%Y-%m"))
    )
    selected_category = filter_col2.selectbox("Categoria", ("Todas", *CATEGORIES))
    search = filter_col3.text_input("Buscar", placeholder="Descrição ou pagamento")

    filtered_rows = store.list_expenses(
        month="" if selected_month == "Todos" else selected_month,
        category=selected_category,
        search=search,
    )
    display_rows = [
        {
            "Data": row["expense_date"],
            "Descrição": row["description"],
            "Categoria": row["category"],
            "Pagamento": row["payment_method"] or "—",
            "Valor": money(row["amount_cents"]),
        }
        for row in filtered_rows
    ]
    if display_rows:
        st.dataframe(
            pd.DataFrame(display_rows),
            width="stretch",
            hide_index=True,
        )
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, delimiter=";")
        writer.writerow(
            ("Data", "Descrição", "Categoria", "Forma de pagamento", "Valor (R$)")
        )
        for row in filtered_rows:
            writer.writerow(
                (
                    row["expense_date"],
                    row["description"],
                    row["category"],
                    row["payment_method"],
                    f"{row['amount_cents'] // 100},{row['amount_cents'] % 100:02d}",
                )
            )
        st.download_button(
            "Exportar CSV",
            data=csv_buffer.getvalue().encode("utf-8-sig"),
            file_name="meus_gastos.csv",
            mime="text/csv",
        )
    else:
        st.info("Nenhum lançamento encontrado para esses filtros.")

    if all_rows:
        with st.expander("Editar ou excluir lançamento"):
            expense_labels = {
                row["id"]: (
                    f'{row["expense_date"]} · {row["description"]} · '
                    f'{money(row["amount_cents"])}'
                )
                for row in all_rows
            }
            selected_id = st.selectbox(
                "Selecione um lançamento",
                options=list(expense_labels),
                format_func=expense_labels.get,
                key="expense_to_edit",
            )
            selected = next(row for row in all_rows if row["id"] == selected_id)

            with st.form("edit_expense_form"):
                edit_col1, edit_col2 = st.columns(2)
                edited_description = edit_col1.text_input(
                    "Descrição",
                    value=selected["description"],
                    key=f"edit_description_{selected_id}",
                )
                edited_amount = edit_col2.text_input(
                    "Valor (R$)",
                    value=f'{selected["amount_cents"] // 100},{selected["amount_cents"] % 100:02d}',
                    key=f"edit_amount_{selected_id}",
                )
                edit_col3, edit_col4 = st.columns(2)
                edited_date = edit_col3.date_input(
                    "Data",
                    value=date.fromisoformat(selected["expense_date"]),
                    format="DD/MM/YYYY",
                    key=f"edit_date_{selected_id}",
                )
                category_index = CATEGORIES.index(selected["category"])
                edited_category = edit_col4.selectbox(
                    "Categoria",
                    CATEGORIES,
                    index=category_index,
                    key=f"edit_category_{selected_id}",
                )
                edited_payment = st.text_input(
                    "Forma de pagamento (opcional)",
                    value=selected["payment_method"],
                    key=f"edit_payment_{selected_id}",
                )
                update_submitted = st.form_submit_button(
                    "Salvar alterações", type="primary"
                )

            if update_submitted:
                if not edited_description.strip():
                    st.error("Informe uma descrição para o gasto.")
                else:
                    try:
                        edited_cents = parse_amount(edited_amount)
                        store.update(
                            selected_id,
                            edited_description.strip(),
                            edited_category,
                            edited_date.isoformat(),
                            edited_cents,
                            edited_payment.strip(),
                        )
                    except (InvalidOperation, ValueError):
                        st.error(
                            "Informe um valor maior que zero, com até duas casas decimais."
                        )
                    except sqlite3.Error as error:
                        st.error(f"Não foi possível atualizar o lançamento: {error}")
                    else:
                        st.success("Lançamento atualizado.")
                        st.rerun()

            confirm_delete = st.checkbox(
                "Confirmo que desejo excluir este lançamento",
                key=f"confirm_delete_{selected_id}",
            )
            if st.button(
                "Excluir lançamento",
                disabled=not confirm_delete,
                key=f"delete_{selected_id}",
            ):
                try:
                    store.delete(selected_id)
                except sqlite3.Error as error:
                    st.error(f"Não foi possível excluir o lançamento: {error}")
                else:
                    st.success("Lançamento excluído.")
                    st.rerun()


def main() -> None:
    store = ExpenseStore()
    try:
        render_app(store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
