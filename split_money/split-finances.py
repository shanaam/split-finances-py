"""
split-finances.py

Calculate and settle shared expenses from one or more CSV files.

Usage:
    python split-finances.py CSV [CSV ...] [--transfer SRC:DST ...]

Each CSV needs the columns (extra columns such as Item are ignored):
    - Payer:    Who paid. Use "Cash" to mean everyone paid equally.
    - Amount:   The amount paid, e.g. 12.50, $12.50, or -5.00 for a refund.
    - Involved: Comma-separated people sharing the expense. Leave empty to
                mean everyone who appears anywhere in the input files.

Bare filenames are also looked up in the payment-csvs/ directory, so
`split-finances.py softball-season` works from anywhere in the repo.

All math is done in integer cents: every expense is split into shares that
sum exactly to the amount paid (leftover pennies go to the people listed
first), so the final balances always sum to exactly zero.
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

PAYMENT_CSV_DIR = Path(__file__).resolve().parent.parent / "payment-csvs"
CASH = "cash"

# ANSI styling, only when printing to a real terminal
if sys.stdout.isatty():
    GREEN, RED, BOLD, DIM, RESET = "\033[32m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"
else:
    GREEN = RED = BOLD = DIM = RESET = ""


def resolve_csv_path(name: str) -> Path:
    """Accept a real path, or fall back to payment-csvs/<name>[.csv]."""
    candidates = [Path(name), PAYMENT_CSV_DIR / name]
    if not name.lower().endswith(".csv"):
        candidates.append(PAYMENT_CSV_DIR / f"{name}.csv")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    sys.exit(f"Error: could not find '{name}' (also looked in {PAYMENT_CSV_DIR}).")


def split_names(field: str | None) -> list[str]:
    """Split a comma-separated name list, tolerating missing spaces. Cash is not a person."""
    names = [name.strip() for name in (field or "").split(",")]
    return [name for name in names if name and name.lower() != CASH]


def parse_amount_cents(raw: str | None, context: str) -> int:
    text = (raw or "").strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    try:
        cents = round(float(cleaned) * 100)
    except ValueError:
        sys.exit(f"Error: could not parse amount {text!r} ({context}).")
    return -cents if negative else cents


def split_cents(amount: int, people: list[str], start: int = 0) -> list[int]:
    """Shares that sum exactly to amount. Leftover pennies go to the people at
    positions start, start+1, ... so callers can rotate who absorbs them."""
    n = len(people)
    base, extra = divmod(amount, n)
    return [base + (1 if (i - start) % n < extra else 0) for i in range(n)]


def read_transactions(paths: list[Path]) -> list[tuple[str, int, dict]]:
    """Return (filename, line number, row) for every row across all files."""
    transactions = []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = {"Payer", "Amount", "Involved"} - set(reader.fieldnames or [])
            if missing:
                sys.exit(f"Error: {path.name} is missing column(s): {', '.join(sorted(missing))}.")
            for line, row in enumerate(reader, start=2):
                transactions.append((path.name, line, row))
    return transactions


def calculate_balances(transactions: list[tuple[str, int, dict]]) -> dict[str, int]:
    """Net balance in cents per person: positive = overpaid, negative = underpaid."""
    everyone = sorted(
        {name for _, _, row in transactions for name in split_names(row["Involved"])}
        | {name for _, _, row in transactions for name in split_names(row["Payer"])}
    )

    balances: dict[str, int] = defaultdict(int)
    for index, (filename, line, row) in enumerate(transactions):
        context = f"{filename} line {line}"
        payer = (row["Payer"] or "").strip()
        if not payer:
            sys.exit(f"Error: missing Payer ({context}).")
        payers = everyone if payer.lower() == CASH else [payer]
        involved = split_names(row["Involved"]) or everyone
        amount = parse_amount_cents(row["Amount"], context)

        # rotate penny absorption by row so no one person collects them all
        for person, share in zip(involved, split_cents(amount, involved, start=index)):
            balances[person] -= share
        for person, share in zip(payers, split_cents(amount, payers)):
            balances[person] += share
    return balances


def apply_transfers(balances: dict[str, int], transfers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fold SRC's balance into DST (e.g. couples settling as one). Returns transfers applied."""
    applied = []
    for src, dst in transfers:
        if src in balances:
            balances[dst] = balances.get(dst, 0) + balances.pop(src)
            applied.append((src, dst))
    return applied


