"""
split-finances.py

Calculate and settle shared expenses from one or more CSV files.

Usage:
    python split-finances.py CSV [CSV ...] [--transfer SRC:DST ...]

Each CSV has the columns (Group and Weight are optional):

    - Group:    Links rows that make up one shared cost. Rows with the same
                Group are pooled: the money they contribute is split across
                the shares they contribute. Leave blank for a standalone
                one-row expense.
    - Item:     Free-text label (ignored by the math).
    - Payer:    Who put money in. Use "Cash" to mean everyone paid equally.
    - Amount:   The amount paid, e.g. 12.50, $12.50, or -5.00 for a refund.
    - Involved: Comma-separated people sharing this row's cost. "All" (or
                "Everyone") expands to the whole roster. Blank on a row that
                only contributes money is fine.
    - Weight:   How much each listed person's share counts (default 1). Use
                2 for e.g. a doubleheader that should count double.

Every row contributes money (if it has Payer + Amount) and/or shares (if it
has Involved) to its group -- blanks simply contribute nothing on that axis.
Within a group the pooled money is divided in proportion to shares, so:

    person's cost = (their share weight / group's total weight) x pooled money

A standalone expense (blank Group) is just a one-row group: Payer paid Amount,
split equally among Involved -- so the simple case stays a single line.

Bare filenames are looked up in the payment-csvs/ directory, so
`split-finances.py softball-season` works from anywhere in the repo.

All math is done in integer cents (leftover pennies go to the largest
fractional shares), so the final balances always sum to exactly zero.
"""

import argparse
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

PAYMENT_CSV_DIR = Path(__file__).resolve().parent.parent / "payment-csvs"
CASH = "cash"
EVERYONE_TOKENS = {"all", "everyone"}
REQUIRED_COLUMNS = {"Payer", "Amount", "Involved"}

# ANSI styling, only when printing to a real terminal
if sys.stdout.isatty():
    GREEN, RED, BOLD, DIM, RESET = "\033[32m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"
else:
    GREEN = RED = BOLD = DIM = RESET = ""


def resolve_csv_path(name: str) -> Path:
    """Accept a real path, or fall back to payment-csvs/<name>[.csv]."""
    candidates = [Path(name), PAYMENT_CSV_DIR / name]
    if not name.lower().endswith(".csv"):
        candidates += [Path(f"{name}.csv"), PAYMENT_CSV_DIR / f"{name}.csv"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    sys.exit(f"Error: could not find '{name}' (also looked in {PAYMENT_CSV_DIR}).")


def split_names(field_value: str | None) -> list[str]:
    """Split a comma-separated name list, tolerating missing spaces."""
    names = [name.strip() for name in (field_value or "").split(",")]
    return [name for name in names if name]


def parse_amount_cents(raw: str | None, context: str) -> int:
    text = (raw or "").strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    try:
        cents = round(float(cleaned) * 100)
    except ValueError:
        sys.exit(f"Error: could not parse amount {text!r} ({context}).")
    return -cents if negative else cents


def apportion(amount: int, weights: list[float]) -> list[int]:
    """Split amount (cents) into integer parts proportional to weights, summing
    exactly to amount. Leftover pennies go to the largest fractional parts."""
    n = len(weights)
    total = sum(weights)
    if n == 0 or total <= 0:
        return [0] * n
    sign = -1 if amount < 0 else 1
    magnitude = abs(amount)
    exact = [magnitude * w / total for w in weights]
    parts = [math.floor(e) for e in exact]
    leftover = magnitude - sum(parts)
    order = sorted(range(n), key=lambda i: (exact[i] - parts[i], -i), reverse=True)
    for i in order[:leftover]:
        parts[i] += 1
    return [sign * p for p in parts]


@dataclass
class Group:
    """A pool of money split across a pool of weighted shares."""
    money_by_payer: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cash: int = 0  # money paid by "Cash" (credited to everyone equally)
    share_weight: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def pot(self) -> int:
        return self.cash + sum(self.money_by_payer.values())


def read_rows(paths: list[Path]) -> list[tuple[str, int, dict]]:
    """Return (filename, line number, row) for every row across all files."""
    rows = []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                sys.exit(f"Error: {path.name} is missing column(s): {', '.join(sorted(missing))}.")
            for line, row in enumerate(reader, start=2):
                rows.append((path.name, line, row))
    return rows


def build_groups(rows: list[tuple[str, int, dict]]) -> tuple[dict, list[str]]:
    """Group rows and return (groups, roster). Roster = every named participant."""
    roster = sorted(
        {
            name
            for _, _, row in rows
            for name in split_names(row["Involved"]) + split_names(row["Payer"])
            if name.lower() not in EVERYONE_TOKENS | {CASH}
        }
    )

    def expand(names: list[str]) -> set[str]:
        out: set[str] = set()
        for name in names:
            out.update(roster if name.lower() in EVERYONE_TOKENS else [name])
        return out

    groups: dict[object, Group] = defaultdict(Group)
    for filename, line, row in rows:
        context = f"{filename} line {line}"
        # blank Group -> a unique key so the row is its own standalone group
        key = row.get("Group", "").strip() or ("__row__", filename, line)
        group = groups[key]

        payer = (row["Payer"] or "").strip()
        amount_raw = (row["Amount"] or "").strip()
        if bool(payer) != bool(amount_raw):
            sys.exit(f"Error: Payer and Amount must be given together ({context}).")
        if payer:
            amount = parse_amount_cents(amount_raw, context)
            if payer.lower() == CASH:
                group.cash += amount
            else:
                group.money_by_payer[payer] += amount

        try:
            weight = float(row.get("Weight", "") or 1)
        except ValueError:
            sys.exit(f"Error: could not parse Weight {row.get('Weight')!r} ({context}).")
        for person in expand(split_names(row["Involved"])):
            group.share_weight[person] += weight

    return groups, roster


def calculate_balances(groups: dict, roster: list[str]) -> dict[str, int]:
    """Net balance in cents per person: positive = overpaid, negative = underpaid."""
    balances: dict[str, int] = defaultdict(int)
    for group in groups.values():
        # Credit whoever put money in.
        for payer, amount in group.money_by_payer.items():
            balances[payer] += amount
        if group.cash:
            for person, share in zip(roster, apportion(group.cash, [1.0] * len(roster))):
                balances[person] += share

        # Debit the shares. With no shares listed, the pot falls on everyone.
        if group.share_weight:
            people = sorted(group.share_weight)
            weights = [group.share_weight[p] for p in people]
        elif group.pot:
            people, weights = roster, [1.0] * len(roster)
        else:
            continue
        for person, share in zip(people, apportion(group.pot, weights)):
            balances[person] -= share

    return dict(balances)


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
        print(f" {DIM}Loaded {count} row{'s' if count != 1 else ''} from {filename}{RESET}")
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
    rows = read_rows(paths)
    if not rows:
        sys.exit("Error: no rows found.")

    groups, roster = build_groups(rows)
    balances = calculate_balances(groups, roster)
    if not balances:
        sys.exit("Error: nothing to split (no money and no participants found).")
    applied = apply_transfers(balances, transfers)
    plan = settlement_plan(balances)
    sources = [(path.name, sum(1 for name, _, _ in rows if name == path.name)) for path in paths]
    print_report(balances, plan, applied, sources)


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    main()
