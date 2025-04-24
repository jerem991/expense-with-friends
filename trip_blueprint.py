import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timedelta # Import timedelta for date calculations
# Import the new Category model
from database import SessionLocal, Trip, Participant, Expense, TripParticipantDefaultProportion, Category
from sqlalchemy.orm import joinedload
from sqlalchemy import desc # Import desc for descending order
from utils import calculate_balances, process_pdf_report # Import calculate_balances
from werkzeug.utils import secure_filename # Import secure_filename
from itertools import groupby # Import groupby for grouping expenses
from sqlalchemy import func # Import func for database functions like lower
from sqlalchemy import and_ # Import and_ for combining filter conditions

# Define the blueprint
# The url_prefix means all routes in this blueprint will start with /trip
trip_blueprint = Blueprint('trip_blueprint', __name__, url_prefix='/trip')

# Helper to get a database session (can be imported or defined locally)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@trip_blueprint.route('/<int:trip_id>')
def view_trip(trip_id):
    """
    Displays the details of a specific trip, including balances,
    with optional search, date range filtering for stats, and expenses grouped by month.
    """
    db = next(get_db())

    # Get search query from request arguments
    search_query = request.args.get('search')

    # Get date range filter from request arguments
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # Convert date strings to datetime objects if they exist
    start_date = None
    end_date = None
    if start_date_str:
        try:
            # Set time to start of the day for inclusive filtering
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            flash("Invalid start date format. Please use YYYY-MM-DD.", 'danger')
            start_date_str = None # Clear invalid date

    if end_date_str:
        try:
            # Set time to end of the day for inclusive filtering
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        except ValueError:
            flash("Invalid end date format. Please use YYYY-MM-DD.", 'danger')
            end_date_str = None # Clear invalid date


    # Base query to fetch the trip with related data
    # Eager load participants, expenses (with payer and category), and default proportions
    query = db.query(Trip).options(
        joinedload(Trip.participants),
        # Eager load expenses and their payer and category
        joinedload(Trip.expenses.and_(True)).joinedload(Expense.payer),
        joinedload(Trip.expenses.and_(True)).joinedload(Expense.category),
        joinedload(Trip.participant_default_proportions).joinedload(TripParticipantDefaultProportion.participant)
    ).filter(Trip.id == trip_id)

    trip = query.first()

    if not trip:
        return "Trip not found", 404

    # Get all expenses for grouping and total calculation (regardless of date filter for chart)
    all_expenses = sorted(trip.expenses, key=lambda x: x.expense_date, reverse=True)


    # Filter expenses by description if a search query is provided
    if search_query:
        filtered_expenses = [
            expense for expense in all_expenses
            if search_query.lower() in expense.description.lower()
        ]
    else:
        filtered_expenses = all_expenses


    # Group filtered expenses by month and year for the table display
    grouped_expenses = {}
    # Use sorted(filtered_expenses, key=lambda x: x.expense_date, reverse=True) to ensure correct grouping order
    for month_year, expenses_in_month in groupby(sorted(filtered_expenses, key=lambda x: x.expense_date, reverse=True), key=lambda x: x.expense_date.strftime('%B %Y')):
        # Convert groupby object to a list and sort by date_added descending within the month
        grouped_expenses[month_year] = sorted(list(expenses_in_month), key=lambda x: x.date_added, reverse=True)


    total_expenses = sum(expense.amount for expense in filtered_expenses) # Calculate total based on filtered expenses for the table header

    # --- Calculate Category Expenses for the Chart (based on date filter) ---
    category_expenses = {}
    # Filter expenses by date range for category calculation
    date_filtered_expenses_for_chart = all_expenses # Start with all expenses for the chart calculation

    if start_date:
        date_filtered_expenses_for_chart = [
            expense for expense in date_filtered_expenses_for_chart
            if expense.expense_date >= start_date
        ]
    if end_date:
         # Use the end_date (which is end-of-day inclusive) for filtering
         date_filtered_expenses_for_chart = [
             expense for expense in date_filtered_expenses_for_chart
             if expense.expense_date <= end_date # Use <= with the end-of-day inclusive date
         ]


    for expense in date_filtered_expenses_for_chart:
        category_name = expense.category.name if expense.category else 'Uncategorized'
        if category_name in category_expenses:
            category_expenses[category_name] += expense.amount
        else:
            category_expenses[category_name] = expense.amount

    # Convert category_expenses dictionary to a list of dictionaries for easier JavaScript processing
    category_expenses_list = [{"category": cat, "amount": amount} for cat, amount in category_expenses.items()]
    # Sort category_expenses_list by amount descending for the chart legend
    category_expenses_list.sort(key=lambda x: x['amount'], reverse=True)


    # Load weights from JSON string for display (reusing proportions_dict name)
    # This still needs to be done for each expense object before passing to template
    for month_year, expenses_list in grouped_expenses.items():
        for expense in expenses_list:
             expense.proportions_dict = json.loads(expense.proportions) if expense.proportions else {}


    # Build a dictionary of default weights for easier access in the template
    default_proportions_dict = {
        str(dp.participant_id): dp.default_proportion # Renamed conceptually to weights
        for dp in trip.participant_default_proportions
    }

    # Calculate balances and transactions based on all expenses (not filtered ones)
    # Balances should reflect the overall trip, not just the currently filtered view
    balances, transactions = calculate_balances(trip)

    # Fetch all categories to display in the template
    categories = db.query(Category).order_by(Category.name).all()


    return render_template(
        'view_trip.html',
        trip_id=trip.id,
        trip=trip,
        total_expenses=total_expenses, # Total for the expenses shown in the table (filtered by search)
        default_proportions=default_proportions_dict, # Passing default weights
        balances=balances, # Pass balances to the template
        transactions=transactions, # Pass transactions to the template
        search_query=search_query, # Pass the search query back to the template
        grouped_expenses=grouped_expenses, # Pass the grouped expenses to the template
        categories=categories, # Pass categories to the template
        category_expenses_list=category_expenses_list, # Pass category expense data for the chart
        start_date=start_date_str, # Pass start date back to template to pre-fill form
        end_date=end_date_str # Pass end date back to template to pre-fill form
    )

