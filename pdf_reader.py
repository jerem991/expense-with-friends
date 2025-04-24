import io
import re
import pdfplumber # Import pdfplumber
from dateutil.parser import parse as parse_date_string
from dateutil.parser import ParserError
from datetime import datetime

def clean_amount_string(amount_str):
    """
    Cleans an amount string by removing currency symbols,
    thousands separators (commas or periods depending on assumed format),
    and converting the decimal separator to a period.

    This is a heuristic and might fail on complex international formats.
    Assumes common formats like 1,234.56 or 1.234,56 or 123.45
    """
    if not amount_str:
        return None

    # Remove common currency symbols and whitespace
    cleaned = re.sub(r'[$\€\£¥₹]', '', amount_str).strip()

    # Attempt to handle decimal/thousands separators
    # Simple approach: remove commas, assume period is decimal
    cleaned = cleaned.replace(',', '')

    try:
        return float(cleaned)
    except ValueError:
        # If direct conversion fails, try to guess format
        # E.g., handle cases like 1.234,56 (European format)
        if ',' in amount_str and '.' in amount_str:
            # If both are present, assume comma is decimal, period is thousands separator
            cleaned = amount_str.replace('.', '').replace(',', '.')
            try:
                return float(cleaned)
            except ValueError:
                return None
        elif ',' in amount_str:
             # If only comma, assume it's the decimal separator
             cleaned = amount_str.replace(',', '.')
             try:
                 return float(cleaned)
             except ValueError:
                return None # Failed to parse even after guessing format

        return None # Still failed


def parse_expense_date_string(date_str):
    """
    Parses a date string using dateutil, which is flexible.
    Returns date in 'YYYY-MM-DD' format or None if parsing fails.
    """
    if not date_str:
        return None
    try:
        # dateutil.parser.parse is good at guessing formats
        date_obj = parse_date_string(date_str)
        return date_obj.strftime('%Y-%m-%d')
    except (ParserError, ValueError):
        return None # Could not parse date


