import json
import os
import re # Import the re module
from datetime import datetime
# Import necessary models for type hinting or if utilities need to interact with them
# In a larger app, utilities might just process data passed to them.
# For calculate_balances, we need access to the model structure.
from database import Trip, Participant, Expense, TripParticipantDefaultProportion
import pdfplumber # Import pdfplumber
from flask import flash # Import flash for displaying messages


# Function to calculate balances
def calculate_balances(trip: Trip):
    """Calculates who owes whom for a given trip using SQLAlchemy objects and weights."""
    participants = trip.participants
    expenses = trip.expenses

    # Initialize balances for each participant
    balances = {participant.name: 0 for participant in participants}
    participant_id_to_name = {p.id: p.name for p in participants}

    # Calculate net amount paid/owed based on weights
    for expense in expenses:
        paid_by_name = expense.payer.name
        amount = expense.amount
        # Load weights from JSON string
        weights = json.loads(expense.proportions) if expense.proportions else {}

        # Calculate total weight for this expense
        total_weight = sum(weights.values())

        balances[paid_by_name] += amount # Person who paid gets the full amount added initially

        if total_weight > 0:
            # Calculate owed amount for each participant based on their weight
            for participant_id_str, weight in weights.items():
                # Ensure participant_id_str is a valid integer and corresponds to a participant in the trip
                try:
                    participant_id = int(participant_id_str)
                    if participant_id in participant_id_to_name:
                        # Calculate owed amount based on the participant's weight relative to the total weight
                        owed_amount = (amount * weight) / total_weight
                        balances[participant_id_to_name[participant_id]] -= owed_amount
                    # else:
                        # print(f"Warning: Participant with ID {participant_id} from expense {expense.id} not found in trip {trip.id}. Skipping proportion.")
                except ValueError:
                    print(f"Warning: Invalid participant ID string '{participant_id_str}' in expense {expense.id} proportions. Skipping.")


        elif len(participants) > 0:
             # If no weights are specified or total weight is 0, split equally among all participants in the trip
             # This might happen for older expenses or if the PDF didn't provide split info
             equal_share = amount / len(participants)
             for participant in participants:
                  balances[participant.name] -= equal_share


    # Simplify debts
    creditors = {p: b for p, b in balances.items() if b > 0}
    debtors = {p: b for p, b in balances.items() if b < 0}
    transactions = []

    # Sort creditors and debtors to ensure consistent transaction ordering (optional but good practice)
    creditor_list = sorted(creditors.items(), key=lambda item: item[1], reverse=True)
    debtor_list = sorted(debtors.items(), key=lambda item: item[1])


    c_idx = 0
    d_idx = 0

    while c_idx < len(creditor_list) and d_idx < len(debtor_list):
        creditor, c_balance = creditor_list[c_idx]
        debtor, d_balance = debtor_list[d_idx]

        # Amount to transfer is the minimum of the absolute balances
        transfer_amount = min(c_balance, abs(d_balance))

        # Only add transaction if amount is significant to avoid tiny transfers
        if round(transfer_amount, 2) > 0:
            transactions.append({
                'from': debtor,
                'to': creditor,
                'amount': round(transfer_amount, 2)
            })

        # Update balances (in the local list of tuples)
        creditor_list[c_idx] = (creditor, c_balance - transfer_amount)
        debtor_list[d_idx] = (debtor, d_balance + transfer_amount)

        # Move to the next creditor or debtor if their balance is settled (within a small tolerance)
        if round(creditor_list[c_idx][1], 2) <= 0:
            c_idx += 1
        if round(debtor_list[d_idx][1], 2) >= 0:
            d_idx += 1

    return balances, transactions