@trip_blueprint.route('/<int:trip_id>/add_participant', methods=['GET', 'POST'])
def add_participant(trip_id):
    """Handles adding a participant to a trip."""
    db = next(get_db())
    trip = db.query(Trip).get(trip_id)
    if not trip:
        return "Trip not found", 404

    if request.method == 'POST':
        participant_name = request.form['participant_name']
        avatar_emoji = request.form.get('avatar_emoji')

        existing_participant = db.query(Participant).filter_by(trip_id=trip_id, name=participant_name).first()
        if participant_name and not existing_participant:
            new_participant = Participant(name=participant_name, trip_id=trip_id, avatar_url=avatar_emoji)
            db.add(new_participant)
            db.commit()
            flash(f"Participant '{participant_name}' added successfully!", 'success')

            # When a new participant is added, create a default weight entry for them in this trip (defaulting to 1)
            new_default_proportion = TripParticipantDefaultProportion(
                trip_id=trip_id,
                participant_id=new_participant.id,
                default_proportion=1.0 # Default weight is 1
            )
            db.add(new_default_proportion)
            db.commit()


        elif existing_participant:
             flash(f"Participant '{participant_name}' already exists in this trip.", 'warning')
        else:
             flash("Participant name cannot be empty.", 'danger')

        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

    # Use blueprint name in url_for
    return render_template('add_participant.html', trip_id=trip_id, trip=trip)

@trip_blueprint.route('/<int:trip_id>/edit_participant/<int:participant_id>', methods=['GET', 'POST'])
def edit_participant(trip_id, participant_id):
    """Handles editing a participant's details."""
    db = next(get_db())
    trip = db.query(Trip).get(trip_id) # Get the trip to pass to the template
    if not trip:
        return "Trip not found", 404

    participant = db.query(Participant).filter_by(id=participant_id, trip_id=trip_id).first()
    if not participant:
        return "Participant not found", 404

    if request.method == 'POST':
        new_name = request.form['participant_name']
        new_avatar_emoji = request.form.get('avatar_emoji')

        # Check if the new name already exists for another participant in this trip
        existing_participant_with_name = db.query(Participant).filter(
            Participant.trip_id == trip_id,
            Participant.name == new_name,
            Participant.id != participant_id
        ).first()

        if new_name and not existing_participant_with_name:
            participant.name = new_name
            participant.avatar_url = new_avatar_emoji # Update avatar_url with the new emoji
            db.commit()
            flash(f"Participant '{participant.name}' updated successfully!", 'success')
            # Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))
        elif existing_participant_with_name:
             flash(f"Participant with name '{new_name}' already exists in this trip.", 'warning')
        else:
             flash("Participant name cannot be empty.", 'danger')

        # If there was an error, re-render the edit page with the current participant data and flash message
        return render_template('edit_participant.html', trip_id=trip_id, trip=trip, participant=participant)


    return render_template('edit_participant.html', trip_id=trip_id, trip=trip, participant=participant)