def settlement_plan(balances: dict[str, int]) -> list[tuple[str, str, int]]:
    """Greedy largest-first matching; at most (people - 1) payments."""
    creditors = sorted(((p, b) for p, b in balances.items() if b > 0), key=lambda x: -x[1])
    debtors = sorted(((p, -b) for p, b in balances.items() if b < 0), key=lambda x: -x[1])
    plan = []
    i = j = 0
    while i < len(creditors) and j < len(debtors):
        creditor, credit = creditors[i]
        debtor, debt = debtors[j]
        paid = min(credit, debt)
        plan.append((debtor, creditor, paid))
        creditors[i] = (creditor, credit - paid)
        debtors[j] = (debtor, debt - paid)
        if creditors[i][1] == 0:
            i += 1
        if debtors[j][1] == 0:
            j += 1
    return plan


def print_report(
    balances: dict[str, int],
    plan: list[tuple[str, str, int]],
    applied_transfers: list[tuple[str, str]],
    sources: list[tuple[str, int]],
) -> None:
    def money(cents: int) -> str:
        return f"${abs(cents) / 100:,.2f}"

    name_w = max(len(name) for name in balances)
    amount_w = max(len(money(cents)) for cents in balances.values())
    rule = DIM + "─" * (name_w * 2 + amount_w + 12) + RESET

    print()
    for filename, count in sources:
        print(f" {DIM}Loaded {count} expense{'s' if count != 1 else ''} from {filename}{RESET}")
    for src, dst in applied_transfers:
        print(f" {DIM}Moved {src}'s balance onto {dst}{RESET}")

    print()
    print(f" {BOLD}Balances{RESET}  {DIM}(+ is owed money, - owes money){RESET}")
    print(rule)
    for person, cents in sorted(balances.items(), key=lambda kv: -kv[1]):
        colour = GREEN if cents > 0 else RED if cents < 0 else ""
        sign = "+" if cents > 0 else "-" if cents < 0 else " "
        print(f" {person:<{name_w}}  {colour}{sign + money(cents):>{amount_w + 1}}{RESET}")
    print(rule)
    total = sum(balances.values())
    status = f"{GREEN}balanced ✓{RESET}" if total == 0 else f"{RED}NOT balanced!{RESET}"
    print(f" {'Total':<{name_w}}  {money(total):>{amount_w + 1}}  {status}")

    print()
    print(f" {BOLD}Settlement plan{RESET}  {DIM}({len(plan)} payment{'s' if len(plan) != 1 else ''}){RESET}")
    print(rule)
    for debtor, creditor, cents in plan:
        print(f" {debtor:<{name_w}}  {DIM}pays{RESET}  {creditor:<{name_w}}  {money(cents):>{amount_w + 1}}")
    print(rule)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split shared expenses from one or more CSV files.",
        epilog="Bare filenames are looked up in payment-csvs/.",
    )
    parser.add_argument("csvs", nargs="+", metavar="CSV", help="expense CSV file(s)")
    parser.add_argument(
        "--transfer",
        action="append",
        default=[],
        metavar="SRC:DST",
        help="move SRC's final balance onto DST (repeatable)",
    )
    args = parser.parse_args()

    transfers = []
    for spec in args.transfer:
        src, sep, dst = spec.partition(":")
        if not (sep and src.strip() and dst.strip()) or src.strip() == dst.strip():
            sys.exit(f"Error: --transfer expects SRC:DST with two different people, got {spec!r}.")
        transfers.append((src.strip(), dst.strip()))

    paths = [resolve_csv_path(name) for name in args.csvs]
    transactions = read_transactions(paths)
    if not transactions:
        sys.exit("Error: no transactions found.")

    balances = calculate_balances(transactions)
    applied = apply_transfers(balances, transfers)
    plan = settlement_plan(balances)
    sources = [(path.name, sum(1 for name, _, _ in transactions if name == path.name)) for path in paths]
    print_report(balances, plan, applied, sources)


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    main()