# Improved PDF processing function based on user provided code
def process_pdf_report(pdf_file):
    """
    Processes a PDF report to extract expense data based on a specific regex pattern.

    Args:
        pdf_file: A file-like object representing the uploaded PDF.

    Returns:
        A list of dictionaries, where each dictionary represents an expense.
        Example format:
        [{
            'description': 'Restaurant Bill',
            'amount': 75.50,
            'paid_by_name': 'Unknown', # Placeholder if not extracted
            'expense_date': 'YYYY-MM-DD', # Formatted date string
        }]
    """
    expenses = []

    try:
        # Ensure the file pointer is at the beginning
        pdf_file.seek(0)
        # Use pdfplumber to open the file object
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                # Extract text from each page
                page_text = page.extract_text()
                if not page_text:
                    continue # Skip empty pages

                # Split text into lines for easier processing
                lines = page_text.split("\n")

                # Define the regex pattern based on the provided structure
                # This pattern looks for:
                # - purchase_day (2 digits)
                # - space
                # - purchase_month (2 digits)
                # - space
                # - processed_day (2 digits)
                # - space
                # - processed_month (2 digits)
                # - space
                # - description (any characters, non-greedily, until the next pattern)
                # - one or more spaces
                # - interest_rate (digits, comma, 2 digits, optional space, %)
                # - one or more spaces
                # - amount (digits, comma, 2 digits)
                # Note: This regex is specific to the provided format.
                # If your PDF format varies, this regex will need adjustment.
                pattern = re.compile(
                    r'(?P<purchase_day>\d{2})\s'
                    r'(?P<purchase_month>\d{2})\s'
                    r'(?P<processed_day>\d{2})\s'
                    r'(?P<processed_month>\d{2})\s'
                    r'(?P<description>.+?)\s+' # Added + for one or more spaces
                    r'(?P<interest_rate>\d+,\d{2})\s*%\s+' # Added + for one or more spaces
                    r'(?P<amount>\d+,\d{2})'
                )

                for line in lines:
                    # Search the line for the pattern
                    match = pattern.search(line)

                    # If a match is found, extract the named groups
                    if match:
                        purchase_data = match.groupdict()

                        # Convert amount from string with comma to float with dot
                        try:
                            amount = float(purchase_data['amount'].replace(',', '.'))
                        except ValueError:
                            print(f"Could not convert amount to float: {purchase_data['amount']}")
                            flash(f"Warning: Could not convert amount '{purchase_data['amount']}' to a number for an expense. Skipping this entry.", 'warning')
                            continue # Skip this expense if amount is invalid

                        # Construct the expense date (assuming current year)
                        # Note: This assumes the year is the current year.
                        # If your reports span multiple years, you'll need a way to determine the correct year.
                        try:
                            # Use a placeholder year (e.g., 2000) to create a valid date object first,
                            # then replace the year with the current year. This helps handle cases
                            # where the report date might cross a year boundary relative to the current date.
                            # A more robust approach would be to try and extract the year from the PDF.
                            # Ensure month and day are valid
                            month = int(purchase_data['purchase_month'])
                            day = int(purchase_data['purchase_day'])
                            current_year = datetime.now().year
                            # Check for valid month and day (basic check)
                            if 1 <= month <= 12 and 1 <= day <= 31:
                                # Attempt to create a date object to validate day/month combination
                                datetime(current_year, month, day)
                                expense_date = f"{current_year}-{purchase_data['purchase_month']}-{purchase_data['purchase_day']}"
                            else:
                                raise ValueError("Invalid month or day") # Raise error for invalid date parts

                        except ValueError:
                            print(f"Could not parse date: {purchase_data['purchase_month']}-{purchase_data['purchase_day']}")
                            flash(f"Warning: Could not parse date '{purchase_data['purchase_month']}-{purchase_data['purchase_day']}' for an expense. Please verify on the validation page.", 'warning')
                            expense_date = None # Set date to None if parsing fails


                        # Append the extracted expense data
                        # Note: paid_by_name is not extracted by the current regex.
                        # You will need to manually select the payer on the validation page.
                        # If your PDF contains payer information, update the regex to capture it.
                        expenses.append({
                            'description': purchase_data['description'].strip(), # Strip whitespace
                            'amount': amount,
                            'paid_by_name': 'Unknown', # Placeholder - update if you can extract this
                            'expense_date': expense_date, # YYYY-MM-DD string or None
                        })

    except pdfplumber.PDFSyntaxError as e:
        print(f"PDF Syntax Error: {e}")
        flash(f"Error reading PDF file: {e}", 'danger')
        return [] # Return empty list if PDF has syntax errors
    except re.error as e:
        print(f"Regex Error: {e}")
        flash(f"Error processing PDF content (regex issue): {e}", 'danger')
        return [] # Return empty list if regex fails
    except Exception as e:
        # Catch any other unexpected errors
        print(f"An unexpected error occurred during PDF processing: {e}")
        flash(f"An unexpected error occurred during PDF processing: {e}", 'danger')
        return [] # Return empty list for other errors


    return expenses