@trip_blueprint.route('/<int:trip_id>/add_expense', methods=['GET', 'POST'])
def add_expense(trip_id):
    """Handles adding an expense to a trip with weights and category."""
    db = next(get_db())
    # Eager load participants and their default weights for this trip
    trip = db.query(Trip).options(
        joinedload(Trip.participants),
        joinedload(Trip.participant_default_proportions).joinedload(TripParticipantDefaultProportion.participant)
    ).get(trip_id)
    if not trip:
        return "Trip not found", 404

    # Fetch all categories
    categories = db.query(Category).order_by(Category.name).all()

    # Build a dictionary of default weights for easier access in the template
    default_proportions_dict = {
        str(dp.participant_id): dp.default_proportion # Renamed conceptually to weights
        for dp in trip.participant_default_proportions
    }


    if request.method == 'POST':
        description = request.form['description']
        amount = float(request.form['amount'])
        paid_by_id = request.form['paid_by']
        expense_date_str = request.form['expense_date']
        category_id = request.form.get('category_id') # Get category_id (can be None)

        # Get weights from form
        weights = {}
        total_submitted_weight = 0
        for participant in trip.participants:
            weight_key = f'proportion_{participant.id}' # Reusing the name, but it's now weight
            if weight_key in request.form:
                try:
                    weight_value = float(request.form[weight_key])
                    if weight_value < 0:
                         flash(f"Weight for {participant.name} cannot be negative. Please enter a non-negative number.", 'danger')
                         # Use blueprint name in url_for
                         return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id)) # Redirect back with error
                    weights[str(participant.id)] = weight_value # Store participant ID as string key
                    total_submitted_weight += weight_value
                except ValueError:
                    flash(f"Invalid weight value for {participant.name}. Please enter numbers only.", 'danger')
                    # Use blueprint name in url_for
                    return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id)) # Redirect back with error

        # Validation for weights: total weight can be 0, but not if there are participants
        if total_submitted_weight == 0 and len(trip.participants) > 0:
             flash("Total weight cannot be zero if there are participants. Please specify how the expense is split.", 'danger')
             # Use blueprint name in url_for
             return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id))


        # Find the participant who paid
        payer = db.query(Participant).filter_by(trip_id=trip_id, id=paid_by_id).first()
        if not payer:
            flash("Invalid payer selected.", 'danger')
            # Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id))

        try:
            expense_date = datetime.strptime(expense_date_str, '%Y-%m-%d')
        except ValueError:
            flash("Invalid date format.", 'danger')
            # Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id))

        # Validate category_id if provided
        category = None
        if category_id:
            category = db.query(Category).get(category_id)
            if not category:
                flash("Invalid category selected.", 'danger')
                return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id))


        if description and amount > 0 and payer and weights:
            new_expense = Expense(
                description=description,
                amount=amount,
                expense_date=expense_date,
                trip_id=trip_id,
                paid_by_id=payer.id,
                proportions=json.dumps(weights), # Store weights as JSON string
                category_id=category.id if category else None # Store category_id
            )
            db.add(new_expense)
            db.commit()
            flash("Expense added successfully!", 'success')
            # Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))
        else:
             flash("Please fill in all required fields.", 'danger')
             # Use blueprint name in url_for
             return redirect(url_for('trip_blueprint.add_expense', trip_id=trip_id))


    return render_template('add_expense.html', trip_id=trip_id, trip=trip, default_proportions=default_proportions_dict, categories=categories) # Passing categories