def guess_expenses_from_pdf_plumber(pdf_file):
    """
    Attempts to guess expense details from the text content of a PDF
    using pdfplumber for extraction.

    This function is heuristic and relies on finding common patterns
    for amounts and dates in the text lines.

    Args:
        pdf_file: A file-like object representing the uploaded PDF
                  (e.g., from Flask's request.files['file']).
                  Must be opened in binary mode ('rb').

    Returns:
        A list of dictionaries, where each dictionary is a potential expense.
        Example format:
        [{
            'description': 'Guessed Description Text',
            'amount': 123.45,
            'expense_date': 'YYYY-MM-DD'
        }, ...]
        Returns an empty list if no potential expenses are found or parsing fails.
    """
    potential_expenses = []
    full_text = ""

    try:
        # Ensure the file pointer is at the beginning
        pdf_file.seek(0)
        # Use pdfplumber to open the file object
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                # Extract text from each page
                page_text = page.extract_text()
                if page_text:
                    # Add text, separating pages with a couple of newlines
                    full_text += page_text + "\n\n"

    except pdfplumber.PDFSyntaxError as e:
         print(f"PDF Syntax Error: {e}")
         return []
    except Exception as e:
        print(f"Error extracting text from PDF using pdfplumber: {e}")
        return [] # Return empty list if text extraction fails

    if not full_text.strip():
        print("No text extracted from PDF.")
        return []

    # --- Heuristic Guessing Logic (Same as before, applied to extracted text) ---

    # Split text into lines
    lines = full_text.splitlines()

    # Regex patterns (can be refined)
    # Amount pattern: Looks for numbers potentially with thousands separators (,. or .,) and two decimal places
    # Also captures numbers with just two decimal places
    # Added currency symbols for better hint, made them optional
    amount_pattern = re.compile(r'(?:\$|\€|\£|¥)?\s*(\d{1,3}(?:[,\.]\d{3})*[\.,]\d{2}|\d+[\.,]\d{2})\b')
    # Date pattern: Looks for common date formats (MM/DD/YYYY, YYYY-MM-DD, DD-Mon-YYYY, etc.)
    # This is just a rough guide; dateutil.parser is more robust but needs a plausible string
    # Look for sequences that look like dates (numbers and separators)
    date_pattern = re.compile(r'\b(\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4})\b') # e.g., 10/26/2023, 2023-10-26, 26.10.23

    # Keep track of the last found date, as items might not have a date on every line
    last_known_date = None

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # Find potential amounts in the line
        amount_matches = list(amount_pattern.finditer(line))

        # Find potential dates in the line
        date_match = date_pattern.search(line)

        current_item_date_str = None

        # Try to find a date for this potential expense item
        if date_match:
            current_item_date_str = date_match.group(1)
            last_known_date = current_item_date_str # Update last known date

        # If no date found on the current line, use the last known date
        elif last_known_date:
             current_item_date_str = last_known_date


        # Process found amounts on this line
        for amount_match in amount_matches:
            raw_amount_str = amount_match.group(0) # Get the full matched string
            cleaned_amount = clean_amount_string(raw_amount_str)

            if cleaned_amount is None:
                 continue # Skip if amount cleaning/parsing failed

            # Now try to determine the description and date for this specific amount
            # This is the most heuristic part.

            # Try to find a date near this amount if not already found on the line
            expense_date_str = current_item_date_str # Start with the best date found so far for the line/context
            description = line.strip() # Default description is the whole line

            # Refined description logic: remove the found amount string from the line
            # And if a date was found on this line, remove that too.
            description = description.replace(raw_amount_str, '').strip()
            if date_match:
                # Remove the date string from the description if it was on the same line
                description = description.replace(date_match.group(0), '').strip()

            # Simple check to filter out lines that are likely just summaries or noise
            # (e.g., line is just an amount, or contains keywords like "Total")
            if len(description) < 3 and len(amount_matches) == 1:
                # If description is very short and only one amount on the line,
                # maybe look at the previous line for description
                if i > 0:
                     prev_line = lines[i-1].strip()
                     # Avoid using previous line if it also looks like an amount/date line
                     if not (amount_pattern.search(prev_line) or date_pattern.search(prev_line)):
                          description = prev_line

            # If description is still empty or just punctuation after cleaning
            if not description or re.fullmatch(r'[.,;:\-–—()\[\]{}"]+', description):
                 # Fallback: Use a generic description
                 description = f"Expense Item (guessed from line {i+1})" # Placeholder


            # Ensure we have a date before adding
            parsed_date = parse_expense_date_string(expense_date_str)

            if parsed_date and cleaned_amount is not None:
                potential_expenses.append({
                    'description': description,
                    'amount': cleaned_amount,
                    'expense_date': parsed_date
                })
                # Optional: Add break here if you assume only one expense per line
                # break

    return potential_expenses

# --- Example Usage (requires a dummy PDF file) ---
# The example usage remains the same as it just provides a file object

if __name__ == '__main__':
    # Create a dummy PDF file for testing purposes
    # This requires the 'reportlab' library: pip install reportlab
    try:
        # Simulate opening the file like an upload
        with open("./report/mars-2025-1.pdf", 'rb') as f:
            # Add a dummy filename attribute to the file object for the print statement in the function
            # (Though the new function doesn't use file.filename directly, it's good practice if needed)
            guessed_expenses = guess_expenses_from_pdf_plumber(f) # Use the new function

        print("\n--- Guessed Expenses (using pdfplumber) ---")
        if guessed_expenses:
            for i, exp in enumerate(guessed_expenses):
                print(f"Expense {i+1}:")
                print(f"  Description: {exp.get('description')}")
                print(f"  Amount: {exp.get('amount')}")
                print(f"  Date: {exp.get('expense_date')}")
                print("-" * 20)
        else:
            print("No expenses guessed from the PDF.")

    except ImportError:
        print("\nInstall 'reportlab' (pip install reportlab) to run the dummy PDF creation example.")
        print("You can still test the function by providing a file-like object to guess_expenses_from_pdf_plumber.")
    except Exception as e:
        print(f"\nAn error occurred during dummy PDF creation or processing: {e}")