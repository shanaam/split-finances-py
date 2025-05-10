"""
split-finances.py
A simple script to calculate and settle expenses among a group of people.
Usage:
    python split-finances.py path/to/expenses.csv
The CSV file should have the following columns:
    - Payer: The person who paid the amount.
    - Amount: The amount paid.
    - Involved: A comma-separated list of people involved in the transaction.
"""

import sys
import os

from collections import defaultdict

import pandas as pd

def calculate_settlements(csv_path):
    """
    Calculate and print the net balances of each person based on the transactions in the CSV file.
    """
    if not os.path.exists(csv_path):
        print(f"Error: File '{csv_path}' does not exist.")
        return

    df = pd.read_csv(csv_path)

    # Validate required columns
    for col in ['Payer', 'Amount', 'Involved']:
        if col not in df.columns:
            print(f"Error: CSV must contain '{col}' column.")
            return

    # Dictionary to track each person's net balance
    balances = defaultdict(float)

    # List of all people involved
    people = set()
    for _, row in df.iterrows():
        if not pd.isna(row['Involved']):
            involved = str(row['Involved']).split(", ")
            people.update(involved)
        if not pd.isna(row['Payer']):
            people.add(row['Payer'])
    
    # if "Cash" is in the list of people, remove it
    if "Cash" in people:
        people.remove("Cash")
    
    # make the set of people a list
    people = list(people)

    # Process each transaction
    for _, row in df.iterrows():
        # payer might be cash in which case, everyone contributed
        if str(row['Payer']).lower() == 'cash':
            payer = people
        else:
            payer = [row['Payer']]
        
        if pd.isna(row['Involved']):
            involved = people
        else:
            involved = str(row['Involved']).split(", ")

        amount = float(row['Amount'])

        # Calculate the amount each person owes
        split_used = amount / len(involved)
        # these people are the ones who received the money, including the payer
        for person in involved:
            balances[person] -= split_used
        
        split_paid = amount / len(payer)
        # these people are the ones who paid the money
        for person in payer:
            balances[person] += split_paid

    # Display net balances
    print("\nNet Balances (positive = overpaid, negative = underpaid):")
    for person, balance in balances.items():
        # format the spacing in the print statement
        print(f"{person:<15}: $ {balance:.2f}")

    # Check if all balances are zero
    total_balance = sum(balances.values())
    print(f"\nTotal balance: ${total_balance:.2f}. This should be zero if all transactions are balanced.")

    # TODO: Use a csv for people covering others debts
    # transfer all of 'Suruthy''s money to 'Arabi'
    if 'Suruthy' in balances and 'Arabi' in balances:
        balances['Arabi'] += balances['Suruthy']
        balances['Suruthy'] = 0
        print(f"\nTransferring all of Suruthy's money to Arabi. New balances:")
        for person, balance in balances.items():
            print(f"{person:<15}: $ {balance:.2f}")

    # Print a settlement plan
    print_settlement_plan(balances)
    

def print_settlement_plan(balances: dict):
    """
    Prints a settlement plan based on the balances.
    This function is a placeholder and can be expanded to create a more detailed plan.
    """
    
    # Settle debts using a greedy algorithm
    creditors = {person: balance for person, balance in balances.items() if balance > 0}
    debtors = {person: -balance for person, balance in balances.items() if balance < 0}
    settlements = []

    # use while loop to settle debts
    while creditors and debtors:
        # Find the first creditor and debtor
        creditor = next(iter(creditors))
        debtor = next(iter(debtors))

        # If the creditor has no balance, remove them from the list
        if creditors[creditor] == 0:
            del creditors[creditor]
            continue

        # If the debtor has no balance, remove them from the list
        if debtors[debtor] == 0:
            del debtors[debtor]
            continue

        # Calculate settlement amount
        settlement_amount = min(creditors[creditor], debtors[debtor])
        settlements.append((debtor, creditor, settlement_amount))

        # Update balances
        creditors[creditor] -= settlement_amount
        debtors[debtor] -= settlement_amount

    print("\nSettlement Plan:")
    for debtor, creditor, amount in settlements:
        print(f"{debtor} pays {creditor} ${amount:.2f}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python splitwise.py path/to/expenses.csv")
    else:
        calculate_settlements(sys.argv[1])