@trip_blueprint.route('/<int:trip_id>/edit_expense/<int:expense_id>', methods=['GET', 'POST'])
def edit_expense(trip_id, expense_id):
    """Handles editing an existing expense with weights and category."""
    db = next(get_db())
    trip = db.query(Trip).options(joinedload(Trip.participants)).get(trip_id)
    if not trip:
        return "Trip not found", 404

    expense_to_edit = db.query(Expense).options(joinedload(Expense.payer)).filter_by(id=expense_id, trip_id=trip_id).first()
    if not expense_to_edit:
        return "Expense not found", 404

    # Fetch all categories
    categories = db.query(Category).order_by(Category.name).all()

    if request.method == 'POST':
        # Update expense details from form
        expense_to_edit.description = request.form['description']
        expense_to_edit.amount = float(request.form['amount'])
        paid_by_id = request.form['paid_by']
        expense_date_str = request.form['expense_date']
        category_id = request.form.get('category_id') # Get category_id (can be None)


        # Get updated weights from form
        updated_weights = {}
        total_submitted_weight = 0
        for participant in trip.participants:
            weight_key = f'proportion_{participant.id}' # Reusing the name, but it's now weight
            if weight_key in request.form:
                try:
                    weight_value = float(request.form[weight_key])
                    if weight_value < 0:
                         flash(f"Weight for {participant.name} cannot be negative. Please enter a non-negative number.", 'danger')
                         # Use blueprint name in url_for
                         return redirect(url_for('trip_blueprint.edit_expense', trip_id=trip_id, expense_id=expense_id)) # Redirect back with error
                    updated_weights[str(participant.id)] = weight_value # Store participant ID as string key
                    total_submitted_weight += weight_value
                except ValueError:
                    flash(f"Invalid weight value for {participant.name}. Please enter numbers only.", 'danger')
                    # Use blueprint name in url_for
                    return redirect(url_for('trip_blueprint.edit_expense', trip_id=trip_id, expense_id=expense_id)) # Redirect back with error

        # Validation for weights: total weight can be 0, but not if there are participants
        if total_submitted_weight == 0 and len(trip.participants) > 0:
             flash("Total weight cannot be zero if there are participants. Please specify how the expense is split.", 'danger')
             # Use blueprint name in url_for
             return redirect(url_for('trip_blueprint.edit_expense', trip_id=trip_id, expense_id=expense_id))


        # Find the updated payer
        new_payer = db.query(Participant).filter_by(trip_id=trip_id, id=paid_by_id).first()
        if new_payer:
            expense_to_edit.payer = new_payer
        else:
             flash("Invalid payer selected.", 'danger')
             # Use blueprint name in url_for
             return redirect(url_for('trip_blueprint.edit_expense', trip_id=trip_id, expense_id=expense_id))


        try:
            expense_to_edit.expense_date = datetime.strptime(expense_date_str, '%Y-%m-%d')
        except ValueError:
            flash("Invalid date format.", 'danger')
            # Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.edit_expense', trip_id=trip_id, expense_id=expense_id))

        # Validate and set category_id
        if category_id:
            category = db.query(Category).get(category_id)
            if category:
                expense_to_edit.category = category # Set the category relationship
            else:
                flash("Invalid category selected.", 'danger')
                return redirect(url_for('trip_blueprint.edit_expense', trip_id=trip_id, expense_id=expense_id))
        else:
            expense_to_edit.category = None # Set category to None if no category is selected


        expense_to_edit.proportions = json.dumps(updated_weights) # Update weights
        expense_to_edit.last_modified = datetime.utcnow() # Update last modified timestamp

        db.commit()
        flash("Expense updated successfully!", 'success')
        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

    # For GET request, render the edit form
    # Load weights from JSON string for display in the form (reusing proportions_dict name)
    expense_to_edit.proportions_dict = json.loads(expense_to_edit.proportions) if expense_to_edit.proportions else {}

    return render_template('edit_expense.html', trip_id=trip_id, trip=trip, expense=expense_to_edit, categories=categories) # Passing categories


@trip_blueprint.route('/<int:trip_id>/set_default_proportions', methods=['POST'])
def set_default_proportions(trip_id):
    """Handles setting the default weights for a trip."""
    db = next(get_db())
    trip = db.query(Trip).options(joinedload(Trip.participants)).get(trip_id)
    if not trip:
        return "Trip not found", 404

    # Remove existing default weights for this trip
    db.query(TripParticipantDefaultProportion).filter_by(trip_id=trip_id).delete()

    default_weights = {}
    total_submitted_weight = 0
    for participant in trip.participants:
        weight_key = f'default_proportion_{participant.id}' # Reusing the name, but it's now weight
        if weight_key in request.form:
            try:
                weight_value = float(request.form[weight_key])
                if weight_value < 0:
                     flash(f"Default weight for {participant.name} cannot be negative. Please enter a non-negative number.", 'danger')
                     db.rollback() # Rollback changes if there's an error
                     # Use blueprint name in url_for
                     return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id)) # Redirect back with error
                default_weights[str(participant.id)] = weight_value # Store participant ID as string key
                total_submitted_weight += weight_value

                # Create and add the new default weight entry
                if weight_value >= 0: # Save non-negative weights
                    new_default_proportion = TripParticipantDefaultProportion( # Reusing the model name
                        trip_id=trip_id,
                        participant_id=participant.id,
                        default_proportion=weight_value # Storing weight here
                    )
                    db.add(new_default_proportion)

            except ValueError:
                flash(f"Invalid default weight value for {participant.name}. Please enter numbers only.", 'danger')
                db.rollback() # Rollback changes if there's an error
                # Use blueprint name in url_for
                return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id)) # Redirect back with error


    # Validation for default weights: total weight can be 0, but not if there are participants
    if total_submitted_weight == 0 and len(trip.participants) > 0:
        flash("Total default weight cannot be zero if there are participants. Please specify how the expense is split.", 'danger')
        db.rollback() # Rollback changes if there's an error
        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))


    db.commit() # Commit all changes (deletions and additions)
    flash("Default weights updated successfully!", 'success')

    # Use blueprint name in url_for
    return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

@trip_blueprint.route('/<int:trip_id>/upload_pdf', methods=['POST'])
def upload_pdf(trip_id):
    """Handles uploading and processing a PDF report."""
    db = next(get_db())
    trip = db.query(Trip).options(joinedload(Trip.participants)).get(trip_id)
    if not trip:
        flash("Trip not found.", 'danger')
        return redirect(url_for('index')) # index is not in blueprint

    if 'pdf_file' not in request.files:
        flash("No file part in the request.", 'danger')
        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

    pdf_file = request.files['pdf_file']

    if pdf_file.filename == '':
        flash("No selected file.", 'danger')
        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

    if pdf_file:
        try:
            # Process the PDF (mockup function)
            extracted_expenses = process_pdf_report(pdf_file)

            if not extracted_expenses:
                flash("No expenses extracted from the PDF.", 'warning')
                # Use blueprint name in url_for
                return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

            # Attempt to guess categories for extracted expenses
            for expense_data in extracted_expenses:
                # Look for an existing expense with the same description (case-insensitive)
                # and a defined category. Order by date added descending to prefer more recent assignments.
                existing_expense_with_category = db.query(Expense).filter(
                    func.lower(Expense.description) == func.lower(expense_data['description']),
                    Expense.category_id.isnot(None)
                ).order_by(desc(Expense.date_added)).first()

                if existing_expense_with_category and existing_expense_with_category.category:
                    # Assign the found category ID to the extracted expense data
                    expense_data['category_id'] = existing_expense_with_category.category.id
                    # Store the category name for display on the validation page
                    expense_data['category_name'] = existing_expense_with_category.category.name
                else:
                    # If no matching expense with category is found, set category_id to None
                    expense_data['category_id'] = None
                    expense_data['category_name'] = 'Uncategorized' # Placeholder name for display


            # Store extracted expenses (now with potential category_id) in the session for validation
            session[f'extracted_expenses_{trip_id}'] = extracted_expenses
            flash(f"PDF processed. {len(extracted_expenses)} expenses extracted. Please validate and assign categories.", 'info')

            # Redirect to the validation page - Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.validate_expenses', trip_id=trip_id))

        except Exception as e:
            flash(f"Error processing PDF: {e}", 'danger')
            # Log the error for debugging
            # Ensure 'app' is accessible or log differently in a blueprint
            # print(f"Error processing PDF for trip {trip_id}: {e}")
            pass # Suppress logging for now if app is not available

        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

    flash("Error uploading file.", 'danger')
    # Use blueprint name in url_for
    return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

@trip_blueprint.route('/<int:trip_id>/validate_expenses', methods=['GET', 'POST'])
def validate_expenses(trip_id):
    """Allows users to validate and adjust extracted expenses before saving."""
    db = next(get_db())
    trip = db.query(Trip).options(
        joinedload(Trip.participants),
        joinedload(Trip.participant_default_proportions).joinedload(TripParticipantDefaultProportion.participant)
    ).get(trip_id)
    if not trip:
        return "Trip not found", 404

    # Fetch all categories to display in the dropdown
    categories = db.query(Category).order_by(Category.name).all()

    # Build a dictionary of default weights for easier access in the template
    default_proportions_dict = {
        str(dp.participant_id): dp.default_proportion # Renamed conceptually to weights
        for dp in trip.participant_default_proportions
    }

    session_key = f'extracted_expenses_{trip_id}'

    if request.method == 'POST':
        validated_expenses_data = []
        form_data = request.form
        extracted_expenses_from_session = session.get(session_key, [])

        # Get the single Paid By participant ID from the form
        paid_by_id_str = form_data.get('paid_by_all')

        # Validate the single paid_by_id
        payer = None
        if paid_by_id_str:
            try:
                payer_id = int(paid_by_id_str)
                # Verify if payer_id exists in trip participants
                payer = db.query(Participant).filter_by(id=payer_id, trip_id=trip_id).first()
                if not payer:
                    flash("Invalid Paid By participant selected for all expenses.", 'danger')
                    # Redirect back to validation page with error
                    return redirect(url_for('trip_blueprint.validate_expenses', trip_id=trip_id))
            except ValueError:
                flash("Invalid Paid By participant ID format.", 'danger')
                # Redirect back to validation page with error
                return redirect(url_for('trip_blueprint.validate_expenses', trip_id=trip_id))
        else:
            flash("Please select a 'Paid By' participant for all expenses.", 'danger')
            # Redirect back to validation page with error
            return redirect(url_for('trip_blueprint.validate_expenses', trip_id=trip_id))


        # Process form data from the validation page
        # Iterate based on the number of expenses originally extracted from session
        for i in range(len(extracted_expenses_from_session)):
            accept_key = f'accept_expense_{i}'
            if form_data.get(accept_key) == 'on': # Check if the expense was accepted (checkbox is 'on')
                # Retrieve original data from session using the index
                original_expense_data = extracted_expenses_from_session[i]
                description = original_expense_data.get('description')
                amount = float(form_data.get(f'amount_{i}')) # Get amount from form in case it was edited (though not currently editable)
                # Get the expense date string from the form
                expense_date_str = form_data.get(f'expense_date_{i}')
                # Get the category ID from the form for this expense
                category_id_str = form_data.get(f'category_{i}')


                # Get weights from the form for this specific expense
                weights = {}
                total_submitted_weight = 0
                weights_valid = True
                for participant in trip.participants:
                    # Use the correct form field name format: proportion_expenseIndex_participantId (reusing name)
                    weight_key = f'proportion_{i}_{participant.id}'
                    if weight_key in form_data:
                         try:
                             weight_value = float(form_data[weight_key]) # Still allow float input here for flexibility if needed later
                             if weight_value < 0:
                                  flash(f"Weight for {participant.name} on expense '{description}' cannot be negative. Please enter a non-negative number. This expense will be skipped.", 'danger')
                                  weights_valid = False # Mark weights as invalid
                                  break # Exit participant loop for this expense
                             weights[str(participant.id)] = weight_value
                             total_submitted_weight += weight_value
                         except ValueError:
                             flash(f"Invalid weight value for {participant.name} on expense '{description}'. Please enter numbers only. This expense will be skipped.", 'danger')
                             weights_valid = False # Mark weights as invalid
                             break # Exit participant loop for this expense

                if weights_valid: # Only process if weights were valid
                    # Validation for weights: total weight can be 0, but not if there are participants
                    if total_submitted_weight == 0 and len(trip.participants) > 0:
                         flash(f"Total weight for expense '{description}' cannot be zero if there are participants. Please specify how the expense is split. This expense will be skipped.", 'danger')
                         continue # Skip this expense

                    try:
                        # Parse the date string from the form
                        expense_date = datetime.strptime(expense_date_str, '%Y-%m-%d')
                    except ValueError:
                        flash(f"Invalid date format '{expense_date_str}' for expense '{description}'. Expected YYYY-MM-DD. This expense will be skipped.", 'warning')
                        continue # Skip this expense

                    # Validate and set category_id for this expense
                    expense_category_id = None
                    if category_id_str:
                         try:
                             expense_category_id = int(category_id_str)
                             # Optional: Verify if category_id exists
                             category = db.query(Category).get(expense_category_id)
                             if not category:
                                  flash(f"Invalid category selected for expense '{description}'. This expense will be saved without a category.", 'warning')
                                  expense_category_id = None # Set to None if category is invalid
                         except ValueError:
                              flash(f"Invalid category ID format for expense '{description}'. This expense will be saved without a category.", 'warning')
                              expense_category_id = None # Set to None if ID format is invalid


                    # Create the Expense object
                    new_expense = Expense(
                        description=description,
                        amount=amount,
                        expense_date=expense_date, # Use the date from the form
                        trip_id=trip_id,
                        paid_by_id=payer.id, # Use the single validated payer ID
                        proportions=json.dumps(weights), # Store weights here
                        category_id=expense_category_id, # Store category_id for this expense
                        date_added=datetime.utcnow(),
                        last_modified=datetime.utcnow()
                    )
                    db.add(new_expense)
                    validated_expenses_data.append(new_expense) # Add to a list for success message count


        db.commit()
        # Clear the extracted expenses from the session after saving
        if session_key in session:
            del session[session_key]

        flash(f"Successfully added {len(validated_expenses_data)} validated expenses to the trip.", 'success')
        # Use blueprint name in url_for
        return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))


    else: # GET request
        extracted_expenses = session.get(session_key, [])
        if not extracted_expenses:
            flash("No expenses found for validation. Please upload a PDF.", 'warning')
            # Use blueprint name in url_for
            return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

        # For GET request, prepare data for the template
        # We need to pass the extracted expenses, trip participants, and categories
        return render_template(
            'validate_expenses.html',
            trip_id=trip_id,
            trip=trip, # Pass the trip object to access participants
            extracted_expenses=extracted_expenses,
            default_proportions=default_proportions_dict, # Passing default weights
            categories=categories # Pass categories to the template
        )

# New route to handle deleting an expense
@trip_blueprint.route('/<int:trip_id>/delete_expense/<int:expense_id>', methods=['POST'])
def delete_expense(trip_id, expense_id):
    """Handles deleting a specific expense from a trip."""
    db = next(get_db())
    expense_to_delete = db.query(Expense).filter_by(id=expense_id, trip_id=trip_id).first()

    if expense_to_delete:
        db.delete(expense_to_delete)
        db.commit()
        flash("Expense deleted successfully!", 'success')
    else:
        flash("Expense not found.", 'danger')

    # Redirect back to the trip details page
    return redirect(url_for('trip_blueprint.view_trip', trip_id=trip_id))

# --- Category Management Routes ---

@trip_blueprint.route('/categories')
def list_categories():
    """Lists all available expense categories."""
    db = next(get_db())
    categories = db.query(Category).order_by(Category.name).all()
    return render_template('list_categories.html', categories=categories)

@trip_blueprint.route('/categories/add', methods=['GET', 'POST'])
def add_category():
    """Handles adding a new expense category."""
    db = next(get_db())
    if request.method == 'POST':
        category_name = request.form['category_name'].strip()
        if category_name:
            # Check if category already exists (case-insensitive)
            existing_category = db.query(Category).filter(func.lower(Category.name) == func.lower(category_name)).first()
            if existing_category:
                flash(f"Category '{category_name}' already exists.", 'warning')
            else:
                new_category = Category(name=category_name)
                db.add(new_category)
                db.commit()
                flash(f"Category '{category_name}' added successfully!", 'success')
                return redirect(url_for('trip_blueprint.list_categories'))
        else:
            flash("Category name cannot be empty.", 'danger')

    return render_template('add_category.html')

@trip_blueprint.route('/categories/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    """Handles deleting an expense category."""
    db = next(get_db())
    category_to_delete = db.query(Category).get(category_id)

    if category_to_delete:
        # Before deleting, set category_id to NULL for all expenses linked to this category
        # This prevents a foreign key constraint error
        db.query(Expense).filter_by(category_id=category_id).update({Expense.category_id: None})
        db.delete(category_to_delete)
        db.commit()
        flash(f"Category '{category_to_delete.name}' deleted successfully. Expenses previously in this category are now uncategorized.", 'success')
    else:
        flash("Category not found.", 'danger')

    return redirect(url_for('trip_blueprint.list_categories'))

